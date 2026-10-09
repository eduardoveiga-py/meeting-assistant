"""Reusable native video surface. No JPEGs, scene control or camera lifecycle."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QLabel, QSizePolicy, QStackedLayout, QWidget

from meeting_assistant.services.program_video import program_video


class ProgramPreview(QWidget):
    def __init__(self, parent=None, monitor=None):
        super().__init__(parent)
        self.monitor = monitor or program_video()
        self.setMinimumSize(160, 40)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.video = QVideoWidget(self)
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.video.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.message = QLabel(self.monitor.last_status, self)
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.message)
        self.stack.addWidget(self.video)
        self.monitor.frame_ready.connect(self.present)
        self.monitor.status_changed.connect(self.status)

    def sizeHint(self):
        return QSize(480, 270)

    @property
    def is_paused(self) -> bool:
        return getattr(self, "_paused", False)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if paused:
            self.monitor.stop()
            self.video.videoSink().setVideoFrame(QVideoFrame())
            self.message.setText(
                "⏸️ Prévia pausada para economizar recursos\n(Clique em Retomar para reativar)"
            )
            self.stack.setCurrentWidget(self.message)
        else:
            self.message.setText(self.monitor.last_status)
            self.monitor.start()
            if self.monitor.last_frame:
                self.present(self.monitor.last_frame)

    def showEvent(self, event):
        super().showEvent(event)
        if not self.is_paused:
            self.monitor.start()
            self.present(self.monitor.last_frame)

    def status(self, text):
        if not self.is_paused:
            self.message.setText(text)
        self.setToolTip(text)

    def present(self, frame):
        if self.is_paused:
            return
        if frame is None:
            self.video.videoSink().setVideoFrame(QVideoFrame())
            self.stack.setCurrentWidget(self.message)
        elif self.isVisible():
            self.stack.setCurrentWidget(self.video)
            self.video.videoSink().setVideoFrame(frame)

