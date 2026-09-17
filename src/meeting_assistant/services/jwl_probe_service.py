from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mss
import mss.tools
from PySide6.QtCore import QObject, Signal

from meeting_assistant.services.display_service import DisplayInfo
from meeting_assistant.services.jwl_secondary_window import JwlSecondaryWindowService

DisplaySnapshotProvider = Callable[[], list[DisplayInfo]]
TargetDisplayProvider = Callable[[], DisplayInfo | None]


class JwlProbeService(QObject):
    """Collect a structured support bundle from the real Windows session.

    This deliberately avoids changing OBS scenes. The bundle captures repeated
    Win32 inventories, candidate scores and a handful of desktop screenshots so
    a remote investigation can distinguish discovery, monitor, DPI and playback
    problems without depending on a single user screenshot.
    """

    started = Signal()
    progress_changed = Signal(int, int)
    finished = Signal(str, str)

    def __init__(
        self,
        secondary_service: JwlSecondaryWindowService,
        display_snapshot_provider: DisplaySnapshotProvider,
        target_display_provider: TargetDisplayProvider,
        *,
        duration_ms: int = 20_000,
        sample_interval_seconds: float = 0.5,
    ) -> None:
        super().__init__()
        self._secondary = secondary_service
        self._display_snapshot_provider = display_snapshot_provider
        self._target_display_provider = target_display_provider
        self._duration_ms = max(5_000, duration_ms)
        self._sample_interval = max(0.25, sample_interval_seconds)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> bool:
        if self._active:
            return False

        # Qt screen access stays on the GUI thread. The worker receives an
        # immutable snapshot and uses Win32/MSS only.
        displays = self._display_snapshot_provider()
        target_display = self._target_display_provider()

        self._stop_event.clear()
        self._active = True
        self.started.emit()
        self._thread = threading.Thread(
            target=self._run,
            args=(displays, target_display),
            name="MeetingAssistant-JwlDiagnostics",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    def _run(
        self,
        displays: list[DisplayInfo],
        target_display: DisplayInfo | None,
    ) -> None:
        started_at = time.monotonic()
        samples: list[dict[str, Any]] = []
        screenshot_offsets = (0.0, 5.0, 10.0, 15.0, 19.0)
        screenshot_index = 0

        try:
            with tempfile.TemporaryDirectory(prefix="meeting-assistant-diagnostics-") as temp:
                temp_dir = Path(temp)
                screen_dir = temp_dir / "screenshots"
                screen_dir.mkdir(parents=True, exist_ok=True)

                with mss.mss() as sct:
                    while not self._stop_event.is_set():
                        elapsed = time.monotonic() - started_at
                        if elapsed * 1000 >= self._duration_ms:
                            break

                        snapshot = self._secondary.diagnostic_snapshot(target_display)
                        snapshot["elapsed_seconds"] = round(elapsed, 3)
                        snapshot["utc"] = datetime.now(UTC).isoformat()
                        samples.append(snapshot)

                        while (
                            screenshot_index < len(screenshot_offsets)
                            and elapsed >= screenshot_offsets[screenshot_index]
                        ):
                            self._capture_virtual_desktop(
                                sct,
                                screen_dir / f"virtual-{screenshot_index:02d}.png",
                            )
                            screenshot_index += 1

                        self.progress_changed.emit(
                            min(self._duration_ms, int(elapsed * 1000)),
                            self._duration_ms,
                        )
                        self._stop_event.wait(self._sample_interval)

                    if screenshot_index == 0:
                        self._capture_virtual_desktop(sct, screen_dir / "virtual-00.png")

                metadata = {
                    "generated_utc": datetime.now(UTC).isoformat(),
                    "duration_ms": self._duration_ms,
                    "sample_interval_seconds": self._sample_interval,
                    "python": sys.version,
                    "platform": platform.platform(),
                    "displays_qt": [asdict(display) for display in displays],
                    "target_display_qt": asdict(target_display) if target_display else None,
                    "sample_count": len(samples),
                }
                (temp_dir / "metadata.json").write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                (temp_dir / "window-timeline.json").write_text(
                    json.dumps(samples, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                summary = self._build_summary(samples, metadata)
                (temp_dir / "summary.txt").write_text(summary, encoding="utf-8")

                bundle_path = self._bundle_path()
                bundle_path.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(
                    bundle_path,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=6,
                ) as archive:
                    for path in sorted(temp_dir.rglob("*")):
                        if path.is_file():
                            archive.write(path, path.relative_to(temp_dir))

            self.progress_changed.emit(self._duration_ms, self._duration_ms)
            self.finished.emit(summary, str(bundle_path))
        except Exception as exc:  # noqa: BLE001 - diagnostic must surface native failures
            report = (
                "Meeting Assistant — diagnóstico técnico do JW Library\n\n"
                f"Falha ao gerar o pacote: {exc}\n\n"
                "Nenhuma cena do OBS foi alterada."
            )
            self.finished.emit(report, "pacote não gerado")
        finally:
            self._active = False

    @staticmethod
    def _capture_virtual_desktop(sct: mss.mss, path: Path) -> None:
        try:
            monitor = sct.monitors[0]
            shot = sct.grab(monitor)
            mss.tools.to_png(shot.rgb, shot.size, output=str(path))
        except (OSError, RuntimeError, ValueError):
            pass

    @staticmethod
    def _build_summary(
        samples: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> str:
        selected_hwnds: list[int] = []
        observed: dict[int, dict[str, Any]] = {}

        for sample in samples:
            selected = sample.get("selected_candidate")
            if isinstance(selected, dict):
                hwnd = selected.get("hwnd")
                if isinstance(hwnd, int):
                    selected_hwnds.append(hwnd)
            for window in sample.get("windows", []):
                if not isinstance(window, dict):
                    continue
                hwnd = window.get("hwnd")
                if isinstance(hwnd, int):
                    previous = observed.get(hwnd)
                    if previous is None or int(window.get("score", -10_000)) > int(
                        previous.get("score", -10_000)
                    ):
                        observed[hwnd] = window

        ranked = sorted(
            observed.values(),
            key=lambda item: int(item.get("score", -10_000)),
            reverse=True,
        )

        lines = [
            "Meeting Assistant — diagnóstico técnico do JW Library",
            "",
            f"Gerado UTC: {metadata['generated_utc']}",
            f"Amostras Win32: {metadata['sample_count']}",
            f"Monitores Qt: {len(metadata['displays_qt'])}",
            f"Tela do Salão resolvida: {'sim' if metadata['target_display_qt'] else 'não'}",
            "",
        ]

        if selected_hwnds:
            unique = list(dict.fromkeys(selected_hwnds))
            lines.append(
                "HWND selecionado pelo motor durante o teste: "
                + ", ".join(str(hwnd) for hwnd in unique)
            )
        else:
            lines.append("O motor não selecionou nenhum HWND durante o teste.")

        lines.extend(["", "Principais janelas observadas:"])
        if not ranked:
            lines.append("  • nenhuma janela relevante foi inventariada")
        else:
            for item in ranked[:12]:
                rect = item.get("rect") or {}
                lines.append(
                    "  • HWND {hwnd} • score {score} • {proc} • {klass} • "
                    "{w}x{h} @ {left},{top} • monitor {monitor} • título: {title}".format(
                        hwnd=item.get("hwnd", "?"),
                        score=item.get("score", "?"),
                        proc=item.get("process_name") or "?",
                        klass=item.get("class_name") or "?",
                        w=max(0, int(rect.get("right", 0)) - int(rect.get("left", 0))),
                        h=max(0, int(rect.get("bottom", 0)) - int(rect.get("top", 0))),
                        left=rect.get("left", "?"),
                        top=rect.get("top", "?"),
                        monitor=item.get("monitor_device") or "?",
                        title=item.get("title") or "<sem título>",
                    )
                )

        lines.extend(
            [
                "",
                "O ZIP contém:",
                "  • metadata.json — sistema e monitores",
                "  • window-timeline.json — inventário Win32 repetido durante 20 s",
                "  • summary.txt — resumo legível",
                "  • screenshots/ — capturas automáticas do desktop virtual",
                "",
                "Nenhuma cena do OBS é alterada por este diagnóstico.",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _bundle_path() -> Path:
        local_appdata = os.environ.get("LOCALAPPDATA")
        root = (
            Path(local_appdata) / "MeetingAssistant" / "diagnostics"
            if local_appdata
            else Path.home() / ".meeting-assistant" / "diagnostics"
        )
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return root / f"jwl-diagnostics-{stamp}.zip"
