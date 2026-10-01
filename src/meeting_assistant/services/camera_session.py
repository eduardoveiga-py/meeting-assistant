"""Application-scoped Windows 11 camera lifecycle, independent of its dialog."""

from __future__ import annotations

import os
import queue
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication

from meeting_assistant.services.virtual_camera import camera_support, request


class CameraControl(QThread):
    result = Signal(str, object, str)

    def __init__(self, parent=None, requester=request):
        super().__init__(parent)
        self.commands = queue.Queue()
        self.requester = requester

    def run(self):
        while (command := self.commands.get()) is not None:
            try:
                status, _ = self.requester(command)
                self.result.emit(command, status, "")
            except (OSError, ValueError) as exc:
                self.result.emit(command, None, str(exc))

    def shutdown(self):
        self.commands.put("T")
        self.commands.put(None)
        self.wait()  # Finite queue, each request has bounded pipe I/O.


class CameraSession(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.supported, reason = camera_support()
        self.state = "off"
        self.message = "Câmera desligada." if self.supported else reason
        self.api_result = ""
        self.buffer = ""
        self.control = None
        self.shutting_down = False
        self.host = QProcess(self)
        self.host.readyReadStandardOutput.connect(self.host_output)
        self.host.finished.connect(self.host_finished)
        self.host.errorOccurred.connect(self.host_error)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.setInterval(10000)
        self.deadline.timeout.connect(self.start_timeout)
        self.health = QTimer(self)
        self.health.setInterval(1500)
        self.health.timeout.connect(self.check_bridge)
        self.health_pending = False

    def _set(self, state, message):
        self.state, self.message = state, message
        self.changed.emit()

    def _command(self, command):
        if self.control is None:
            self.control = CameraControl(self)
            self.control.result.connect(self.control_result)
            self.control.start()
        self.control.commands.put(command)

    def start(self):
        if not self.supported or self.state in {"starting", "running", "stopping"}:
            return
        executable = (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "MeetingAssistant/VirtualCamera/meeting-assistant-camera.exe"
        )
        if not executable.is_file():
            self._set("error", "Câmera nativa ausente. Instale o componente Camera do pacote Windows 11.")
            return
        self.executable = str(executable)
        self.api_result = self.buffer = ""
        self._set("starting", "Preparando vídeo do Program e câmera do Windows…")
        self.deadline.start()
        self._command("S")

    def stop(self):
        self.deadline.stop()
        self._set("stopping", "Encerrando câmera…")
        if self.host.state() != QProcess.ProcessState.NotRunning:
            self.host.write(b"stop\n")
            QTimer.singleShot(2000, self._finish_stop)
        else:
            self._command("T")

    def _finish_stop(self):
        if self.state == "stopping" and self.host.state() != QProcess.ProcessState.NotRunning:
            self.host.kill()  # Only our session host, never OBS/Zoom/JWL.

    def control_result(self, command, status, error):
        if self.shutting_down:
            return
        if command == "I":
            self.health_pending = False
            if self.state == "running" and not error and status is not None and not status.enabled:
                self._command("S")  # OBS restarted while the user still wants the camera active.
            return
        if command == "S" and self.state == "starting":
            if error or status is None or not status.enabled:
                self.deadline.stop()
                self._set("error", error or "A ponte do OBS não confirmou o envio.")
                self._command("T")
                return
            self.host.start(self.executable, [])
        elif command == "T" and self.state == "stopping":
            if error:
                self._set("error", "Câmera encerrada; ponte indisponível: " + error)
            else:
                self._set("off", "Câmera desligada. A prévia do Program continua disponível.")

    def host_output(self):
        self.buffer += bytes(self.host.readAllStandardOutput()).decode("utf-8", errors="replace")
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            line = line.strip()[:200]
            self.api_result = line
            if line == "CAMERA_STARTED" and self.state == "starting":
                self.deadline.stop()
                self._set("running", "Câmera ativa no Windows. Selecione Meeting Assistant no WhatsApp.")
                self.health.start()
            elif line.startswith("CAMERA_ERROR"):
                self.deadline.stop()
                self._set("error", line + " — confira instalação e permissão de câmera no Windows.")

    def host_error(self, _error):
        if self.shutting_down or self.state == "stopping":
            return
        self.deadline.stop()
        self._set("error", self.api_result or "Não foi possível executar a câmera nativa.")
        self._command("T")

    def host_finished(self, exit_code=0, *_):
        self.deadline.stop()
        if self.shutting_down:
            return
        if self.state != "error":
            if exit_code and self.state != "stopping":
                self._set("error", f"Câmera encerrada com código {exit_code}. {self.api_result}")
            else:
                self._set("stopping", "Câmera encerrada; desativando envio…")
        self._command("T")

    def start_timeout(self):
        if self.state != "starting":
            return
        self._set("error", "O Windows não confirmou a câmera em 10 segundos. Copie o diagnóstico.")
        if self.host.state() != QProcess.ProcessState.NotRunning:
            self.host.kill()
        self._command("T")

    def check_bridge(self):
        if self.state == "running" and not self.health_pending:
            self.health_pending = True
            self._command("I")

    def diagnostic(self):
        return {
            "camera_backend": "windows11-media-foundation",
            "camera_state": self.state,
            "camera_api": self.api_result,
            "camera_message": self.message,
            "camera_approved_in_whatsapp": False,
        }

    def shutdown(self):
        if self.shutting_down:
            return
        self.shutting_down = True
        self.deadline.stop()
        self.health.stop()
        if self.host.state() != QProcess.ProcessState.NotRunning:
            self.host.write(b"stop\n")
            if not self.host.waitForFinished(1500):
                self.host.kill()
                self.host.waitForFinished(500)
        if self.control is not None:
            self.control.shutdown()
            self.control = None


def camera_session():
    app = QApplication.instance()
    if not hasattr(app, "_camera_session"):
        app._camera_session = CameraSession(app)
        app.aboutToQuit.connect(app._camera_session.shutdown)
    return app._camera_session
