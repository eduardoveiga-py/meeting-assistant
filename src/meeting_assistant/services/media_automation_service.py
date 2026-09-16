from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import obsws_python as obs
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage

from meeting_assistant.services.obs_controller import (
    ObsConnectionConfig,
    decode_image_data,
    extract_current_scene,
)

SENSOR_WIDTH = 160
SENSOR_HEIGHT = 90
PIXEL_THRESHOLD = 12


class MediaSignalEvent(StrEnum):
    STARTED = "started"
    ENDED = "ended"


@dataclass(frozen=True, slots=True)
class MediaAutomationConfig:
    obs: ObsConnectionConfig
    sensor_source: str
    media_scene: str
    eligible_return_scenes: tuple[str, ...]


@dataclass(slots=True)
class MediaSignalDetector:
    """Debounce puro para transformar diferença visual em início/fim de mídia."""

    start_threshold: float = 5.0
    end_threshold: float = 1.5
    start_hits_required: int = 2
    end_hits_required: int = 3
    active: bool = False
    start_hits: int = 0
    end_hits: int = 0

    def reset(self) -> None:
        self.active = False
        self.start_hits = 0
        self.end_hits = 0

    def update(self, changed_percent: float) -> MediaSignalEvent | None:
        if not self.active:
            if changed_percent >= self.start_threshold:
                self.start_hits += 1
            else:
                self.start_hits = 0

            if self.start_hits >= self.start_hits_required:
                self.active = True
                self.start_hits = 0
                self.end_hits = 0
                return MediaSignalEvent.STARTED
            return None

        if changed_percent <= self.end_threshold:
            self.end_hits += 1
        else:
            self.end_hits = 0

        if self.end_hits >= self.end_hits_required:
            self.active = False
            self.start_hits = 0
            self.end_hits = 0
            return MediaSignalEvent.ENDED
        return None


def pixel_difference(reference: bytes, current: bytes) -> float:
    if not reference or len(reference) != len(current):
        raise ValueError("frames devem ter o mesmo tamanho e não podem estar vazios")

    changed = 0
    for before, after in zip(reference, current, strict=True):
        if abs(before - after) > PIXEL_THRESHOLD:
            changed += 1
    return (changed / len(reference)) * 100.0


def should_restore_scene(
    *,
    auto_switched: bool,
    manual_override: bool,
    return_scene: str | None,
    current_scene: str | None,
    media_scene: str,
) -> bool:
    return bool(
        auto_switched
        and not manual_override
        and return_scene
        and current_scene == media_scene
    )


