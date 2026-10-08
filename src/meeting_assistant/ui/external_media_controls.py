"""Modeless controls on the operator's monitor; native work stays in services."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QDialog, QGridLayout, QLabel, QPushButton, QSizePolicy

from meeting_assistant.services.external_player_controls import BROWSERS
from meeting_assistant.ui.window_geometry import fit_window


class ExternalMediaControls(QDialog):
    command_requested = Signal(str)
    stop_requested = Signal()

    def __init__(self, process, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        name = {"chrome.exe": "Chrome", "msedge.exe": "Edge", "vlc.exe": "VLC"}.get(
            process.casefold(), "Player"
        )
        self.setWindowTitle("Mídia externa — " + name)
        self.setModal(False)
        self.resize(400, 240)
        self.setMinimumSize(300, 200)
        self._finish = False
        self._phase = "checking"
        self._busy = False
        layout = QGridLayout(self)
        self.hint = QLabel("Controles do aplicativo escolhido. Parar retorna ao JWL.")
        self.hint.setWordWrap(True)
        self.hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.hint, 0, 0, 1, 2)
        self.buttons = {}
        for action, label, row, column in (
            ("play", "▶ Reproduzir", 1, 0), ("pause", "⏸ Pausar", 1, 1),
            ("maximize", "▣ Maximizar", 2, 0), ("fullscreen", "⛶ Tela cheia do vídeo", 3, 0),
        ):
            button = QPushButton(label)
            button.setMinimumHeight(34)
            button.clicked.connect(
                lambda _checked=False, command=action: self.command_requested.emit(command)
            )
            self.buttons[action] = button
            layout.addWidget(button, row, column, 1, 2 if action == "fullscreen" else 1)
        # VLC remains in its captured main window. Its separate native fullscreen
        # output is not adopted by guessing another HWND; Maximizar fills the hall.
        self.buttons["fullscreen"].setVisible(process.casefold() in BROWSERS)
        self.buttons["maximize"].setToolTip("Preenche o monitor do Salão sem selecionar outra janela.")
        self.stop_button = QPushButton("■ Parar mídia")
        self.stop_button.setMinimumHeight(34)
        self.stop_button.clicked.connect(self.stop_requested)
        layout.addWidget(self.stop_button, 2, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.status, 4, 0, 1, 2)
        self.update_phase("checking", "Preparando a apresentação…")

    def show_on_operator_monitor(self):
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.left() + 16, area.top() + 16)
            fit_window(self, area)
        self.show()
        if screen is not None:
            fit_window(self, screen.availableGeometry())

    def update_phase(self, phase, message):
        self._phase = phase
        self.status.setText(message)
        for button in self.buttons.values():
            button.setEnabled(phase == "presenting" and not self._busy)
        returning = phase in {"stopping_media", "stopping", "returning"}
        self.stop_button.setEnabled(not returning)
        self.stop_button.setText("Retornando…" if returning else (
            "Repetir retorno" if phase == "return_failed" else "■ Parar mídia"
        ))

    def control_status(self, busy, message):
        self._busy = busy
        self.update_phase(self._phase, message)

    def finish(self):
        self._finish = True
        self.close()
        self.deleteLater()

    def closeEvent(self, event):
        if self._finish:
            event.accept()
        else:
            event.ignore()
            if self.stop_button.isEnabled():
                self.stop_requested.emit()
