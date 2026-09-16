from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import obsws_python as obs
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage

from meeting_assistant.services.obs_controller import ObsConnectionConfig, decode_image_data

PROBE_WIDTH = 160
PROBE_HEIGHT = 90
PIXEL_THRESHOLD = 12
MAX_PROBE_TARGETS = 12


@dataclass(frozen=True, slots=True)
class VisualSample:
    elapsed_ms: int
    changed_percent: float
    mean_difference: float
    motion_percent: float = 0.0
    motion_mean_difference: float = 0.0
    video_active: bool | None = None
    video_showing: bool | None = None


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    source_name: str
    input_kind: str | None
    settings: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class SourceProbeResult:
    source_name: str
    samples: tuple[VisualSample, ...]

    @property
    def peak_changed_percent(self) -> float:
        return max((sample.changed_percent for sample in self.samples), default=0.0)

    @property
    def peak_mean_difference(self) -> float:
        return max((sample.mean_difference for sample in self.samples), default=0.0)

    @property
    def tail_average(self) -> float:
        if not self.samples:
            return 0.0
        tail = self.samples[-min(4, len(self.samples)) :]
        return sum(sample.changed_percent for sample in tail) / len(tail)

    @property
    def peak_motion_percent(self) -> float:
        return max((sample.motion_percent for sample in self.samples), default=0.0)

    @property
    def tail_motion_average(self) -> float:
        if not self.samples:
            return 0.0
        tail = self.samples[-min(4, len(self.samples)) :]
        return sum(sample.motion_percent for sample in tail) / len(tail)

    @property
    def active_values(self) -> tuple[bool, ...]:
        values: list[bool] = []
        for sample in self.samples:
            if sample.video_active is not None and sample.video_active not in values:
                values.append(sample.video_active)
        return tuple(values)

    @property
    def showing_values(self) -> tuple[bool, ...]:
        values: list[bool] = []
        for sample in self.samples:
            if sample.video_showing is not None and sample.video_showing not in values:
                values.append(sample.video_showing)
        return tuple(values)


def extract_scene_source_names(payload: dict[str, Any]) -> list[str]:
    items = payload.get("sceneItems") or payload.get("scene_items") or []
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("sourceName") or item.get("source_name")
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    return names


def pixel_difference(
    reference: bytes,
    current: bytes,
    threshold: int = PIXEL_THRESHOLD,
) -> tuple[float, float]:
    if not reference or len(reference) != len(current):
        raise ValueError("frames devem ter o mesmo tamanho e não podem estar vazios")

    changed = 0
    absolute_sum = 0
    for before, after in zip(reference, current, strict=True):
        difference = abs(before - after)
        absolute_sum += difference
        if difference > threshold:
            changed += 1

    total = len(reference)
    return (changed / total) * 100.0, absolute_sum / total


