"""Audio routing and independent gain controls over the serialized OBS queue."""

from uuid import uuid4

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from meeting_assistant.services.obs_audio import APPS, MIC, SOURCES, app_name
from meeting_assistant.ui.window_geometry import ScreenFitController


class AudioSetupDialog(QDialog):
    def __init__(self, controller, settings, parent=None, *, settings_service=None):
        super().__init__(parent)
        self.controller, self.settings = controller, settings
        self.settings_service = settings_service
        self.token = uuid4().hex
        self.busy = False
        self._lists_loaded = False
        self._pending_selection = None
        self._request_data = {}
        self._pending_action = ""
        self._source_states = {}
        self._missing_sources = list(SOURCES)
        self._needs_prepare = True
        self._monitor_id = ""
        self._monitor_name = ""
        self._monitor_error = ""
        self._saved_gains = {name: settings.audio_gains_db.get(name, 0.0) for name in SOURCES}
        self.setWindowTitle("Áudio → Zoom e WhatsApp")
        self.resize(590, 650)
        self.setMinimumSize(360, 280)
        outer = QVBoxLayout(self)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        self.scroll, body = self._page("Envio")
        self._label(body, "Escolha o som enviado às chamadas. Para ajustar apenas o volume, use Volumes.")
        row = QHBoxLayout()
        self.refresh_button = QPushButton("Atualizar lista")
        self.refresh_button.setToolTip("Consulta o OBS sem silenciar nem alterar o envio.")
        self.refresh_button.clicked.connect(lambda: self.request("inspect"))
        self.prepare_button = QPushButton("Criar fontes")
        self.prepare_button.setToolTip("Cria ou repara fontes do app no OBS e silencia o envio até ativar.")
        self.prepare_button.clicked.connect(lambda: self.request("prepare"))
        row.addWidget(self.refresh_button)
        row.addWidget(self.prepare_button)
        body.addLayout(row)

        self.profile = self.combo()
        self.profile.clear()
        self.profile.addItem("Mesa e mídias nos dois aplicativos", "shared")
        self.profile.addItem("Incluir participantes do Zoom no WhatsApp", "whatsapp_zoom")
        self.profile.setCurrentIndex(max(0, self.profile.findData(settings.audio_profile)))
        self._field(body, "O que enviar", self.profile)
        self.microphone = self.combo()
        self._field(body, "Microfone / entrada da mesa", self.microphone)
        self.applications = {label: self.combo("Não enviar") for label in APPS}
        self._field(body, "JW Library", self.applications["JW Library"])
        self.zoom_label = self._field(body, "Participantes do Zoom", self.applications["Zoom"])
        self.whatsapp_device = self.combo()
        self.whatsapp_label = self._field(
            body, "Cabo exclusivo do WhatsApp (segundo cabo)", self.whatsapp_device
        )
        self.second_hint = self._label(body, "")

        self.other_sources = QGroupBox("Outras mídias")
        self.other_sources.setCheckable(True)
        self.other_sources.setChecked(False)
        other_layout = QVBoxLayout(self.other_sources)
        self.other_content = QWidget()
        other_body = QVBoxLayout(self.other_content)
        other_body.setContentsMargins(0, 0, 0, 0)
        for label in ("VLC", "Chrome", "Edge"):
            self._field(other_body, label, self.applications[label])
        other_layout.addWidget(self.other_content)
        self.other_content.hide()
        self.other_sources.toggled.connect(self.other_content.setVisible)
        body.addWidget(self.other_sources)
        self.route_summary = self._label(body, "")
        self.route_confirmation = QCheckBox()
        self.route_confirmation.setAccessibleName("Conferi o roteamento de áudio")
        self.route_confirmation.setToolTip("Confira os dispositivos e a entrada física conforme a aba Ajuda.")
        row = QHBoxLayout()
        row.addWidget(self.route_confirmation)
        confirmation_label = self._label(
            row, "Conferi os microfones das chamadas e a mesa sem retorno do Zoom nem mídias duplicadas."
        )
        row.setStretch(1, 1)
        body.addLayout(row)
        # One explicit confirmation covers the same physical checks; gain changes do not require it.
        self.confirmations = [self.route_confirmation]
        self.route_confirmation.toggled.connect(self.refresh_enabled)
        body.addStretch()

        self.volume_scroll, volume_body = self._page("Volume e Melhorias")
        self._label(
            volume_body, "Aumente somente a fonte desejada e clique em Salvar volumes. "
            "Os dispositivos e o envio atual serão preservados. Comece com +3 dB."
        )
        self.volume_hint = self._label(volume_body, "")
        self.gains, self.gain_notes, self.gain_groups = {}, {}, {}
        self.noise_gates = {}
        self.compressors = {}
        self.suppressions = {}

        slider_style = '''
        QSlider::groove:horizontal {
            border: none;
            height: 10px;
            background: #202025;
            border-radius: 5px;
        }
        QSlider::sub-page:horizontal {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1055ff, stop:1 #9020ff);
            border-radius: 5px;
        }
        QSlider::add-page:horizontal {
            background: #202025;
            border-radius: 5px;
        }
        QSlider::handle:horizontal {
            background: white;
            border: none;
            width: 22px;
            height: 22px;
            margin-top: -6px;
            margin-bottom: -6px;
            border-radius: 11px;
        }
        '''

        for name in SOURCES:
            label = "Mesa de Som (Física)" if name == MIC else name.replace("Meeting Assistant - udio ", "").replace("Meeting Assistant - ", "")
            group = QGroupBox(label)
            group.setStyleSheet("QGroupBox { font-weight: bold; margin-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
            layout = QVBoxLayout(group)
            
            vol_layout = QHBoxLayout()
            import PySide6.QtWidgets as _qtw
            import PySide6.QtCore as _qtc
            from functools import partial
            
            gain = _qtw.QSlider(_qtc.Qt.Orientation.Horizontal, group)
            gain.setRange(-30, 18)
            gain.setValue(int(self._saved_gains[name]))
            gain.setStyleSheet(slider_style)
            gain.setCursor(_qtc.Qt.CursorShape.PointingHandCursor)
            
            db_label = QLabel("", group)
            db_label.setFixedWidth(65)
            db_label.setAlignment(_qtc.Qt.AlignmentFlag.AlignCenter)
            
            def _update_db(lbl, val):
                prefix = "+" if val > 0 else ""
                lbl.setText(f"{prefix}{val} dB")
            
            updater = partial(_update_db, db_label)
            gain.valueChanged.connect(updater)
            updater(gain.value())
            
            vol_layout.addWidget(QLabel("🔈", group))
            vol_layout.addWidget(gain)
            vol_layout.addWidget(QLabel("🔊", group))
            vol_layout.addWidget(db_label)
            layout.addLayout(vol_layout)
            
            filters_layout = QHBoxLayout()
            
            supp = None
            if name == MIC:
                supp = _qtw.QCheckBox("Redução de Ruído", group)
                supp.setToolTip("ATENÇÃO: Remove barulho de ar condicionado usando IA. Use apenas se necessário, pois pode engolir o som dos cânticos se vazar nos microfones.")
                supp.stateChanged.connect(self.refresh_enabled)
                filters_layout.addWidget(supp)

            ng = _qtw.QCheckBox("Corte de Ruído", group)
            ng.setToolTip("Noise Gate: Corta completamente o som quando ninguém está falando (ótimo para matar chiado de estática).")
            comp = _qtw.QCheckBox("Compressor", group)
            comp.setToolTip("Nivela o áudio: Abaixa quem fala muito perto do microfone e levanta o volume de quem fala baixo.")
            
            ng.stateChanged.connect(self.refresh_enabled)
            comp.stateChanged.connect(self.refresh_enabled)
            
            filters_layout.addWidget(ng)
            filters_layout.addWidget(comp)
            layout.addLayout(filters_layout)

            note = self._label(layout, "")
            
            self.gains[name], self.gain_notes[name] = gain, note
            self.noise_gates[name] = ng
            self.compressors[name] = comp
            if supp:
                self.suppressions[name] = supp
            self.gain_groups[name] = group
            gain.valueChanged.connect(self.refresh_enabled)
            volume_body.addWidget(group)
        self._label(
            volume_body, "0 dB mantém o volume original. O limitador reduz picos, "
            "mas não corrige ruído ou distorção já presentes na entrada."
        )
        volume_body.addStretch()

        self.help_scroll, help_body = self._page("Ajuda")
        self._label(
            help_body,
            "<b>1. Mesa e mídias</b><br>"
            "OBS → Configurações → Áudio → Avançado → Monitoramento: "
            "CABLE-A Input (ou CABLE Input).<br>"
            "Zoom → Microfone: CABLE-A Output (ou CABLE Output). "
            "No perfil comum, use a mesma saída no WhatsApp."
        )
        self._label(
            help_body,
            "<b>2. Participantes do Zoom no WhatsApp</b><br>"
            "Esse perfil precisa de dois cabos virtuais e do plugin Audio Monitor no OBS. "
            "Escolha a segunda entrada, como CABLE-B Input, na aba Envio. "
            "WhatsApp → Microfone: CABLE-B Output. O Zoom continua no primeiro cabo.<br>"
            'Cabos: <a href="https://vb-audio.com/Cable/">VB-Audio oficial</a><br>'
            'Plugin: <a href="https://github.com/exeldro/obs-audio-monitor/releases/tag/0.10.1">'
            "Audio Monitor 0.10.1</a><br>"
            "Reinicie conforme o instalador e depois clique em Atualizar lista. "
            "Instalar o plugin sozinho não instala o segundo cabo."
        )
        self._label(
            help_body,
            "<b>3. Selecionar fontes e ativar</b><br>"
            "Abra JWL e Zoom antes de atualizar a lista. Selecione a entrada física da mesa "
            "e os aplicativos que serão ouvidos. Outras mídias contém VLC e navegadores.<br>"
            "A mesa que retorna ao notebook deve excluir o som recebido do Zoom e não "
            "duplicar as mídias capturadas pelo app. No OBS, deixe outras fontes sem monitoramento. "
            "O app não verifica os microfones escolhidos dentro das chamadas nem o cabo físico.<br>"
            "Confira esses pontos, marque a confirmação na aba Envio e clique em Ativar envio."
        )
        self._label(
            help_body,
            "<b>4. Durante a reunião</b><br>"
            "Atualizar lista e Salvar volumes preservam o envio. Criar fontes silencia o mix "
            "até você ativá-lo novamente. O botão Silenciar envio interrompe o mix enviado "
            "às chamadas. O botão WhatsApp da tela principal controla somente seu alto-falante."
        )
        help_body.addStretch()

        self.status = self._label(outer, "Lendo a configuração do OBS…")
        self.readiness = self._label(outer, "")
        self.levels = self._label(outer, "Medidores OBS: aguardando sinal.")
        self.activate_button = QPushButton("Ativar envio")
        self.activate_button.clicked.connect(lambda: self.request("activate"))
        outer.addWidget(self.activate_button)
        self.gain_button = QPushButton("🪄 Salvar Volumes e Filtros")
        self.gain_button.clicked.connect(lambda: self.request("gains"))
        outer.addWidget(self.gain_button)
        row = QHBoxLayout()
        self.mute_button = QPushButton("Silenciar envio")
        self.mute_button.clicked.connect(lambda: self.request("mute"))
        self.close_button = QPushButton("Fechar")
        self.close_button.clicked.connect(self.reject)
        row.addWidget(self.mute_button)
        row.addWidget(self.close_button)
        outer.addLayout(row)
        self.profile.currentIndexChanged.connect(self._profile_changed)
        for combo in (self.microphone, self.whatsapp_device, *self.applications.values()):
            combo.currentIndexChanged.connect(self._selection_changed)
        self.tabs.currentChanged.connect(self.refresh_enabled)
        controller.audio_task_finished.connect(self.on_result)
        if hasattr(controller, "audio_levels_changed"):
            controller.audio_levels_changed.connect(self._levels_changed)
        self.finished.connect(self.disconnect_results)
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._load_existing)
        self._screen_fit = ScreenFitController(self)
        confirmation_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        policy = confirmation_label.sizePolicy()
        policy.setHeightForWidth(True)
        confirmation_label.setSizePolicy(policy)
        self._profile_changed()

    def _page(self, name):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        body = QVBoxLayout(content)
        scroll.setWidget(content)
        self.tabs.addTab(scroll, name)
        return scroll, body

    @staticmethod
    def _label(layout, text, *, row=None):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setOpenExternalLinks(True)
        policy = label.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        policy.setHeightForWidth(True)
        label.setSizePolicy(policy)
        if row is None:
            layout.addWidget(label)
        else:
            layout.addWidget(label, row, 0, 1, 2)
        return label

    def _field(self, layout, text, widget):
        label = self._label(layout, text)
        layout.addWidget(widget)
        return label

    @staticmethod
    def combo(placeholder="Não selecionado"):
        combo = QComboBox()
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(8)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        combo.addItem(placeholder, "")
        combo.setProperty("placeholder", placeholder)
        return combo

    def showEvent(self, event):
        super().showEvent(event)
        if not self._lists_loaded:
            self._load_timer.start(0)

    def _load_existing(self):
        if self.isVisible() and not self.busy and not self._lists_loaded:
            self.request("inspect")

    def _selection_changed(self):
        self.route_confirmation.setChecked(False)
        self.refresh_enabled()

    def _profile_changed(self):
        advanced = self.profile.currentData() == "whatsapp_zoom"
        if not advanced:
            self.applications["Zoom"].setCurrentIndex(0)
        for widget in (self.zoom_label, self.applications["Zoom"],
                       self.whatsapp_label, self.whatsapp_device, self.second_hint):
            widget.setVisible(advanced)
        self._selection_changed()

    def _activation_blockers(self):
        blockers = []
        if not self._lists_loaded:
            blockers.append(("aguarde a leitura do OBS ou clique em Atualizar lista", self.refresh_button))
        elif self._needs_prepare:
            blockers.append(("clique em Criar fontes para preparar o áudio", self.prepare_button))
        if not self.microphone.currentData():
            blockers.append(("selecione a entrada física da mesa", self.microphone))
        if self._monitor_error:
            blockers.append((self._monitor_error, self.route_summary))
        advanced = self.profile.currentData() == "whatsapp_zoom"
        if advanced and not self.whatsapp_device.currentData():
            message = (
                "selecione o segundo cabo do WhatsApp"
                if self.whatsapp_device.count() > 1
                else "segundo cabo não encontrado; veja Ajuda para instalar e depois atualize a lista"
            )
            blockers.append((message, self.whatsapp_device))
        if not self.route_confirmation.isChecked():
            blockers.append(("marque a confirmação do roteamento", self.route_confirmation))
        return blockers

    def _gain_changes(self):
        return {
            name: gain.value() for name, gain in self.gains.items()
            if self._source_states.get(name, {}).get("gain_ready")
            and gain.value() != self._saved_gains.get(name, 0.0)
        }

    def refresh_enabled(self, *_args):
        if not hasattr(self, "activate_button"):
            return
        on_routing = self.tabs.currentIndex() == 0
        self.activate_button.setVisible(on_routing)
        self.gain_button.setVisible(self.tabs.currentIndex() == 1)
        # A usable click explains missing fields and focuses them instead of a silent disabled button.
        for button in (self.refresh_button, self.prepare_button, self.mute_button,
                       self.close_button, self.activate_button):
            button.setEnabled(not self.busy)
        self.gain_button.setEnabled(not self.busy and bool(self._gain_changes()))
        for widget in (self.profile, self.microphone, self.whatsapp_device,
                       self.route_confirmation, self.other_sources, *self.applications.values()):
            widget.setEnabled(not self.busy)
        advanced = self.profile.currentData() == "whatsapp_zoom"
        self.applications["Zoom"].setEnabled(not self.busy and advanced)
        self.whatsapp_device.setEnabled(not self.busy and advanced)
        self.prepare_button.setVisible(self._needs_prepare)
        any_gain_ready = False
        for name, gain in self.gains.items():
            ready = self._source_states.get(name, {}).get("gain_ready", False)
            any_gain_ready = any_gain_ready or ready
            self.gain_groups[name].setVisible(ready)
            gain.setEnabled(not self.busy and ready)
            self.gain_notes[name].setText(
                "Pronta para salvar volume." if ready else "Configure na aba Envio."
            )
        self.volume_hint.setText(
            "Altere um ganho para habilitar Salvar volumes."
            if any_gain_ready else "Nenhuma fonte com ganho pronta. Configure e ative na aba Envio primeiro."
        )
        blockers = self._activation_blockers()
        self.readiness.setText("Falta: " + blockers[0][0] + "." if blockers else "")
        self.readiness.setVisible(on_routing and bool(blockers) and not self.busy)
        first = self._monitor_name or "primeiro cabo do OBS"
        second = self.whatsapp_device.currentText() if self.whatsapp_device.currentData() else "segundo cabo"
        self.route_summary.setText(
            f"OBS monitora em: {first}. Zoom usa a saída correspondente. "
            + (f"WhatsApp usa a saída de {second}." if advanced else "WhatsApp usa a mesma saída do Zoom.")
        )
        self.second_hint.setText(
            "Escolha um cabo diferente do monitoramento do OBS."
            if self.whatsapp_device.count() > 1
            else "Segundo cabo não encontrado. Instale os dois cabos pela aba Ajuda e atualize a lista."
        )

    def _data(self):
        return {
            "profile": self.profile.currentData(),
            "whatsapp_device": self.whatsapp_device.currentData(),
            "gains_db": {name: gain.value() for name, gain in self.gains.items()},
            "extra_filters": {name: {"noise_gate": self.noise_gates[name].isChecked(), "compressor": self.compressors[name].isChecked(), "noise_suppression": self.suppressions[name].isChecked() if name in self.suppressions else False, "auto_ducking": self.settings.auto_mute_mic_for_jwl_media} for name in self.gains},
            "microphone": self.microphone.currentData(),
            "applications": {k: v.currentData() for k, v in self.applications.items()},
            "routing_confirmed": self.route_confirmation.isChecked(),
            "scenes": [
                self.settings.scene_background, self.settings.scene_speaker, self.settings.scene_media
            ],
        }

    def request(self, action):
        if self.busy:
            return
        if action == "activate" and self._activation_blockers():
            message, widget = self._activation_blockers()[0]
            self.tabs.setCurrentIndex(0)
            self.status.setText("Envio não ativado: " + message + ".")
            self.scroll.ensureWidgetVisible(widget, 50, 30)
            widget.setFocus()
            return
        if action == "gains":
            data = {"gains_db": self._gain_changes()}
            if not data["gains_db"]:
                self.status.setText("Altere o ganho de uma fonte configurada antes de salvar.")
                return
        else:
            data = self._data()
        if action in {"prepare", "inspect"}:
            self._pending_selection = data if self._lists_loaded else None
        self._request_data = data
        self._pending_action = action
        self.busy = True
        self.refresh_enabled()
        self.status.setText("Aguardando OBS…")
        self.controller.audio_task(self.token, action, data)

    def on_result(self, token, action, ok, result):
        if token != self.token or action != self._pending_action:
            return
        self._pending_action = ""
        self.busy = False
        self.status.setText(result["message"])
        if ok and action in {"activate", "gains"}:
            gains = result.get("gains_db", {})
            self.settings.audio_gains_db.update(gains)
            self._saved_gains.update(gains)
            if action == "activate":
                self.settings.audio_profile = result["profile"]
                self.settings.whatsapp_audio_device = result["whatsapp_device"]
                selected = {MIC, *(app_name(k) for k, v in self._request_data["applications"].items() if v)}
                for name in selected:
                    self._source_states[name] = {"gain_ready": True, "gain_db": gains.get(name, 0.0)}
            if self.settings_service:
                try:
                    self.settings_service.save(self.settings)
                except OSError:
                    self.status.setText("OBS confirmou, mas não foi possível salvar os ajustes do app.")
        if ok and action in {"prepare", "inspect"}:
            self._apply_snapshot(result)
            if action == "prepare":
                self.route_confirmation.setChecked(False)
        if action in {"prepare", "inspect"}:
            self._pending_selection = None
        self.refresh_enabled()

    def _apply_snapshot(self, result):
        prior = self._pending_selection
        before = self._data()
        self._source_states = result.get("source_states", {})
        self._missing_sources = result.get("missing_sources", [])
        self._needs_prepare = result.get("needs_prepare", bool(self._missing_sources))
        self._monitor_id = result.get("monitor", {}).get("monitorDeviceId", "")
        self._monitor_name = result.get("monitor", {}).get("monitorDeviceName", "")
        self._monitor_error = result.get("monitor_error", "")
        wanted = (
            prior["whatsapp_device"] if prior is not None
            else self.settings.whatsapp_audio_device or result.get("whatsapp_device", "")
        )
        outputs = [x for x in result.get("outputs", []) if x["itemValue"] != self._monitor_id]
        self.populate(self.whatsapp_device, outputs, wanted)
        self.populate(
            self.microphone, result["microphones"],
            prior["microphone"] if prior is not None
            else result["selected"].get(MIC, {}).get("device_id", ""),
        )
        for label, combo in self.applications.items():
            self.populate(
                combo, result["applications"][label],
                prior["applications"][label] if prior is not None
                else result["selected"].get(app_name(label), {}).get("window", ""), allow_offline=True
            )
        for name, state in self._source_states.items():
            actual = state.get("gain_db")
            if actual is None:
                continue
            edited = prior is not None and prior["gains_db"][name] != self._saved_gains.get(name, 0.0)
            self._saved_gains[name] = actual
            if not edited:
                self.gains[name].setValue(actual)
                # Display rounding must not mark another source as edited.
                self._saved_gains[name] = self.gains[name].value()
        self._lists_loaded = True
        after = self._data()
        if any(before[k] != after[k] for k in ("microphone", "whatsapp_device", "applications")):
            self.route_confirmation.setChecked(False)
        if any(self.applications[k].currentData() for k in ("VLC", "Chrome", "Edge")):
            self.other_sources.setChecked(True)

    @staticmethod
    def populate(combo, choices, selected, allow_offline=False):
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem(combo.property("placeholder"), "")
            for item in choices:
                combo.addItem(item["itemName"], item["itemValue"])
            idx = combo.findData(selected)
            if idx < 0 and selected and allow_offline:
                name = selected.split(":", 1)[0] if ":" in selected else selected
                combo.addItem(f"{name} (offline)", selected)
                idx = combo.count() - 1
            combo.setCurrentIndex(max(0, idx))
        finally:
            combo.blockSignals(False)

    def _levels_changed(self, levels):
        def display(value):
            return "—" if value is None else f"{value:.1f} dBFS"

        self.levels.setText(f"Medidores OBS · mesa: {display(levels[0])} · mídias: {display(levels[1])}")

    def disconnect_results(self):
        self._load_timer.stop()
        self.controller.audio_task_finished.disconnect(self.on_result)
        if hasattr(self.controller, "audio_levels_changed"):
            self.controller.audio_levels_changed.disconnect(self._levels_changed)

    def reject(self):
        if not self.busy:
            super().reject()
