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
