"""Real UI entry points, confirmed persistence and closing a shared workspace."""

from copy import deepcopy
from dataclasses import replace
from unittest.mock import MagicMock, Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from test_obs_maintenance import MaintenanceObs, configure

from meeting_assistant.core.state import AppState
from meeting_assistant.services.obs_audio import MIC
from meeting_assistant.services.obs_controller import ObsController
from meeting_assistant.services.settings import AppSettings, SettingsService
from meeting_assistant.ui.main_window import MainWindow
from meeting_assistant.ui.setup_assistant_dialog import SetupAssistantDialog

pytestmark = pytest.mark.usefixtures("audio_monitor_profile")


def make_owner(tmp_path):
    controller = ObsController()
    fake = MaintenanceObs(jwl_plugin=False)
    configure(fake)
    controller._client = fake
    controller.local_connection = True
    controller.reconfigure = Mock(wraps=controller.reconfigure)
    services = [controller, *[MagicMock() for _ in range(5)]]
    services[1].snapshot.return_value = []
    services[2].snapshot.return_value = []
    services[5].active = services[5].returning = False
    settings = AppSettings(
        congregation_name="Original",
        obs_password="saved-websocket",
        camera_username="saved-user",
        camera_password="saved-camera",
        audio_gains_db={MIC: 5.0},
    )
    store = SettingsService(tmp_path / "settings.json")
    store.save(settings)
    owner = MainWindow(AppState(), settings, store, *services)
    owner.obs_scenes = list(fake.scenes)
    return owner, fake


def run_queued(owner, expected):
    command, payload = owner.obs._commands.get_nowait()
    assert command == expected
    if command == "audio_task":
        owner.obs._handle_audio_task(*payload)
    elif command == "maintenance_task":
        owner.obs._handle_maintenance_task(*payload)
    return payload


def open_audio(dialog, owner):
    dialog.select_page("audio")
    QApplication.processEvents()
    assert dialog.audio.busy
    run_queued(owner, "audio_task")
    QApplication.processEvents()
    assert not dialog.audio.busy


def test_general_save_does_not_reconnect_and_merges_confirmed_volume_edits(tmp_path):
    owner, fake = make_owner(tmp_path)
    dialog = SetupAssistantDialog(owner, page="meeting")
    dialog.show()
    before_sources = deepcopy(fake.sources)
    dialog.editor.congregation_name_edit.setText("Atualizada")
    open_audio(dialog, owner)
    dialog.audio.gains[MIC].setValue(-3)
    QTest.mouseClick(dialog.audio.gain_button, Qt.LeftButton)
    run_queued(owner, "audio_task")
    assert owner.settings.audio_gains_db[MIC] == -3
    assert owner.settings_service.load().audio_gains_db[MIC] == -3
    assert dialog._save()
    saved = owner.settings_service.load()
    assert saved.congregation_name == "Atualizada" and saved.audio_gains_db[MIC] == -3
    assert saved.obs_password == "saved-websocket" and saved.camera_password == "saved-camera"
    assert fake.sources == before_sources
    owner.obs.reconfigure.assert_not_called()
    dialog.close()
    owner.close()


def test_only_a_connection_change_reconfigures_obs(tmp_path):
    owner, _ = make_owner(tmp_path)
    dialog = SetupAssistantDialog(owner, page="meeting")
    dialog.editor.congregation_name_edit.setText("Novo nome")
    assert dialog._save()
    owner.obs.reconfigure.assert_not_called()
    dialog.editor.port_spin.setValue(4456)
    assert dialog._save()
    assert owner.obs.reconfigure.call_count == 1
    assert owner.obs.reconfigure.call_args.args[0].port == 4456
    dialog.close()
    owner.close()


def test_open_read_and_navigation_preserve_saved_values_and_live_audio(tmp_path):
    owner, fake = make_owner(tmp_path)
    saved = owner.settings_service.path.read_bytes()
    before = deepcopy(fake.sources), deepcopy(fake.scenes), deepcopy(fake.filters)
    dialog = SetupAssistantDialog(owner, page="meeting")
    dialog.show()
    assert dialog.navigation.count() == 5
    assert not dialog.editor.isWindow() and not dialog.audio.isWindow()
    assert not dialog.hall.isWindow() and not dialog.camera.isWindow()
    open_audio(dialog, owner)
    for page in ("video", "diagnostics", "installation", "meeting"):
        dialog.select_page(page)
        QApplication.processEvents()
    assert owner.settings_service.path.read_bytes() == saved
    assert (fake.sources, fake.scenes, fake.filters) == before
    dialog.close()
    owner.close()


