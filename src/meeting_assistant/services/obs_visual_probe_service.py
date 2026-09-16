from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import obsws_python as obs
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage

from meeting_assistant.services.obs_controller import ObsConnectionConfig, decode_image_data

PROBE_WIDTH = 160
PROBE_HEIGHT = 90
PIXEL_THRESHOLD = 12


@dataclass(frozen=True, slots=True)
class VisualSample:
    elapsed_ms: int
    changed_percent: float
    mean_difference: float


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


def classify_samples(samples: list[VisualSample]) -> str:
    if not samples:
        return "Nenhuma amostra válida foi obtida."

    peak = max(sample.changed_percent for sample in samples)
    tail = samples[-min(4, len(samples)) :]
    tail_average = sum(sample.changed_percent for sample in tail) / len(tail)

    if peak >= 5.0 and tail_average <= 1.5:
        return (
            "Sinal forte: a cena saiu claramente do estado de repouso e retornou ao final. "
            "Este é um bom candidato para automação."
        )
    if peak >= 5.0:
        return (
            "Mudança visual forte detectada, mas a cena não retornou claramente ao estado "
            "de repouso até o fim do teste."
        )
    if peak >= 2.0:
        return (
            "Mudança visual moderada detectada. Será necessário calibrar o limiar antes de "
            "automatizar."
        )
    return (
        "Pouca mudança visual foi detectada. Esta cena provavelmente não é um bom sensor "
        "para a mídia do JW Library."
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

    def start(self, config: ObsConnectionConfig, source_name: str) -> bool:
        with self._lock:
            if self._active:
                return False
            self._active = True

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(config, source_name),
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

    def _run(self, config: ObsConnectionConfig, source_name: str) -> None:
        client: obs.ReqClient | None = None
        try:
            self.started.emit()
            client = obs.ReqClient(
                host=config.host,
                port=config.port,
                password=config.password,
                timeout=3,
            )

            reference = self._calibrate(client, source_name)
            if reference is None:
                raise RuntimeError(
                    f"Não foi possível obter uma imagem válida da cena/fonte '{source_name}'."
                )

            self.baseline_ready.emit()
            samples = self._observe(client, source_name, reference)
            report = self._build_report(source_name, samples)
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

    def _calibrate(self, client: obs.ReqClient, source_name: str) -> bytes | None:
        deadline = time.monotonic() + self._calibration_seconds
        reference: bytes | None = None
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            frame = self._capture(client, source_name)
            if frame is not None:
                reference = frame
            self._stop_event.wait(0.35)
        return reference

    def _observe(
        self,
        client: obs.ReqClient,
        source_name: str,
        reference: bytes,
    ) -> list[VisualSample]:
        started_at = time.monotonic()
        duration_ms = int(self._duration_seconds * 1000)
        samples: list[VisualSample] = []

        while not self._stop_event.is_set():
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            if elapsed_ms >= duration_ms:
                break

            frame = self._capture(client, source_name)
            if frame is not None and len(frame) == len(reference):
                changed, mean = pixel_difference(reference, frame)
                samples.append(
                    VisualSample(
                        elapsed_ms=elapsed_ms,
                        changed_percent=changed,
                        mean_difference=mean,
                    )
                )

            self.progress_changed.emit(min(elapsed_ms, duration_ms), duration_ms)
            self._stop_event.wait(self._sample_interval)

        self.progress_changed.emit(duration_ms, duration_ms)
        return samples

    @staticmethod
    def _capture(client: obs.ReqClient, source_name: str) -> bytes | None:
        request_data = {
            "sourceName": source_name,
            "imageFormat": "jpeg",
            "imageWidth": 320,
            "imageHeight": 180,
            "imageCompressionQuality": 65,
        }
        payload = client.send("GetSourceScreenshot", request_data, raw=True)
        image_data = payload.get("imageData") or payload.get("image_data")
        if not isinstance(image_data, str):
            return None
        decoded = decode_image_data(image_data)
        if not decoded:
            return None
        return image_to_luma(decoded)

    def _build_report(self, source_name: str, samples: list[VisualSample]) -> str:
        lines = [
            "Meeting Assistant — probe visual de mídia pelo OBS",
            f"Data UTC: {datetime.now(UTC).isoformat(timespec='seconds')}",
            f"Cena/fonte observada: {source_name}",
            f"Resolução de análise: {PROBE_WIDTH}x{PROBE_HEIGHT} em tons de cinza",
            f"Amostras válidas: {len(samples)}",
            "",
        ]

        if not samples:
            lines.append("Nenhuma amostra válida foi obtida após a calibração.")
            return "\n".join(lines)

        peak = max(samples, key=lambda sample: sample.changed_percent)
        mean_peak = max(samples, key=lambda sample: sample.mean_difference)
        tail = samples[-min(4, len(samples)) :]
        tail_average = sum(sample.changed_percent for sample in tail) / len(tail)

        lines.extend(
            [
                f"Maior alteração: {peak.changed_percent:.2f}% em +{peak.elapsed_ms / 1000:.1f}s",
                f"Maior diferença média: {mean_peak.mean_difference:.2f} em "
                f"+{mean_peak.elapsed_ms / 1000:.1f}s",
                f"Média das últimas amostras: {tail_average:.2f}%",
                "",
                "Conclusão automática:",
                classify_samples(samples),
                "",
                "Amostras:",
            ]
        )
        lines.extend(
            f"  +{sample.elapsed_ms / 1000:5.1f}s • alterado "
            f"{sample.changed_percent:6.2f}% • diferença média {sample.mean_difference:6.2f}"
            for sample in samples
        )
        lines.extend(
            [
                "",
                "Observação:",
                "Este teste lê somente screenshots de baixa resolução fornecidos pelo OBS.",
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
        path = folder / f"obs-media-probe-{stamp}.txt"
        path.write_text(report, encoding="utf-8")
        return path
