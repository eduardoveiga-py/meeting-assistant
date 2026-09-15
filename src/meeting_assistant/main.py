from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from meeting_assistant.core.state import AppState
from meeting_assistant.services.settings import SettingsService
from meeting_assistant.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Meeting Assistant")
    app.setOrganizationName("Meeting Assistant")

    settings_service = SettingsService()
    settings = settings_service.load()

    state = AppState(simulation_enabled=settings.simulation_enabled)
    window = MainWindow(state)
    if settings.always_on_top:
        window.setWindowFlag(window.windowFlags().__class__.WindowStaysOnTopHint, True)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
