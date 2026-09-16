from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from meeting_assistant.services.jwl_service import JwlService, JwlWindowInfo


@dataclass(frozen=True, slots=True)
class ProbeSample:
    elapsed_ms: int
    windows: tuple[JwlWindowInfo, ...]


def structural_signature(windows: list[JwlWindowInfo] | tuple[JwlWindowInfo, ...]) -> tuple:
    return tuple(
        (
            item.hwnd,
            item.pid,
            item.title,
            item.class_name,
            item.left,
            item.top,
            item.right,
            item.bottom,
            item.visible,
            item.minimized,
        )
        for item in windows
    )


def _window_summary(item: JwlWindowInfo) -> str:
    title = item.title or "<sem título>"
    visible = "visível" if item.visible else "oculta"
    minimized = "minimizada" if item.minimized else "normal"
    return (
        f"HWND {item.hwnd} • PID {item.pid} • {item.process_name or '?'} • "
        f"{item.class_name} • {item.size} • {visible}/{minimized} • {title}"
    )


def describe_changes(
    previous: tuple[JwlWindowInfo, ...],
    current: tuple[JwlWindowInfo, ...],
) -> list[str]:
    before = {item.hwnd: item for item in previous}
    after = {item.hwnd: item for item in current}
    lines: list[str] = []

    for hwnd in sorted(after.keys() - before.keys()):
        lines.append(f"+ janela criada: {_window_summary(after[hwnd])}")

    for hwnd in sorted(before.keys() - after.keys()):
        lines.append(f"- janela removida: {_window_summary(before[hwnd])}")

    for hwnd in sorted(before.keys() & after.keys()):
        old = before[hwnd]
        new = after[hwnd]
        changes: list[str] = []
        if old.title != new.title:
            changes.append(f"título '{old.title}' → '{new.title}'")
        if old.class_name != new.class_name:
            changes.append(f"classe {old.class_name} → {new.class_name}")
        if (old.left, old.top, old.right, old.bottom) != (
            new.left,
            new.top,
            new.right,
            new.bottom,
        ):
            changes.append(
                f"retângulo {old.left},{old.top},{old.right},{old.bottom} → "
                f"{new.left},{new.top},{new.right},{new.bottom}"
            )
        if old.visible != new.visible:
            changes.append(f"visível {old.visible} → {new.visible}")
        if old.minimized != new.minimized:
            changes.append(f"minimizada {old.minimized} → {new.minimized}")
        if changes:
            lines.append(f"~ HWND {hwnd}: " + "; ".join(changes))

    return lines


class JwlProbeService(QObject):
    started = Signal()
    progress_changed = Signal(int, int)
    finished = Signal(str, str)

    def __init__(
        self,
        jwl_service: JwlService,
        duration_ms: int = 20000,
        sample_interval_ms: int = 300,
    ) -> None:
        super().__init__()
        self._jwl = jwl_service
        self._duration_ms = max(5000, duration_ms)
        self._timer = QTimer(self)
        self._timer.setInterval(max(200, sample_interval_ms))
        self._timer.timeout.connect(self._sample)
        self._started_at = 0.0
        self._samples: list[ProbeSample] = []
        self._last_signature: tuple | None = None
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> bool:
        if self._active:
            return False

        self._active = True
        self._samples.clear()
        self._last_signature = None
        self._started_at = time.monotonic()
        self.started.emit()
        self._sample()
        self._timer.start()
        return True

    def stop(self) -> None:
        if not self._active:
            return
        self._finish()

    def _sample(self) -> None:
        if not self._active:
            return

        elapsed_ms = int((time.monotonic() - self._started_at) * 1000)
        windows = tuple(self._jwl.scan(include_hidden=True))
        signature = structural_signature(windows)
        if signature != self._last_signature:
            self._samples.append(ProbeSample(elapsed_ms=elapsed_ms, windows=windows))
            self._last_signature = signature

        self.progress_changed.emit(min(elapsed_ms, self._duration_ms), self._duration_ms)
        if elapsed_ms >= self._duration_ms:
            self._finish()

    def _finish(self) -> None:
        self._timer.stop()
        self._active = False
        report = self._build_report()
        path = self._save_report(report)
        self.finished.emit(report, str(path))

    def _build_report(self) -> str:
        lines = [
            "Meeting Assistant — observação do JW Library",
            f"Data UTC: {datetime.now(UTC).isoformat(timespec='seconds')}",
            f"Duração: {self._duration_ms / 1000:.1f}s",
            f"Mudanças estruturais observadas: {max(0, len(self._samples) - 1)}",
            "",
        ]

        if not self._samples:
            lines.append("Nenhuma janela do JW Library foi observada.")
            return "\n".join(lines)

        first = self._samples[0]
        lines.append(f"Estado inicial (+{first.elapsed_ms / 1000:.1f}s):")
        if first.windows:
            lines.extend(f"  {_window_summary(item)}" for item in first.windows)
        else:
            lines.append("  nenhuma janela candidata")

        previous = first.windows
        for sample in self._samples[1:]:
            changes = describe_changes(previous, sample.windows)
            if changes:
                lines.append("")
                lines.append(f"Mudança em +{sample.elapsed_ms / 1000:.1f}s:")
                lines.extend(f"  {line}" for line in changes)
            previous = sample.windows

        lines.extend(
            [
                "",
                "Observação:",
                "O foco da janela não é usado como sinal de mídia, pois muda quando o operador alterna entre apps.",
                "Este teste ainda não troca cenas do OBS.",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _save_report(report: str) -> Path:
        root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        folder = root / "MeetingAssistant" / "diagnostics"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = folder / f"jwl-probe-{stamp}.txt"
        path.write_text(report, encoding="utf-8")
        return path
