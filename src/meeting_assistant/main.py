from __future__ import annotations

import ctypes
import sys
from importlib.resources import as_file, files

from PySide6.QtCore import QLoggingCategory, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from meeting_assistant.core.state import AppState
from meeting_assistant.services.display_service import DisplayService, resolve_hall_display
from meeting_assistant.services.jwl_probe_service import JwlProbeService
from meeting_assistant.services.jwl_secondary_window import JwlSecondaryWindowService
from meeting_assistant.services.jwl_service import JwlService
from meeting_assistant.services.media_automation_service import (
    MediaAutomationConfig,
    MediaAutomationService,
)
from meeting_assistant.services.obs_controller import ObsConnectionConfig, ObsController
from meeting_assistant.services.obs_visual_probe_service import ObsVisualProbeService
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
    state.automation_enabled = False

    def current_obs_config() -> ObsConnectionConfig:
        return ObsConnectionConfig(
            host=settings.obs_host,
            port=settings.obs_port,
            password=settings.obs_password,
        )

    def current_probe_config() -> tuple[ObsConnectionConfig, str]:
        return current_obs_config(), settings.scene_media

    def current_media_automation_config() -> MediaAutomationConfig:
        eligible = tuple(
            scene
            for scene in (settings.scene_background, settings.scene_speaker)
            if scene
        )
        return MediaAutomationConfig(
            obs=current_obs_config(),
            sensor_source=settings.scene_media,
            media_scene=settings.scene_media,
            eligible_return_scenes=eligible,
            preferred_return_scene=settings.scene_speaker,
        )

    obs_config = current_obs_config()
    obs_controller = ObsController(poll_interval=0.5, preview_interval=0.15)
    display_service = DisplayService(app)
    jwl_service = JwlService(interval_ms=2000)

    def current_hall_display():
        if settings.simulation_enabled:
            return None
        return resolve_hall_display(
            display_service.snapshot(),
            settings.hall_display_key,
        )

    jwl_secondary = JwlSecondaryWindowService(
        display_provider=current_hall_display,
        interval_ms=450,
    )

    visual_probe = ObsVisualProbeService()
    jwl_probe = JwlProbeService(
        visual_probe=visual_probe,
        config_provider=current_probe_config,
    )
    media_automation = MediaAutomationService(
        config_provider=current_media_automation_config,
        secondary_window_provider=lambda: jwl_secondary.current,
        sample_interval_seconds=0.18,
    )

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
    # Startup routing belongs to the media automation now. Preserving the OBS
    # scene here is essential when Meeting Assistant is reopened mid-video.
    window._startup_scene_applied = True

    if settings.always_on_top:
        window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    media_automation.status_changed.connect(window.set_automation_status)
    media_automation.signal_changed.connect(window.set_automation_signal)
    media_automation.media_started.connect(obs_controller.set_program_scene)
    media_automation.media_ended.connect(obs_controller.set_program_scene)
    media_automation.error.connect(window.set_automation_status)
    window.automation_enabled_changed.connect(media_automation.set_enabled)
    window.automation_enabled_changed.connect(jwl_secondary.set_guard_enabled)
    jwl_secondary.status_changed.connect(
        lambda _ok, message: (
            window.set_automation_status(message)
            if state.automation_enabled and not media_automation.enabled
            else None
        )
    )

    app.aboutToQuit.connect(media_automation.stop)
    app.aboutToQuit.connect(jwl_secondary.stop)
    app.aboutToQuit.connect(obs_controller.stop)
    app.aboutToQuit.connect(jwl_probe.stop)
    app.aboutToQuit.connect(jwl_service.stop)

    window.show()
    display_service.start()
    jwl_service.start()
    jwl_secondary.start()
    obs_controller.start(obs_config)
    media_automation.start()
    media_automation.set_enabled(False)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
