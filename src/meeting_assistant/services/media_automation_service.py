from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import obsws_python as obs
from PySide6.QtCore import QObject, Signal

from meeting_assistant.services.idle_reference_store import IdleReferenceStore
from meeting_assistant.services.jwl_screen_sensor import (
    CaptureRegion,
    JwlScreenSensor,
    choose_capture_regions,
)
from meeting_assistant.services.jwl_service import JwlWindowInfo
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
    hall_display_bounds: tuple[int, int, int, int] | None = None
    simulation_enabled: bool = False
    idle_reference_key: str = ""


@dataclass(slots=True)
class MediaSignalDetector:
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


def classify_initial_signal(
    changed_percent: float,
    *,
    start_threshold: float = 3.0,
    end_threshold: float = 1.5,
) -> bool | None:
    """Classifica uma amostra inicial: True=mídia, False=repouso, None=ambígua."""

    if changed_percent >= start_threshold:
        return True
    if changed_percent <= end_threshold:
        return False
    return None


def select_trigger_hwnds(
    differences: dict[int, float],
    threshold: float,
) -> set[int]:
    return {
        hwnd
        for hwnd, changed_percent in differences.items()
        if changed_percent >= threshold
    }


def active_region_signal(
    differences: dict[int, float],
    trigger_hwnds: set[int],
) -> float | None:
    values = [
        differences[hwnd]
        for hwnd in trigger_hwnds
        if hwnd in differences
    ]
    return min(values) if values else None


