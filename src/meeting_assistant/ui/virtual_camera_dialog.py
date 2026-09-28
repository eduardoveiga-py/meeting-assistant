"""Experimental video controls; independent of the validated hall engine."""

from __future__ import annotations

import json
import os
import platform
import threading
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from meeting_assistant.services.compat_camera import CompatibilityGate, registered_camera, resolve_backend
from meeting_assistant.services.video_metrics import VideoMetrics
from meeting_assistant.services.virtual_camera import FRAME_BYTES, HEIGHT, WIDTH, camera_support, request
from meeting_assistant.ui.window_geometry import ScreenFitController


class VideoRequest(QThread):
    result = Signal(str, object, object, str)
    command_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.condition = threading.Condition()
        self.command = None
        self.stopping = False

    def submit(self, command):
        with self.condition:
            self.command = command
            self.condition.notify()

    def shutdown(self):
        with self.condition:
            self.stopping = True
            self.condition.notify()
        self.wait()  # Called only after the last bounded request has finished.

    def run(self):
        # Keep one decoding thread/context for the dialog lifetime, not one per frame.
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.command is not None or self.stopping)
                if self.stopping:
                    return
                command, self.command = self.command, None
            try:
                status, pixels = request(command)
                image = frame_image(pixels) if pixels else None
                self.result.emit(command, status, image, "")
            except (OSError, ValueError) as exc:
                self.result.emit(command, None, None, str(exc))
            except Exception:
                self.result.emit(command, None, None, "Falha no diagnóstico de vídeo.")
            self.command_finished.emit()


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
            if stride == WIDTH:
                view[: rows * WIDTH] = pixels[offset : offset + rows * WIDTH]
                continue
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
        self.transport = None
        self.closing = False
        self.stop_requested = False
        self.pending_command = None
        self.metrics = VideoMetrics()
        self.last_diagnostic = {
            "protocol": 1,
            "diagnostic_revision": 2,
            "target_fps": 30,
            "bridge_fps": 0.0,
            "preview_fps": 0.0,
            "transport_errors": 0,
            "platform": platform.system(),
            "release": platform.release(),
            "camera_approved_in_whatsapp": False,
        }
        self.supported, support = camera_support()
        self.compat_gate = None
        self.compat_installed = registered_camera()
        self.host_buffer = ""
        self.host = QProcess(self)
        self.host.readyReadStandardOutput.connect(self.host_output)
        self.host.finished.connect(self.host_finished)
        self.host.errorOccurred.connect(
            lambda _: self.camera_state.setText("Falha ao executar câmera nativa.")
        )
        root = QVBoxLayout(self)
        title = QLabel(
            "Moderno: Windows 11. Compatibilidade: Windows 10/11 x64 (instalação separada).\n"
            "Fechar esta tela encerra o teste e o envio de vídeo. "
            "A câmera do OBS para o Zoom continua independente."
        )
        title.setWordWrap(True)
        root.addWidget(title)
        ndi_button = QPushButton("NDI → WhatsApp (Windows 10/11)")
        ndi_button.clicked.connect(self.open_ndi)
        root.addWidget(ndi_button)
        self.preview = QLabel("Sem quadro confirmado do Program do OBS")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        self.preview.setMinimumSize(0, 100)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
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
        self.backend = QComboBox()
        self.backend.addItem("Automático", "auto")
        self.backend.addItem("Moderno — Windows 11", "modern")
        self.backend.addItem("Compatibilidade — Windows 10/11", "compat")
        root.addWidget(self.backend)
        self.camera_button = QPushButton("Iniciar câmera selecionada")
        self.camera_button.setEnabled(self.supported)
        self.camera_button.clicked.connect(self.toggle_camera)
        self.backend.currentIndexChanged.connect(self.refresh_backend)
        self.refresh_backend()
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
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.poll)
        self._screen_fit = ScreenFitController(self)

    def open_ndi(self):
        from meeting_assistant.ui.ndi_dialog import NdiDialog

        if self.camera_running():
            self.camera_state.setText("Pare a câmera própria antes de abrir o teste NDI.")
            return
        self.timer.stop()
        if self.transport is not None:
            self.send("T")
        NdiDialog(self).exec()

    def poll(self):
        # Keep the diagnostic consumer from competing with the camera for frames.
        if self.closing or self.worker is not None:
            return
        camera_running = self.camera_running()
        command = "I" if camera_running else "F"
        self.timer.setInterval(500 if camera_running else 33)
        self.send(command)

    def send(self, command):
        if self.worker is not None:
            if command != "F":
                self.pending_command = command
            return
        if command in ("S", "T"):
            self.metrics.reset()
        if self.transport is None:
            self.transport = VideoRequest(self)
            self.transport.result.connect(self.result)
            self.transport.command_finished.connect(self.worker_finished)
            self.transport.start()
        self.worker = self.transport
        self.transport.submit(command)

    def result(self, command, status, pixels, error):
        if error:
            self.status.setText(error)
            self.last_diagnostic["last_error"] = error
            self.last_diagnostic["transport_errors"] += 1
            self.last_diagnostic["bridge"] = None
            self.metrics.reset()
            self.last_diagnostic.update(observed_fps=0.0, bridge_fps=0.0, preview_fps=0.0)
            if not self.closing:
                self.timer.start(1000)  # Retry without flooding errors or blocking the UI.
            self.preview.clear()
            self.preview.setText("Sem quadro confirmado")
            return
        self.last_diagnostic.pop("last_error", None)
        self.last_diagnostic["bridge"] = status.diagnostic()
        now = time.monotonic()
        camera_running = self.camera_running()
        displayed = False
        if pixels is not None and not camera_running and pixels:
            try:
                image = frame_image(pixels) if isinstance(pixels, bytes) else pixels
                self.preview.setPixmap(
                    QPixmap.fromImage(image).scaled(
                        self.preview.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                displayed = True
            except ValueError as exc:
                self.status.setText(str(exc))
        elif camera_running and status.enabled and status.fresh:
            self.preview.clear()
            self.preview.setText(
                "Prévia pausada: vídeo recente na ponte OBS. "
                "Confira o reconhecimento e a imagem no aplicativo de chamada."
            )
        elif not status.fresh:
            self.preview.clear()
            self.preview.setText("Sem vídeo recente — câmera deve fornecer preto")
        if status.enabled and status.fresh:
            bridge_fps, preview_fps = self.metrics.observe(now, status.sequence, displayed)
        else:
            self.metrics.reset()
            bridge_fps = preview_fps = 0.0
        self.last_diagnostic.update(
            observed_fps=bridge_fps,
            bridge_fps=bridge_fps,
            preview_fps=preview_fps,
            preview_paused_for_camera=camera_running,
        )
        preview_text = "pausada (câmera em uso)" if camera_running else f"{preview_fps:.1f} fps"
        self.status.setText(
            f"Envio: {'ligado' if status.enabled else 'desligado'} • quadro: {status.sequence}\n"
            f"Ponte: {bridge_fps:.1f} fps • Prévia: {preview_text} • "
            f"{'vídeo recente' if status.fresh else 'sem vídeo recente'}"
        )
        if not self.closing and (command == "S" or status.enabled):
            interval = 500 if camera_running else 33
            if self.timer.interval() != interval:
                self.timer.setInterval(interval)
            if not self.timer.isActive():
                self.timer.start()
        if command == "T":
            self.timer.stop()

    def worker_finished(self):
        self.worker = None
        for button in self.controls:
            button.setEnabled(True)
        if self.closing:
            self.pending_command = None
            self.reject()
        elif self.pending_command is not None:
            command, self.pending_command = self.pending_command, None
            self.send(command)

    def camera_running(self):
        return self.compat_gate is not None or self.host.state() != QProcess.ProcessState.NotRunning

    def refresh_backend(self):
        selected = resolve_backend(self.backend.currentData(), self.supported)
        self.last_diagnostic["camera_backend"] = selected
        self.last_diagnostic["compat_registered"] = self.compat_installed
        self.last_diagnostic["compat_enabled"] = self.compat_gate is not None
        self.camera_button.setEnabled(self.supported if selected == "modern" else self.compat_installed)
        if selected == "compat" and not self.compat_installed:
            self.camera_state.setText(
                "Instale o componente Compat e reabra esta tela. Reconhecimento no WhatsApp exige teste."
            )

    def toggle_camera(self):
        if self.compat_gate is not None:
            self.compat_gate.close()
            self.compat_gate = None
            self.backend.setEnabled(True)
            self.camera_button.setText("Iniciar câmera selecionada")
            self.camera_state.setText(
                "Envio de compatibilidade parado; câmera registrada permanece na lista."
            )
            self.refresh_backend()
            self.send("T")
            return
        if self.host.state() != QProcess.ProcessState.NotRunning:
            self.host.write(b"stop\n")
            return
        if resolve_backend(self.backend.currentData(), self.supported) == "compat":
            if not self.compat_installed:
                return
            try:
                self.compat_gate = CompatibilityGate()
            except OSError as exc:
                self.camera_state.setText(str(exc))
                return
            self.backend.setEnabled(False)
            self.camera_button.setText("Parar câmera de compatibilidade")
            self.camera_state.setText(
                "Envio DirectShow autorizado. Selecione Meeting Assistant Compat num aplicativo compatível. "
                "No WhatsApp testado no Windows 10, use a opção NDI."
            )
            self.preview.clear()
            self.preview.setText("Prévia pausada: confira a imagem no aplicativo que usa a câmera.")
            self.refresh_backend()
            self.send("S")
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
        self.host_buffer = ""
        self.backend.setEnabled(False)
        self.host.start(str(executable), [])

    def host_output(self):
        self.host_buffer += bytes(self.host.readAllStandardOutput()).decode("utf-8", errors="replace")
        while "\n" in self.host_buffer:
            text, self.host_buffer = self.host_buffer.split("\n", 1)
            text = text.strip()[:200]
            self.last_diagnostic["camera_api"] = text
            if text == "CAMERA_STARTED":
                self.camera_state.setText(
                    "Windows confirmou a câmera. Selecione Meeting Assistant no WhatsApp."
                )
                self.camera_button.setText("Parar câmera própria")
                self.preview.clear()
                self.preview.setText(
                    "Câmera em uso: confira a imagem no WhatsApp. Diagnóstico continua ativo."
                )
            elif text.startswith("CAMERA_ERROR"):
                self.camera_state.setText(text + " — confira instalação e permissões de câmera do Windows.")

    def host_finished(self, exit_code=0, *_):
        self.camera_button.setText("Iniciar câmera selecionada")
        self.backend.setEnabled(True)
        if exit_code:
            error = self.last_diagnostic.get("camera_api", "Falha ao iniciar componente nativo")
            self.camera_state.setText(f"{error} • saída {exit_code}. Copie o diagnóstico.")
        else:
            self.camera_state.setText("Processo da câmera encerrado. OBS/Zoom não foram encerrados.")

    def reject(self):
        if self.compat_gate is not None:
            self.compat_gate.close()
            self.compat_gate = None
            self.last_diagnostic["compat_enabled"] = False
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
        if self.transport is not None:
            self.transport.shutdown()
            self.transport.deleteLater()
            self.transport = None
        super().reject()
