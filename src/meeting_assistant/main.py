from __future__ import annotations

import ctypes
import sys
from importlib.resources import as_file, files

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from meeting_assistant.core.state import AppState
from meeting_assistant.services.settings import SettingsService
from meeting_assistant.ui.main_window import MainWindow

APP_USER_MODEL_ID = "MeetingAssistant.Desktop.3"


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)


def _load_app_icon() -> QIcon:
    resource = files("meeting_assistant.resources").joinpath("app_icon.svg")
    with as_file(resource) as icon_path:
        return QIcon(str(icon_path))


def main() -> int:
    _set_windows_app_id()

    app = QApplication(sys.argv)
    app.setApplicationName("Meeting Assistant")
    app.setOrganizationName("Meeting Assistant")

    app_icon = _load_app_icon()
    app.setWindowIcon(app_icon)

    settings_service = SettingsService()
    settings = settings_service.load()

    state = AppState(simulation_enabled=settings.simulation_enabled)
    window = MainWindow(state, app_icon=app_icon)
    if settings.always_on_top:
        window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
