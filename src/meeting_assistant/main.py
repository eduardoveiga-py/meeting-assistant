from __future__ import annotations

import ctypes
import sys
import time
from importlib.resources import as_file, files

from PySide6.QtCore import QLoggingCategory, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from meeting_assistant.core.state import AppState
from meeting_assistant.services.display_service import DisplayService, resolve_hall_display
from meeting_assistant.services.hall_monitor_sensor import HallMonitorSensorRegionProvider
from meeting_assistant.services.jwl_fast_window_guard import JwlFastWindowGuard
from meeting_assistant.services.jwl_probe_service import JwlProbeService
from meeting_assistant.services.jwl_service import JwlService
from meeting_assistant.services.jwl_uia_secondary_window import JwlUiaSecondaryWindowService
from meeting_assistant.services.jwl_virtual_desktop_pin import (
    JwlVirtualDesktopPinService,
    pin_result_to_dict,
)
from meeting_assistant.services.media_automation_service import (
    MediaAutomationConfig,
    MediaAutomationService,
)
from meeting_assistant.services.meeting_launcher import MeetingLauncherService
from meeting_assistant.services.obs_controller import ObsConnectionConfig, ObsController
from meeting_assistant.services.settings import SettingsService
from meeting_assistant.services.telemetry_service import TelemetryService
from meeting_assistant.services.zoom_hall_service import ZoomHallService
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

    # QApplication must be constructed before pywinauto/comtypes is imported.
    # The JW Library UIA service intentionally performs that import lazily on
    # its own STA worker thread, after Qt has established OLE and DPI awareness.
    app = QApplication(sys.argv)
    app.setApplicationName("Meeting Assistant")
    app.setOrganizationName("Meeting Assistant")

    app_icon = _load_app_icon()
    app.setWindowIcon(app_icon)

    settings_service = SettingsService()
    settings = settings_service.load()
    telemetry = TelemetryService(
        enabled=settings.telemetry_enabled,
        repo_url=settings.telemetry_repo_url,
        screenshots_enabled=settings.telemetry_screenshots,
    )
    telemetry.start()
    telemetry.event(
        "settings_loaded",
        simulation_enabled=settings.simulation_enabled,
        hall_display_configured=bool(settings.hall_display_key),
        zoom_link_configured=bool(settings.zoom_join_url),
        screenshots_enabled=settings.telemetry_screenshots,
    )
    telemetry.request_sync()

    state = AppState(simulation_enabled=settings.simulation_enabled)
    state.automation_enabled = False

    def current_obs_config() -> ObsConnectionConfig:
        return ObsConnectionConfig(
            host=settings.obs_host,
            port=settings.obs_port,
            password=settings.obs_password,
        )

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

    display_cache = display_service.snapshot()

    def update_display_cache(displays) -> None:
        nonlocal display_cache
        display_cache = list(displays)
        telemetry.event("displays_changed", displays=display_cache)

    display_service.displays_changed.connect(update_display_cache)

    def current_hall_display():
        if settings.simulation_enabled:
            return None
        return resolve_hall_display(
            list(display_cache),
            settings.hall_display_key,
        )

    jwl_secondary = JwlUiaSecondaryWindowService(
        display_provider=current_hall_display,
        interval_ms=650,
    )
    jwl_fast_guard = JwlFastWindowGuard(
        candidate_provider=lambda: jwl_secondary.current,
        display_provider=current_hall_display,
        interval_ms=180,
    )
    jwl_virtual_desktop = JwlVirtualDesktopPinService()
    hall_capture_region = HallMonitorSensorRegionProvider(current_hall_display)

    jwl_probe = JwlProbeService(
        secondary_service=jwl_secondary,
        display_snapshot_provider=lambda: list(display_cache),
        target_display_provider=current_hall_display,
    )
    media_automation = MediaAutomationService(
        config_provider=current_media_automation_config,
        secondary_window_provider=lambda: jwl_secondary.current,
        capture_region_provider=hall_capture_region,
        sample_interval_seconds=0.18,
    )
    meeting_launcher = MeetingLauncherService(lambda: settings)
    zoom_hall = ZoomHallService(
        display_provider=current_hall_display,
        jwl_window_provider=lambda: jwl_secondary.current,
    )

    window = MainWindow(
        state=state,
        settings=settings,
        settings_service=settings_service,
        obs_controller=obs_controller,
        display_service=display_service,
        jwl_service=jwl_service,
        jwl_probe=jwl_probe,
        meeting_launcher=meeting_launcher,
        zoom_hall_service=zoom_hall,
        app_icon=app_icon,
    )
    # Startup routing belongs to the media automation now. Preserving the OBS
    # scene here is essential when Meeting Assistant is reopened mid-video.
    window._startup_scene_applied = True
    window.set_telemetry_session(telemetry.session_id)
    window.set_telemetry_status(
        False,
        "Telemetria aguardando a primeira sincronização em segundo plano.",
    )
    telemetry.sync_status_changed.connect(window.set_telemetry_status)

    if settings.always_on_top:
        window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    media_automation.status_changed.connect(window.set_automation_status)
    media_automation.signal_changed.connect(window.set_automation_signal)
    media_automation.media_started.connect(obs_controller.set_program_scene)
    media_automation.media_ended.connect(obs_controller.set_program_scene)
    media_automation.error.connect(window.set_automation_status)

    media_automation.status_changed.connect(
        lambda message: telemetry.event("media_automation_status", message=message)
    )
    media_automation.media_started.connect(
        lambda scene: (
            telemetry.event("media_started", requested_scene=scene),
            telemetry.capture_screenshot("media-started"),
        )
    )
    media_automation.media_ended.connect(
        lambda scene: (
            telemetry.event("media_ended", requested_scene=scene),
            telemetry.capture_screenshot("media-ended"),
        )
    )
    media_automation.error.connect(
        lambda message: (
            telemetry.event("media_automation_error", severity="error", message=message),
            telemetry.request_sync(),
        )
    )

    last_sensor_telemetry_at = 0.0
    last_sensor_active: bool | None = None

    def record_sensor_signal(source: str, changed_percent: float, active: bool) -> None:
        nonlocal last_sensor_telemetry_at, last_sensor_active
        now = time.monotonic()
        if active == last_sensor_active and now - last_sensor_telemetry_at < 2.0:
            return
        last_sensor_telemetry_at = now
        last_sensor_active = active
        telemetry.event(
            "hall_sensor_sample",
            source=source,
            changed_percent=round(changed_percent, 2),
            media_active=active,
        )

    media_automation.signal_changed.connect(record_sensor_signal)

    obs_controller.connected_changed.connect(
        lambda connected, message: telemetry.event(
            "obs_connection",
            connected=connected,
            message=message,
        )
    )
    obs_controller.scene_changed.connect(
        lambda scene: telemetry.event("obs_program_scene", scene=scene)
    )
    obs_controller.error.connect(
        lambda message: (
            telemetry.event("obs_error", severity="error", message=message),
            telemetry.request_sync(),
        )
    )
    jwl_service.status_changed.connect(
        lambda running, message: telemetry.event(
            "jwl_status",
            running=running,
            message=message,
        )
    )
    jwl_secondary.status_changed.connect(
        lambda ok, message: telemetry.event(
            "jwl_secondary_status",
            ok=ok,
            message=message,
            hwnd=jwl_secondary.current.hwnd if jwl_secondary.current else 0,
        )
    )

    recovery_started_at: float | None = None

    def record_jwl_recovery(recovering: bool) -> None:
        nonlocal recovery_started_at
        now = time.monotonic()
        if recovering:
            recovery_started_at = now
            # Never let the exposed Windows desktop be classified as media
            # while the Hall output is being repaired.
            media_automation.set_enabled(False)
            telemetry.event(
                "jwl_recovery_started",
                hwnd=jwl_fast_guard.cached_hwnd,
                reason=jwl_fast_guard.last_recovery_reason,
            )
            return

        if recovery_started_at is not None:
            elapsed_ms = round((now - recovery_started_at) * 1000)
            telemetry.event(
                "jwl_recovery_finished",
                hwnd=jwl_fast_guard.cached_hwnd,
                elapsed_ms=elapsed_ms,
            )
            recovery_started_at = None

        if state.automation_enabled and not zoom_hall.active:
            media_automation.set_enabled(True)

    def record_jwl_candidate(hwnd: int, source: str) -> None:
        telemetry.event(
            "jwl_fast_guard_candidate",
            hwnd=hwnd,
            source=source,
        )
        if hwnd > 0:
            jwl_virtual_desktop.ensure_pinned(hwnd)

    jwl_fast_guard.recovery_changed.connect(record_jwl_recovery)
    jwl_fast_guard.candidate_changed.connect(record_jwl_candidate)
    jwl_fast_guard.shell_recovery_requested.connect(
        jwl_virtual_desktop.recover_shell_cloak
    )
    jwl_virtual_desktop.result.connect(
        lambda result: (
            telemetry.event(
                "jwl_virtual_desktop_pin",
                result=pin_result_to_dict(result),
            ),
            telemetry.request_sync(),
        )
    )
    jwl_fast_guard.recovery_detail.connect(
        lambda detail: telemetry.event(
            "jwl_recovery_attempt",
            detail=detail,
        )
    )

    meeting_launcher.progress_changed.connect(
        lambda message: telemetry.event("meeting_launcher_progress", message=message)
    )
    meeting_launcher.finished.connect(
        lambda summary: (
            telemetry.event("meeting_launcher_finished", summary=summary),
            telemetry.request_sync(),
        )
    )
    zoom_hall.status_changed.connect(
        lambda ok, message: telemetry.event("zoom_hall_status", ok=ok, message=message)
    )
    zoom_hall.active_changed.connect(
        lambda active, message: (
            telemetry.event("zoom_hall_active", active=active, message=message),
            telemetry.capture_screenshot("zoom-hall-on" if active else "zoom-hall-off"),
            telemetry.request_sync(),
        )
    )

    def apply_automation_runtime(enabled: bool) -> None:
        effective = bool(enabled and not zoom_hall.active)
        telemetry.event(
            "automation_runtime",
            requested=enabled,
            effective=effective,
            zoom_hall_active=zoom_hall.active,
        )
        media_automation.set_enabled(effective)
        jwl_secondary.set_guard_enabled(effective)
        jwl_fast_guard.set_enabled(effective)

    window.automation_enabled_changed.connect(apply_automation_runtime)
    zoom_hall.about_to_show.connect(lambda: apply_automation_runtime(False))
    zoom_hall.active_changed.connect(
        lambda active, _message: (
            apply_automation_runtime(state.automation_enabled) if not active else None
        )
    )
    jwl_secondary.status_changed.connect(
        lambda _ok, message: (
            window.set_automation_status(message)
            if state.automation_enabled and not media_automation.enabled
            else None
        )
    )

    app.aboutToQuit.connect(media_automation.stop)
    app.aboutToQuit.connect(lambda: zoom_hall.restore_jwl() if zoom_hall.active else None)
    app.aboutToQuit.connect(jwl_fast_guard.stop)
    app.aboutToQuit.connect(jwl_virtual_desktop.stop)
    app.aboutToQuit.connect(jwl_secondary.stop)
    app.aboutToQuit.connect(obs_controller.stop)
    app.aboutToQuit.connect(jwl_probe.stop)
    app.aboutToQuit.connect(jwl_service.stop)
    app.aboutToQuit.connect(lambda: telemetry.event("qt_about_to_quit"))
    app.aboutToQuit.connect(telemetry.stop)

    window.show()
    telemetry.event("ui_shown", session_id=telemetry.session_id)
    display_service.start()
    jwl_service.start()
    jwl_secondary.start()
    jwl_virtual_desktop.start()
    jwl_fast_guard.start()
    obs_controller.start(obs_config)
    media_automation.start()
    media_automation.set_enabled(False)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
