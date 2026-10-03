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

    def showEvent(self, event):
        super().showEvent(event)
        self.monitor.start()
        self.present(self.monitor.last_frame)

    def status(self, text):
        self.message.setText(text)
        self.setToolTip(text)

    def present(self, frame):
        if frame is None:
            self.video.videoSink().setVideoFrame(QVideoFrame())
            self.stack.setCurrentWidget(self.message)
        elif self.isVisible():
            self.stack.setCurrentWidget(self.video)
            self.video.videoSink().setVideoFrame(frame)
