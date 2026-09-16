from __future__ import annotations

import ctypes
import sys
from importlib.resources import as_file, files

from PySide6.QtCore import QLoggingCategory, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from meeting_assistant.core.state import AppState
from meeting_assistant.services.display_service import DisplayService
from meeting_assistant.services.jwl_probe_service import JwlProbeService
from meeting_assistant.services.jwl_service import JwlService
from meeting_assistant.services.obs_controller import ObsConnectionConfig, ObsController
from meeting_assistant.services.settings import SettingsService
from meeting_assistant.ui.main_window import MainWindow

APP_USER_MODEL_ID = "MeetingAssistant.Desktop.3"


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)


def _configure_qt_logging() -> None:
    QLoggingCategory.setFilterRules("qt.qpa.fonts.warning=false")


def _load_app_icon() -> QIcon:
    resource = files("meeting_assistant.resources").joinpath("app_icon.svg")
    with as_file(resource) as icon_path:
        return QIcon(str(icon_path))


def main() -> int:
    _set_windows_app_id()
    _configure_qt_logging()

    app = QApplication(sys.argv)
    app.setApplicationName("Meeting Assistant")
    app.setOrganizationName("Meeting Assistant")

    app_icon = _load_app_icon()
    app.setWindowIcon(app_icon)

    settings_service = SettingsService()
    settings = settings_service.load()
    state = AppState(simulation_enabled=settings.simulation_enabled)

    obs_controller = ObsController(poll_interval=1.0, preview_interval=1.0)
    display_service = DisplayService(app)
    jwl_service = JwlService(interval_ms=2000)
    jwl_probe = JwlProbeService(jwl_service)

    window = MainWindow(
        state=state,
        settings=settings,
        settings_service=settings_service,
        obs_controller=obs_controller,
        display_service=display_service,
        jwl_service=jwl_service,
        jwl_probe=jwl_probe,
        app_icon=app_icon,
    )
    if settings.always_on_top:
        window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    app.aboutToQuit.connect(obs_controller.stop)
    app.aboutToQuit.connect(jwl_probe.stop)
    app.aboutToQuit.connect(jwl_service.stop)

    window.show()
    display_service.start()
    jwl_service.start()

    obs_controller.start(
        ObsConnectionConfig(
            host=settings.obs_host,
            port=settings.obs_port,
            password=settings.obs_password,
        )
    )

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
