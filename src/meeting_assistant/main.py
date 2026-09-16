from __future__ import annotations

import ctypes
import sys
from importlib.resources import as_file, files

from PySide6.QtCore import QLoggingCategory, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from meeting_assistant.core.state import AppState
from meeting_assistant.services.display_service import DisplayService
from meeting_assistant.services.jwl_service import JwlService, JwlWindowInfo
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


def _format_jwl_snapshot(snapshot: list[JwlWindowInfo]) -> str:
    if not snapshot:
        return "JW Library detectado, mas nenhuma janela candidata está visível."

    lines = [f"JW Library • {len(snapshot)} janela(s) candidata(s)"]
    for item in snapshot:
        lines.append(
            f"HWND {item.hwnd} • PID {item.pid} • {item.process_name or '?'}\n"
            f"{item.class_name} • {item.size} • {item.title}"
        )
    return "\n\n".join(lines)


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

    window = MainWindow(
        state=state,
        settings=settings,
        settings_service=settings_service,
        obs_controller=obs_controller,
        display_service=display_service,
        app_icon=app_icon,
    )
    if settings.always_on_top:
        window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    def on_jwl_status(running: bool, message: str) -> None:
        window._set_component_status(  # noqa: SLF001 - composition root wires services to UI
            "JW Library",
            "ok" if running else "error",
            "● JW Library",
            message,
        )

    def on_jwl_snapshot(snapshot: list[JwlWindowInfo]) -> None:
        window.status_labels["JW Library"].setToolTip(_format_jwl_snapshot(snapshot))

    jwl_service.status_changed.connect(on_jwl_status)
    jwl_service.snapshot_changed.connect(on_jwl_snapshot)

    app.aboutToQuit.connect(obs_controller.stop)
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