def sensor_candidate_score(
    source_name: str,
    input_kind: str | None,
    settings: dict[str, Any],
) -> int:
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
    """Detecta mídia pela janela de saída real do JW Library no Windows."""

    status_changed = Signal(str)
    signal_changed = Signal(str, float, bool)
    media_started = Signal(str)
    media_ended = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        config_provider: Callable[[], MediaAutomationConfig],
        window_provider: Callable[[], list[JwlWindowInfo]],
        target_hwnd_provider: Callable[[], int | None] | None = None,
        reference_store: IdleReferenceStore | None = None,
        sample_interval_seconds: float = 0.18,
    ) -> None:
        super().__init__()
        self._config_provider = config_provider
        self._window_provider = window_provider
        self._target_hwnd_provider = target_hwnd_provider or (lambda: None)
        self._reference_store = reference_store or IdleReferenceStore()
        self._sample_interval = max(0.12, sample_interval_seconds)
        self._stop_event = threading.Event()
        self._enabled_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._detector = MediaSignalDetector()
        self._last_status: str | None = None
        self._last_signal_emit_at = 0.0
        self._trigger_hwnds: set[int] = set()
        self._active_since = 0.0
        self._sensor_label = "JW Library / Windows"
        self._initial_active_hits = 0
        self._initial_idle_hits = 0

    @property
    def enabled(self) -> bool:
        return self._enabled_event.is_set()

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._enabled_event.set()
            self._last_signal_emit_at = 0.0
            self._emit_status("Automação ativada; verificando a saída atual do JW Library…")
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
        sensor: JwlScreenSensor | None = None
        regions: list[CaptureRegion] = []
        baselines: dict[int, bytes] = {}
        active_config: MediaAutomationConfig | None = None
        was_enabled = False
        initial_state_pending = False
        initial_reference_loaded = False

        while not self._stop_event.is_set():
            if not self._enabled_event.is_set():
                if was_enabled:
                    self._emit_status(
                        "Automação pausada; monitoramento de mídia suspenso."
                    )
                was_enabled = False
                regions = []
                baselines = {}
                initial_state_pending = False
                initial_reference_loaded = False
                self._reset_detection()
                if sensor is not None:
                    sensor.close()
                    sensor = None
                self._stop_event.wait(0.15)
                continue

            was_enabled = True
            config = self._config_provider()
            if config != active_config:
                active_config = config
                regions = []
                baselines = {}
                initial_state_pending = False
                initial_reference_loaded = False
                self._reset_detection()

            if not config.simulation_enabled and config.hall_display_bounds is None:
                self._emit_status(
                    "Automação aguardando a Tela do Salão configurada aparecer no Windows…"
                )
                self._stop_event.wait(0.5)
                continue

            if sensor is None:
                try:
                    sensor = JwlScreenSensor()
                except Exception as exc:
                    self._emit_error(f"Falha ao iniciar captura do Windows: {exc}")
                    self._stop_event.wait(1.0)
                    continue

            target_hwnd = None if config.simulation_enabled else self._target_hwnd_provider()
            if not config.simulation_enabled and target_hwnd is None:
                self._emit_status(
                    "Automação aguardando o guardião identificar a saída do JW Library na Tela do Salão…"
                )
                self._stop_event.wait(0.35)
                continue

            if regions and target_hwnd is not None and regions[0].hwnd != target_hwnd:
                regions = []
                baselines = {}
                initial_state_pending = False
                initial_reference_loaded = False
                self._reset_detection()
                continue

            if not regions or not baselines:
                self._sensor_label = (
                    "JW Library / Simulação"
                    if config.simulation_enabled
                    else "JW Library / Tela do Salão"
                )
                regions = choose_capture_regions(
                    self._window_provider(),
                    preferred_display_bounds=(
                        None if config.simulation_enabled else config.hall_display_bounds
                    ),
                    preferred_hwnd=target_hwnd,
                )
                if not regions:
                    self._emit_status(
                        "Automação aguardando a janela de saída do JW Library ficar visível…"
                    )
                    self._stop_event.wait(0.35)
                    continue

                stored_reference = (
                    self._reference_store.load(config.idle_reference_key)
                    if not config.simulation_enabled and config.idle_reference_key
                    else None
                )
                if stored_reference is not None:
                    baselines = {regions[0].hwnd: stored_reference}
                    initial_state_pending = True
                    initial_reference_loaded = True
                    self._initial_active_hits = 0
                    self._initial_idle_hits = 0
                    self._reset_detection()
                    self._emit_status(
                        "Referência de repouso carregada; verificando se já existe mídia ativa…"
                    )
                    continue

                baselines = self._calibrate(sensor, regions)
                if not baselines:
                    if not self._enabled_event.is_set():
                        continue
                    regions = []
                    self._emit_status("Recalibrando a saída visual do JW Library…")
                    self._stop_event.wait(0.5)
                    continue

                regions = [region for region in regions if region.hwnd in baselines]
                if (
                    not config.simulation_enabled
                    and config.idle_reference_key
                    and len(regions) == 1
                ):
                    self._reference_store.save(
                        config.idle_reference_key,
                        baselines[regions[0].hwnd],
                    )
                    self._emit_status(
                        "Referência de repouso salva. Mantendo Palco e aguardando mídia."
                    )
                else:
                    self._emit_status(
                        "Automação pronta: aguardando foto/vídeo do JW Library."
                    )
                self._reset_detection()
                self.media_ended.emit(config.preferred_return_scene or "")
                self.signal_changed.emit(self._sensor_label, 0.0, False)
                initial_state_pending = False
                initial_reference_loaded = False
                continue

            try:
                differences = self._sample_differences(sensor, regions, baselines)
                if not differences:
                    raise RuntimeError("nenhuma região do JW Library pôde ser capturada")

                changed_percent = max(differences.values())
                if initial_state_pending and initial_reference_loaded:
                    classified = classify_initial_signal(
                        changed_percent,
                        start_threshold=self._detector.start_threshold,
                        end_threshold=self._detector.end_threshold,
                    )
                    if classified is True:
                        self._initial_active_hits += 1
                        self._initial_idle_hits = 0
                    elif classified is False:
                        self._initial_idle_hits += 1
                        self._initial_active_hits = 0
                    else:
                        self._initial_active_hits = 0
                        self._initial_idle_hits = 0

                    self._emit_signal_snapshot(changed_percent, force=True)
                    if self._initial_active_hits >= 2:
                        self._detector.active = True
                        self._trigger_hwnds = set(differences)
                        self._active_since = time.monotonic()
                        initial_state_pending = False
                        self.media_started.emit(config.media_scene)
                        self._emit_status(
                            "Mídia já estava ativa ao iniciar; recuperando a cena Mídias."
                        )
                    elif self._initial_idle_hits >= 2:
                        initial_state_pending = False
                        self._reset_detection()
                        self.media_ended.emit(config.preferred_return_scene or "")
                        self._emit_status(
                            "Saída em repouso confirmada; Palco ativo e automação pronta."
                        )
                    self._stop_event.wait(self._sample_interval)
                    continue

                event, changed_percent = self._update_detection(differences)
                self._emit_signal_snapshot(changed_percent, force=event is not None)

                if event == MediaSignalEvent.STARTED:
                    self.media_started.emit(config.media_scene)
                    self._emit_status("Foto/vídeo detectado: solicitando Mídias.")
                elif event == MediaSignalEvent.ENDED:
                    self.media_ended.emit(config.preferred_return_scene or "")
                    self._emit_status(
                        "Texto do Ano voltou à saída: solicitando retorno para Palco."
                    )
                    self._trigger_hwnds.clear()
                    self._active_since = 0.0

                self._stop_event.wait(self._sample_interval)
            except Exception as exc:
                self._emit_error(f"Automação visual: {exc}")
                regions = []
                baselines = {}
                initial_state_pending = False
                initial_reference_loaded = False
                self._reset_detection()
                self._stop_event.wait(0.5)

        if sensor is not None:
            sensor.close()

    def _update_detection(
        self,
        differences: dict[int, float],
    ) -> tuple[MediaSignalEvent | None, float]:
        if not self._detector.active:
            changed_percent = max(differences.values())
            event = self._detector.update(changed_percent)
            if event == MediaSignalEvent.STARTED:
                self._trigger_hwnds = select_trigger_hwnds(
                    differences,
                    self._detector.start_threshold,
                )
                self._active_since = time.monotonic()
            return event, changed_percent

        active_signal = active_region_signal(differences, self._trigger_hwnds)
        if active_signal is None:
            self._detector.end_hits = 0
            return None, max(differences.values())

        if time.monotonic() - self._active_since < 0.8:
            self._detector.end_hits = 0
            return None, active_signal

        event = self._detector.update(active_signal)
        return event, active_signal

    def _calibrate(
        self,
        sensor: JwlScreenSensor,
        regions: list[CaptureRegion],
    ) -> dict[int, bytes]:
        self._emit_status(
            "Primeira calibração: mantenha o Texto do Ano visível por cerca de 1 segundo."
        )
        candidates: dict[int, bytes] = {}
        stable_hits: dict[int, int] = {region.hwnd: 0 for region in regions}
        expected_hwnds = {region.hwnd for region in regions}
        deadline = time.monotonic() + 4.0
        ready: dict[int, bytes] = {}

        while (
            time.monotonic() < deadline
            and not self._stop_event.is_set()
            and self._enabled_event.is_set()
        ):
            for region in regions:
                frame = sensor.capture(region)
                if frame is None:
                    continue
                previous = candidates.get(region.hwnd)
                if previous is None:
                    candidates[region.hwnd] = frame
                    continue
                if pixel_difference(previous, frame) <= 1.0:
                    stable_hits[region.hwnd] += 1
                else:
                    candidates[region.hwnd] = frame
                    stable_hits[region.hwnd] = 0

            ready = {
                hwnd: candidates[hwnd]
                for hwnd, hits in stable_hits.items()
                if hits >= 3 and hwnd in candidates
            }
            if ready.keys() >= expected_hwnds:
                return ready
            self._stop_event.wait(0.18)

        return ready

    @staticmethod
    def _sample_differences(
        sensor: JwlScreenSensor,
        regions: list[CaptureRegion],
        baselines: dict[int, bytes],
    ) -> dict[int, float]:
        differences: dict[int, float] = {}
        for region in regions:
            baseline = baselines.get(region.hwnd)
            if baseline is None:
                continue
            frame = sensor.capture(region)
            if frame is None or len(frame) != len(baseline):
                continue
            differences[region.hwnd] = pixel_difference(baseline, frame)
        return differences

    def _reset_detection(self) -> None:
        self._detector.reset()
        self._trigger_hwnds.clear()
        self._active_since = 0.0
        self._initial_active_hits = 0
        self._initial_idle_hits = 0

    def _emit_signal_snapshot(self, changed_percent: float, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_signal_emit_at < 0.35:
            return
        self._last_signal_emit_at = now
        self.signal_changed.emit(
            self._sensor_label,
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
