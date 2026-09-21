from unittest.mock import Mock

from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QScrollArea

from meeting_assistant.services.obs_audio import MIC, SOURCES
from meeting_assistant.services.settings import AppSettings
from meeting_assistant.ui.audio_setup_dialog import AudioSetupDialog
from meeting_assistant.ui.shortcuts import MainWindowShortcuts
from meeting_assistant.ui.window_geometry import fit_window


class Controller(QObject):
    audio_task_finished = Signal(str, str, bool, object)

    def __init__(self):
        super().__init__()
        self.audio_task = Mock()


def test_audio_dialog_requires_selection_and_all_confirmations_and_fits():
    app = QApplication.instance()
    controller = Controller()
    dialog = AudioSetupDialog(controller, AppSettings())
    dialog.show()
    fit_window(dialog, QRect(0, 0, 800, 560))
    app.processEvents()
    assert not dialog.activate_button.isEnabled()
    dialog.request("prepare")
    assert dialog.busy
    assert not dialog.close_button.isEnabled()
    result = {
        "message": "Prepared",
        "microphones": [{"itemName": "Mesa", "itemValue": "usb"}],
        "applications": {k: [] for k in dialog.applications},
        "selected": {n: {} for n in SOURCES},
    }
    result["selected"][MIC] = {"device_id": "usb"}
    controller.audio_task_finished.emit("wrong-dialog", "prepare", True, result)
    assert dialog.busy
    controller.audio_task_finished.emit(dialog.token, "prepare", True, result)
    assert not dialog.busy
    assert not dialog.activate_button.isEnabled()
    for check in dialog.confirmations:
        check.setChecked(True)
    assert dialog.activate_button.isEnabled()
    app.processEvents()
    for button in (dialog.activate_button, dialog.mute_button, dialog.close_button):
        assert dialog.rect().contains(button.geometry())
    assert dialog.findChild(QScrollArea).horizontalScrollBar().maximum() == 0
    dialog.reject()


def test_local_shortcut_does_not_fire_in_dialog_or_other_window():
    app = QApplication.instance()
    owner = QMainWindow()
    actions = [Mock() for _ in range(9)]
    manager = MainWindowShortcuts(owner, actions)
    owner.show()
    owner.activateWindow()
    app.processEvents()
    QTest.keyClick(owner, Qt.Key.Key_F2)
    assert actions[0].call_count == 1
    assert all(not s.autoRepeat() for s in manager.shortcuts)
    modal = QDialog(owner)
    modal.setModal(True)
    modal.show()
    modal.activateWindow()
    app.processEvents()
    QTest.keyClick(modal, Qt.Key.Key_F2)
    manager.dispatch(actions[0])
    assert actions[0].call_count == 1
    modal.close()
    other = QMainWindow()
    other.show()
    other.activateWindow()
    app.processEvents()
    manager.dispatch(actions[0])
    assert actions[0].call_count == 1
    other.close()
    owner.close()


def test_controller_reports_disconnection_and_sanitizes_audio_errors(monkeypatch):
    from meeting_assistant.services.obs_controller import ObsController

    controller = ObsController()
    received = []
    controller.audio_task_finished.connect(lambda *args: received.append(args))
    controller._handle_audio_task('token', 'prepare', {})
    assert received[-1][2] is False
    assert 'desconectado' in received[-1][3]['message']
    controller._client = object()
    monkeypatch.setattr('meeting_assistant.services.obs_audio.run_audio_task',
                        Mock(side_effect=RuntimeError('private SDK request contents')))
    controller._handle_audio_task('token', 'prepare', {})
    assert received[-1][2] is False
    assert 'private' not in received[-1][3]['message']
    controller._client = None
