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
    ensure_fade_transition,
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
    preferred_return_scene: str | None = None


@dataclass(slots=True)
class MediaSignalDetector:
    """Converte diferença visual em início/fim com debounce curto."""

    start_threshold: float = 3.0
    end_threshold: float = 1.5
    start_hits_required: int = 2
    end_hits_required: int = 2
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
    changed = sum(
        1
        for before, after in zip(reference, current, strict=True)
        if abs(before - after) > PIXEL_THRESHOLD
    )
    return (changed / len(reference)) * 100.0


def sensor_candidate_score(
    source_name: str,
    input_kind: str | None,
    settings: dict[str, Any],
) -> int:
    """Pontua fontes que parecem ser a captura direta do JW Library."""

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


def set_program_scene(client: obs.ReqClient, scene_name: str) -> None:
    ensure_fade_transition(client)
    client.send(
        "SetCurrentProgramScene",
        {"sceneName": scene_name},
        raw=True,
    )


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
    """Fluxo determinístico Palco → Mídias → Palco."""

    status_changed = Signal(str)
    signal_changed = Signal(str, float, bool)
    media_started = Signal(str)
    media_ended = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        config_provider: Callable[[], MediaAutomationConfig],
        sample_interval_seconds: float = 0.18,
    ) -> None:
        super().__init__()
        self._config_provider = config_provider
        self._sample_interval = max(0.12, sample_interval_seconds)
        self._stop_event = threading.Event()
        self._enabled_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._detector = MediaSignalDetector()
        self._last_status: str | None = None
        self._last_signal_emit_at = 0.0
        self._active_since = 0.0
        self._scene_seen_media = False
        self._direct_seen_media = False

    @property
    def enabled(self) -> bool:
        return self._enabled_event.is_set()

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._enabled_event.set()
            self._last_signal_emit_at = 0.0
            self._emit_status("Automação ativada; calibrando saída do JW Library…")
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
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.5)

    def _run(self) -> None:
        client: obs.ReqClient | None = None
        active_config: MediaAutomationConfig | None = None
        scene_baseline: bytes | None = None
        direct_baseline: bytes | None = None
        direct_source: str | None = None
        was_enabled = False

        while not self._stop_event.is_set():
            if not self._enabled_event.is_set():
                if was_enabled:
                    self._emit_status(
                        "Automação pausada; monitoramento de mídia suspenso."
                    )
                was_enabled = False
                scene_baseline = None
                direct_baseline = None
                direct_source = None
                self._reset_detector()
                self._close_client(client)
                client = None
                self._stop_event.wait(0.15)
                continue

            was_enabled = True
            config = self._config_provider()
            if config != active_config:
                active_config = config
                scene_baseline = None
                direct_baseline = None
                direct_source = None
                self._reset_detector()
                self._close_client(client)
                client = None

            if not config.sensor_source or not config.media_scene:
                self._emit_status("Automação aguardando configuração da cena Mídias.")
                self._stop_event.wait(1.0)
                continue

            if client is None:
                client = self._connect(config.obs)
                if client is None:
                    self._stop_event.wait(1.0)
                    continue
                direct_source = self._resolve_direct_sensor(
                    client,
                    config.sensor_source,
                )
                scene_baseline = None
                direct_baseline = None

            try:
                if scene_baseline is None or direct_baseline is None:
                    scene_baseline = self._calibrate(
                        client,
                        config.sensor_source,
                        "cena Mídias",
                    )
                    if scene_baseline is None:
                        if not self._enabled_event.is_set():
                            continue
                        raise RuntimeError("não foi possível calibrar a cena Mídias")

                    assert direct_source is not None
                    if direct_source == config.sensor_source:
                        direct_baseline = scene_baseline
                    else:
                        direct_baseline = self._calibrate(
                            client,
                            direct_source,
                            direct_source,
                        )
                    if direct_baseline is None:
                        if not self._enabled_event.is_set():
                            continue
                        raise RuntimeError(
                            f"não foi possível calibrar '{direct_source}'"
                        )

                    self._emit_status(
                        "Automação pronta: aguardando foto/vídeo do JW Library."
                    )
                    sensor_label = self._sensor_label(
                        direct_source,
                        config.sensor_source,
                    )
                    self.signal_changed.emit(sensor_label, 0.0, False)
                    continue

                assert direct_source is not None
                scene_frame = self._capture_luma(client, config.sensor_source)
                direct_frame = (
                    scene_frame
                    if direct_source == config.sensor_source
                    else self._capture_luma(client, direct_source)
                )
                if scene_frame is None or len(scene_frame) != len(scene_baseline):
                    raise RuntimeError("a cena Mídias não retornou imagem válida")
                if direct_frame is None or len(direct_frame) != len(direct_baseline):
                    raise RuntimeError(
                        f"o sensor '{direct_source}' não retornou imagem válida"
                    )

                scene_diff = pixel_difference(scene_baseline, scene_frame)
                direct_diff = pixel_difference(direct_baseline, direct_frame)
                current_scene = self._current_scene(client)
                event = self._update_detection(scene_diff, direct_diff)
                display_signal = max(scene_diff, direct_diff)
                sensor_label = self._sensor_label(
                    direct_source,
                    config.sensor_source,
                )
                self._emit_signal_snapshot(
                    sensor_label,
                    display_signal,
                    force=event is not None,
                )

                if event == MediaSignalEvent.STARTED:
                    self._handle_media_started(client, config, current_scene)
                elif event == MediaSignalEvent.ENDED:
                    self._handle_media_ended(client, config, current_scene)

                self._stop_event.wait(self._sample_interval)
            except Exception as exc:
                message = str(exc).strip() or type(exc).__name__
                self.error.emit(f"Automação de mídia: {message}")
                self._emit_status("Automação reconectando e recalibrando sensores…")
                scene_baseline = None
                direct_baseline = None
                direct_source = None
                self._reset_detector()
                self._close_client(client)
                client = None
                self._stop_event.wait(1.0)

        self._close_client(client)

    def _update_detection(
        self,
        scene_diff: float,
        direct_diff: float,
    ) -> MediaSignalEvent | None:
        if not self._detector.active:
            start_signal = max(scene_diff, direct_diff)
            event = self._detector.update(start_signal)
            if event == MediaSignalEvent.STARTED:
                self._active_since = time.monotonic()
                self._scene_seen_media = scene_diff >= self._detector.start_threshold
                self._direct_seen_media = direct_diff >= self._detector.start_threshold
            return event

        if scene_diff >= self._detector.start_threshold:
            self._scene_seen_media = True
        if direct_diff >= self._detector.start_threshold:
            self._direct_seen_media = True

        if time.monotonic() - self._active_since < 1.0:
            self._detector.end_hits = 0
            return None

        scene_idle = self._scene_seen_media and scene_diff <= self._detector.end_threshold
        direct_idle = (
            self._direct_seen_media
            and direct_diff <= self._detector.end_threshold
        )
        end_signal = 0.0 if scene_idle or direct_idle else 100.0
        return self._detector.update(end_signal)

    def _connect(self, config: ObsConnectionConfig) -> obs.ReqClient | None:
        try:
            client = obs.ReqClient(
                host=config.host,
                port=config.port,
                password=config.password,
                timeout=3,
            )
            client.send("GetVersion", raw=True)
            ensure_fade_transition(client)
            self._emit_status("Automação conectada ao OBS; preparando sensores…")
            return client
        except Exception as exc:
            message = str(exc).strip() or type(exc).__name__
            self.error.emit(f"Automação sem conexão com OBS: {message}")
            self._emit_status("Automação aguardando OBS WebSocket…")
            return None

    def _resolve_direct_sensor(
        self,
        client: obs.ReqClient,
        scene_name: str,
    ) -> str:
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
            settings = input_payload.get("inputSettings") or input_payload.get(
                "input_settings"
            )
            if not isinstance(settings, dict):
                settings = {}
            score = sensor_candidate_score(source_name, input_kind, settings)
            if score > best_score:
                best_source = source_name
                best_score = score
        return best_source

    def _calibrate(
        self,
        client: obs.ReqClient,
        source_name: str,
        label: str,
    ) -> bytes | None:
        candidate: bytes | None = None
        stable_hits = 0
        self._emit_status(
            f"Calibrando {label}: deixe a saída no Texto do Ano + logo JW."
        )
        while not self._stop_event.is_set() and self._enabled_event.is_set():
            frame = self._capture_luma(client, source_name)
            if frame is None:
                self._stop_event.wait(0.18)
                continue
            if candidate is None or len(candidate) != len(frame):
                candidate = frame
                stable_hits = 0
            else:
                changed = pixel_difference(candidate, frame)
                if changed <= 0.8:
                    stable_hits += 1
                    if stable_hits >= 3:
                        return frame
                else:
                    candidate = frame
                    stable_hits = 0
            self._stop_event.wait(0.18)
        return None

    def _handle_media_started(
        self,
        client: obs.ReqClient,
        config: MediaAutomationConfig,
        current_scene: str | None,
    ) -> None:
        if current_scene != config.media_scene:
            set_program_scene(client, config.media_scene)
        self.media_started.emit(config.media_scene)
        self._emit_status("Foto/vídeo detectado: fade para Mídias.")

    def _handle_media_ended(
        self,
        client: obs.ReqClient,
        config: MediaAutomationConfig,
        current_scene: str | None,
    ) -> None:
        current_scene = self._current_scene(client) or current_scene
        return_scene = config.preferred_return_scene
        if current_scene == config.media_scene and return_scene:
            set_program_scene(client, return_scene)
            self.media_ended.emit(return_scene)
            self._emit_status(
                "Texto do Ano + logo JW detectados: fade de volta para Palco."
            )
        else:
            self.media_ended.emit(current_scene or "")
            self._emit_status(
                "Mídia terminou; cena manual atual preservada."
            )
        self._reset_detector()

    def _reset_detector(self) -> None:
        self._detector.reset()
        self._active_since = 0.0
        self._scene_seen_media = False
        self._direct_seen_media = False

    @staticmethod
    def _sensor_label(direct_source: str, scene_source: str) -> str:
        if direct_source == scene_source:
            return scene_source
        return f"{direct_source} + {scene_source}"

    def _emit_signal_snapshot(
        self,
        source_name: str,
        changed_percent: float,
        *,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        if not force and now - self._last_signal_emit_at < 0.5:
            return
        self._last_signal_emit_at = now
        self.signal_changed.emit(source_name, changed_percent, self._detector.active)

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