def test_volumes_work_during_automation_but_source_preparation_waits(tmp_path):
    owner, _ = make_owner(tmp_path)
    owner.state.automation_enabled = True
    dialog = SetupAssistantDialog(owner, page="audio")
    dialog.show()
    open_audio(dialog, owner)
    dialog.audio.gains[MIC].setValue(7)
    QTest.mouseClick(dialog.audio.gain_button, Qt.LeftButton)
    run_queued(owner, "audio_task")
    assert owner.settings.audio_gains_db[MIC] == 7
    dialog.select_page("video")
    dialog.video_tabs.setCurrentIndex(1)
    QTest.mouseClick(dialog.maintenance.complete_button, Qt.LeftButton)
    assert owner.obs._commands.empty() and "Pause" in dialog.status.text()
    dialog.close()
    owner.close()


def test_source_buttons_reach_serial_worker_and_repeated_completion_is_safe(tmp_path):
    owner, fake = make_owner(tmp_path)
    dialog = SetupAssistantDialog(owner, page="video")
    dialog.video_tabs.setCurrentIndex(1)
    dialog.show()
    QApplication.processEvents()
    before, start = deepcopy(fake.sources), len(fake.calls)
    repeated_start = None
    for button, action in (
        (dialog.maintenance.check_button, "inspect"),
        (dialog.maintenance.complete_button, "complete"),
        (dialog.maintenance.complete_button, "complete"),
    ):
        if action == "complete":
            repeated_start = len(fake.calls)
        QTest.mouseClick(button, Qt.LeftButton)
        assert dialog.maintenance.busy and not dialog.save_button.isEnabled()
        assert run_queued(owner, "maintenance_task")[1] == action
        assert not dialog.maintenance.busy and dialog.save_button.isEnabled()
    assert "Plugin JWL" in dialog.maintenance.report.toPlainText()
    assert {name: fake.sources[name] for name in before} == before
    assert all(r.startswith("Get") for r, _ in fake.calls[repeated_start:])
    assert not any(r == "SetCurrentProgramScene" for r, _ in fake.calls[start:])
    dialog.close()
    owner.close()


def test_pending_audio_is_not_silently_discarded_and_cancel_keeps_the_edits(tmp_path, monkeypatch):
    owner, _ = make_owner(tmp_path)
    dialog = SetupAssistantDialog(owner, page="audio")
    dialog.show()
    open_audio(dialog, owner)
    dialog.audio.gains[MIC].setValue(8)
    ask = Mock(return_value=QMessageBox.Cancel)
    monkeypatch.setattr(QMessageBox, "question", ask)
    dialog.reject()
    assert dialog.isVisible() and dialog.audio.gains[MIC].value() == 8
    assert owner.settings_service.load().audio_gains_db[MIC] == 5
    assert ask.call_count == 1
    ask.return_value = QMessageBox.Discard
    dialog.reject()
    assert not dialog.isVisible()
    assert owner.settings_service.load().audio_gains_db[MIC] == 5
    owner.close()


def test_close_waits_for_confirmed_volume_before_disconnect(tmp_path):
    owner, _ = make_owner(tmp_path)
    dialog = SetupAssistantDialog(owner, page="audio")
    dialog.show()
    open_audio(dialog, owner)
    dialog.audio.gains[MIC].setValue(6)
    dialog.audio.request("gains")
    dialog.reject()
    assert dialog.isVisible() and dialog._close_pending
    run_queued(owner, "audio_task")
    assert not dialog.isVisible() and dialog._views_disconnected
    assert owner.settings_service.load().audio_gains_db[MIC] == 6
    owner.close()


def test_main_volume_button_opens_the_same_workspace_directly(tmp_path, monkeypatch):
    owner, _ = make_owner(tmp_path)
    opened = Mock()
    monkeypatch.setattr(owner, "_open_settings_workspace", opened)
    owner.show()
    QApplication.processEvents()
    QTest.mouseClick(owner.volume_button, Qt.LeftButton)
    opened.assert_called_once_with("audio")
    owner.close()


def test_rejected_settings_save_preserves_file_and_in_memory_values(tmp_path):
    owner, _ = make_owner(tmp_path)
    before = owner.settings_service.path.read_bytes()
    values = replace(owner.settings)
    owner.state.automation_enabled = True
    dialog = SetupAssistantDialog(owner, page="meeting")
    dialog.editor.camera_password_edit.setText("pending-change")
    assert not dialog._save()
    assert owner.settings == values and owner.settings_service.path.read_bytes() == before
    dialog.editor.camera_password_edit.setText(owner.settings.camera_password)
    dialog.close()
    owner.close()
