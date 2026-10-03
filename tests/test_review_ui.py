from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication, QScrollArea

from meeting_assistant.core.state import AppState
from meeting_assistant.services.meeting_shutdown import EndSummary
from meeting_assistant.services.settings import AppSettings, SettingsService
from meeting_assistant.ui.main_window import MainWindow


def make_window(tmp_path):
    services = [MagicMock() for _ in range(6)]
    services[1].snapshot.return_value = []
    services[2].snapshot.return_value = []
    services[4].busy = False
    services[5].active = False
    services[5].returning = False
    return MainWindow(AppState(), AppSettings(), SettingsService(tmp_path / "settings.json"), *services)


@pytest.mark.parametrize("state", ["live", "muted", "unknown"])
def test_every_microphone_state_and_update_banner_fit_operator_width(tmp_path, state):
    window = make_window(tmp_path)
    window.resize(520, 780)
    window.show()
    window._zoom_audio_result(state, "Diagnostic")
    window._on_update_available("0.10.0", "", "Long release notes")
    QApplication.processEvents()
    assert window.findChild(QScrollArea).horizontalScrollBar().maximum() == 0
    assert window.width() == 520
    window.close()


def test_end_meeting_pauses_automation_and_waits_for_verified_result(tmp_path):
    window = make_window(tmp_path)
    window.state.automation_enabled = True
    window.launcher.end_meeting.return_value = True
    window._end_meeting()
    assert not window.state.automation_enabled
    assert window._meeting_ending
    assert not window.end_meeting_button.isEnabled()
    window.obs.operator_task.assert_called_with("stop_virtual")
    window._on_end_finished(EndSummary(("zoom.exe",), ("zoom.exe",), ()))
    assert "pendente" in window.mode_label.text()
    assert window._meeting_active
    window._on_end_finished(EndSummary(("zoom.exe",), (), ()))
    assert not window._meeting_active
    window.close()


def test_layout_save_uses_roles_and_preserves_previous_jwl_when_temporarily_unavailable(tmp_path):
    window = make_window(tmp_path)
    role = {"monitor": "screen", "relative": [0.4, 0, 0.6, 1]}
    window.settings.window_layouts = {"version": 2, "roles": {"jwl_main": role}}
    window.layout_service = MagicMock()
    window.layout_service.latest = {}
    window.show()
    QApplication.processEvents()
    window._persist_layout()
    saved = window.settings_service.load().window_layouts
    assert saved["roles"]["jwl_main"] == role
    assert "app" in saved["roles"]
    assert "jwlibrary" not in saved
    window.close()


@pytest.mark.parametrize(
    "invalid",
    [
        {"version": 2, "roles": "wrong"},
        {"version": 2, "roles": {"jwl_main": {"monitor": "m", "relative": [0, 0, -1, 1]}}},
        {"jwlibrary": [1, 2]},
    ],
)
def test_invalid_layout_recovers_and_preserves_backup(tmp_path, invalid):
    import json

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"display_settings_version": 1, "window_layouts": invalid}))
    settings = SettingsService(path).load()
    assert settings.window_layouts == {}
    assert list(tmp_path.glob("settings.json.invalid-*.bak"))
