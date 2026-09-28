from unittest.mock import Mock

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from meeting_assistant.services.virtual_camera import (
    FRAME_BYTES,
    HEADER,
    HEIGHT,
    MAGIC,
    WIDTH,
    camera_support,
    decode_header,
    request,
)
from meeting_assistant.ui.virtual_camera_dialog import VirtualCameraDialog, frame_image
from meeting_assistant.ui.window_geometry import fit_window


def header(**changes):
    values = dict(
        magic=MAGIC,
        version=1,
        size=48,
        width=WIDTH,
        height=HEIGHT,
        payload=0,
        flags=3,
        reserved=0,
        sequence=30,
        tick_ms=1000,
    )
    values.update(changes)
    return HEADER.pack(*values.values())


@pytest.mark.parametrize(
    "change",
    [
        dict(magic=0),
        dict(version=2),
        dict(size=64),
        dict(width=9999),
        dict(payload=FRAME_BYTES + 1),
        dict(flags=2),
        dict(reserved=1),
    ],
)
def test_reject_bad_frame_protocol(change):
    with pytest.raises(ValueError):
        decode_header(header(**change))


def test_platform_gate_allows_bridge_but_not_camera_on_windows10():
    assert not camera_support("Windows", 19045, "AMD64")[0]
    assert camera_support("Windows", 22000, "AMD64")[0]
    assert not camera_support("Windows", 26100, "ARM64")[0]
    assert not camera_support("Linux", 22000, "AMD64")[0]


def test_request_closes_pipe_on_invalid_payload():
    pipe = Mock()
    pipe.transfer.side_effect = [b"", header(payload=FRAME_BYTES)]
    with pytest.raises(ValueError):
        request("I", lambda _: pipe)
    pipe.close.assert_called_once()


def test_stopped_frame_returns_no_stale_pixels_and_acknowledges():
    pipe = Mock()
    pipe.transfer.side_effect = [b"", header(flags=0), b""]
    status, pixels = request("F", lambda _: pipe)
    assert not status.enabled and not status.fresh and not pixels
    assert pipe.transfer.call_args.args == (1, b"A")
    pipe.close.assert_called_once()


