from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import obsws_python as obs
from PySide6.QtCore import QObject, Signal

from meeting_assistant.services.jwl_idle_reference import (
    JwlIdleReference,
    JwlIdleReferenceStore,
)
from meeting_assistant.services.jwl_screen_sensor import (
    SAMPLE_HEIGHT,
    SAMPLE_WIDTH,
    CaptureRegion,
    JwlScreenSensor,
)
from meeting_assistant.services.jwl_secondary_window import JwlSecondaryWindowInfo
from meeting_assistant.services.obs_controller import (
    ObsConnectionConfig,
    ensure_fade_transition,
)

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
    """Convert visual difference into start/end events with short debounce."""

    start_threshold: float = 3.0
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
    changed = sum(
        1
        for before, after in zip(reference, current, strict=True)
        if abs(before - after) > PIXEL_THRESHOLD
    )
    return (changed / len(reference)) * 100.0


def dark_pixel_ratio(frame: bytes, *, threshold: int = 48) -> float:
    if not frame:
        return 0.0
    dark = sum(1 for value in frame if value <= threshold)
    return (dark / len(frame)) * 100.0


def sensor_candidate_score(
    source_name: str,
    input_kind: str | None,
    settings: dict[str, Any],
) -> int:
    """Compatibility helper retained for older OBS diagnostics."""

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


