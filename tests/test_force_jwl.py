"""Exercise the operator's explicit return button without enabling the guardian."""

from dataclasses import asdict
from unittest.mock import MagicMock, Mock

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from meeting_assistant.core.state import AppState, OperatingMode
from meeting_assistant.services.settings import AppSettings, SettingsService
from meeting_assistant.ui.main_window import MainWindow


class ReturnService(QObject):
    active_changed = Signal(bool, str)
    status_changed = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.active = self.returning = False
        self.restore_jwl = Mock(return_value=True)


@pytest.fixture
def owner(tmp_path, monkeypatch):
    services = [MagicMock() for _ in range(6)]
    services[1].snapshot.return_value = []
    services[2].snapshot.return_value = []
    services[5] = ReturnService()
    window = MainWindow(
        AppState(simulation_enabled=False), AppSettings(),
        SettingsService(tmp_path / "settings.json"), *services
    )
    window.show()
    QApplication.processEvents()
    errors = []
    monkeypatch.setattr("sys.excepthook", lambda kind, value, trace: errors.append(value))
    yield window, errors
    window.close()


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("zoom_active", [False, True])
def test_force_button_requests_verified_return_preserving_automation_and_settings(
    owner, enabled, zoom_active
):
    window, errors = owner
    window.state.automation_enabled = enabled
    window._set_automation_ui(enabled)
    window.zoom_hall.active = zoom_active
    if zoom_active:
        window.zoom_hall.active_changed.emit(True, "Zoom no Salão")
    requested = []
    window.automation_enabled_changed.connect(requested.append)
    settings_before = asdict(window.settings)
    auto_label = window.auto_button.text()
    zoom_checked = window.mode_buttons[OperatingMode.ZOOM].isChecked()
    window.obs.reset_mock()

    QTest.mouseClick(window.force_jwl_button, Qt.LeftButton)

    assert not errors
    window.zoom_hall.restore_jwl.assert_called_once_with()
    assert window.state.automation_enabled is enabled
    assert asdict(window.settings) == settings_before and requested == []
    assert window.auto_button.text() == auto_label
    assert window.mode_buttons[OperatingMode.ZOOM].isChecked() is zoom_checked
    assert "Solicitando" in window.mode_label.text()
    window.obs.set_program_scene.assert_not_called()
    window.obs.operator_task.assert_not_called()

    window.zoom_hall.active = False
    window.zoom_hall.active_changed.emit(False, "JW Library confirmado visível.")
    window.zoom_hall.status_changed.emit(True, "JW Library confirmado visível.")
    assert not window.mode_buttons[OperatingMode.ZOOM].isChecked()
    assert "confirmado" in window.mode_label.text()


def test_force_button_preserves_return_service_failure(owner):
    window, errors = owner

    def unavailable():
        window.zoom_hall.status_changed.emit(False, "Saída do JW Library não encontrada.")
        return False

    window.zoom_hall.restore_jwl.side_effect = unavailable
    QTest.mouseClick(window.force_jwl_button, Qt.LeftButton)
    assert not errors
    assert window.mode_label.text() == "Saída do JW Library não encontrada."
    assert not window.state.automation_enabled


def test_force_button_reports_unaccepted_request_without_false_success(owner):
    window, errors = owner
    window.zoom_hall.restore_jwl.return_value = False
    QTest.mouseClick(window.force_jwl_button, Qt.LeftButton)
    assert not errors
    assert "não iniciado" in window.mode_label.text()
    assert not window.state.automation_enabled


@pytest.mark.parametrize("phase", ["preparing", "presenting", "return_failed"])
def test_force_button_uses_external_media_return_instead_of_overlapping_native_requests(owner, phase):
    window, errors = owner
    external = Mock(active=True, phase=phase)
    # Close cleanup may inspect the external service: keep it idle after this test.
    window.external_media = external
    try:
        QTest.mouseClick(window.force_jwl_button, Qt.LeftButton)
        assert not errors
        external.stop_external_media.assert_called_once_with()
        window.zoom_hall.restore_jwl.assert_not_called()
        assert not window.state.automation_enabled
    finally:
        external.active = False
