from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

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


def sensor_candidate_score(
    source_name: str,
    input_kind: str | None,
    settings: dict[str, Any],
) -> int:
    """Pontua fontes OBS que parecem ser a captura direta do JW Library."""

    score = 0
    name = source_name.casefold()
    kind = (input_kind or "").casefold()
    settings_text = " ".join(str(value) for value in settings.values()).casefold()

    if kind == "window_capture":
        score += 40
    elif kind == "monitor_capture":
        score -= 40

    if "jw library" in name or "jwlibrary" in name:
        score += 25

    if "jwlibrary.exe" in settings_text:
        score += 120
    elif "jw library" in settings_text or "jwlibrary" in settings_text:
        score += 70

    return score


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
    """Detecta mídia do JW Library e automatiza a cena Mídia com proteção manual."""

    request_scene_change = Signal(str)
    status_changed = Signal(str)
    signal_changed = Signal(str, float, bool)
    media_started = Signal(str)
    media_ended = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        config_provider: Callable[[], MediaAutomationConfig],
        sample_interval_seconds: float = 0.4,
    ) -> None:
        super().__init__()
        self._config_provider = config_provider
        self._sample_interval = max(0.25, sample_interval_seconds)
        self._stop_event = threading.Event()
        self._enabled_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._detector = MediaSignalDetector()
        self._last_status: str | None = None
        self._last_signal_emit_at = 0.0

        self._return_scene: str | None = None
        self._auto_switched = False
        self._manual_override = False
        self._program_seen_media = False
        self._switch_requested_at = 0.0

    @property
    def enabled(self) -> bool:
        return self._enabled_event.is_set()

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._enabled_event.set()
            self._last_signal_emit_at = 0.0
            self._emit_status("Automação ativada; conectando ao sensor do JW Library…")
        else:
            self._enabled_event.clear()
            self._emit_status("Automação pausada; monitoramento de mídia suspenso.")

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
        self._enabled_event.clear()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.5)

    def _run(self) -> None:
        client: obs.ReqClient | None = None
        active_config: MediaAutomationConfig | None = None
        resolved_sensor: str | None = None
        baseline: bytes | None = None
        was_enabled = False

        while not self._stop_event.is_set():
            enabled = self._enabled_event.is_set()
            if not enabled:
                if was_enabled:
                    self._emit_status("Automação pausada; monitoramento de mídia suspenso.")
                was_enabled = False
                resolved_sensor = None
                baseline = None
                self._detector.reset()
                self._reset_session()
                self._close_client(client)
                client = None
                self._stop_event.wait(0.20)
                continue

            was_enabled = True
            config = self._config_provider()
            if config != active_config:
                active_config = config
                resolved_sensor = None
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
                resolved_sensor = None
                baseline = None

            try:
                if resolved_sensor is None:
                    resolved_sensor = self._resolve_sensor_source(client, config.sensor_source)
                    self._emit_status(
                        f"Sensor de mídia: '{resolved_sensor}'. Calibrando estado parado…"
                    )

                if baseline is None:
                    baseline = self._calibrate(client, resolved_sensor)
                    if baseline is None:
                        if not self._enabled_event.is_set():
                            continue
                        raise RuntimeError(
                            f"não foi possível calibrar o sensor '{resolved_sensor}'"
                        )
                    self._emit_status(
                        f"Automação pronta • sensor: '{resolved_sensor}' • aguardando mídia."
                    )
                    self.signal_changed.emit(resolved_sensor, 0.0, False)
                    continue

                frame = self._capture_luma(client, resolved_sensor)
                if frame is None or len(frame) != len(baseline):
                    raise RuntimeError(
                        f"sensor '{resolved_sensor}' não retornou imagem válida"
                    )

                changed_percent = pixel_difference(baseline, frame)
                current_scene = self._current_scene(client)
                event = self._detector.update(changed_percent)
                self._emit_signal_snapshot(resolved_sensor, changed_percent, force=event is not None)

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
                resolved_sensor = None
                baseline = None
                self._detector.reset()
                self._reset_session()
                self._close_client(client)
                client = None
                self._stop_event.wait(2.0)

        self._close_client(client)

    def _emit_signal_snapshot(
        self,
        source_name: str,
        changed_percent: float,
        *,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        if not force and now - self._last_signal_emit_at < 1.0:
            return
        self._last_signal_emit_at = now
        self.signal_changed.emit(source_name, changed_percent, self._detector.active)

    def _connect(self, config: ObsConnectionConfig) -> obs.ReqClient | None:
        try:
            client = obs.ReqClient(
                host=config.host,
                port=config.port,
                password=config.password,
                timeout=3,
            )
            client.send("GetVersion", raw=True)
            self._emit_status("Automação conectada ao OBS; procurando sensor do JW Library…")
            return client
        except Exception as exc:
            message = str(exc).strip() or type(exc).__name__
            self.error.emit(f"Automação de mídia sem conexão com OBS: {message}")
            self._emit_status("Automação aguardando OBS WebSocket…")
            return None

    def _resolve_sensor_source(self, client: obs.ReqClient, scene_name: str) -> str:
        """Prefere a captura de janela do JW Library; usa a cena Mídia como fallback."""

        try:
            payload = client.send(
                "GetSceneItemList",
                {"sceneName": scene_name},
                raw=True,
            )
        except Exception:
            return scene_name

        items = payload.get("sceneItems") or payload.get("scene_items") or []
        best_source = scene_name
        best_score = 0

        for item in items:
            if not isinstance(item, dict):
                continue
            source_name = item.get("sourceName") or item.get("source_name")
            if not isinstance(source_name, str) or not source_name:
                continue

            try:
                input_payload = client.send(
                    "GetInputSettings",
                    {"inputName": source_name},
                    raw=True,
                )
            except Exception:
                continue

            input_kind = input_payload.get("inputKind") or input_payload.get("input_kind")
            if not isinstance(input_kind, str):
                input_kind = None
            settings = input_payload.get("inputSettings") or input_payload.get("input_settings")
            if not isinstance(settings, dict):
                settings = {}

            score = sensor_candidate_score(source_name, input_kind, settings)
            if score > best_score:
                best_source = source_name
                best_score = score

        return best_source

    def _calibrate(self, client: obs.ReqClient, source_name: str) -> bytes | None:
        candidate: bytes | None = None
        stable_hits = 0
        self._emit_status(
            f"Calibrando '{source_name}': deixe o JW Library sem mídia por alguns segundos."
        )

        while not self._stop_event.is_set() and self._enabled_event.is_set():
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
        self._emit_status(f"Mídia detectada: entrando em '{config.media_scene}'.")

    def _handle_media_ended(
        self,
        client: obs.ReqClient,
        config: MediaAutomationConfig,
        current_scene: str | None,
    ) -> None:
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
            self._emit_status(f"Mídia encerrada: retornando para '{return_scene}'.")
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