def image_to_luma(image_bytes: bytes) -> bytes | None:
    image = QImage.fromData(image_bytes)
    if image.isNull():
        return None

    image = image.scaled(
        PROBE_WIDTH,
        PROBE_HEIGHT,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    raw = gray.constBits()
    expected = gray.sizeInBytes()
    data = bytes(raw[:expected])
    return data if data else None


def classify_samples(samples: list[VisualSample] | tuple[VisualSample, ...]) -> str:
    if not samples:
        return "Nenhuma amostra válida foi obtida."

    peak = max(sample.changed_percent for sample in samples)
    tail = samples[-min(4, len(samples)) :]
    tail_average = sum(sample.changed_percent for sample in tail) / len(tail)
    peak_motion = max(sample.motion_percent for sample in samples)
    tail_motion = sum(sample.motion_percent for sample in tail) / len(tail)

    if peak >= 5.0 and tail_average <= 1.5:
        return (
            "Sinal forte: a fonte saiu claramente do estado de repouso e retornou ao final. "
            "Este é um bom candidato para automação."
        )
    if peak >= 5.0 and peak_motion >= 2.0 and tail_motion <= 0.5:
        return (
            "A fonte permaneceu diferente do baseline, mas o movimento caiu no final. "
            "Isso pode distinguir reprodução ativa de um quadro final congelado."
        )
    if peak >= 5.0:
        return (
            "Mudança visual forte detectada, mas a fonte não retornou claramente ao estado "
            "de repouso até o fim do teste."
        )
    if peak >= 2.0:
        return (
            "Mudança visual moderada detectada. Será necessário calibrar o limiar antes de "
            "automatizar."
        )
    return "Pouca mudança visual foi detectada nesta fonte."


def rank_results(results: list[SourceProbeResult]) -> list[SourceProbeResult]:
    return sorted(
        results,
        key=lambda result: (
            result.peak_changed_percent,
            result.peak_mean_difference,
            result.peak_motion_percent,
        ),
        reverse=True,
    )


class ObsVisualProbeService(QObject):
    started = Signal()
    baseline_ready = Signal()
    progress_changed = Signal(int, int)
    finished = Signal(str, str)
    failed = Signal(str)

    def __init__(
        self,
        calibration_seconds: float = 2.0,
        duration_seconds: float = 20.0,
        sample_interval_seconds: float = 0.4,
    ) -> None:
        super().__init__()
        self._calibration_seconds = max(1.0, calibration_seconds)
        self._duration_seconds = max(5.0, duration_seconds)
        self._sample_interval = max(0.25, sample_interval_seconds)
        self._lock = threading.Lock()
        self._active = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def start(self, config: ObsConnectionConfig, scene_name: str) -> bool:
        with self._lock:
            if self._active:
                return False
            self._active = True

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(config, scene_name),
            name="MeetingAssistant-OBS-VisualProbe",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    def _run(self, config: ObsConnectionConfig, scene_name: str) -> None:
        client: obs.ReqClient | None = None
        try:
            self.started.emit()
            client = obs.ReqClient(
                host=config.host,
                port=config.port,
                password=config.password,
                timeout=3,
            )

            targets = self._discover_targets(client, scene_name)
            metadata = [self._get_metadata(client, target) for target in targets]
            baselines = self._calibrate(client, targets)
            if not baselines:
                raise RuntimeError(
                    f"Não foi possível obter imagem válida da cena '{scene_name}' nem de suas fontes."
                )

            self.baseline_ready.emit()
            results = self._observe(client, baselines)
            report = self._build_report(scene_name, targets, baselines, metadata, results)
            path = self._save_report(report)
            self.finished.emit(report, str(path))
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)
        finally:
            if client is not None:
                try:
                    base_client = getattr(client, "base_client", None)
                    websocket = getattr(base_client, "ws", None)
                    if websocket is not None:
                        websocket.close()
                except Exception:
                    pass
            with self._lock:
                self._active = False

    def _discover_targets(self, client: obs.ReqClient, scene_name: str) -> list[str]:
        targets = [scene_name]
        visited: set[tuple[str, str]] = set()

        def visit(container_name: str, *, is_group: bool = False) -> None:
            if len(targets) >= MAX_PROBE_TARGETS:
                return
            key = ("group" if is_group else "scene", container_name)
            if key in visited:
                return
            visited.add(key)

            request_name = "GetGroupSceneItemList" if is_group else "GetSceneItemList"
            try:
                payload = client.send(
                    request_name,
                    {"sceneName": container_name},
                    raw=True,
                )
            except Exception:
                return

            items = payload.get("sceneItems") or payload.get("scene_items") or []
            for item in items:
                if len(targets) >= MAX_PROBE_TARGETS or not isinstance(item, dict):
                    break
                source_name = item.get("sourceName") or item.get("source_name")
                if not isinstance(source_name, str) or not source_name:
                    continue
                if source_name not in targets:
                    targets.append(source_name)

                source_type = str(
                    item.get("sourceType") or item.get("source_type") or ""
                ).upper()
                if bool(item.get("isGroup") or item.get("is_group")):
                    visit(source_name, is_group=True)
                elif source_type == "OBS_SOURCE_TYPE_SCENE":
                    visit(source_name, is_group=False)

        visit(scene_name)
        return targets

    @staticmethod
    def _get_metadata(client: obs.ReqClient, source_name: str) -> SourceMetadata:
        input_kind: str | None = None
        settings: tuple[tuple[str, str], ...] = ()
        try:
            payload = client.send(
                "GetInputSettings",
                {"inputName": source_name},
                raw=True,
            )
            raw_kind = payload.get("inputKind") or payload.get("input_kind")
            if isinstance(raw_kind, str) and raw_kind:
                input_kind = raw_kind
            raw_settings = payload.get("inputSettings") or payload.get("input_settings") or {}
            if isinstance(raw_settings, dict):
                values: list[tuple[str, str]] = []
                for key in sorted(raw_settings):
                    value = raw_settings[key]
                    if isinstance(value, (str, int, float, bool)):
                        rendered = str(value)
                        if len(rendered) > 160:
                            rendered = rendered[:157] + "..."
                        values.append((str(key), rendered))
                    if len(values) >= 10:
                        break
                settings = tuple(values)
        except Exception:
            pass
        return SourceMetadata(
            source_name=source_name,
            input_kind=input_kind,
            settings=settings,
        )

    def _calibrate(
        self,
        client: obs.ReqClient,
        targets: list[str],
    ) -> dict[str, bytes]:
        deadline = time.monotonic() + self._calibration_seconds
        baselines: dict[str, bytes] = {}

        while not self._stop_event.is_set() and time.monotonic() < deadline:
            for source_name in targets:
                if self._stop_event.is_set():
                    break
                frame = self._capture(client, source_name)
                if frame is not None:
                    baselines[source_name] = frame
            self._stop_event.wait(0.25)

        return baselines

    def _observe(
        self,
        client: obs.ReqClient,
        baselines: dict[str, bytes],
    ) -> list[SourceProbeResult]:
        started_at = time.monotonic()
        duration_ms = int(self._duration_seconds * 1000)
        sample_map: dict[str, list[VisualSample]] = {
            source_name: [] for source_name in baselines
        }
        previous_frames = dict(baselines)

        while not self._stop_event.is_set():
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            if elapsed_ms >= duration_ms:
                break

            for source_name, reference in baselines.items():
                if self._stop_event.is_set():
                    break
                frame = self._capture(client, source_name)
                if frame is None or len(frame) != len(reference):
                    continue
                changed, mean = pixel_difference(reference, frame)
                previous = previous_frames.get(source_name, reference)
                motion, motion_mean = pixel_difference(previous, frame)
                video_active, video_showing = self._get_active_state(client, source_name)
                sample_map[source_name].append(
                    VisualSample(
                        elapsed_ms=elapsed_ms,
                        changed_percent=changed,
                        mean_difference=mean,
                        motion_percent=motion,
                        motion_mean_difference=motion_mean,
                        video_active=video_active,
                        video_showing=video_showing,
                    )
                )
                previous_frames[source_name] = frame

            self.progress_changed.emit(min(elapsed_ms, duration_ms), duration_ms)
            self._stop_event.wait(self._sample_interval)

        self.progress_changed.emit(duration_ms, duration_ms)
        return [
            SourceProbeResult(source_name=name, samples=tuple(samples))
            for name, samples in sample_map.items()
        ]

    @staticmethod
    def _get_active_state(
        client: obs.ReqClient,
        source_name: str,
    ) -> tuple[bool | None, bool | None]:
        try:
            payload = client.send(
                "GetSourceActive",
                {"sourceName": source_name},
                raw=True,
            )
        except Exception:
            return None, None
        active = payload.get("videoActive")
        if active is None:
            active = payload.get("video_active")
        showing = payload.get("videoShowing")
        if showing is None:
            showing = payload.get("video_showing")
        return (
            active if isinstance(active, bool) else None,
            showing if isinstance(showing, bool) else None,
        )

    @staticmethod
    def _capture(client: obs.ReqClient, source_name: str) -> bytes | None:
        request_data = {
            "sourceName": source_name,
            "imageFormat": "jpeg",
            "imageWidth": 320,
            "imageHeight": 180,
            "imageCompressionQuality": 65,
        }
        try:
            payload = client.send("GetSourceScreenshot", request_data, raw=True)
        except Exception:
            return None
        image_data = payload.get("imageData") or payload.get("image_data")
        if not isinstance(image_data, str):
            return None
        decoded = decode_image_data(image_data)
        if not decoded:
            return None
        return image_to_luma(decoded)

    def _build_report(
        self,
        scene_name: str,
        targets: list[str],
        baselines: dict[str, bytes],
        metadata: list[SourceMetadata],
        results: list[SourceProbeResult],
    ) -> str:
        ranked = rank_results(results)
        best = ranked[0] if ranked else None
        metadata_map = {item.source_name: item for item in metadata}

        lines = [
            "Meeting Assistant — descoberta de sensor visual pelo OBS",
            f"Data UTC: {datetime.now(UTC).isoformat(timespec='seconds')}",
            f"Cena usada para descoberta: {scene_name}",
            f"Resolução de análise: {PROBE_WIDTH}x{PROBE_HEIGHT} em tons de cinza",
            f"Alvos encontrados: {len(targets)}",
            f"Alvos com screenshot válido: {len(baselines)}",
            "",
            "Alvos encontrados:",
        ]
        for target in targets:
            state = "screenshot OK" if target in baselines else "sem screenshot válido"
            meta = metadata_map.get(target)
            kind = meta.input_kind if meta and meta.input_kind else "cena/indeterminado"
            lines.append(f"  • {target} — {state} — tipo: {kind}")
            if meta and meta.settings:
                for key, value in meta.settings:
                    lines.append(f"      {key} = {value}")

        lines.extend(["", "Ranking de sensores:"])
        if not ranked:
            lines.append("  nenhum sensor produziu amostras válidas")
        else:
            for index, result in enumerate(ranked, start=1):
                active = "/".join(str(value) for value in result.active_values) or "n/d"
                showing = "/".join(str(value) for value in result.showing_values) or "n/d"
                lines.append(
                    f"  {index}. {result.source_name} — baseline pico "
                    f"{result.peak_changed_percent:.2f}% • movimento pico "
                    f"{result.peak_motion_percent:.2f}% • movimento final "
                    f"{result.tail_motion_average:.2f}% • baseline final "
                    f"{result.tail_average:.2f}% • ativo {active} • exibindo {showing} • "
                    f"{len(result.samples)} amostras"
                )

        lines.extend(["", "Conclusão automática:"])
        if best is None:
            lines.append("Nenhuma fonte adequada pôde ser avaliada.")
        elif best.peak_changed_percent < 2.0:
            lines.append(
                "Nenhuma fonte da cena mudou de forma útil neste teste. Isso indica que a "
                "configuração atual do OBS não está observando a saída visual que muda quando "
                "o JW Library toca mídia."
            )
        else:
            lines.append(f"Melhor candidato: {best.source_name}")
            lines.append(classify_samples(best.samples))

        if best is not None and best.samples:
            lines.extend(["", f"Amostras do melhor candidato ({best.source_name}):"])
            lines.extend(
                f"  +{sample.elapsed_ms / 1000:5.1f}s • baseline "
                f"{sample.changed_percent:6.2f}% • movimento {sample.motion_percent:6.2f}% • "
                f"ativo {sample.video_active!s:5} • exibindo {sample.video_showing!s:5}"
                for sample in best.samples
            )

        lines.extend(
            [
                "",
                "Observação:",
                "Baseline mede diferença contra o estado parado antes do Play.",
                "Movimento mede diferença entre frames consecutivos.",
                "Ativo/exibindo vêm do estado da fonte informado pelo OBS, quando disponível.",
                "Nenhuma cena do OBS é alterada pelo probe.",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _save_report(report: str) -> Path:
        root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        folder = root / "MeetingAssistant" / "diagnostics"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = folder / f"obs-source-probe-{stamp}.txt"
        path.write_text(report, encoding="utf-8")
        return path
