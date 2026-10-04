"""Guided, explicit audio setup over the controller's serialized OBS queue."""

from uuid import uuid4

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
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
    def __init__(self, controller, settings, parent=None, *, settings_service=None):
        super().__init__(parent)
        self.controller = controller
        self.settings = settings
        self.settings_service = settings_service
        self.token = uuid4().hex
        self.busy = False
        self._lists_loaded = False
        self._prepare_selection = None
        self.setWindowTitle("Áudio da mesa e das mídias → Zoom + WhatsApp")
        self.resize(590, 690)
        self.setMinimumSize(360, 280)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        self.scroll = scroll
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
            "3. Zoom e WhatsApp → Áudio → Microfone: <b>CABLE Output</b>. "
            "Alto-falante: saída física do salão.<br>"
            "4. Abra os aplicativos de mídia, prepare as listas e selecione as fontes abaixo.<br>"
            "A preparação silencia as fontes deste módulo. A ativação afeta o áudio ao vivo. "
            "A câmera virtual continua cuidando da imagem."
        )
        guide.setWordWrap(True)
        guide.setOpenExternalLinks(True)
        body.addWidget(guide)
        self.prepare_button = QPushButton("Preparar fontes / atualizar listas")
        self.prepare_button.setToolTip("Prepara as fontes e silencia o envio antes de alterar a seleção.")
        self.prepare_button.clicked.connect(lambda: self.request("prepare"))
        body.addWidget(self.prepare_button)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.profile = self.combo()
        self.profile.clear()
        self.profile.addItem("Mesa + mídias nos dois aplicativos", "shared")
        self.profile.addItem("WhatsApp também recebe participantes do Zoom", "whatsapp_zoom")
        self.profile.setCurrentIndex(max(0, self.profile.findData(settings.audio_profile)))
        form.addRow("Perfil", self.profile)
        self.whatsapp_device = self.combo()
        form.addRow("Segunda entrada virtual para WhatsApp", self.whatsapp_device)
        self.profile.currentIndexChanged.connect(self._profile_changed)
        self.microphone = self.combo()
        form.addRow("Entrada da mesa", self.microphone)
        self.applications = {}
        self.gains = {}
        for label in APPS:
            combo = self.combo()
            self.applications[label] = combo
            form.addRow(label, combo)
        for name in (MIC, *(app_name(label) for label in APPS)):
            gain = QDoubleSpinBox()
            gain.setRange(0, 18)
            gain.setSuffix(" dB")
            gain.setValue(settings.audio_gains_db.get(name, 0))
            self.gains[name] = gain
            form.addRow("Ganho: " + name.removeprefix("Meeting Assistant - "), gain)
        # Native Windows fonts can make an unwrapped label wider than the dialog.
        for row in range(form.rowCount()):
            form.itemAt(row, QFormLayout.ItemRole.LabelRole).widget().setWordWrap(True)
        body.addLayout(form)
        advanced = QLabel(
            "O perfil com participantes Zoom requer dois cabos virtuais "
            "(como o pacote CABLE A+B disponível em "
            '<a href="https://vb-audio.com/Cable/">vb-audio.com/Cable</a>) e o plugin '
            '<a href="https://github.com/exeldro/obs-audio-monitor/releases/tag/0.10.1">'
            "Audio Monitor 0.10.1</a> instalado no OBS. "
            "OBS monitora mesa + mídias no Cabo A (microfone do Zoom); "
            "o plugin envia mesa + mídias + Zoom ao Cabo B (microfone do WhatsApp). "
            "Os dois destinos precisam ser diferentes. Reinicie OBS após instalar o plugin. "
            "No perfil comum, Zoom não pode ser selecionado como fonte. "
            "O ganho fica antes do limitador a −3 dB. Comece em 0 dB e aumente aos poucos; "
            "o limitador não corrige distorção já existente na entrada da mesa."
        )
        advanced.setWordWrap(True)
        advanced.setOpenExternalLinks(True)
        body.addWidget(advanced)
        note = QLabel(
            "Selecione somente os aplicativos usados. Todas as abas do navegador escolhido "
            "podem ser ouvidas. Se a mesa já devolve as mídias ao notebook, a mistura pode "
            "duplicá-las. O retorno do Zoom não pode entrar novamente na saída da mesa "
            "que alimenta o notebook (mix-minus). O botão principal do app controla "
            "somente o retorno do WhatsApp; ele não silencia o mix enviado aos aplicativos."
        )
        note.setWordWrap(True)
        body.addWidget(note)
        self.confirmations = []
        for text in (
            "Conferi CABLE Input como monitoramento do OBS.",
            "Conferi os microfones virtuais do perfil escolhido e a saída física como alto-falante.",
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
            "no Zoom/WhatsApp nem o cabo físico da mesa. No OBS, deixe outras fontes sem monitoramento. "
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
        self.readiness = QLabel()
        self.readiness.setWordWrap(True)
        self.readiness.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        outer.addWidget(self.readiness)
        self.levels = QLabel("Medidores OBS: aguardando sinal.")
        self.levels.setWordWrap(True)
        outer.addWidget(self.levels)
        self.activate_button = QPushButton("Aplicar seleção e ativar envio")
        self.activate_button.setToolTip("Ativar o envio ao Zoom e WhatsApp conforme o perfil selecionado.")
        self.activate_button.clicked.connect(lambda: self.request("activate"))
        outer.addWidget(self.activate_button)
        self.mute_button = QPushButton("Silenciar mix enviado aos aplicativos")
        self.mute_button.clicked.connect(lambda: self.request("mute"))
        outer.addWidget(self.mute_button)
        self.close_button = QPushButton("Fechar")
        self.close_button.clicked.connect(self.reject)
        outer.addWidget(self.close_button)
        controller.audio_task_finished.connect(self.on_result)
        if hasattr(controller, "audio_levels_changed"):
            controller.audio_levels_changed.connect(self._levels_changed)
        self.finished.connect(self.disconnect_results)
        self._profile_changed()
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

    def _activation_blockers(self):
        blockers = []
        if not self.microphone.currentData():
            blockers.append(("selecione a entrada física da mesa", self.microphone))
        if self.profile.currentData() == "whatsapp_zoom" and not self.whatsapp_device.currentData():
            blockers.append(
                ("selecione o segundo cabo virtual para WhatsApp", self.whatsapp_device)
            )
        missing_confirmation = next((c for c in self.confirmations if not c.isChecked()), None)
        if missing_confirmation is not None:
            blockers.append(("confirme as três verificações de roteamento", missing_confirmation))
        return blockers

    def refresh_enabled(self):
        blockers = self._activation_blockers()
        self.prepare_button.setEnabled(not self.busy)
        self.mute_button.setEnabled(not self.busy)
        self.close_button.setEnabled(not self.busy)
        self.activate_button.setEnabled(not self.busy and not blockers)
        self.readiness.setText(
            "Para habilitar Aplicar: " + "; ".join(message for message, _ in blockers) + "."
            if blockers
            else ""
        )
        self.readiness.setVisible(bool(blockers) and not self.busy)
        for widget in (
            self.microphone,
            self.profile,
            self.whatsapp_device,
            *self.gains.values(),
            *self.applications.values(),
            *self.confirmations,
        ):
            widget.setEnabled(not self.busy)
        self.applications["Zoom"].setEnabled(not self.busy and self.profile.currentData() == "whatsapp_zoom")
        self.whatsapp_device.setEnabled(not self.busy and self.profile.currentData() == "whatsapp_zoom")
        for label, combo in self.applications.items():
            self.gains[app_name(label)].setEnabled(
                not self.busy and combo.isEnabled() and bool(combo.currentData())
            )
        self.gains[MIC].setEnabled(not self.busy and bool(self.microphone.currentData()))

    def _profile_changed(self):
        if self.profile.currentData() == "shared":
            self.applications["Zoom"].setCurrentIndex(0)
        for check in self.confirmations:
            check.setChecked(False)
        self.refresh_enabled()

    def request(self, action):
        if self.busy:
            return
        if action == "activate" and self._activation_blockers():
            self.refresh_enabled()
            self.scroll.ensureWidgetVisible(self._activation_blockers()[0][1], 50, 40)
            return
        data = {
            "profile": self.profile.currentData(),
            "whatsapp_device": self.whatsapp_device.currentData(),
            "gains_db": {name: gain.value() for name, gain in self.gains.items()},
            "microphone": self.microphone.currentData(),
            "applications": {k: v.currentData() for k, v in self.applications.items()},
            "routing_confirmed": all(c.isChecked() for c in self.confirmations),
            "scenes": [
                self.settings.scene_background,
                self.settings.scene_speaker,
                self.settings.scene_media,
            ],
        }
        if action == "prepare":
            # First discovery restores OBS's saved choices. Subsequent refreshes
            # preserve the operator's edits, including deliberate deselection.
            self._prepare_selection = data if self._lists_loaded else None
        self.busy = True
        self.refresh_enabled()
        self.status.setText("Aguardando OBS…")
        self.controller.audio_task(self.token, action, data)

    def on_result(self, token, action, ok, result):
        if token != self.token:
            return
        self.busy = False
        self.status.setText(result["message"])
        if ok and action == "activate":
            self.settings.audio_profile = result["profile"]
            self.settings.whatsapp_audio_device = result["whatsapp_device"]
            self.settings.audio_gains_db = result["gains_db"]
            if self.settings_service:
                try:
                    self.settings_service.save(self.settings)
                except OSError:
                    self.status.setText(
                        "Rota aplicada, mas ajustes do app não foram salvos. Confira permissões."
                    )
        if ok and action == "prepare":
            prior = self._prepare_selection
            self.populate(
                self.whatsapp_device,
                result.get("outputs", []),
                prior["whatsapp_device"] if prior is not None else self.settings.whatsapp_audio_device,
            )
            self.populate(
                self.microphone,
                result["microphones"],
                prior["microphone"] if prior is not None else result["selected"][MIC].get("device_id"),
            )
            for label, combo in self.applications.items():
                self.populate(
                    combo,
                    result["applications"][label],
                    prior["applications"][label]
                    if prior is not None
                    else result["selected"][app_name(label)].get("window"),
                )
            self._lists_loaded = True
            self._profile_changed()
        if action == "prepare":
            self._prepare_selection = None
        self.refresh_enabled()
        if ok and action == "prepare" and self._activation_blockers():
            self.scroll.ensureWidgetVisible(self._activation_blockers()[0][1], 50, 40)

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

    def _levels_changed(self, levels):
        voice, media = levels

        def display(value):
            return "—" if value is None else f"{value:.1f} dBFS"

        self.levels.setText(f"Medidores OBS · mesa: {display(voice)} · mídias: {display(media)}")

    def disconnect_results(self):
        self.controller.audio_task_finished.disconnect(self.on_result)
        if hasattr(self.controller, "audio_levels_changed"):
            self.controller.audio_levels_changed.disconnect(self._levels_changed)

    def reject(self):
        if not self.busy:
            super().reject()
