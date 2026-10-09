"""One preview reader shared by all views. Latest frame only, bounded memory."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtMultimedia import QVideoFrame, QVideoFrameFormat
from PySide6.QtWidgets import QApplication

from meeting_assistant.services.video_metrics import VideoMetrics
from meeting_assistant.services.virtual_camera import FRAME_BYTES, HEIGHT, WIDTH, PreviewConnection


def video_frame(pixels):
    """Convert NV12 to YUV420P via fast slicing to avoid 200ms+ GUI freeze on Qt fallback renderer."""
    if len(pixels) != FRAME_BYTES:
        raise ValueError("Quadro NV12 incompleto.")
    fmt = QVideoFrameFormat(QSize(WIDTH, HEIGHT), QVideoFrameFormat.PixelFormat.Format_YUV420P)
    fmt.setColorSpace(QVideoFrameFormat.ColorSpace.ColorSpace_BT709)
    fmt.setColorRange(QVideoFrameFormat.ColorRange.ColorRange_Video)
    frame = QVideoFrame(fmt)
    if not frame.map(QVideoFrame.MapMode.WriteOnly):
        raise ValueError("Não foi possível preparar o quadro de vídeo.")
    try:
        source = memoryview(pixels)
        y_size = WIDTH * HEIGHT
        y_stride = frame.bytesPerLine(0)
        y_view = frame.bits(0)
        if y_stride == WIDTH:
            y_view[:y_size] = source[:y_size]
        else:
            for row in range(HEIGHT):
                y_view[row * y_stride : row * y_stride + WIDTH] = source[row * WIDTH : (row + 1) * WIDTH]
                
        uv_source = source[y_size : y_size + y_size // 2]
        u_stride = frame.bytesPerLine(1)
        u_view = frame.bits(1)
        u_width = WIDTH // 2
        u_height = HEIGHT // 2
        
        v_stride = frame.bytesPerLine(2)
        v_view = frame.bits(2)
        
        if u_stride == u_width and v_stride == u_width:
            u_view[: u_width * u_height] = uv_source[::2]
            v_view[: u_width * u_height] = uv_source[1::2]
        else:
            for row in range(u_height):
                row_uv = uv_source[row * WIDTH : (row + 1) * WIDTH]
                u_view[row * u_stride : row * u_stride + u_width] = row_uv[::2]
                v_view[row * v_stride : row * v_stride + u_width] = row_uv[1::2]
    finally:
        frame.unmap()
    return frame


@dataclass(frozen=True)
class VideoUpdate:
    status: object = None
    frame: object = None
    error: str = ""
    received_at: float = 0.0


class LatestFrame:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = None
        self.replaced = 0

    def put(self, update):
        with self.lock:
            if self.pending is not None and self.pending.frame is not None:
                self.replaced += 1
            self.pending = update

    def take(self):
        with self.lock:
            update, self.pending = self.pending, None
            return update


class PreviewReader(threading.Thread):
    def __init__(self, mailbox, connection_factory=PreviewConnection):
        super().__init__(name="MeetingAssistant-ProgramPreview", daemon=True)
        self.mailbox = mailbox
        self.connection_factory = connection_factory
        self.stopping = threading.Event()

    def run(self):
        connection = None
        last_sequence = None
        deadline = time.monotonic()
        try:
            while not self.stopping.is_set():
                try:
                    if connection is None:
                        connection = self.connection_factory()
                    status, pixels = connection.read()
                    frame = None
                    if pixels and status.sequence != last_sequence:
                        frame = video_frame(pixels)
                        last_sequence = status.sequence
                    elif not status.fresh:
                        last_sequence = None
                    if frame is not None or not status.fresh:
                        self.mailbox.put(VideoUpdate(status, frame, received_at=time.monotonic()))
                    deadline += 1 / 30
                    now = time.monotonic()
                    if deadline < now:
                        deadline = now
                    self.stopping.wait(max(0, deadline - now))
                except (OSError, ValueError) as exc:
                    self.mailbox.put(VideoUpdate(error=str(exc), received_at=time.monotonic()))
                    if connection is not None:
                        connection.close()
                        connection = None
                    last_sequence = None
                    self.stopping.wait(1.0)
                    deadline = time.monotonic()
        finally:
            if connection is not None:
                connection.close()

    def stop(self):
        self.stopping.set()
        self.join(timeout=3.0)  # Pipe operations have individual deadlines.


class ProgramVideo(QObject):
    frame_ready = Signal(object)
    status_changed = Signal(str)

    def __init__(self, parent=None, reader_factory=PreviewReader):
        super().__init__(parent)
        self.mailbox = LatestFrame()
        self.reader_factory = reader_factory
        self.reader = None
        self.metrics = VideoMetrics()
        self.last_frame = None
        self.last_status = "Aguardando ponte de vídeo do OBS…"
        self.last_received = 0.0
        self.last_fresh_time = 0.0
        self.diagnostic = {
            "protocol": 1,
            "video_revision": 3,
            "target_fps": 30,
            "bridge_fps": 0.0,
            "preview_fps": 0.0,
            "transport_errors": 0,
            "preview_channel": "Preview.v1",
            "preview_paused_for_camera": False,
            "preview_measurement": "frames_submitted_to_Qt_video_renderer",
        }
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.present_latest)

    def start(self):
        if self.reader is None:
            self.reader = self.reader_factory(self.mailbox)
            self.reader.start()
            self.timer.start()

    def stop(self):
        self.timer.stop()
        if self.reader is not None:
            self.reader.stop()
            self.reader = None

    def _unavailable(self, text):
        self.last_frame = None
        self.metrics.reset()
        self.diagnostic.update(bridge_fps=0.0, preview_fps=0.0)
        if self.last_status != text:
            self.last_status = text
            self.status_changed.emit(text)
            self.frame_ready.emit(None)

    def present_latest(self):
        update = self.mailbox.take()
        now = time.monotonic()
        if update is None:
            if self.last_received and now - self.last_received > 3.0:
                self._unavailable("Sem vídeo recente do OBS")
            return
        self.last_received = update.received_at
        self.diagnostic["preview_replaced_frames"] = self.mailbox.replaced
        if update.error:
            self.diagnostic["transport_errors"] += 1
            self.diagnostic["last_error"] = update.error
            self.diagnostic["bridge"] = None
            self._unavailable("Ponte de vídeo indisponível. Instale a versão atual e reabra o OBS.")
            return
        self.diagnostic.pop("last_error", None)
        self.diagnostic["bridge"] = update.status.diagnostic()
        if update.status.fresh:
            self.last_fresh_time = update.received_at
        if self.last_fresh_time is None or now - self.last_fresh_time > 3.0 or now - update.received_at > 3.0:
            self._unavailable("Sem vídeo recente do OBS")
            return
        rendered = update.frame is not None
        bridge, preview = self.metrics.observe(now, update.status.sequence, rendered)
        self.diagnostic.update(bridge_fps=bridge, preview_fps=preview)
        if rendered:
            self.last_frame = update.frame
            self.frame_ready.emit(update.frame)
        text = f"Program do OBS • ponte {bridge:.1f} fps • prévia {preview:.1f} fps"
        if text != self.last_status:
            self.last_status = text
            self.status_changed.emit(text)


def program_video():
    app = QApplication.instance()
    if not hasattr(app, "_program_video"):
        app._program_video = ProgramVideo(app)
        app.aboutToQuit.connect(app._program_video.stop)
    return app._program_video
