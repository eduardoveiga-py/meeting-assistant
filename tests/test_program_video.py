import time
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QRect
from PySide6.QtMultimedia import QVideoFrameFormat

from meeting_assistant.services.program_video import (
    LatestFrame,
    PreviewReader,
    ProgramVideo,
    VideoUpdate,
    video_frame,
)
from meeting_assistant.services.virtual_camera import HEIGHT, WIDTH, FrameStatus
from meeting_assistant.ui.program_preview import ProgramPreview
from meeting_assistant.ui.window_geometry import fit_window


def black_pixels():
    return bytes([16]) * (WIDTH * HEIGHT) + bytes([128]) * (WIDTH * HEIGHT // 2)


def test_nv12_stays_video_frame_and_preserves_color():
    frame = video_frame(black_pixels())
    assert frame.pixelFormat() == QVideoFrameFormat.PixelFormat.Format_NV12
    assert frame.width() == 1280 and frame.height() == 720
    # Conversion is used only by this assertion, not by the production renderer.
    assert frame.toImage().pixelColor(640, 360).red() < 3
    with pytest.raises(ValueError):
        video_frame(b"short")


def test_slow_gui_discards_old_frames_without_backlog():
    slot = LatestFrame()
    for sequence in range(100):
        slot.put(VideoUpdate(FrameStatus(True, True, sequence, 1000), object()))
    assert slot.take().status.sequence == 99
    assert slot.take() is None
    assert slot.replaced == 99


def test_stale_frame_is_cleared_and_reconnection_recovers(qt_application):
    monitor = ProgramVideo()
    received = []
    monitor.frame_ready.connect(received.append)
    frame = video_frame(black_pixels())
    monitor.mailbox.put(VideoUpdate(FrameStatus(True, True, 1, 100), frame, received_at=time.monotonic()))
    monitor.present_latest()
    assert received[-1] is frame
    monitor.mailbox.put(VideoUpdate(error="OBS fechado", received_at=time.monotonic()))
    monitor.present_latest()
    assert received[-1] is None
    assert monitor.diagnostic["transport_errors"] == 1
    assert monitor.diagnostic["preview_fps"] == 0
    monitor.mailbox.put(VideoUpdate(FrameStatus(True, True, 2, 100), frame, received_at=time.monotonic()))
    monitor.present_latest()
    assert received[-1] is frame and "last_error" not in monitor.diagnostic
    monitor.last_received -= 2
    monitor.present_latest()
    assert received[-1] is None


def test_two_surfaces_share_one_reader_and_do_not_resize(qt_application):
    reader = Mock()
    factory = Mock(return_value=reader)
    monitor = ProgramVideo(reader_factory=factory)
    surfaces = [ProgramPreview(monitor=monitor), ProgramPreview(monitor=monitor)]
    try:
        for surface in surfaces:
            surface.resize(440, 240)
            surface.show()
            fit_window(surface, QRect(0, 0, 800, 560))
        qt_application.processEvents()
        sizes = [s.size() for s in surfaces]
        monitor.frame_ready.emit(video_frame(black_pixels()))
        qt_application.processEvents()
        assert [s.size() for s in surfaces] == sizes
        reader.start.assert_called_once()
        assert factory.call_count == 1
        for surface in surfaces:
            assert surface.video.videoSink().videoFrame().isValid()
    finally:
        for surface in surfaces:
            surface.close()
        monitor.stop()


def test_reader_reconnects_and_stops_with_bounded_shutdown():
    slot = LatestFrame()
    first = Mock()
    first.read.side_effect = OSError("OBS reiniciou")
    second = Mock()
    second.read.return_value = (FrameStatus(True, True, 1, 100), black_pixels())
    factory = Mock(side_effect=[first, second])
    reader = PreviewReader(slot, factory)
    reader.start()
    deadline = time.monotonic() + 3
    result = None
    while time.monotonic() < deadline:
        update = slot.take()
        if update and update.frame is not None:
            result = update
            break
        time.sleep(0.01)
    reader.stop()
    assert result is not None and result.status.sequence == 1
    assert not reader.is_alive()
    assert factory.call_count == 2
    first.close.assert_called_once()
    second.close.assert_called_once()