class MediaAutomationService(QObject):
    """Observa uma cena/fonte do OBS e automatiza a cena Mídia com segurança.

    A captura roda em uma conexão WebSocket separada para nunca bloquear a conexão
    usada pela interface. Mudanças de cena são solicitadas ao ObsController por sinal.
    """

    request_scene_change = Signal(str)
    status_changed = Signal(str)
    media_started = Signal(str)
    media_ended = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        config_provider: Callable[[], MediaAutomationConfig],
        enabled_provider: Callable[[], bool],
        sample_interval_seconds: float = 0.4,
    ) -> None:
        super().__init__()
        self._config_provider = config_provider
        self._enabled_provider = enabled_provider
        self._sample_interval = max(0.25, sample_interval_seconds)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._detector = MediaSignalDetector()
        self._last_status: str | None = None

        self._return_scene: str | None = None
        self._auto_switched = False
        self._manual_override = False
        self._program_seen_media = False
        self._switch_requested_at = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="MeetingAssistant-MediaAutomation",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.5)

    def _run(self) -> None:
        client: obs.ReqClient | None = None
        active_config: MediaAutomationConfig | None = None
        baseline: bytes | None = None
        was_enabled = False

        while not self._stop_event.is_set():
            enabled = bool(self._enabled_provider())
            if not enabled:
                if was_enabled:
                    self._emit_status("Automação pausada; monitoramento de mídia suspenso.")
                was_enabled = False
                baseline = None
                self._detector.reset()
                self._reset_session()
                self._close_client(client)
                client = None
                self._stop_event.wait(0.25)
                continue

            was_enabled = True
            config = self._config_provider()
            if config != active_config:
                active_config = config
                baseline = None
                self._detector.reset()
                self._reset_session()
                self._close_client(client)
                client = None

            if not config.sensor_source or not config.media_scene:
                self._emit_status("Automação aguardando configuração da cena de Mídia.")
                self._stop_event.wait(1.0)
                continue

            if client is None:
                client = self._connect(config.obs)
                if client is None:
                    self._stop_event.wait(2.0)
                    continue
                baseline = None

            try:
                if baseline is None:
                    baseline = self._calibrate(client, config.sensor_source)
                    if baseline is None:
                        if not self._enabled_provider():
                            continue
                        raise RuntimeError(
                            f"não foi possível calibrar o sensor '{config.sensor_source}'"
                        )
                    self._emit_status(
                        "Automação pronta: aguardando mídia no JW Library."
                    )
                    continue

                frame = self._capture_luma(client, config.sensor_source)
                if frame is None or len(frame) != len(baseline):
                    raise RuntimeError(
                        f"sensor '{config.sensor_source}' não retornou imagem válida"
                    )

                changed_percent = pixel_difference(baseline, frame)
                current_scene = self._current_scene(client)
                event = self._detector.update(changed_percent)

                if self._detector.active:
                    self._observe_manual_override(current_scene, config.media_scene)

                if event == MediaSignalEvent.STARTED:
                    self._handle_media_started(client, config, current_scene)
                elif event == MediaSignalEvent.ENDED:
                    self._handle_media_ended(client, config, current_scene)

                self._stop_event.wait(self._sample_interval)
            except Exception as exc:
                message = str(exc).strip() or type(exc).__name__
                self.error.emit(f"Automação de mídia: {message}")
                self._emit_status("Automação de mídia reconectando ao OBS…")
                baseline = None
                self._detector.reset()
                self._reset_session()
                self._close_client(client)
                client = None
                self._stop_event.wait(2.0)

        self._close_client(client)

    def _connect(self, config: ObsConnectionConfig) -> obs.ReqClient | None:
        try:
            client = obs.ReqClient(
                host=config.host,
                port=config.port,
                password=config.password,
                timeout=3,
            )
            client.send("GetVersion", raw=True)
            self._emit_status("Automação conectada; calibrando estado parado do JW Library…")
            return client
        except Exception as exc:
            message = str(exc).strip() or type(exc).__name__
            self.error.emit(f"Automação de mídia sem conexão com OBS: {message}")
            self._emit_status("Automação aguardando OBS WebSocket…")
            return None

    def _calibrate(self, client: obs.ReqClient, source_name: str) -> bytes | None:
        candidate: bytes | None = None
        stable_hits = 0
        self._emit_status("Automação calibrando: deixe o JW Library sem mídia por alguns segundos.")

        while not self._stop_event.is_set() and self._enabled_provider():
            frame = self._capture_luma(client, source_name)
            if frame is None:
                self._stop_event.wait(0.4)
                continue

            if candidate is None or len(candidate) != len(frame):
                candidate = frame
                stable_hits = 0
            else:
                changed = pixel_difference(candidate, frame)
                if changed <= 1.0:
                    stable_hits += 1
                    if stable_hits >= 3:
                        return frame
                else:
                    candidate = frame
                    stable_hits = 0

            self._stop_event.wait(0.4)
        return None

    def _handle_media_started(
        self,
        client: obs.ReqClient,
        config: MediaAutomationConfig,
        current_scene: str | None,
    ) -> None:
        self._reset_session()

        if current_scene == config.media_scene:
            self._manual_override = True
            self.media_started.emit(config.media_scene)
            self._emit_status(
                "Mídia detectada; cena Mídia já estava selecionada manualmente."
            )
            return

        if current_scene not in config.eligible_return_scenes:
            self._manual_override = True
            label = current_scene or "desconhecida"
            self.media_started.emit(label)
            self._emit_status(
                f"Mídia detectada, mas Program está em '{label}'; automação não assumiu a cena."
            )
            return

        self._return_scene = current_scene
        self._auto_switched = True
        self._switch_requested_at = time.monotonic()
        self.request_scene_change.emit(config.media_scene)
        self.media_started.emit(config.media_scene)
        self._emit_status(
            f"Mídia detectada: entrando em '{config.media_scene}'."
        )

    def _handle_media_ended(
        self,
        client: obs.ReqClient,
        config: MediaAutomationConfig,
        current_scene: str | None,
    ) -> None:
        # Atualiza uma última vez antes de decidir se pode restaurar.
        current_scene = self._current_scene(client) or current_scene
        return_scene = self._return_scene

        if should_restore_scene(
            auto_switched=self._auto_switched,
            manual_override=self._manual_override,
            return_scene=return_scene,
            current_scene=current_scene,
            media_scene=config.media_scene,
        ):
            assert return_scene is not None
            self.request_scene_change.emit(return_scene)
            self.media_ended.emit(return_scene)
            self._emit_status(
                f"Mídia encerrada: retornando para '{return_scene}'."
            )
        elif self._manual_override:
            self.media_ended.emit(current_scene or "")
            self._emit_status(
                "Mídia encerrada; alteração manual detectada, cena atual preservada."
            )
        else:
            self.media_ended.emit(current_scene or "")
            self._emit_status("Mídia encerrada; nenhuma restauração automática necessária.")

        self._reset_session()

    def _observe_manual_override(
        self,
        current_scene: str | None,
        media_scene: str,
    ) -> None:
        if not self._auto_switched or self._manual_override or current_scene is None:
            return

        if current_scene == media_scene:
            self._program_seen_media = True
            return

        if self._program_seen_media:
            self._manual_override = True
            return

        if time.monotonic() - self._switch_requested_at >= 2.5:
            self._manual_override = True

    def _reset_session(self) -> None:
        self._return_scene = None
        self._auto_switched = False
        self._manual_override = False
        self._program_seen_media = False
        self._switch_requested_at = 0.0

    @staticmethod
    def _current_scene(client: obs.ReqClient) -> str | None:
        payload = client.send("GetCurrentProgramScene", raw=True)
        return extract_current_scene(payload)

    @staticmethod
    def _capture_luma(client: obs.ReqClient, source_name: str) -> bytes | None:
        payload = client.send(
            "GetSourceScreenshot",
            {
                "sourceName": source_name,
                "imageFormat": "jpeg",
                "imageWidth": 320,
                "imageHeight": 180,
                "imageCompressionQuality": 60,
            },
            raw=True,
        )
        image_data = payload.get("imageData") or payload.get("image_data")
        if not isinstance(image_data, str):
            return None
        decoded = decode_image_data(image_data)
        if not decoded:
            return None

        image = QImage.fromData(decoded)
        if image.isNull():
            return None
        image = image.scaled(
            SENSOR_WIDTH,
            SENSOR_HEIGHT,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
        raw = gray.constBits()
        data = bytes(raw[: gray.sizeInBytes()])
        return data if data else None

    def _emit_status(self, message: str) -> None:
        if message == self._last_status:
            return
        self._last_status = message
        self.status_changed.emit(message)

    @staticmethod
    def _close_client(client: obs.ReqClient | None) -> None:
        if client is None:
            return
        try:
            base_client = getattr(client, "base_client", None)
            websocket = getattr(base_client, "ws", None)
            if websocket is not None:
                websocket.close()
        except Exception:
            pass
