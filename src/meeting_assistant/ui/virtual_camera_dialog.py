"""Experimental video controls; independent of the validated hall engine."""

from __future__ import annotations

import json
import os
import platform
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QVBoxLayout

from meeting_assistant.services.virtual_camera import FRAME_BYTES, HEIGHT, WIDTH, camera_support, request
from meeting_assistant.ui.window_geometry import ScreenFitController


class VideoRequest(QThread):
    result = Signal(str, object, bytes, str)

    def __init__(self, command, parent=None):
        super().__init__(parent)
        self.command = command

    def run(self):
        try:
            status, pixels = request(self.command)
            self.result.emit(self.command, status, pixels, "")
        except (OSError, ValueError) as exc:
            self.result.emit(self.command, None, b"", str(exc))
        except Exception:
            self.result.emit(self.command, None, b"", "Falha no diagnóstico de vídeo.")


def frame_image(pixels):
    from PySide6.QtMultimedia import QVideoFrame, QVideoFrameFormat

    if len(pixels) != FRAME_BYTES:
        raise ValueError("Quadro NV12 incompleto.")
    fmt = QVideoFrameFormat(QSize(WIDTH, HEIGHT), QVideoFrameFormat.PixelFormat.Format_NV12)
    fmt.setColorSpace(QVideoFrameFormat.ColorSpace.ColorSpace_BT709)
    fmt.setColorRange(QVideoFrameFormat.ColorRange.ColorRange_Video)
    frame = QVideoFrame(fmt)
    if not frame.map(QVideoFrame.MapMode.WriteOnly):
        raise ValueError("Prévia indisponível.")
    try:
        for plane, rows, offset in ((0, HEIGHT, 0), (1, HEIGHT // 2, WIDTH * HEIGHT)):
            stride = frame.bytesPerLine(plane)
            view = frame.bits(plane)
            for row in range(rows):
                view[row * stride : row * stride + WIDTH] = pixels[
                    offset + row * WIDTH : offset + (row + 1) * WIDTH
                ]
    finally:
        frame.unmap()
    return frame.toImage()


class VirtualCameraDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Câmera Meeting Assistant — experimental")
        self.resize(560, 600)
        self.setMinimumSize(360, 300)
        self.worker = None
        self.closing = False
        self.stop_requested = False
        self.last_sequence = None
        self.last_time = None
        self.last_diagnostic = {
            "protocol": 1,
            "platform": platform.system(),
            "release": platform.release(),
            "camera_approved_in_whatsapp": False,
        }
        self.supported, support = camera_support()
        self.host = QProcess(self)
        self.host.readyReadStandardOutput.connect(self.host_output)
        self.host.finished.connect(self.host_finished)
        self.host.errorOccurred.connect(
            lambda _: self.camera_state.setText("Falha ao executar câmera nativa.")
        )
        root = QVBoxLayout(self)
        title = QLabel(
            support + "\nFechar esta tela encerra o teste e a câmera própria. "
            "A câmera do OBS para o Zoom continua independente."
        )
        title.setWordWrap(True)
        root.addWidget(title)
        self.preview = QLabel("Sem quadro confirmado do Program do OBS")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(0, 100)
        root.addWidget(self.preview, 1)
        self.status = QLabel("Instale o plugin de teste no OBS e clique em Verificar.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.controls = []
        for label, command in (
            ("Verificar ponte OBS", "I"),
            ("Iniciar envio de vídeo", "S"),
            ("Parar envio de vídeo", "T"),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, cmd=command: self.send(cmd))
            root.addWidget(button)
            self.controls.append(button)
        self.camera_state = QLabel("Câmera própria ainda não iniciada.")
        self.camera_state.setWordWrap(True)
        root.addWidget(self.camera_state)
        self.camera_button = QPushButton("Iniciar câmera própria (Windows 11)")
        self.camera_button.setEnabled(self.supported)
        self.camera_button.clicked.connect(self.toggle_camera)
        root.addWidget(self.camera_button)
        copy_button = QPushButton("Copiar diagnóstico técnico")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(
                json.dumps(self.last_diagnostic, ensure_ascii=False, indent=2)
            )
        )
        root.addWidget(copy_button)
        close = QPushButton("Fechar e encerrar teste")
        close.clicked.connect(self.reject)
        root.addWidget(close)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(lambda: self.send("F"))
        self._screen_fit = ScreenFitController(self)

    def send(self, command):
        if self.worker is not None:
            return
        self.worker = VideoRequest(command, self)
        self.worker.result.connect(self.result)
        self.worker.finished.connect(self.worker_finished)
        for button in self.controls:
            button.setEnabled(False)
        self.worker.start()

    def result(self, command, status, pixels, error):
        if error:
            self.status.setText(error)
            self.last_diagnostic["last_error"] = error
            self.preview.clear()
            self.preview.setText("Sem quadro confirmado")
            return
        self.last_diagnostic.pop("last_error", None)
        self.last_diagnostic["bridge"] = status.diagnostic()
        now = time.monotonic()
        fps = 0.0
        if self.last_sequence is not None and now > self.last_time and status.sequence >= self.last_sequence:
            fps = (status.sequence - self.last_sequence) / (now - self.last_time)
        self.last_sequence, self.last_time = status.sequence, now
        self.last_diagnostic["observed_fps"] = round(fps, 1)
        self.status.setText(
            f"Envio: {'ligado' if status.enabled else 'desligado'} • "
            f"quadro: {status.sequence} • taxa observada: {fps:.1f}/s • "
            f"{'vídeo recente' if status.fresh else 'sem vídeo recente'}"
        )
        if pixels:
            try:
                image = frame_image(pixels)
                self.preview.setPixmap(
                    QPixmap.fromImage(image).scaled(
                        self.preview.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            except ValueError as exc:
                self.status.setText(str(exc))
        elif not status.fresh:
            self.preview.clear()
            self.preview.setText("Sem vídeo recente — câmera deve fornecer preto")
        if command == "S" or status.enabled:
            self.timer.start()
        if command == "T":
            self.timer.stop()

    def worker_finished(self):
        self.worker.deleteLater()
        self.worker = None
        for button in self.controls:
            button.setEnabled(True)
        if self.closing:
            self.reject()

    def toggle_camera(self):
        if self.host.state() != QProcess.ProcessState.NotRunning:
            self.host.write(b"stop\n")
            return
        if not self.supported:
            return
        executable = (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "MeetingAssistant"
            / "VirtualCamera"
            / "meeting-assistant-camera.exe"
        )
        if not executable.is_file():
            self.camera_state.setText(
                "Componente nativo ausente. Execute o instalador de teste no Windows 11."
            )
            return
        self.camera_state.setText("Aguardando confirmação da API do Windows…")
        self.host.start(str(executable), [])

    def host_output(self):
        text = bytes(self.host.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
        self.last_diagnostic["camera_api"] = text[:200]
        if "CAMERA_STARTED" in text:
            self.camera_state.setText("Windows confirmou a câmera. Selecione Meeting Assistant no WhatsApp.")
            self.camera_button.setText("Parar câmera própria")
        elif "CAMERA_ERROR" in text:
            self.camera_state.setText(text + " — confira instalação e permissões de câmera do Windows.")

    def host_finished(self, *_):
        self.camera_button.setText("Iniciar câmera própria (Windows 11)")
        self.camera_state.setText("Processo da câmera encerrado. OBS/Zoom não foram encerrados.")

    def reject(self):
        self.timer.stop()
        if self.worker is not None:
            self.closing = True
            return
        if not self.stop_requested:
            self.closing = True
            self.stop_requested = True
            self.send("T")
            return
        if self.host.state() != QProcess.ProcessState.NotRunning:
            self.host.write(b"stop\n")
            if not self.host.waitForFinished(1500):
                self.host.kill()
                self.host.waitForFinished(500)
        super().reject()
