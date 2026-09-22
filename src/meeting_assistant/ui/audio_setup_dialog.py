"""Guided, explicit audio setup over the controller's serialized OBS queue."""

from uuid import uuid4

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from meeting_assistant.services.obs_audio import APPS, MIC, app_name
from meeting_assistant.ui.window_geometry import ScreenFitController


class AudioSetupDialog(QDialog):
    def __init__(self, controller, settings, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.settings = settings
        self.token = uuid4().hex
        self.busy = False
        self.setWindowTitle("Áudio da mesa e das mídias → Zoom")
        self.resize(590, 690)
        self.setMinimumSize(360, 280)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        body = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        guide = QLabel(
            '1. Instale o <a href="https://vb-audio.com/Cable/">VB-CABLE oficial</a> '
            "e reinicie o Windows conforme o instalador.<br>"
            "2. OBS → Configurações → Áudio → Avançado → Dispositivo de monitoramento: "
            "<b>CABLE Input</b>.<br>"
            "3. Zoom → Áudio → Microfone: <b>CABLE Output</b>. Alto-falante: saída física do salão.<br>"
            "4. Abra os aplicativos de mídia, prepare as listas e selecione as fontes abaixo.<br>"
            "A preparação silencia as fontes deste módulo. A ativação afeta o áudio ao vivo. "
            "A câmera virtual continua cuidando da imagem."
        )
        guide.setWordWrap(True)
        guide.setOpenExternalLinks(True)
        body.addWidget(guide)
        self.prepare_button = QPushButton("Preparar / atualizar listas — silencia envio")
        self.prepare_button.clicked.connect(lambda: self.request("prepare"))
        body.addWidget(self.prepare_button)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.microphone = self.combo()
        form.addRow("Entrada da mesa", self.microphone)
        self.applications = {}
        for label in APPS:
            combo = self.combo()
            self.applications[label] = combo
            form.addRow(label, combo)
        body.addLayout(form)
        note = QLabel(
            "Selecione somente os aplicativos usados. Todas as abas do navegador escolhido "
            "podem ser ouvidas. Se a mesa já devolve as mídias ao notebook, a mistura pode "
            "duplicá-las. O retorno do Zoom não pode entrar novamente na saída da mesa "
            "que alimenta o notebook (mix-minus)."
        )
        note.setWordWrap(True)
        body.addWidget(note)
        self.confirmations = []
        for text in (
            "Conferi CABLE Input como monitoramento do OBS.",
            "Conferi CABLE Output como microfone do Zoom e a saída física como alto-falante.",
            "Conferi que a entrada da mesa não devolve Zoom nem duplica as mídias.",
        ):
            row = QHBoxLayout()
            check = QCheckBox()
            check.setAccessibleName(text)
            check.setToolTip(text)
            label = QLabel(text)
            label.setWordWrap(True)
            row.addWidget(check)
            row.addWidget(label, 1)
            check.toggled.connect(self.refresh_enabled)
            body.addLayout(row)
            self.confirmations.append(check)
        hint = QLabel(
            "As confirmações são manuais. O app não verifica os dispositivos escolhidos "
            "no Zoom nem o cabo físico da mesa. No OBS, deixe outras fontes sem monitoramento. "
            "As escolhas ficam salvas na coleção de cenas do OBS, incluindo a ativação."
        )
        hint.setWordWrap(True)
        body.addWidget(hint)
        body.addStretch()
        self.status = QLabel(
            "Envio ainda não verificado nesta tela. Preparar altera somente as fontes de áudio do app."
        )
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        outer.addWidget(self.status)
        self.activate_button = QPushButton("Aplicar seleção e ativar envio ao Zoom")
        self.activate_button.clicked.connect(lambda: self.request("activate"))
        outer.addWidget(self.activate_button)
        self.mute_button = QPushButton("Silenciar envio do app")
        self.mute_button.clicked.connect(lambda: self.request("mute"))
        outer.addWidget(self.mute_button)
        self.close_button = QPushButton("Fechar")
        self.close_button.clicked.connect(self.reject)
        outer.addWidget(self.close_button)
        controller.audio_task_finished.connect(self.on_result)
        self.finished.connect(self.disconnect_results)
        self.refresh_enabled()
        self._screen_fit = ScreenFitController(self)

    @staticmethod
    def combo():
        combo = QComboBox()
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(12)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        combo.addItem("Não selecionado", "")
        return combo

    def refresh_enabled(self):
        self.prepare_button.setEnabled(not self.busy)
        self.mute_button.setEnabled(not self.busy)
        self.close_button.setEnabled(not self.busy)
        self.activate_button.setEnabled(
            not self.busy
            and bool(self.microphone.currentData())
            and all(c.isChecked() for c in self.confirmations)
        )
        for widget in (self.microphone, *self.applications.values(), *self.confirmations):
            widget.setEnabled(not self.busy)

    def request(self, action):
        if self.busy:
            return
        data = {
            "microphone": self.microphone.currentData(),
            "applications": {k: v.currentData() for k, v in self.applications.items()},
            "routing_confirmed": all(c.isChecked() for c in self.confirmations),
            "scenes": [
                self.settings.scene_background,
                self.settings.scene_speaker,
                self.settings.scene_media,
            ],
        }
        self.busy = True
        self.refresh_enabled()
        self.status.setText("Aguardando OBS…")
        self.controller.audio_task(self.token, action, data)

    def on_result(self, token, action, ok, result):
        if token != self.token:
            return
        self.busy = False
        self.status.setText(result["message"])
        if ok and action == "prepare":
            self.populate(self.microphone, result["microphones"], result["selected"][MIC].get("device_id"))
            for label, combo in self.applications.items():
                self.populate(
                    combo, result["applications"][label], result["selected"][app_name(label)].get("window")
                )
            for check in self.confirmations:
                check.setChecked(False)
        self.refresh_enabled()

    def populate(self, combo, choices, selected):
        combo.clear()
        combo.addItem("Não selecionado", "")
        for item in choices:
            combo.addItem(item["itemName"], item["itemValue"])
        combo.setCurrentIndex(max(0, combo.findData(selected)))
        # Connect only once, including the first prepare result.
        if not combo.property("audioConnected"):
            combo.currentIndexChanged.connect(self.refresh_enabled)
            combo.setProperty("audioConnected", True)

    def disconnect_results(self):
        self.controller.audio_task_finished.disconnect(self.on_result)

    def reject(self):
        if not self.busy:
            super().reject()
