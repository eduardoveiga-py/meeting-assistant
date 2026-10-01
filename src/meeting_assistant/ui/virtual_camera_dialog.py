"""Windows 11 camera controls; closing the view does not stop the session."""

import json
import platform

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QVBoxLayout

from meeting_assistant.services.camera_session import camera_session
from meeting_assistant.services.program_video import program_video
from meeting_assistant.ui.program_preview import ProgramPreview
from meeting_assistant.ui.window_geometry import ScreenFitController


class VirtualCameraDialog(QDialog):
    def __init__(self, parent=None, session=None, monitor=None):
        super().__init__(parent)
        self.setWindowTitle("Câmera Meeting Assistant — Windows 11")
        self.resize(560, 530)
        self.setMinimumSize(360, 300)
        self.session = session or camera_session()
        self.monitor = monitor or program_video()
        root = QVBoxLayout(self)
        title = QLabel(
            "O WhatsApp recebe o Program do OBS, incluindo as trocas de cena.\n"
            "Fechar esta tela mantém a câmera ativa. Para encerrar, use Parar câmera ou saia do app."
        )
        title.setWordWrap(True)
        root.addWidget(title)
        self.preview = ProgramPreview(self, self.monitor)
        root.addWidget(self.preview, 1)
        self.status = QLabel(self.monitor.last_status)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.monitor.status_changed.connect(self.status.setText)
        self.camera_state = QLabel()
        self.camera_state.setWordWrap(True)
        root.addWidget(self.camera_state)
        self.camera_button = QPushButton()
        self.camera_button.clicked.connect(self.toggle_camera)
        root.addWidget(self.camera_button)
        copy_button = QPushButton("Copiar diagnóstico técnico")
        copy_button.clicked.connect(self.copy_diagnostic)
        root.addWidget(copy_button)
        close = QPushButton("Fechar")
        close.clicked.connect(self.reject)
        root.addWidget(close)
        self.session.changed.connect(self.refresh)
        self.refresh()
        self._screen_fit = ScreenFitController(self)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.update_diagnostic)
        self.timer.start()
        self.update_diagnostic()

    def refresh(self):
        running = self.session.state == "running"
        self.camera_state.setText(self.session.message)
        self.camera_button.setText("Parar câmera" if running else "Iniciar câmera para WhatsApp")
        self.camera_button.setEnabled(
            self.session.supported and self.session.state not in {"starting", "stopping"}
        )

    def toggle_camera(self):
        if self.session.state == "running":
            self.session.stop()
        else:
            self.session.start()

    def update_diagnostic(self):
        self.last_diagnostic = {
            "diagnostic_revision": 3,
            "platform": platform.system(), "release": platform.release(),
            "windows_version": platform.version(),
            **self.monitor.diagnostic, **self.session.diagnostic(),
        }

    def copy_diagnostic(self):
        self.update_diagnostic()
        QApplication.clipboard().setText(json.dumps(self.last_diagnostic, ensure_ascii=False, indent=2))