def test_nv12_black_frame_is_decoded_without_preview_screenshot():
    image = frame_image(bytes([16]) * (WIDTH * HEIGHT) + bytes([128]) * (WIDTH * HEIGHT // 2))
    assert image.width() == WIDTH and image.height() == HEIGHT
    assert image.pixelColor(640, 360).red() < 3
    with pytest.raises(ValueError):
        frame_image(b"short")


def test_dialog_windows10_gate_and_visible_controls(monkeypatch):
    monkeypatch.setattr(
        "meeting_assistant.ui.virtual_camera_dialog.camera_support", lambda: (False, "Requer Windows 11")
    )
    dialog = VirtualCameraDialog()
    dialog.show()
    fit_window(dialog, QRect(0, 0, 800, 560))
    QApplication.instance().processEvents()
    assert not dialog.camera_button.isEnabled()
    for button in [*dialog.controls, dialog.camera_button]:
        assert dialog.rect().contains(button.geometry())
    dialog.stop_requested = True
    dialog.reject()


def test_close_while_reading_still_queues_stop(monkeypatch):
    dialog = VirtualCameraDialog()
    worker = Mock()
    dialog.worker = worker
    dialog.reject()
    assert dialog.closing and not dialog.stop_requested
    send = Mock()
    monkeypatch.setattr(dialog, "send", send)
    dialog.worker_finished()
    send.assert_called_once_with("T")
    assert dialog.stop_requested
    dialog.reject()


def test_preview_frame_does_not_expand_dialog(qt_application):
    from meeting_assistant.services.virtual_camera import FrameStatus

    dialog = VirtualCameraDialog()
    dialog.show()
    fit_window(dialog, QRect(0, 0, 800, 560))
    qt_application.processEvents()
    before = dialog.size()
    pixels = bytes([16]) * (WIDTH * HEIGHT) + bytes([128]) * (WIDTH * HEIGHT // 2)
    dialog.result("F", FrameStatus(True, True, 30, 1000), pixels, "")
    qt_application.processEvents()
    assert dialog.width() == before.width()
    assert dialog.height() == before.height()
    assert dialog.rect().contains(dialog.camera_button.geometry())
    dialog.stop_requested = True
    dialog.reject()


def test_camera_error_survives_process_exit_and_partial_output():
    dialog = VirtualCameraDialog()
    actual_host = dialog.host
    fake = Mock()
    fake.readAllStandardOutput.side_effect = [b"CAMERA_ER", b"ROR 0x80070005\n"]
    dialog.host = fake
    dialog.host_output()
    assert "camera_api" not in dialog.last_diagnostic
    dialog.host_output()
    dialog.host_finished(3)
    assert "0x80070005" in dialog.camera_state.text()
    dialog.host = actual_host
    dialog.stop_requested = True
    dialog.reject()


def test_live_camera_does_not_compete_with_diagnostic_frame_consumer(monkeypatch):
    from PySide6.QtCore import QProcess

    dialog = VirtualCameraDialog()
    actual_host = dialog.host
    fake = Mock()
    fake.state.return_value = QProcess.ProcessState.Running
    dialog.host = fake
    send = Mock()
    monkeypatch.setattr(dialog, "send", send)
    dialog.poll()
    send.assert_called_once_with("I")
    fake.state.return_value = QProcess.ProcessState.NotRunning
    dialog.poll()
    assert send.call_args.args == ("F",)
    dialog.host = actual_host
    dialog.stop_requested = True
    dialog.reject()


def test_metrics_distinguish_bridge_from_slow_preview_and_reset():
    from meeting_assistant.services.video_metrics import VideoMetrics

    metrics = VideoMetrics()
    # Bridge produces 30 fps while the diagnostic consumer displays only 2 fps.
    for i in range(5):
        bridge, preview = metrics.observe(i / 2, i * 15, rendered=True)
    assert bridge == 30.0 and preview == 2.0
    assert metrics.observe(2.1, 0, rendered=True) == (0.0, 0.0)
    # Repeated reads of the same frame are not new displayed frames.
    for i in range(1, 11):
        bridge, preview = metrics.observe(2.1 + i / 10, 0, rendered=True)
    assert bridge == preview == 0.0


def test_user_stop_is_not_lost_during_frame_read(monkeypatch):
    dialog = VirtualCameraDialog()
    dialog.worker = Mock()
    dialog.send("T")
    assert dialog.pending_command == "T"
    send = Mock()
    monkeypatch.setattr(dialog, "send", send)
    dialog.worker_finished()
    send.assert_called_once_with("T")
    dialog.stop_requested = True
    dialog.reject()


def test_fast_preview_timer_does_not_restart_for_every_frame(monkeypatch):
    from meeting_assistant.services.virtual_camera import FrameStatus

    dialog = VirtualCameraDialog()
    timer = Mock()
    timer.interval.return_value = 33
    timer.isActive.return_value = True
    dialog.timer = timer
    dialog.result("F", FrameStatus(True, True, 30, 1000), None, "")
    timer.start.assert_not_called()
    assert dialog.last_diagnostic["diagnostic_revision"] == 2
    dialog.stop_requested = True
    dialog.reject()


def test_error_clears_success_and_retries_at_low_rate():
    from meeting_assistant.services.virtual_camera import FrameStatus

    dialog = VirtualCameraDialog()
    dialog.result("F", FrameStatus(True, True, 30, 1000), None, "")
    dialog.result("F", None, None, "OBS fechado")
    assert dialog.last_diagnostic["bridge"] is None
    assert dialog.last_diagnostic["transport_errors"] == 1
    assert dialog.last_diagnostic["bridge_fps"] == 0.0
    assert dialog.timer.interval() == 1000
    assert dialog.timer.isActive()
    dialog.stop_requested = True
    dialog.reject()


def test_preview_reuses_decoder_thread_and_closes_cleanly(monkeypatch, qt_application):
    import threading
    import time

    from meeting_assistant.services.virtual_camera import FrameStatus

    threads, commands = set(), []
    pixels = bytes([16]) * (WIDTH * HEIGHT) + bytes([128]) * (WIDTH * HEIGHT // 2)

    def backend(command):
        threads.add(threading.get_ident())
        commands.append(command)
        return FrameStatus(command != "T", command != "T", len(commands), 1000), (
            pixels if command == "F" else b""
        )

    monkeypatch.setattr("meeting_assistant.ui.virtual_camera_dialog.request", backend)
    dialog = VirtualCameraDialog()
    dialog.send("S")
    deadline = time.monotonic() + 3
    while commands.count("F") < 12 and time.monotonic() < deadline:
        qt_application.processEvents()
        time.sleep(0.003)
    dialog.reject()
    deadline = time.monotonic() + 3
    while dialog.transport is not None and time.monotonic() < deadline:
        qt_application.processEvents()
        time.sleep(0.003)
    assert commands.count("F") >= 12
    assert len(threads) == 1
    assert commands[-1] == "T"
    assert dialog.transport is None and dialog.worker is None


def test_compat_backend_pauses_preview_and_stops_gate(monkeypatch):
    import meeting_assistant.ui.virtual_camera_dialog as ui

    monkeypatch.setattr(ui, "camera_support", lambda: (False, "Windows 10"))
    monkeypatch.setattr(ui, "registered_camera", lambda: True)
    gate = Mock()
    monkeypatch.setattr(ui, "CompatibilityGate", lambda: gate)
    dialog = ui.VirtualCameraDialog()
    send = Mock()
    monkeypatch.setattr(dialog, "send", send)
    assert dialog.camera_button.isEnabled()
    dialog.toggle_camera()
    assert dialog.last_diagnostic["camera_backend"] == "compat"
    assert dialog.last_diagnostic["compat_enabled"] is True
    assert not dialog.backend.isEnabled()
    assert dialog.camera_running()
    send.assert_called_with("S")
    dialog.poll()
    send.assert_called_with("I")
    dialog.toggle_camera()
    gate.close.assert_called_once()
    send.assert_called_with("T")
    assert dialog.backend.isEnabled() and dialog.compat_gate is None
    dialog.stop_requested = True
    dialog.reject()


def test_backend_selection_preserves_windows11_and_manual_choice():
    from meeting_assistant.services.compat_camera import resolve_backend

    assert resolve_backend("auto", True) == "modern"
    assert resolve_backend("auto", False) == "compat"
    assert resolve_backend("compat", True) == "compat"


def test_closing_compat_gate_precedes_async_shutdown(monkeypatch):
    dialog = VirtualCameraDialog()
    gate = Mock()
    dialog.compat_gate = gate
    dialog.worker = Mock()
    dialog.reject()
    gate.close.assert_called_once()
    assert dialog.compat_gate is None and dialog.closing
    dialog.worker = None
    dialog.stop_requested = True
    dialog.reject()
