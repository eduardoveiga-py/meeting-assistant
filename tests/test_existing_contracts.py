"""Test contract validation for all core services, public classes, and UI components.

Serves as an anti-regression lock across all development and stabilization phases.
"""

from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication

from meeting_assistant.core.state import AppState, OperatingMode
from meeting_assistant.services.camera_session import CameraSession
from meeting_assistant.services.display_service import DisplayService
from meeting_assistant.services.jwl_fast_window_guard import JwlFastWindowGuard
from meeting_assistant.services.jwl_probe_service import JwlProbeService
from meeting_assistant.services.jwl_secondary_window import JwlSecondaryWindowService
from meeting_assistant.services.jwl_service import JwlService
from meeting_assistant.services.meeting_launcher import MeetingLauncherService
from meeting_assistant.services.meeting_shutdown import MeetingShutdownService
from meeting_assistant.services.obs_controller import ObsController
from meeting_assistant.services.settings import AppSettings, SettingsService
from meeting_assistant.services.telemetry_service import TelemetryService
from meeting_assistant.services.yeartext_store import YeartextStore
from meeting_assistant.services.zoom_hall_service import ZoomHallService
from meeting_assistant.ui.audio_setup_dialog import AudioSetupDialog
from meeting_assistant.ui.main_window import MainWindow
from meeting_assistant.ui.settings_dialog import SettingsDialog
from meeting_assistant.ui.setup_assistant_dialog import SetupAssistantDialog
from meeting_assistant.ui.virtual_camera_dialog import VirtualCameraDialog


def test_core_state_and_settings_contract():
    state = AppState()
    assert state.current_mode == OperatingMode.BACKGROUND
    assert hasattr(state, "automation_enabled")
    assert hasattr(state, "simulation_enabled")

    settings = AppSettings()
    assert hasattr(settings, "obs_host")
    assert hasattr(settings, "obs_port")
    assert hasattr(settings, "obs_password")
    assert hasattr(settings, "scene_speaker")
    assert hasattr(settings, "scene_media")
    assert hasattr(settings, "scene_background")


def test_services_instantiation_contract(tmp_path):
    settings_file = tmp_path / "settings.json"
    settings_service = SettingsService(settings_file)
    settings = settings_service.load()

    obs_ctrl = ObsController()
    assert hasattr(obs_ctrl, "start")
    assert hasattr(obs_ctrl, "stop")
    assert hasattr(obs_ctrl, "set_program_scene")
    assert hasattr(obs_ctrl, "reconfigure")

    app = QApplication.instance() or QApplication([])
    disp_service = DisplayService(app)
    assert hasattr(disp_service, "snapshot")

    jwl = JwlService()
    assert hasattr(jwl, "snapshot")
    assert hasattr(jwl, "scan")

    sec_service = JwlSecondaryWindowService(lambda: None)
    probe = JwlProbeService(sec_service, disp_service.snapshot, lambda: None)
    assert hasattr(probe, "start")

    launcher = MeetingLauncherService(lambda: settings)
    assert hasattr(launcher, "start_meeting")
    assert hasattr(launcher, "end_meeting")

    zoom = ZoomHallService(lambda: None, lambda: None)
    assert hasattr(zoom, "show_on_hall")
    assert hasattr(zoom, "restore_jwl")

    camera = CameraSession()
    assert hasattr(camera, "start")
    assert hasattr(camera, "stop")

    guard = JwlFastWindowGuard(lambda: None, lambda: None)
    assert hasattr(guard, "start")
    assert hasattr(guard, "stop")

    telemetry = TelemetryService(enabled=False)
    assert hasattr(telemetry, "event")

    yt_dir = tmp_path / "yeartext"
    yt_dir.mkdir()
    yeartext = YeartextStore(yt_dir)
    assert hasattr(yeartext, "current")

    shutdown = MeetingShutdownService()
    assert hasattr(shutdown, "start")
    assert hasattr(shutdown, "stop")


def test_ui_dialogs_instantiation_contract(tmp_path):
    _app = QApplication.instance() or QApplication([])
    settings = AppSettings()
    store = SettingsService(tmp_path / "settings.json")
    state = AppState()

    services = [MagicMock() for _ in range(6)]
    services[1].snapshot.return_value = []
    services[2].snapshot.return_value = []
    services[5].active = services[5].returning = False

    main_win = MainWindow(state, settings, store, *services)
    assert main_win is not None
    assert hasattr(main_win, "automation_enabled_changed")
    assert hasattr(main_win, "idle_reference_requested")

    audio_dlg = AudioSetupDialog(services[0], settings, parent=main_win, settings_service=store)
    assert audio_dlg is not None

    settings_dlg = SettingsDialog(settings, ["Palco", "Mídias"], parent=main_win)
    assert settings_dlg is not None

    setup_dlg = SetupAssistantDialog(main_win)
    assert setup_dlg is not None

    vcam_dlg = VirtualCameraDialog(parent=main_win)
    assert vcam_dlg is not None
