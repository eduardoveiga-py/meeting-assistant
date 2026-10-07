from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from meeting_assistant.services.display_service import (
    DisplayInfo,
    display_info_from_screen,
)
from meeting_assistant.services.obs_setup import camera_url
from meeting_assistant.services.settings import AppSettings
from meeting_assistant.ui.window_geometry import ScreenFitController


class SettingsDialog(QDialog):
    virtual_camera_requested = Signal()
    audio_setup_requested = Signal()
    observe_requested = Signal()
    calibrate_requested = Signal()
    hall_setup_requested = Signal()
    setup_assistant_requested = Signal()
    update_history_requested = Signal()
    save_layout_requested = Signal()
    restore_layout_requested = Signal()

    def __init__(
        self,
        settings: AppSettings,
        available_scenes: list[str],
        parent=None,
        available_displays: list[DisplayInfo] | None = None,
        embedded: bool = False,
    ) -> None:
        super().__init__(parent)
        self.prepare_obs_requested = False
        # One copy of every field. The workspace mounts these sections directly;
        # apply_to only writes editor fields, never confirmed live audio settings.
        self.setWindowTitle("Ajustes do Meeting Assistant")
        self.setModal(not embedded)
        self.setMinimumSize(360, 240)
        self.resize(580, 680)

        if available_displays is None:
            app = QGuiApplication.instance()
            primary = app.primaryScreen() if app is not None else None
            available_displays = (
                [display_info_from_screen(screen, primary=screen is primary) for screen in app.screens()]
                if app is not None
                else []
            )

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setObjectName("SettingsContentScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        root = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        if not embedded:
            tools_group = QGroupBox("Ferramentas e áudio")
            tools_layout = QVBoxLayout(tools_group)
            for text, signal in (
                ("Áudio da mesa e das mídias → Zoom + WhatsApp…", self.audio_setup_requested),
                ("Observar mídia no JW Library (20 s)", self.observe_requested),
                ("Calibrar Texto do Ano", self.calibrate_requested),
                ("Salvar disposição atual das janelas", self.save_layout_requested),
                ("Aplicar disposição salva / JWL à direita", self.restore_layout_requested),
            ):
                button = QPushButton(text)
                button.clicked.connect(signal.emit)
                tools_layout.addWidget(button)
            hint = QLabel(
                "Observar e calibrar fecham os ajustes sem salvar alterações pendentes. "
                "Salve antes se tiver editado algum campo. F1 na tela principal mostra os atalhos."
            )
            hint.setWordWrap(True)
            tools_layout.addWidget(hint)

            update_btn = QPushButton("Atualizações e versões anteriores")
            update_btn.clicked.connect(self.update_history_requested.emit)
            tools_layout.addWidget(update_btn)
            root.addWidget(tools_group)

        output_group = QGroupBox("Saída do Salão")
        output_form = QFormLayout(output_group)

        self.whatsapp_check = QCheckBox("WhatsApp e câmera virtual")
        self.whatsapp_check.setChecked(settings.whatsapp_enabled)
        output_form.addRow("WhatsApp", self.whatsapp_check)

        self.simulation_check = QCheckBox("Usar modo de simulação")
        self.simulation_check.setChecked(settings.simulation_enabled)
        self.simulation_check.setToolTip(
            "No modo de simulação a automação não protege nem usa uma segunda tela física."
        )

        self.hall_display_combo = QComboBox()
        self.hall_display_combo.addItem(
            "Automático — segunda tela física (padrão)",
            "",
        )
        for display in available_displays:
            self.hall_display_combo.addItem(display.label, display.key)

        selected_index = self.hall_display_combo.findData(settings.hall_display_key)
        if selected_index < 0 and settings.hall_display_key:
            self.hall_display_combo.addItem(
                "Monitor configurado — atualmente desconectado",
                settings.hall_display_key,
            )
            selected_index = self.hall_display_combo.count() - 1
        self.hall_display_combo.setCurrentIndex(max(0, selected_index))

        self.global_hotkeys_check = QCheckBox("Atalhos globais Ctrl+Alt+F2–F7")
        self.global_hotkeys_check.setChecked(settings.global_shortcuts)
        output_form.addRow(self.global_hotkeys_check)
        output_form.addRow("Modo", self.simulation_check)
        output_form.addRow("Monitor do Salão", self.hall_display_combo)

        output_hint = QLabel(
            "No modo físico, a primeira tela não principal é o padrão. "
            "O Meeting Assistant identifica e protege a saída secundária do JW Library nesse monitor."
        )
        output_hint.setWordWrap(True)
        output_form.addRow("", output_hint)
        root.addWidget(output_group)

        startup_group = QGroupBox("Inicialização da reunião")
        startup_form = QFormLayout(startup_group)

        self.congregation_name_edit = QLineEdit(settings.congregation_name)
        self.congregation_name_edit.setPlaceholderText("Ex: Congregação Ticuna")
        startup_form.addRow("Congregação", self.congregation_name_edit)

        self.zoom_join_edit = QLineEdit(settings.zoom_join_url)
        self.zoom_join_edit.setPlaceholderText("https://...zoom.us/j/123456789?pwd=...")
        self.zoom_join_edit.setToolTip(
            "Cole o link normal da reunião. O Meeting Assistant o converte para "
            "abrir diretamente no aplicativo Zoom."
        )

        self.obs_executable_edit = QLineEdit(settings.obs_executable)
        self.obs_executable_edit.setPlaceholderText(
            "Automático — normalmente C:\\Program Files\\obs-studio\\bin\\64bit\\obs64.exe"
        )
        self.zoom_executable_edit = QLineEdit(settings.zoom_executable)
        self.zoom_executable_edit.setPlaceholderText(
            "Automático — normalmente %APPDATA%\\Zoom\\bin\\Zoom.exe"
        )

        startup_form.addRow("Link da reunião Zoom", self.zoom_join_edit)
        startup_form.addRow("Executável do OBS", self.obs_executable_edit)
        startup_form.addRow("Executável do Zoom", self.zoom_executable_edit)

        startup_hint = QLabel(
            "Deixe os caminhos vazios para detecção automática. "
            "Para Zoom → Salão, ative uma vez no Zoom a opção 'Usar dois monitores' "
            "antes de entrar na reunião."
        )
        startup_hint.setWordWrap(True)
        startup_form.addRow("", startup_hint)
        self.obs_logon_check = QCheckBox("Iniciar OBS com o Windows")
        self.obs_logon_check.setChecked(settings.obs_start_at_logon)
        startup_form.addRow("", self.obs_logon_check)
        root.addWidget(startup_group)

        camera_group = QGroupBox("Câmera IP — Palco")
        camera_form = QFormLayout(camera_group)
        self.camera_ip_edit = QLineEdit(settings.camera_ip)
        self.camera_user_edit = QLineEdit(settings.camera_username)
        self.camera_password_edit = QLineEdit(settings.camera_password)
        self.camera_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.camera_port_spin = QSpinBox()
        self.camera_port_spin.setRange(1, 65535)
        self.camera_port_spin.setValue(settings.camera_rtsp_port)
        camera_form.addRow("IP", self.camera_ip_edit)
        camera_form.addRow("Usuário", self.camera_user_edit)
        camera_form.addRow("Senha", self.camera_password_edit)
        camera_form.addRow("Porta RTSP", self.camera_port_spin)
        camera_hint = QLabel(
            "Perfil iM7-FC: canal 1, fluxo principal. Porta padrão 554; "
            "37777 não é usada no OBS. Salvar apenas guarda os dados localmente. "
            "A preparação aplica a fonte ao OBS e pode iniciar a conexão com a câmera. "
            "A senha fica nos dados locais do app e na coleção de cenas do OBS."
        )
        camera_hint.setWordWrap(True)
        camera_form.addRow(camera_hint)
        prepare_button = QPushButton("Salvar e preparar cenas / câmera no OBS")
        prepare_button.clicked.connect(self._prepare_obs)
        camera_form.addRow(prepare_button)
        prepare_button.setVisible(not embedded)
        root.addWidget(camera_group)

        telemetry_group = QGroupBox("Diagnóstico automático")
        telemetry_form = QFormLayout(telemetry_group)

        self.telemetry_check = QCheckBox("Gravar diagnóstico local")
        self.telemetry_check.setChecked(settings.telemetry_enabled)
        self.telemetry_sync_check = QCheckBox("Sincronizar com repositório")
        self.telemetry_sync_check.setChecked(settings.telemetry_sync_enabled)
        self.telemetry_screenshots_check = QCheckBox("Incluir capturas de tela")
        self.telemetry_screenshots_check.setChecked(settings.telemetry_screenshots)
        self.telemetry_repo_edit = QLineEdit(settings.telemetry_repo_url)
        self.telemetry_repo_edit.setPlaceholderText(
            "https://github.com/.../meeting-assistant-diagnostics.git"
        )

        telemetry_form.addRow("", self.telemetry_check)
        telemetry_form.addRow("", self.telemetry_sync_check)
        telemetry_form.addRow("", self.telemetry_screenshots_check)
        telemetry_form.addRow("Repositório de destino", self.telemetry_repo_edit)
        export_button = QPushButton("Exportar diagnóstico…")
        export_button.clicked.connect(self._export_diagnostics)
        telemetry_form.addRow(export_button)

        telemetry_hint = QLabel(
            "O diagnóstico fica local por padrão. Envio opcional exige Git, acesso ao destino e "
            "verificação da privacidade do repositório pelo operador. "
            "Screenshots capturam todos os monitores e podem conter dados pessoais; "
            "não entram na exportação ZIP. A remoção automática de segredos não substitui a revisão. "
            "Alterações desta seção valem no próximo reinício."
        )
        telemetry_hint.setWordWrap(True)
        telemetry_form.addRow("", telemetry_hint)
        root.addWidget(telemetry_group)

        media_group = QGroupBox("Mídias e idioma")
        media_layout = QVBoxLayout(media_group)
        media_form = QFormLayout()
        self.media_language_edit = QLineEdit(settings.congregation_language)
        self.media_language_edit.setToolTip("Idioma da Congregacao (T = Portugues, E = Ingles, S = Espanhol)")
        media_form.addRow("Codigo do Idioma:", self.media_language_edit)

        self.auto_mute_mic_for_jwl_media = QCheckBox("Silenciar mesa durante mídias")
        self.auto_mute_mic_for_jwl_media.setChecked(settings.auto_mute_mic_for_jwl_media)
        media_form.addRow("", self.auto_mute_mic_for_jwl_media)
        
        media_layout.addLayout(media_form)
        self.download_media_button = QPushButton("📥 Baixar e Preparar Mídias da Semana")
        self.download_media_button.setText("Download de mídias — em desenvolvimento")
        self.download_media_button.setEnabled(False)
        self.download_media_button.hide()
        self.download_media_button.setToolTip("Esta função ainda não baixa arquivos.")
        self.download_media_button.clicked.connect(self._on_download_media_clicked)
        media_layout.addWidget(self.download_media_button)
        root.addWidget(media_group)

        connection_group = QGroupBox("OBS WebSocket")
        connection_form = QFormLayout(connection_group)

        self.host_edit = QLineEdit(settings.obs_host)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(settings.obs_port)
        self.password_edit = QLineEdit(settings.obs_password)
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)

        connection_form.addRow("Host", self.host_edit)
        connection_form.addRow("Porta", self.port_spin)
        connection_form.addRow("Senha", self.password_edit)
        root.addWidget(connection_group)

        scenes_group = QGroupBox("Mapeamento de cenas")
        scenes_form = QFormLayout(scenes_group)
        self.background_combo = self._scene_combo(settings.scene_background, available_scenes)
        self.speaker_combo = self._scene_combo(settings.scene_speaker, available_scenes)
        self.media_combo = self._scene_combo(settings.scene_media, available_scenes)
        self.zoom_combo = self._scene_combo(settings.scene_zoom, available_scenes)

        scenes_form.addRow("Texto do Ano", self.background_combo)
        scenes_form.addRow("Palco", self.speaker_combo)
        scenes_form.addRow("Mídia", self.media_combo)
        scenes_form.addRow("Zoom → Salão", self.zoom_combo)
        if settings.obs_standard_scenes:
            for combo in (self.background_combo, self.speaker_combo, self.media_combo):
                combo.setEnabled(False)
        root.addWidget(scenes_group)
        hall_setup = QPushButton("Texto do Ano, captura JWL e câmera virtual…")
        hall_setup.clicked.connect(self.hall_setup_requested.emit)
        root.addWidget(hall_setup)
        hall_setup.setVisible(not embedded)
        assistant = QPushButton("Assistente de instalação e configuração…")
        assistant.clicked.connect(self.setup_assistant_requested.emit)
        root.addWidget(assistant)
        assistant.setVisible(not embedded)

        # Related fields stay in the same category instead of one long form.
        self.sections = {}
        self.section_picker = QComboBox(self)
        self.section_stack = QStackedWidget(self)
        for key, title, groups in (
            ("meeting", "Reunião e janelas", (output_group, startup_group, media_group)),
            ("video", "OBS e vídeo", (connection_group, scenes_group, camera_group)),
            ("diagnostics", "Diagnóstico", (telemetry_group,)),
        ):
            page = QScrollArea()
            page.setWidgetResizable(True)
            page.setFrameShape(QFrame.NoFrame)
            page.setObjectName(f"SettingsSection_{key}")
            container = QWidget()
            layout = QVBoxLayout(container)
            for group in groups:
                root.removeWidget(group)
                layout.addWidget(group)
                form = group.layout()
                if isinstance(form, QFormLayout):
                    form.setRowWrapPolicy(QFormLayout.WrapAllRows)
                    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            layout.addStretch()
            page.setWidget(container)
            for combo in container.findChildren(QComboBox):
                combo.setMinimumContentsLength(8)
                combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
                combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                combo.setToolTip(combo.currentText())
                combo.currentTextChanged.connect(combo.setToolTip)
            self.sections[key] = page
            self.section_picker.addItem(title, key)
            self.section_stack.addWidget(page)
        if not embedded:
            root.removeWidget(tools_group)
            self.sections["diagnostics"].widget().layout().insertWidget(0, tools_group)
        hall_setup.hide()
        assistant.hide()
        outer.removeWidget(scroll)
        scroll.setParent(None)
        scroll.deleteLater()
        outer.addWidget(self.section_picker)
        outer.addWidget(self.section_stack, 1)
        self.section_picker.currentIndexChanged.connect(self.section_stack.setCurrentIndex)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        if embedded:
            media_group.hide()
            self.setWindowFlags(Qt.Widget)
            buttons.hide()
            self.setMinimumSize(0, 0)
        else:
            self._screen_fit = ScreenFitController(self)

    def _prepare_obs(self) -> None:
        try:
            camera_url(
                self.camera_ip_edit.text(),
                self.camera_user_edit.text(),
                self.camera_password_edit.text(),
                self.camera_port_spin.value(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Câmera IP", str(exc))
            return
        answer = QMessageBox.question(
            self,
            "Preparar OBS",
            "Padronizar Texto do Ano, Palco e Mídias e aplicar a câmera IP? "
            "Fontes existentes serão preservadas. A fonte de câmera terá áudio silenciado. "
            "Revise o resultado antes de usar numa reunião.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.prepare_obs_requested = True
            self.accept()

    def _export_diagnostics(self) -> None:
        from meeting_assistant.services.diagnostics_export import export_latest_session

        filename, _ = QFileDialog.getSaveFileName(
            self, "Exportar diagnóstico para revisão", "diagnostico-meeting-assistant.zip", "ZIP (*.zip)"
        )
        if not filename:
            return
        try:
            export_latest_session(Path(filename))
        except (OSError, ValueError):
            QMessageBox.warning(
                self, "Diagnóstico", "Não foi possível exportar. Confira sessão e pasta de destino."
            )
            return
        QMessageBox.information(
            self, "Diagnóstico exportado", "Arquivo salvo localmente. Revise os textos antes de compartilhar."
        )

    @staticmethod
    def _scene_combo(current: str, available_scenes: list[str]) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        names = list(dict.fromkeys([current, *available_scenes]))
        combo.addItems([name for name in names if name])
        combo.setCurrentText(current)
        return combo

    def _on_download_media_clicked(self):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            "Mídias da Reunião",
            "A estrutura do downloader de mídias foi criada com sucesso.\n\n"
            "O botão fará a varredura da API do JW.org para o idioma '" 
            + self.media_language_edit.text().strip() + 
            "' e montará os arquivos para o JW Library automaticamente."
        )

    def apply_to(self, settings: AppSettings) -> None:
        settings.congregation_name = self.congregation_name_edit.text().strip()
        settings.global_shortcuts = self.global_hotkeys_check.isChecked()
        settings.camera_ip = self.camera_ip_edit.text().strip()
        settings.camera_username = self.camera_user_edit.text().strip()
        settings.camera_password = self.camera_password_edit.text()
        settings.camera_rtsp_port = self.camera_port_spin.value()
        settings.obs_start_at_logon = self.obs_logon_check.isChecked()
        settings.simulation_enabled = self.simulation_check.isChecked()
        settings.whatsapp_enabled = self.whatsapp_check.isChecked()
        settings.congregation_language = self.media_language_edit.text().strip()
        settings.auto_mute_mic_for_jwl_media = self.auto_mute_mic_for_jwl_media.isChecked()
        settings.hall_display_key = str(self.hall_display_combo.currentData() or "")
        settings.obs_host = self.host_edit.text().strip() or "127.0.0.1"
        settings.obs_port = self.port_spin.value()
        settings.obs_password = self.password_edit.text()
        settings.scene_background = self.background_combo.currentText().strip()
        settings.scene_speaker = self.speaker_combo.currentText().strip()
        settings.scene_media = self.media_combo.currentText().strip()
        settings.scene_zoom = self.zoom_combo.currentText().strip()
        settings.zoom_join_url = self.zoom_join_edit.text().strip()
        settings.obs_executable = self.obs_executable_edit.text().strip()
        settings.zoom_executable = self.zoom_executable_edit.text().strip()
        settings.telemetry_enabled = self.telemetry_check.isChecked()
        settings.telemetry_sync_enabled = self.telemetry_sync_check.isChecked()
        settings.telemetry_screenshots = self.telemetry_screenshots_check.isChecked()
        settings.telemetry_repo_url = self.telemetry_repo_edit.text().strip()
