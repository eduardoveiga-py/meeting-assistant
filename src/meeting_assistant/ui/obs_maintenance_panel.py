"""One inspect/complete flow; delegates every OBS operation to its worker."""

from uuid import uuid4

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget


class ObsMaintenancePanel(QWidget):
    idle = Signal()
    activity_changed = Signal(bool)
    plugins_requested = Signal()

    def __init__(self, owner, save_settings, can_prepare, parent=None):
        super().__init__(parent)
        self.owner, self.save_settings, self.can_prepare = owner, save_settings, can_prepare
        self.token = uuid4().hex
        self.busy, self._action = False, ""
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        hint = QLabel(
            "Verifique e complete só o que falta. Fontes prontas e Program são preservados. "
            "Áudio novo começa silenciado; ative na categoria Áudio."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.check_button = QPushButton("Verificar fontes e plugins")
        self.check_button.clicked.connect(lambda: self.request("inspect"))
        layout.addWidget(self.check_button)
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        self.report.setMinimumHeight(140)
        self.report.setPlainText("Clique em Verificar. A leitura não altera o OBS.")
        layout.addWidget(self.report, 1)
        self.complete_button = QPushButton("Completar fontes ausentes")
        self.complete_button.clicked.connect(lambda: self.request("complete"))
        layout.addWidget(self.complete_button)
        self.plugins_button = QPushButton("Instalar ou reparar plugins…")
        self.plugins_button.clicked.connect(self.plugins_requested.emit)
        layout.addWidget(self.plugins_button)
        self.capture_button = QPushButton("Preparar captura JWL")
        self.capture_button.clicked.connect(self._capture)
        layout.addWidget(self.capture_button)
        self.virtual_button = QPushButton("Ligar câmera virtual do OBS")
        self.virtual_button.clicked.connect(owner.obs.ensure_virtual_camera)
        layout.addWidget(self.virtual_button)
        self.status = QLabel("Preparação disponível com a automação pausada.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        owner.obs.maintenance_task_finished.connect(self._finished)
        owner.obs.hall_task_finished.connect(self._capture_finished)

    def request(self, action):
        if self.busy or action != "inspect" and not self.can_prepare():
            return
        if not self.save_settings():
            return
        self._busy(action)
        self.owner.obs.maintenance_task(
            self.token, action, self.owner.settings, self.owner.yeartext_store.directory
        )

    def _busy(self, action):
        self.busy, self._action = True, action
        self.status.setText("Aguardando confirmação do OBS…")
        for button in (self.check_button, self.complete_button, self.capture_button, self.plugins_button):
            button.setEnabled(False)
        self.virtual_button.setEnabled(False)
        self.activity_changed.emit(True)

    def _finished(self, token, action, ok, result):
        if token != self.token or action != self._action:
            return
        states = {
            "ok": "OK",
            "missing": "A CRIAR",
            "blocked": "PRÉ-REQUISITO",
            "attention": "REVISAR",
            "optional": "OPCIONAL",
        }
        if "rows" in result:
            self.report.setPlainText(
                "\n\n".join(
                    f"{states[row['state']]} · {row['label']}\n{row['detail']}" for row in result["rows"]
                )
            )
        self._unbusy(result["message"])

    def _capture(self):
        if self.busy or not self.can_prepare() or not self.save_settings():
            return
        self._busy("capture")
        self.owner.obs.hall_task("media", {"scene": self.owner.settings.scene_media})

    def _capture_finished(self, action, ok, message):
        if action == "media" and self._action == "capture":
            self._unbusy(message)

    def _unbusy(self, message):
        self.busy, self._action = False, ""
        self.status.setText(message)
        for button in (self.check_button, self.complete_button, self.capture_button, self.plugins_button):
            button.setEnabled(True)
        self.virtual_button.setEnabled(True)
        self.activity_changed.emit(False)
        self.idle.emit()

    def disconnect_results(self):
        self.owner.obs.maintenance_task_finished.disconnect(self._finished)
        self.owner.obs.hall_task_finished.disconnect(self._capture_finished)
