"""Operator-directed NDI integration; no dependency on native camera prototype."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QProcess, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from meeting_assistant.services.ndi_output import SETUP_HELP, NdiUnavailable, find_webcam_input, run_action
from meeting_assistant.ui.window_geometry import ScreenFitController


class NdiRequest(QThread):
    result = Signal(object, str)

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.action = action

    def run(self):
        try:
            self.result.emit(run_action(self.action), "")
        except NdiUnavailable as exc:
            self.result.emit(None, str(exc))
        except Exception:
            # Do not display connection details or credentials in diagnostics.
            self.result.emit(
                None,
                "Não foi possível consultar/controlar NDI. Confira OBS aberto, "
                "WebSocket e os ajustes de conexão salvos no app; tente Verificar novamente.",
            )


class NdiDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NDI → WhatsApp")
        self.resize(540, 590)
        self.worker = None
        self.report = {"backend": "ndi", "status": "not_checked", "whatsapp_video_confirmed": False}
        self.executable = find_webcam_input()
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        body = QVBoxLayout(content)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        self.add_text(
            body,
            "Envia o Program do OBS: as trocas de cenas aparecem na câmera NDI. "
            "Use este caminho no Windows 10/11; não precisa iniciar Compat ou a ponte experimental.",
        )
        self.add_text(body, "Primeira configuração: " + SETUP_HELP)
        self.add_text(
            body,
            "No NDI Webcam Input, clique com o botão direito no ícone junto ao relógio "
            "e selecione este computador → a transmissão do OBS. No WhatsApp, escolha "
            "o NDI Webcam Video correspondente. Mantenha o microfone atual: esta etapa trata do vídeo.",
        )
        self.status = self.add_text(
            body, "Clique em Verificar NDI no OBS. A consulta usa os ajustes já salvos."
        )
        self.controls = []
        for text, action in (
            ("Verificar NDI no OBS", "inspect"),
            ("Iniciar saída NDI", "start"),
            ("Parar saída NDI", "stop"),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, a=action: self.submit(a))
            body.addWidget(button)
            self.controls.append(button)
        button = QPushButton("Abrir NDI Webcam Input")
        button.clicked.connect(self.open_webcam)
        body.addWidget(button)
        for text, url in (
            ("Download oficial: DistroAV", "https://github.com/DistroAV/DistroAV/releases"),
            ("Download oficial: NDI Tools", "https://ndi.video/tools/download/"),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            body.addWidget(button)
        button = QPushButton("Copiar diagnóstico NDI")
        button.clicked.connect(
            lambda: QApplication.clipboard().setText(json.dumps(self.report, ensure_ascii=False, indent=2))
        )
        body.addWidget(button)
        self.add_text(
            body,
            "Fechar esta tela mantém a saída NDI no estado atual. "
            "Para encerrar o envio, use Parar saída NDI e confira a câmera no WhatsApp. "
            "A saída NDI pode ser descoberta por outros dispositivos na rede local.",
        )
        close = QPushButton("Fechar — manter estado atual")
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        self._screen_fit = ScreenFitController(self)

    @staticmethod
    def add_text(layout, text):
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        return label

    def submit(self, action):
        if self.worker is not None:
            return
        self.status.setText("Consultando OBS…")
        for button in self.controls:
            button.setEnabled(False)
        self.worker = NdiRequest(action, self)
        self.worker.result.connect(self.received)
        self.worker.finished.connect(self.finished_request)
        self.worker.start()

    def received(self, report, error):
        if error:
            self.report = {
                "backend": "ndi",
                "status": "error",
                "message": error,
                "whatsapp_video_confirmed": False,
            }
            self.status.setText(error)
            return
        self.report = {"backend": "ndi", **report}
        state = "ATIVA" if report["active"] else "PARADA"
        text = f"Saída NDI no OBS: {state}. Fonte: {report['source_name'] or 'consulte o DistroAV'}."
        if not report["confirmed"]:
            text += " A mudança ainda não foi confirmada; clique em Verificar novamente."
        text += " Reconhecimento e imagem no WhatsApp precisam ser conferidos na chamada."
        self.status.setText(text)

    def finished_request(self):
        self.worker.deleteLater()
        self.worker = None
        for button in self.controls:
            button.setEnabled(True)

    def open_webcam(self):
        if not self.executable or not self.executable.is_file():
            name, _ = QFileDialog.getOpenFileName(
                self, "Selecione o executável do NDI Webcam Input", "", "Aplicativos (*.exe)"
            )
            if not name:
                return
            self.executable = Path(name)
        if self.executable.suffix.lower() != ".exe" or not self.executable.is_file():
            self.status.setText("Selecione o executável instalado do NDI Webcam Input.")
            return
        ok, _ = QProcess.startDetached(str(self.executable), [], str(self.executable.parent))
        self.status.setText(
            "Abertura solicitada. Use o ícone do NDI junto ao relógio para escolher a fonte."
            if ok
            else "Não foi possível abrir o NDI Webcam Input."
        )

    def reject(self):
        if self.worker is not None:
            self.status.setText("Aguarde a consulta ao OBS terminar antes de fechar.")
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
            self.reject()
        else:
            super().closeEvent(event)
