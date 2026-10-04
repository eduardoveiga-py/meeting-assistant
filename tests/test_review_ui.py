from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea

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


def layout_details(window):
    return "\n".join(
        str((widget.text(), widget.width(), widget.sizeHint().width(), widget.minimumSizeHint().width()))
        for kind in (QPushButton, QLabel)
        for widget in window.findChildren(kind)
        if widget.isVisible()
    )


@pytest.mark.parametrize("state", ["live", "muted", "unknown"])
def test_every_microphone_state_and_update_banner_fit_operator_width(tmp_path, state):
    window = make_window(tmp_path)
    window.resize(520, 520)
    window.show()
    window._zoom_audio_result(state, "Diagnostic")
    window._on_update_available("0.10.0", "", "Long release notes")
    QApplication.processEvents()
    assert window.findChild(QScrollArea).horizontalScrollBar().maximum() == 0, layout_details(window)
    assert window.width() == 520
    window.close()


@pytest.mark.parametrize("state", ["off", "starting", "running", "stopping", "error"])
def test_camera_controls_fit_without_clipping_at_operator_width(tmp_path, state):
    window = make_window(tmp_path)
    window.camera_session = MagicMock(state=state, supported=True, message="Camera diagnostic")
    window._on_camera_state()
    window.resize(520, 520)
    window.show()
    QApplication.processEvents()
    assert window.findChild(QScrollArea).horizontalScrollBar().maximum() == 0, layout_details(window)
    for button in window.findChildren(QPushButton):
        if button.isVisible():
            assert button.sizeHint().width() <= button.width(), layout_details(window)
    window.close()


@pytest.mark.parametrize("height", [620, 640, 780])
@pytest.mark.parametrize("enabled", [False, True])
def test_header_text_is_exposed_and_preview_retains_useful_height(tmp_path, height, enabled):
    window = make_window(tmp_path)
    window.resize(520, height)
    window._set_automation_ui(enabled)
    window.show()
    QApplication.processEvents()
    try:
        title = window.findChild(QLabel, "Title")
        subtitle = window.findChild(QLabel, "Subtitle")
        badge = window.automation_badge
        scroll = window.centralWidget()
        for label in (title, subtitle, badge):
            assert label.isVisible() and label.width() > 0, layout_details(window)
            assert scroll.viewport().rect().contains(
                label.mapTo(scroll.viewport(), label.rect().topLeft())
            )
            assert scroll.viewport().rect().contains(
                label.mapTo(scroll.viewport(), label.rect().bottomRight())
            )
        for label in (title, subtitle):
            assert label.height() >= label.heightForWidth(label.width()), layout_details(window)
        assert badge.height() == badge.sizeHint().height(), layout_details(window)
        assert window.preview.height() >= 80, layout_details(window)
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.verticalScrollBar().maximum() == 0
    finally:
        window.close()


def test_launch_summary_does_not_run_legacy_native_layout_on_gui(tmp_path, monkeypatch):
    import sys

    from meeting_assistant.services.meeting_launcher import LaunchSummary

    native = MagicMock()
    for name in ("win32api", "win32con", "win32gui"):
        monkeypatch.setitem(sys.modules, name, native)
    window = make_window(tmp_path)
    window._on_launch_finished(LaunchSummary(True, True, True, True, ()))
    native.EnumWindows.assert_not_called()
    native.GetSystemMetrics.assert_not_called()
    window.close()


def test_short_window_keeps_controls_readable_and_restores_preview_when_grown(tmp_path):
    window = make_window(tmp_path)
    window.show()
    window._screen_fit._timer.stop()
    QApplication.processEvents()
    fonts = {button: button.font().pixelSize() for button in window.findChildren(QPushButton)}
    button_heights = {button: button.sizeHint().height() for button in fonts}
    try:
        for height in (520, 780, 520):
            window.resize(520, height)
            QApplication.processEvents()
            scroll = window.centralWidget()
            assert scroll.horizontalScrollBar().maximum() == 0, layout_details(window)
            assert scroll.verticalScrollBar().maximum() == 0, layout_details(window)
            assert window.preview.height() >= (100 if height >= 600 else 40)
            for button in fonts:
                assert button.font().pixelSize() == fonts[button]
                assert button.sizeHint().height() == button_heights[button]
                if button.isVisible():
                    assert button.sizeHint().width() <= button.width(), layout_details(window)
                    assert scroll.viewport().rect().contains(
                        button.mapTo(scroll.viewport(), button.rect().bottomRight())
                    ), layout_details(window)
    finally:
        window.close()


def test_end_meeting_pauses_automation_and_waits_for_verified_result(tmp_path):
    window = make_window(tmp_path)
    window.state.automation_enabled = True
    window.launcher.end_meeting.return_value = True
    window._end_meeting()
    assert not window.state.automation_enabled
    assert window._meeting_ending
    assert not window.power_button.isEnabled()
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
