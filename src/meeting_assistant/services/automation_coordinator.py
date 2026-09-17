from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QObject, Signal


class ToggleService(Protocol):
    def set_enabled(self, enabled: bool) -> None: ...


class AutomationCoordinator(QObject):
    """Liga/desliga guardião e sensor como uma única automação operacional."""

    status_changed = Signal(str)

    def __init__(
        self,
        media_automation: ToggleService,
        hall_output_guard: ToggleService,
    ) -> None:
        super().__init__()
        self._media_automation = media_automation
        self._hall_output_guard = hall_output_guard
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
        self._armed = enabled
        if not enabled:
            self._media_automation.set_enabled(False)
            self._hall_output_guard.set_enabled(False)
            self.status_changed.emit("Automação pausada.")
            return

        # O guardião vem primeiro para fornecer um HWND estável ao sensor.
        self._hall_output_guard.set_enabled(True)
        self._media_automation.set_enabled(True)
        self.status_changed.emit(
            "Verificando o estado atual da Tela do Salão antes de escolher Palco ou Mídias…"
        )
