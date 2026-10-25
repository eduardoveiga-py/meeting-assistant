"""State machine differentiating between static image display and video playback with audio."""

from __future__ import annotations

import atexit
import logging
from enum import StrEnum
from typing import Any

from PySide6.QtCore import QObject, Signal

from meeting_assistant.services.profile_manager import MeetingProfile

logger = logging.getLogger(__name__)


class MeetingState(StrEnum):
    IDLE = "IDLE"
    CAMERA_LIVE = "CAMERA_LIVE"
    DISPLAYING_IMAGE = "DISPLAYING_IMAGE"
    PLAYING_VIDEO = "PLAYING_VIDEO"
    SCREEN_SHARE = "SCREEN_SHARE"
    EMERGENCY_MUTE = "EMERGENCY_MUTE"


class MeetingStateMachine(QObject):
    """Coordinates state transitions between camera, image, video, screenshare, and emergency mute."""

    state_changed = Signal(str, str)  # (old_state, new_state)
    transition_error = Signal(str)

    def __init__(
        self,
        obs_service: Any = None,
        profile: MeetingProfile | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.obs = obs_service
        self.profile = profile or MeetingProfile()
        self._current_state: MeetingState = MeetingState.IDLE
        self._previous_state: MeetingState = MeetingState.IDLE
        self._exit_handler_registered = False

        self._register_exit_handler()

    @property
    def current_state(self) -> MeetingState:
        return self._current_state

    @property
    def state(self) -> MeetingState:
        return self._current_state

    def _register_exit_handler(self) -> None:
        if not self._exit_handler_registered:
            atexit.register(self.emergency_restore_on_exit)
            self._exit_handler_registered = True

    def set_profile(self, profile: MeetingProfile) -> None:
        self.profile = profile

    def set_obs_service(self, obs_service: Any) -> None:
        self.obs = obs_service

    def transition_to(self, new_state: MeetingState | str) -> bool:
        if isinstance(new_state, str):
            try:
                new_state = MeetingState(new_state)
            except ValueError:
                self.transition_error.emit(f"Estado desconhecido: {new_state}")
                return False

        if new_state == self._current_state:
            return True

        old_state = self._current_state
        try:
            self._apply_state_effects(new_state)
            self._previous_state = old_state
            self._current_state = new_state
            self.state_changed.emit(old_state.value, new_state.value)
            logger.info("Estado alterado: %s -> %s", old_state.value, new_state.value)
            return True
        except Exception as exc:
            msg = f"Falha na transição para {new_state.value}: {exc}"
            logger.error(msg, exc_info=True)
            self.transition_error.emit(msg)
            return False

    def _apply_state_effects(self, state: MeetingState) -> None:
        if not self.obs:
            return

        p = self.profile
        if state == MeetingState.CAMERA_LIVE:
            self._safe_switch_scene(p.scene_camera)
            self._safe_set_mute(p.mic_input_name, False)
            self._safe_set_mute(p.media_input_name, True)

        elif state == MeetingState.DISPLAYING_IMAGE:
            self._safe_switch_scene(p.scene_media)
            # CRITICAL PRESERVATION LAW: Speaker microphone remains UNMUTED for comments!
            self._safe_set_mute(p.mic_input_name, False)
            self._safe_set_mute(p.media_input_name, True)

        elif state == MeetingState.PLAYING_VIDEO:
            self._safe_switch_scene(p.scene_media)
            # Video with active audio: mute mic to prevent feedback, unmute media
            self._safe_set_mute(p.mic_input_name, True)
            self._safe_set_mute(p.media_input_name, False)

        elif state == MeetingState.SCREEN_SHARE:
            self._safe_switch_scene(p.scene_screenshare)
            self._safe_set_mute(p.mic_input_name, False)

        elif state == MeetingState.EMERGENCY_MUTE:
            self._safe_switch_scene(p.scene_safe)
            self._safe_set_mute(p.mic_input_name, True)
            self._safe_set_mute(p.media_input_name, True)

    def on_secondary_window_appeared(self, has_audio: bool = False) -> None:
        """Called when a secondary media/window projection appears."""
        if has_audio:
            self.transition_to(MeetingState.PLAYING_VIDEO)
        else:
            self.transition_to(MeetingState.DISPLAYING_IMAGE)

    def on_media_audio_started(self) -> None:
        """Called when WASAPI meters detect active audio from a media process."""
        if self._current_state in (
            MeetingState.CAMERA_LIVE,
            MeetingState.DISPLAYING_IMAGE,
            MeetingState.IDLE,
        ):
            self.transition_to(MeetingState.PLAYING_VIDEO)

    def on_media_audio_stopped(self) -> None:
        """Called when media audio ceases (after release hold verification)."""
        if self._current_state == MeetingState.PLAYING_VIDEO:
            self.transition_to(MeetingState.CAMERA_LIVE)

    def on_emergency_mute(self) -> None:
        self.transition_to(MeetingState.EMERGENCY_MUTE)

    def on_restore_camera(self) -> None:
        self.transition_to(MeetingState.CAMERA_LIVE)

    def emergency_restore_on_exit(self) -> None:
        """Fail-Safe called upon app shutdown (closeEvent and atexit).

        Ensures the microphone in OBS is NEVER left muted accidentally.
        """
        if not self.obs:
            return
        try:
            logger.info("Executando fail-safe emergency_restore_on_exit: desmutando microfone.")
            self._safe_set_mute(self.profile.mic_input_name, False)
        except Exception as exc:
            logger.warning("Falha no emergency_restore_on_exit: %s", exc)

    def _safe_switch_scene(self, scene_name: str) -> None:
        if not scene_name:
            return
        try:
            if hasattr(self.obs, "switch_scene"):
                self.obs.switch_scene(scene_name)
            elif hasattr(self.obs, "set_program_scene"):
                self.obs.set_program_scene(scene_name)
        except Exception as exc:
            logger.warning("Não foi possível mudar de cena para '%s': %s", scene_name, exc)

    def _safe_set_mute(self, input_name: str, muted: bool) -> None:
        if not input_name:
            return
        try:
            if hasattr(self.obs, "set_input_mute"):
                self.obs.set_input_mute(input_name, muted)
            elif hasattr(self.obs, "set_muted"):
                self.obs.set_muted(input_name, muted)
        except Exception as exc:
            logger.warning("Não foi possível alterar mute de '%s' para %s: %s", input_name, muted, exc)