def capture_region_for_secondary(window: JwlSecondaryWindowInfo) -> CaptureRegion:
    """Use one stable central crop from the actual Hall-output window."""

    width = window.rect.width
    height = window.rect.height
    crop_width = min(960, max(320, int(width * 0.76)))
    crop_height = min(540, max(180, int(height * 0.66)))
    left = window.rect.left + max(0, (width - crop_width) // 2)
    top = window.rect.top + max(0, (height - crop_height) // 2)
    return CaptureRegion(
        hwnd=window.hwnd,
        left=left,
        top=top,
        width=crop_width,
        height=crop_height,
    )


class MediaAutomationService(QObject):
    """Automate Palco/Mídias from pixels actually visible on the Hall display."""

    status_changed = Signal(str)
    signal_changed = Signal(str, float, bool)
    media_started = Signal(str)
    media_ended = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        config_provider: Callable[[], MediaAutomationConfig],
        secondary_window_provider: Callable[[], JwlSecondaryWindowInfo | None] | None = None,
        *,
        capture_region_provider: Callable[[], CaptureRegion | None] | None = None,
        reference_store: JwlIdleReferenceStore | None = None,
        sample_interval_seconds: float = 0.18,
    ) -> None:
        super().__init__()
        self._config_provider = config_provider
        self._secondary_window_provider = secondary_window_provider
        self._capture_region_provider = capture_region_provider
        self._reference_store = reference_store or JwlIdleReferenceStore()
        self._sample_interval = max(0.12, sample_interval_seconds)
        self._stop_event = threading.Event()
        self._enabled_event = threading.Event()
        self._recalibrate_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._detector = MediaSignalDetector()
        self._last_status: str | None = None
        self._last_signal_emit_at = 0.0

    @property
    def enabled(self) -> bool:
        return self._enabled_event.is_set()

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._enabled_event.set()
            self._last_signal_emit_at = 0.0
            self._emit_status("Automação ativada; lendo a Tela do Salão…")
        else:
            self._enabled_event.clear()
            self._emit_status("Automação pausada; monitoramento de mídia suspenso.")

    def reset_idle_reference(self) -> None:
        # The capture worker owns its cached reference and all reference I/O.
        # Keep the last good file until a replacement has actually been saved.
        self._recalibrate_event.set()
        self._emit_status(
            "Nova calibração solicitada; mantenha apenas o Texto do Ano visível."
        )

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
        sensor: JwlScreenSensor | None = None
        active_config: MediaAutomationConfig | None = None
        reference = self._reference_store.load()
        active_region_key: tuple[int, int, int, int] | None = None
        initial_route_pending = True
        idle_hits = 0

        while not self._stop_event.is_set():
            if self._recalibrate_event.is_set():
                self._recalibrate_event.clear()
                reference = None
                initial_route_pending = True
                idle_hits = 0
                self._detector.reset()
            if not self._enabled_event.is_set():
                active_region_key = None
                initial_route_pending = True
                idle_hits = 0
                self._detector.reset()
                if sensor is not None:
                    sensor.close()
                    sensor = None
                self._stop_event.wait(0.15)
                continue

            config = self._config_provider()
            if config != active_config:
                active_config = config
                initial_route_pending = True
                idle_hits = 0
                self._detector.reset()

            window = (
                self._secondary_window_provider()
                if self._secondary_window_provider is not None
                else None
            )
            if window is not None and (window.minimized or not window.visible):
                self._emit_status(
                    "Saída JWL localizada; aguardando o guardião restaurá-la na Tela do Salão…"
                )
                self._stop_event.wait(0.25)
                continue

            region = (
                self._capture_region_provider()
                if self._capture_region_provider is not None
                else None
            )
            if region is None and window is not None:
                region = capture_region_for_secondary(window)
            if region is None:
                self._emit_status("Automação aguardando a Tela do Salão física…")
                active_region_key = None
                self._stop_event.wait(0.35)
                continue

            if sensor is None:
                try:
                    sensor = JwlScreenSensor()
                except Exception as exc:
                    self._emit_error(f"Falha ao iniciar captura do Windows: {exc}")
                    self._stop_event.wait(1.0)
                    continue

            region_key = (region.left, region.top, region.width, region.height)
            if active_region_key != region_key:
                active_region_key = region_key
                initial_route_pending = True
                idle_hits = 0
                self._detector.reset()

            if reference is None:
                reference = self._calibrate_first_reference(sensor, region)
                if reference is None:
                    self._stop_event.wait(0.35)
                    continue
                try:
                    self._reference_store.save(reference)
                except (OSError, ValueError) as exc:
                    self._emit_error(f"Não foi possível salvar o repouso do JW Library: {exc}")
                    reference = None
                    self._stop_event.wait(0.7)
                    continue
                self._emit_status(
                    "Referência do Texto do Ano salva; iniciando automação em Palco."
                )
                self.signal_changed.emit("Tela do Salão / pixels nativos", 0.0, False)
                self.media_ended.emit(config.preferred_return_scene or "")
                initial_route_pending = False
                self._detector.reset()
                self._stop_event.wait(self._sample_interval)
                continue

            frame = sensor.capture(region)
            if self._recalibrate_event.is_set() or not self.enabled:
                continue
            if frame is None:
                self._emit_status(
                    "Tela do Salão encontrada, mas o frame ainda não pôde ser lido; tentando novamente…"
                )
                self._stop_event.wait(0.3)
                continue

            try:
                changed_percent = pixel_difference(reference.pixels, frame)
            except ValueError:
                self._reference_store.clear()
                reference = None
                initial_route_pending = True
                self._emit_status("Referência visual incompatível; recalibrando em segurança…")
                continue

            if initial_route_pending:
                event, idle_hits = self._classify_initial_state(changed_percent, idle_hits)
                if event == MediaSignalEvent.STARTED:
                    self._detector.active = True
                elif event == MediaSignalEvent.ENDED:
                    self._detector.reset()
                self._emit_signal_snapshot(changed_percent, force=event is not None)

                if event == MediaSignalEvent.STARTED:
                    self.media_started.emit(config.media_scene)
                    self._emit_status(
                        "Mídia já estava ativa ao iniciar; recuperando a cena Mídias."
                    )
                    initial_route_pending = False
                elif event == MediaSignalEvent.ENDED:
                    self.media_ended.emit(config.preferred_return_scene or "")
                    self._emit_status(
                        "Tela do Salão está em repouso; mantendo/recuperando Palco."
                    )
                    initial_route_pending = False
                self._stop_event.wait(self._sample_interval)
                continue

            event = self._detector.update(changed_percent)
            self._emit_signal_snapshot(changed_percent, force=event is not None)

            if event == MediaSignalEvent.STARTED:
                self.media_started.emit(config.media_scene)
                self._emit_status("Foto/vídeo detectado na Tela do Salão: solicitando Mídias.")
            elif event == MediaSignalEvent.ENDED:
                self.media_ended.emit(config.preferred_return_scene or "")
                self._emit_status("Texto do Ano reapareceu: solicitando retorno para Palco.")

            self._stop_event.wait(self._sample_interval)

        if sensor is not None:
            sensor.close()

    def _calibrate_first_reference(
        self,
        sensor: JwlScreenSensor,
        region: CaptureRegion,
    ) -> JwlIdleReference | None:
        self._emit_status(
            "Primeira calibração: mantenha o Texto do Ano visível na Tela do Salão por 1 segundo."
        )
        previous: bytes | None = None
        stable_hits = 0
        deadline = time.monotonic() + 6.0

        while (
            time.monotonic() < deadline
            and not self._stop_event.is_set()
            and self._enabled_event.is_set()
        ):
            frame = sensor.capture(region)
            if frame is None:
                self._stop_event.wait(0.18)
                continue

            # The configured idle screen is intentionally black with light year
            # text/logo. Refuse to learn a bright stable photo as "idle" if the
            # app is started for the first time while media is already showing.
            if dark_pixel_ratio(frame) < 65.0:
                stable_hits = 0
                previous = frame
                self._emit_status(
                    "Aguardando o Texto do Ano para criar a referência de repouso…"
                )
                self._stop_event.wait(0.18)
                continue

            if previous is None:
                previous = frame
                self._stop_event.wait(0.18)
                continue

            if pixel_difference(previous, frame) <= 0.8:
                stable_hits += 1
            else:
                stable_hits = 0
                previous = frame

            if stable_hits >= 5:
                return JwlIdleReference(
                    pixels=frame,
                    sample_width=SAMPLE_WIDTH,
                    sample_height=SAMPLE_HEIGHT,
                )
            self._stop_event.wait(0.18)

        self._emit_status(
            "Não foi possível calibrar o repouso; deixe o Texto do Ano visível e tente novamente."
        )
        return None

    def _classify_initial_state(
        self,
        changed_percent: float,
        idle_hits: int,
    ) -> tuple[MediaSignalEvent | None, int]:
        if changed_percent >= self._detector.start_threshold:
            self._detector.start_hits += 1
            idle_hits = 0
            if self._detector.start_hits >= self._detector.start_hits_required:
                self._detector.start_hits = 0
                return MediaSignalEvent.STARTED, 0
            return None, 0

        self._detector.start_hits = 0
        if changed_percent <= self._detector.end_threshold:
            idle_hits += 1
            if idle_hits >= 2:
                return MediaSignalEvent.ENDED, 0
            return None, idle_hits

        return None, 0

    def _emit_signal_snapshot(self, changed_percent: float, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_signal_emit_at < 0.35:
            return
        self._last_signal_emit_at = now
        self.signal_changed.emit(
            "Tela do Salão / pixels nativos",
            changed_percent,
            self._detector.active,
        )

    def _emit_error(self, message: str) -> None:
        self.error.emit(message)
        self._emit_status(message)

    def _emit_status(self, message: str) -> None:
        if message == self._last_status:
            return
        self._last_status = message
        self.status_changed.emit(message)
