from unittest.mock import Mock

from PySide6.QtCore import QProcess, QRect

from meeting_assistant.services.camera_session import CameraSession
from meeting_assistant.services.program_video import ProgramVideo
from meeting_assistant.services.virtual_camera import FrameStatus
from meeting_assistant.ui.virtual_camera_dialog import VirtualCameraDialog
from meeting_assistant.ui.window_geometry import fit_window


def test_start_waits_for_bridge_before_camera_creation(monkeypatch, tmp_path):
    monkeypatch.setattr("meeting_assistant.services.camera_session.camera_support", lambda: (True, "OK"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    executable = tmp_path / "MeetingAssistant/VirtualCamera/meeting-assistant-camera.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    session = CameraSession()
    session._command = Mock()
    host = session.host
    session.host = Mock()
    session.start()
    session.host.start.assert_not_called()
    session._command.assert_called_once_with("S")
    session.start()
    assert session._command.call_count == 1
    session.control_result("S", FrameStatus(True, True, 1, 100), "")
    session.host.start.assert_called_once_with(str(executable), [])
    session.deadline.stop()
    session.host = host


def test_camera_error_keeps_hresult_after_process_exit():
    session = CameraSession()
    host = session.host
    session.host = Mock()
    session._command = Mock()
    session.state = "starting"
    session.host.readAllStandardOutput.side_effect = [b"CAMERA_ER", b"ROR 0x80070005\n"]
    session.host_output()
    assert session.state == "starting"
    session.host_output()
    session.host_finished(3)
    assert session.state == "error" and "0x80070005" in session.message
    session._command.assert_called_with("T")
    session.host = host


def test_dialog_close_keeps_camera_running_and_controls_fit(qt_application):
    session = CameraSession()
    session.supported = True
    session.state = "running"
    session.stop = Mock()
    monitor = ProgramVideo(reader_factory=lambda _: Mock())
    dialog = VirtualCameraDialog(session=session, monitor=monitor)
    dialog.show()
    fit_window(dialog, QRect(0, 0, 800, 560))
    qt_application.processEvents()
    assert dialog.rect().contains(dialog.camera_button.geometry())
    assert dialog.camera_button.text() == "Parar câmera"
    dialog.reject()
    session.stop.assert_not_called()
    assert session.state == "running"
    monitor.stop()


def test_explicit_stop_stops_host_then_authorization_not_preview():
    session = CameraSession()
    host = session.host
    session.host = Mock()
    session.host.state.return_value = QProcess.ProcessState.Running
    session._command = Mock()
    session.state = "running"
    session.stop()
    session.host.write.assert_called_once_with(b"stop\n")
    session.host_finished(0)
    session._command.assert_called_once_with("T")
    session.control_result("T", FrameStatus(False, False, 0, 0), "")
    assert session.state == "off"
    session.host = host


def test_obs_restart_rearms_only_an_active_camera():
    session = CameraSession()
    session._command = Mock()
    session.state = "running"
    session.control_result("I", FrameStatus(False, False, 0, 0), "")
    session._command.assert_called_once_with("S")
    session._command.reset_mock()
    session.state = "off"
    session.control_result("I", FrameStatus(False, False, 0, 0), "")
    session._command.assert_not_called()


def test_api_start_is_not_reported_as_whatsapp_validation():
    session = CameraSession()
    host = session.host
    session.host = Mock()
    session.host.readAllStandardOutput.return_value = b"CAMERA_STARTED\n"
    session.state = "starting"
    session.host_output()
    assert session.state == "running"
    assert session.diagnostic()["camera_approved_in_whatsapp"] is False
    session.health.stop()
    session.host = host
