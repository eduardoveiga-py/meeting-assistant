from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QObject, Signal


class SceneController(Protocol):
    def set_program_scene(self, scene_name: str) -> None: ...


class ToggleService(Protocol):
    def set_enabled(self, enabled: bool) -> None: ...


class AutomationCoordinator(QObject):
    """Garante estado inicial determinístico antes de armar a automação."""

    status_changed = Signal(str)

    def __init__(
        self,
        obs_controller: SceneController,
        media_automation: ToggleService,
        hall_output_guard: ToggleService,
        palco_scene_provider: Callable[[], str],
    ) -> None:
        super().__init__()
        self._obs = obs_controller
        self._media_automation = media_automation
        self._hall_output_guard = hall_output_guard
        self._palco_scene_provider = palco_scene_provider
        self._requested = False
        self._armed = False

    @property
    def requested(self) -> bool:
        return self._requested

    @property
    def armed(self) -> bool:
        return self._armed

    def request(self, enabled: bool) -> None:
        self._requested = enabled
        if not enabled:
            self._armed = False
            self._media_automation.set_enabled(False)
            self._hall_output_guard.set_enabled(False)
            return

        self._armed = False
        self._media_automation.set_enabled(False)
        self._hall_output_guard.set_enabled(True)
        palco_scene = self._palco_scene_provider().strip()
        if not palco_scene:
            self.status_changed.emit(
                "Não foi possível ativar: configure a cena Palco em Ajustes."
            )
            return

        self.status_changed.emit(
            "Preparando automação: retornando o OBS para Palco antes de armar o sensor…"
        )
        self._obs.set_program_scene(palco_scene)

    def on_scene_changed(self, scene_name: str) -> None:
        if not self._requested or self._armed:
            return
        if scene_name != self._palco_scene_provider().strip():
            return
        self._armed = True
        self._media_automation.set_enabled(True)

    def on_obs_connected(self, connected: bool, _message: str) -> None:
        if not connected or not self._requested or self._armed:
            return
        palco_scene = self._palco_scene_provider().strip()
        if not palco_scene:
            return
        self.status_changed.emit(
            "OBS reconectado; retornando para Palco antes de rearmar a automação…"
        )
        self._obs.set_program_scene(palco_scene)
