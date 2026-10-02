from __future__ import annotations

from PySide6.QtCore import (
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from meeting_assistant.core.state import AppState, OperatingMode
from meeting_assistant.services.display_service import DisplayInfo, DisplayService
from meeting_assistant.services.hall_capture import verified_hall_target
from meeting_assistant.services.jwl_probe_service import JwlProbeService
from meeting_assistant.services.jwl_service import JwlService, JwlWindowInfo
from meeting_assistant.services.meeting_launcher import LaunchSummary, MeetingLauncherService
from meeting_assistant.services.obs_controller import ObsConnectionConfig, ObsController
from meeting_assistant.services.obs_setup import STANDARD_SCENES, configure_obs_logon
from meeting_assistant.services.settings import AppSettings, SettingsService
from meeting_assistant.services.yeartext_store import YeartextStore
from meeting_assistant.services.zoom_hall_service import ZoomHallService
from meeting_assistant.ui.hall_setup_dialog import HallSetupDialog
from meeting_assistant.ui.program_preview import ProgramPreview
from meeting_assistant.ui.settings_dialog import SettingsDialog
from meeting_assistant.ui.window_geometry import ScreenFitController


class MainWindow(QMainWindow):
    automation_enabled_changed = Signal(bool)
    idle_reference_requested = Signal()
    hall_capture_diagnostic = Signal(object)

    def __init__(
        self,
        state: AppState,
        settings: AppSettings,
        settings_service: SettingsService,
        obs_controller: ObsController,
        display_service: DisplayService,
        jwl_service: JwlService,
        jwl_probe: JwlProbeService,
        meeting_launcher: MeetingLauncherService,
        zoom_hall_service: ZoomHallService,
        app_icon: QIcon | None = None,
        hall_window_provider=None,
        hall_display_provider=None,
        whatsapp_audio_guard=None,
        camera_session=None,
        update_service=None,
    ) -> None:
        super().__init__()
        self.state = state
        self.settings = settings
        self.settings_service = settings_service
        self.obs = obs_controller
        self.displays = display_service
        self.jwl = jwl_service
        self.jwl_probe = jwl_probe
        self.launcher = meeting_launcher
        self.zoom_hall = zoom_hall_service
        self.app_icon = app_icon or QIcon()
        self._hall_window_provider = hall_window_provider or (lambda: None)
        self._hall_display_provider = hall_display_provider or (lambda: None)
        self.whatsapp_audio_guard = whatsapp_audio_guard
        self.camera_session = camera_session
        self.update_service = update_service
        
        if self.update_service:
            self.update_service.update_available.connect(self._on_update_available)
        self._camera_auto_start_attempted = False
        self.yeartext_store = YeartextStore(settings_service.path.parent / "yeartext")
        self._latest_media_active = False
        self._setup_assistant = None
        self.obs_connected = False
        self.obs_scenes: list[str] = []
        self.current_obs_scene: str | None = None
        self.display_snapshot: list[DisplayInfo] = []
        self.jwl_snapshot: list[JwlWindowInfo] = []
        self._startup_scene_applied = False
        self.telemetry_session_id = ""

        self.state.automation_enabled = False

        self.setWindowIcon(self.app_icon)
        self.resize(520, 780)
        self.setMinimumSize(360, 280)

        self._build_ui()
        self._apply_style()
        from meeting_assistant.ui.shortcuts import MainWindowShortcuts

        self._shortcuts = MainWindowShortcuts(self, [
            lambda: self._select_mode(OperatingMode.BACKGROUND),
            lambda: self._select_mode(OperatingMode.SPEAKER),
            lambda: self._select_mode(OperatingMode.MEDIA),
            lambda: self._select_mode(OperatingMode.ZOOM),
            self._toggle_automation, self._activate_safe_scene,
            self._start_meeting, self._show_diagnostics, self._show_settings,
        ])
        self._connect_obs_signals()
        self._connect_display_signals()
        self._connect_jwl_signals()
        self._connect_launcher_signals()
        if self.camera_session is not None:
            self.camera_session.changed.connect(self._on_camera_state)
            self._on_camera_state()
        else:
            self.camera_button.setEnabled(False)
            self.camera_button.setText("📹 Câmera WhatsApp")
            self.camera_button.setToolTip(
                "A câmera virtual nativa do Windows 11 não está disponível nesta execução."
            )
        if self.whatsapp_audio_guard is not None:
            self.whatsapp_audio_guard.state_changed.connect(self._on_whatsapp_audio_state)
            self.whatsapp_audio_guard.start()
        else:
            self.whatsapp_audio_button.setEnabled(False)
            self.whatsapp_audio_button.setText("🔇 WhatsApp")
            self.whatsapp_audio_button.setToolTip(
                "O controle do retorno do WhatsApp fica disponível no Windows 11."
            )
        self._on_displays_changed(self.displays.snapshot())
        self._on_jwl_snapshot(self.jwl.snapshot())
        self._set_automation_ui(False)
        self._refresh_mode()
        self._screen_fit = ScreenFitController(self)
        self._yeartext_timer = QTimer(self)
        self._yeartext_timer.setInterval(60000)
        self._yeartext_timer.timeout.connect(self._refresh_yeartext_notice)
        self._yeartext_timer.start()
        self._refresh_yeartext_notice()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(5)

        header = QHBoxLayout()
        header.setSpacing(10)

        brand_icon = QLabel()
        brand_icon.setObjectName("BrandIcon")
        brand_icon.setFixedSize(34, 34)
        brand_icon.setAlignment(Qt.AlignCenter)
        if not self.app_icon.isNull():
            brand_icon.setPixmap(self.app_icon.pixmap(30, 30))
        header.addWidget(brand_icon, alignment=Qt.AlignVCenter)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("Meeting Assistant")
        title.setObjectName("Title")
        subtitle = QLabel("Operação local • OBS • Zoom • JW Library")
        subtitle.setObjectName("Subtitle")
        self.yeartext_notice = subtitle
        subtitle.linkActivated.connect(lambda _: self._open_hall_setup(self))
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        self.automation_badge = QLabel("AUTOMAÇÃO PAUSADA")
        self.automation_badge.setObjectName("AutomationBadge")
        self.automation_badge.setAlignment(Qt.AlignCenter)
        header.addWidget(self.automation_badge)
        root.addLayout(header)

        status_grid = QGridLayout()
        status_grid.setHorizontalSpacing(5)
        status_grid.setVerticalSpacing(5)
        self.status_labels: dict[str, QLabel] = {}
        for index, name in enumerate(("OBS", "JW Library", "Zoom", "Tela 2")):
            label = QLabel(f"○ {name}")
            label.setObjectName("StatusBadge")
            label.setProperty("state", "pending")
            label.setToolTip(f"{name}: aguardando verificação")
            self.status_labels[name] = label
            status_grid.addWidget(label, 0, index)
        root.addLayout(status_grid)

        controls_card = QFrame()
        controls_card.setObjectName("Card")
        controls = QVBoxLayout(controls_card)
        controls.setContentsMargins(10, 9, 10, 10)
        controls.setSpacing(4)

        controls.addWidget(self._section_label("SAÍDA DO SALÃO"))

        mode_grid = QGridLayout()
        mode_grid.setHorizontalSpacing(6)
        mode_grid.setVerticalSpacing(6)
        self.mode_buttons: dict[OperatingMode, QPushButton] = {}
        button_specs = [
            (OperatingMode.BACKGROUND, "📖 Texto do Ano", 0, 0),
            (OperatingMode.SPEAKER, "🎤 Palco", 0, 1),
            (OperatingMode.MEDIA, "🎥 Mídia", 1, 0),
            (OperatingMode.ZOOM, "💻 Zoom → Salão", 1, 1),
        ]
        for mode, text, row, col in button_specs:
            button = QPushButton(text)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, m=mode: self._select_mode(m))
            self.mode_buttons[mode] = button
            mode_grid.addWidget(button, row, col)
        controls.addLayout(mode_grid)

        self.auto_button = QPushButton("🚥 Ativar automação")
        self.auto_button.clicked.connect(self._toggle_automation)
        automation_row = QHBoxLayout()
        automation_row.addWidget(self.auto_button, 1)
        controls.addLayout(automation_row)

        self.automation_status = QLabel("Automação pausada")
        self.automation_status.setObjectName("AutomationStatus")
        self.automation_status.setWordWrap(True)
        controls.addWidget(self.automation_status)

        panic = QPushButton("🛟 Cena segura → Palco")
        panic.setObjectName("DangerButton")
        panic.clicked.connect(self._activate_safe_scene)
        automation_row.addWidget(panic, 1)

        self.whatsapp_audio_button = QPushButton("🔇 WhatsApp")
        self.whatsapp_audio_button.setCheckable(True)
        self.whatsapp_audio_button.setChecked(False)
        self.whatsapp_audio_button.setMinimumWidth(0)
        self.whatsapp_audio_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.whatsapp_audio_button.setToolTip(
            "Silencia ou libera somente o áudio recebido do WhatsApp nas caixas do salão."
        )
        self.whatsapp_audio_button.clicked.connect(self._toggle_whatsapp_audio)
        automation_row.addWidget(self.whatsapp_audio_button, 1)

        controls.addSpacing(2)
        controls.addWidget(self._section_label("SISTEMA"))

        self.start_meeting_button = QPushButton("▶️ Iniciar reunião")
        self.start_meeting_button.setToolTip(
            "Abre OBS, JW Library e Zoom. Se o link estiver configurado, "
            "o Zoom entra diretamente na reunião."
        )
        self.start_meeting_button.clicked.connect(self._start_meeting)

        system_grid = QGridLayout()
        system_grid.setHorizontalSpacing(6)
        
        # Row 0
        system_grid.addWidget(self.start_meeting_button, 0, 0)
        self.end_meeting_button = QPushButton("🔴 Encerrar")
        self.end_meeting_button.setToolTip("Encerra OBS, JW Library, Zoom e WhatsApp.")
        self.end_meeting_button.clicked.connect(self._end_meeting)
        system_grid.addWidget(self.end_meeting_button, 0, 1)
        settings_button = QPushButton("⚙️ Ajustes")
        settings_button.clicked.connect(self._show_settings)
        system_grid.addWidget(settings_button, 0, 2)
        
        # Row 1
        self.ext_media_button = QPushButton("🎬 Mídia")
        self.ext_media_button.setCheckable(True)
        self.ext_media_button.setToolTip("Envia o player de vídeo ativo para o telão")
        self.ext_media_button.toggled.connect(self._toggle_ext_media)
        system_grid.addWidget(self.ext_media_button, 1, 0)

        self.camera_button = QPushButton("📷 Câmera WhatsApp")
        self.camera_button.setToolTip(
            "Inicia ou para a câmera virtual nativa que transmite o Program do OBS ao WhatsApp."
        )
        self.camera_button.clicked.connect(self._toggle_camera)
        system_grid.addWidget(self.camera_button, 1, 1)
        
        self.zoom_mic_button = QPushButton("🎤 Mic Zoom")
        self.zoom_mic_button.setToolTip("Muta ou desmuta o microfone no Zoom")
        self.zoom_mic_button.clicked.connect(self._toggle_zoom_mic)
        system_grid.addWidget(self.zoom_mic_button, 1, 2)

        controls.addLayout(system_grid)

        # Retain the existing probe progress callbacks; the command lives in Settings.
        self.jwl_probe_button = QPushButton("Observar mídia (20 s)", self)
        self.jwl_probe_button.hide()

        controls.addSpacing(2)
        controls.addWidget(self._section_label("RETORNO — SALÃO"))

        preview_row = QHBoxLayout()
        self.preview = ProgramPreview(self)
        self.preview.setObjectName("Preview")
        self.preview.setMaximumSize(480, 270)
        preview_row.addWidget(self.preview, 1)
        controls.addLayout(preview_row, 1)

        self.zoom_output_label = QLabel(
            "Zoom recebe: OBS Virtual Camera • transições feitas pelo OBS"
        )
        self.zoom_output_label.setObjectName("ZoomOutputLabel")
        self.zoom_output_label.setAlignment(Qt.AlignCenter)
        self.zoom_output_label.setWordWrap(True)
        controls.addWidget(self.zoom_output_label)

        self.mode_label = QLabel()
        self.mode_label.setObjectName("ModeLabel")
        self.mode_label.setWordWrap(True)
        self.mode_label.setMinimumWidth(0)
        self.mode_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        controls.addWidget(self.mode_label)

        root.addWidget(controls_card, 1)

        self.footer = QLabel()
        self.footer.hide() # Hidden as requested
        self.footer.setObjectName("Footer")
        self.footer.setAlignment(Qt.AlignCenter)
        self.footer.setWordWrap(True)
        root.addWidget(self.footer)

        scroll = QScrollArea()
        scroll.setObjectName("MainContentScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(central)
        self.setCentralWidget(scroll)

    def _connect_obs_signals(self) -> None:
        self.obs.connected_changed.connect(self._on_obs_connected)
        self.obs.scenes_changed.connect(self._on_obs_scenes)
        self.obs.scene_changed.connect(self._on_obs_scene)
        self.obs.error.connect(self._on_obs_error)
        self.obs.setup_finished.connect(self._on_obs_setup_finished)
        self.obs.hall_task_finished.connect(self._on_hall_task_finished)

    def _connect_display_signals(self) -> None:
        self.displays.displays_changed.connect(self._on_displays_changed)

    def _connect_jwl_signals(self) -> None:
        self.jwl.status_changed.connect(self._on_jwl_status)
        self.jwl.snapshot_changed.connect(self._on_jwl_snapshot)
        self.jwl_probe.started.connect(self._on_jwl_probe_started)
        self.jwl_probe.progress_changed.connect(self._on_jwl_probe_progress)
        self.jwl_probe.finished.connect(self._on_jwl_probe_finished)

    def _connect_launcher_signals(self) -> None:
        self.launcher.progress_changed.connect(self._on_launch_progress)
        self.launcher.finished.connect(self._on_launch_finished)
        self.zoom_hall.status_changed.connect(self._on_zoom_hall_status)
        self.zoom_hall.active_changed.connect(self._on_zoom_hall_active)

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def _select_mode(self, mode: OperatingMode) -> None:
        if mode is OperatingMode.ZOOM:
            if not self.zoom_hall.toggle():
                self.mode_buttons[OperatingMode.ZOOM].setChecked(self.zoom_hall.active)
            return

        if self.zoom_hall.active:
            self.zoom_hall.restore_jwl()

        if self.obs_connected:
            scene_name = self._scene_for_mode(mode)
            if self.obs_scenes and scene_name not in self.obs_scenes:
                QMessageBox.warning(
                    self,
                    "Cena não encontrada",
                    f"A cena configurada '{scene_name}' não existe no OBS.\n"
                    "Abra Ajustes e escolha uma das cenas encontradas.",
                )
                return
            self.mode_label.setText(f"Solicitando ao OBS: {scene_name}")
            self.obs.set_program_scene(scene_name)
            return

        if self.state.simulation_enabled:
            self.state.set_mode(mode)
            self._refresh_mode()
        else:
            self.mode_label.setText("OBS desconectado")

    def _toggle_automation(self, checked: bool = False) -> None:
        del checked
        enabled = not self.state.automation_enabled
        self.state.automation_enabled = enabled
        self._set_automation_ui(enabled)
        self.automation_enabled_changed.emit(enabled)

    def _calibrate_idle_reference(self) -> None:
        if self.zoom_hall.active:
            QMessageBox.information(self, "Texto do Ano", "Primeiro pare Zoom → Salão.")
            return
        answer = QMessageBox.question(
            self,
            "Calibrar Texto do Ano",
            "Deixe somente o Texto do Ano do JW Library na Tela do Salão, "
            "sem foto ou vídeo em reprodução.\n\n"
            "A aparência atual será adicionada às referências já salvas.\n\n"
            "Confirmar essa tela como referência e ativar a automação?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.idle_reference_requested.emit()
        self.state.automation_enabled = True
        self._set_automation_ui(True)
        self.automation_enabled_changed.emit(True)

    def _activate_safe_scene(self, checked: bool = False) -> None:
        del checked
        if self.state.automation_enabled:
            self.state.automation_enabled = False
            self._set_automation_ui(False)
            self.automation_enabled_changed.emit(False)
        self._select_mode(OperatingMode.SPEAKER)

    def _set_automation_ui(self, enabled: bool) -> None:
        if enabled:
            self.automation_badge.setText("AUTOMAÇÃO ATIVA")
            self.automation_badge.setProperty("active", True)
            self.auto_button.setText("⏸️ Pausar automação")
            self.automation_status.setText("Automação ativada; calibrando Mídias…")
        else:
            self.automation_badge.setText("AUTOMAÇÃO PAUSADA")
            self.automation_badge.setProperty("active", False)
            self.auto_button.setText("🚥 Ativar automação")
            self.automation_status.setText("Automação pausada")
        self._repolish(self.automation_badge)

    def set_automation_status(self, message: str) -> None:
        self.automation_status.setText(message)
        self.automation_badge.setToolTip(message)
        self.auto_button.setToolTip(message)

    def set_telemetry_session(self, session_id: str) -> None:
        self.telemetry_session_id = session_id
        pass

    def set_telemetry_status(self, ok: bool, message: str) -> None:
        self.footer.setToolTip(message)

    def set_automation_signal(
        self,
        source_name: str,
        changed_percent: float,
        active: bool,
    ) -> None:
        if not self.state.automation_enabled:
            return
        self._latest_media_active = active
        state_text = "MÍDIA DETECTADA" if active else "repouso / aguardando mídia"
        self.automation_status.setText(
            f"Sensor: {source_name} • sinal {changed_percent:.1f}% • {state_text}"
        )

    def _on_obs_connected(self, connected: bool, message: str) -> None:
        self.obs_connected = connected
        if connected:
            if (
                self.camera_session is not None
                and not self._camera_auto_start_attempted
                and self.camera_session.state == "off"
            ):
                self._camera_auto_start_attempted = True
                # Give OBS a short moment to finish loading the native bridge
                # before asking it to publish the first frame.
                QTimer.singleShot(1200, self._auto_start_camera)
            current = self.yeartext_store.current()
            if current and current.get("obs_pending") and self.settings.obs_host.lower() in {
                "127.0.0.1", "localhost", "::1",
            }:
                self.obs.hall_task("yeartext", {
                    "directory": str(self.yeartext_store.directory), "scene": self.settings.scene_background,
                })
            self._set_component_status("OBS", "ok", "● OBS", message)
            if not self._startup_scene_applied and self.settings.scene_speaker:
                self._startup_scene_applied = True
                self.mode_label.setText("Inicializando em Palco…")
                self.obs.set_program_scene(self.settings.scene_speaker)
        else:
            self.current_obs_scene = None
            self._set_component_status("OBS", "error", "● OBS", message)
            self.mode_label.setText("Salão: aguardando OBS")

    def _on_obs_scenes(self, scenes: list[str]) -> None:
        self.obs_scenes = scenes
        self.status_labels["OBS"].setToolTip(
            f"OBS conectado • {len(scenes)} cena(s) encontrada(s)"
        )

    def _on_obs_scene(self, scene_name: str) -> None:
        self.current_obs_scene = scene_name
        mode = self._mode_for_scene(scene_name)
        if mode is not None and not self.zoom_hall.active:
            self.state.set_mode(mode)
        self._refresh_mode()

    def _on_displays_changed(self, displays: list[DisplayInfo]) -> None:
        self.display_snapshot = displays
        self.state.second_display_available = len(displays) >= 2
        self._update_window_title()

        if not displays:
            self._set_component_status(
                "Tela 2",
                "error",
                "● Tela 2",
                "Nenhum monitor foi detectado pelo Windows.",
            )
            return

        if len(displays) == 1:
            display = displays[0]
            self._set_component_status(
                "Tela 2",
                "warning",
                "○ Tela 2",
                f"Somente 1 monitor detectado ({display.name}, {display.resolution}). "
                "Modo de simulação ativo.",
            )
            return

        secondary = next((item for item in displays if not item.primary), displays[1])
        self._set_component_status(
            "Tela 2",
            "ok",
            "● Tela 2",
            f"Segunda tela detectada: {secondary.name} • {secondary.resolution} • "
            f"posição {secondary.x},{secondary.y}",
        )

    def _on_jwl_status(self, running: bool, message: str) -> None:
        self._set_component_status(
            "JW Library",
            "ok" if running else "error",
            "● JW Library",
            message,
        )

    def _on_jwl_snapshot(self, snapshot: list[JwlWindowInfo]) -> None:
        self.jwl_snapshot = snapshot
        self.status_labels["JW Library"].setToolTip(self._format_jwl_snapshot(snapshot))

    def _start_jwl_probe(self) -> None:
        candidates = self.jwl.scan(include_hidden=True)
        if not candidates:
            QMessageBox.information(
                self,
                "Observação do JW Library",
                "Nenhuma janela/processo candidato do JW Library foi encontrado.\n\n"
                "Abra o JW Library e tente novamente.",
            )
            return

        if not self.jwl_probe.start():
            return

        self.mode_label.setText(
            "Teste JWL: toque uma mídia e depois pare-a durante os próximos 20 segundos."
        )

    def _on_jwl_probe_started(self) -> None:
        self.jwl_probe_button.setEnabled(False)
        self.jwl_probe_button.setText("🧪 Observando JW Library… 20 s")

    def _on_jwl_probe_progress(self, elapsed_ms: int, total_ms: int) -> None:
        remaining = max(0, (total_ms - elapsed_ms + 999) // 1000)
        self.jwl_probe_button.setText(f"🧪 Observando JW Library… {remaining} s")

    def _on_jwl_probe_finished(self, report: str, path: str) -> None:
        self.jwl_probe_button.setEnabled(True)
        self.jwl_probe_button.setText("🧪 Observar mídia no JW Library (20 s)")
        self.mode_label.setText("Teste do JW Library concluído; nenhuma cena foi alterada.")

        dialog = QMessageBox(self)
        dialog.setWindowTitle("Observação do JW Library concluída")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText("O teste foi concluído sem automatizar o OBS.")
        dialog.setInformativeText(f"Relatório salvo em:\n{path}")
        dialog.setDetailedText(report)
        dialog.exec()


    def _toggle_ext_media(self, checked: bool) -> None:
        from meeting_assistant.services.external_media_service import ExternalMediaService
        if not hasattr(self, "_ext_media_service"):
            self._ext_media_service = ExternalMediaService(self._hall_display_provider)
            self._ext_media_service.state_changed.connect(
                lambda active, msg: self.mode_label.setText(msg)
            )
        
        if checked:
            if not self._ext_media_service.start_external_media():
                self.ext_media_button.setChecked(False)
        else:
            self._ext_media_service.stop_external_media()

    def _on_update_available(self, version: str, download_url: str, release_notes: str) -> None:
        self.update_banner.setText(f"✨ Nova versão disponível (v{version}) - Clique para instalar")
        self.update_banner.download_url = download_url
        self.update_banner.version = version
        self.update_banner.show()

    def _trigger_update(self) -> None:
        if hasattr(self.update_banner, "download_url") and self.update_service:
            self.update_banner.setText("Baixando atualização... Por favor, aguarde.")
            self.update_banner.setEnabled(False)
            self.update_service.download_and_install_async(
                self.update_banner.download_url,
                self.update_banner.version
            )

    def _start_meeting(self) -> None:
        if not self.settings.zoom_join_url.strip():
            self.mode_label.setText(
                "Abrindo programas; configure o link da reunião do Zoom em Ajustes."
            )
        self.start_meeting_button.setEnabled(False)
        self.start_meeting_button.setText("⏳ Iniciando reunião…")
        if not self.launcher.start_meeting():
            self.start_meeting_button.setEnabled(True)
            self.start_meeting_button.setText("▶️ Iniciar reunião")

    def _end_meeting(self) -> None:
        self.end_meeting_button.setEnabled(False)
        self.end_meeting_button.setText("⏳ Encerrando…")
        self.launcher.end_meeting()
        self.end_meeting_button.setEnabled(True)
        self.end_meeting_button.setText("⏹️ Encerrar reunião")
        self.mode_label.setText("Reunião encerrada. Programas fechados.")

    def _on_launch_progress(self, message: str) -> None:
        self.mode_label.setText(message)

    def _on_launch_finished(self, payload: object) -> None:
        self.start_meeting_button.setEnabled(True)
        self.start_meeting_button.setText("▶️ Iniciar reunião")
        if not isinstance(payload, LaunchSummary):
            self.mode_label.setText("Inicialização concluída.")
            return

        if payload.obs_running:
            self.obs.ensure_virtual_camera()

        if payload.zoom_running:
            zoom_text = "● Zoom"
            zoom_state = "ok"
            if payload.zoom_meeting_active:
                zoom_tooltip = "Zoom aberto e reunião detectada."
            elif self.settings.zoom_join_url:
                zoom_tooltip = "Zoom aberto; aguardando a janela da reunião."
            else:
                zoom_tooltip = "Zoom aberto; configure o link da reunião em Ajustes."
        else:
            zoom_text = "○ Zoom"
            zoom_state = "error"
            zoom_tooltip = "Zoom não foi detectado após a tentativa de inicialização."

        self._set_component_status("Zoom", zoom_state, zoom_text, zoom_tooltip)
        self.mode_label.setText(" • ".join(payload.notes[-3:]) or "Inicialização concluída.")

        # Layout organization requested by the user
        try:
            import win32api
            import win32con
            import win32gui
            
            screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            app_width = self.width()
            
            # Position this app on the left, vertically centered
            app_height = self.height()
            self.move(0, (screen_height - app_height) // 2)
            
            def arrange_windows(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                title = win32gui.GetWindowText(hwnd).strip()
                class_name = win32gui.GetClassName(hwnd)
                
                if class_name == "ApplicationFrameWindow" and "JW Library" in title:
                    # JWL to the right, full screen minus app width
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    win32gui.SetWindowPos(
                        hwnd, win32con.HWND_TOP,
                        app_width, 0,
                        screen_width - app_width, screen_height,
                        win32con.SWP_SHOWWINDOW,
                    )
                elif ("Zoom Meeting" in title or "Zoom" == title) and "Zoom" in class_name:
                    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                return True

            win32gui.EnumWindows(arrange_windows, None)
        except Exception:
            pass

    def _on_zoom_hall_status(self, ok: bool, message: str) -> None:
        self._set_component_status(
            "Zoom",
            "ok" if ok else "warning",
            "● Zoom" if ok else "○ Zoom",
            message,
        )
        self.mode_label.setText(message)

    def _on_zoom_hall_active(self, active: bool, message: str) -> None:
        button = self.mode_buttons[OperatingMode.ZOOM]
        if active:
            self.state.set_mode(OperatingMode.ZOOM)
            button.setText("⏹️ Parar Zoom → Salão")
            button.setChecked(True)
            if self.state.automation_enabled:
                self.automation_status.setText(
                    "Zoom → Salão ativo • sensor do JW Library suspenso temporariamente"
                )
            self.zoom_output_label.setText(
                "Salão recebe: Zoom local • Zoom remoto continua recebendo OBS Virtual Camera"
            )
            self.mode_label.setText("Salão: Zoom")
            return

        button.setText("💻 Zoom → Salão")
        self.zoom_output_label.setText(
            "Zoom recebe: OBS Virtual Camera • transições feitas pelo OBS"
        )
        if self.current_obs_scene:
            mode = self._mode_for_scene(self.current_obs_scene)
            if mode is not None:
                self.state.set_mode(mode)
        self._refresh_mode()
        if self.state.automation_enabled:
            self.automation_status.setText("Automação retomando leitura da Tela do Salão…")
        self.mode_label.setText(message)

    def _on_obs_error(self, message: str) -> None:
        self.mode_label.setText(message)

    def _auto_start_camera(self) -> None:
        if not self.obs_connected or self.camera_session is None:
            return
        if self.camera_session.state == "off":
            self.camera_session.start()

    def _toggle_zoom_mic(self) -> None:
        def worker():
            try:
                import pywinauto
                desktop = pywinauto.Desktop(backend="uia")
                zoom_windows = [w for w in desktop.windows() if "Zoom" in w.window_text()]
                for w in zoom_windows:
                    mute_btns = w.descendants(
                        control_type="Button", 
                        title_re=".*[aA]udio.*|.*[áÁ]udio.*|.*[mM]ute.*"
                    )
                    for btn in mute_btns:
                        btn.invoke()
                        return
            except Exception:
                pass
        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _toggle_camera(self) -> None:
        if self.camera_session is None:
            return
        if self.camera_session.state == "running":
            self.camera_session.stop()
        else:
            self.camera_session.start()

    def _on_camera_state(self) -> None:
        if self.camera_session is None or not hasattr(self, "camera_button"):
            return
        state = self.camera_session.state
        running = state == "running"
        busy = state in {"starting", "stopping"}
        if running:
            text = "⏹️ Parar câmera WhatsApp"
        elif state == "error":
            text = "📹 Tentar câmera WhatsApp"
        else:
            text = "📹 Iniciar câmera WhatsApp"
        self.camera_button.setText(text)
        self.camera_button.setEnabled(
            bool(self.camera_session.supported) and not busy
        )
        self.camera_button.setToolTip(self.camera_session.message)

    def _toggle_whatsapp_audio(self) -> None:
        if self.whatsapp_audio_guard is None:
            return
        # The guard is fail-closed.  A failed attempt to unmute leaves the
        # button in its previous safe state and reports the reason below.
        self.whatsapp_audio_guard.toggle()

    def _on_whatsapp_audio_state(self, muted: bool, message: str) -> None:
        if not hasattr(self, "whatsapp_audio_button"):
            return
        self.whatsapp_audio_button.blockSignals(True)
        self.whatsapp_audio_button.setChecked(not muted)
        self.whatsapp_audio_button.setText(
            "🔇 WhatsApp" if muted else "🔊 WhatsApp"
        )
        self.whatsapp_audio_button.setToolTip(message)
        self.whatsapp_audio_button.blockSignals(False)
        self.mode_label.setText(message)

    def _open_virtual_camera(self, parent=None) -> None:
        from meeting_assistant.ui.virtual_camera_dialog import VirtualCameraDialog

        dialog = VirtualCameraDialog(parent or self)
        dialog.exec()
        dialog.deleteLater()

    def _open_audio_setup(self, parent=None) -> None:
        from meeting_assistant.ui.audio_setup_dialog import AudioSetupDialog

        dialog = AudioSetupDialog(self.obs, self.settings, parent or self)
        dialog.exec()
        dialog.deleteLater()

    def _show_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.obs_scenes, self)
        dialog.hall_setup_requested.connect(lambda: self._open_hall_setup(dialog))
        dialog.audio_setup_requested.connect(lambda: self._open_audio_setup(dialog))
        dialog.virtual_camera_requested.connect(lambda: self._open_virtual_camera(dialog))
        dialog.observe_requested.connect(
            lambda: (dialog.reject(), QTimer.singleShot(0, self._start_jwl_probe))
        )
        dialog.calibrate_requested.connect(
            lambda: (dialog.reject(), QTimer.singleShot(0, self._calibrate_idle_reference))
        )
        dialog.setup_assistant_requested.connect(
            lambda: (dialog.reject(), QTimer.singleShot(0, self._open_setup_assistant))
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        from dataclasses import replace

        pending = replace(self.settings)
        dialog.apply_to(pending)
        if pending.obs_start_at_logon != self.settings.obs_start_at_logon or (
            pending.obs_start_at_logon and pending.obs_executable != self.settings.obs_executable
        ):
            try:
                configure_obs_logon(pending.obs_start_at_logon, pending.obs_executable)
            except ValueError as exc:
                QMessageBox.warning(self, "Inicialização OBS", str(exc))
                return
            except Exception:
                QMessageBox.warning(
                    self, "Inicialização OBS",
                    "Não foi possível configurar o atalho do OBS. Confira o executável e as permissões. "
                    "Os ajustes não foram salvos.",
                )
                return
        dialog.apply_to(self.settings)
        self.settings_service.save(self.settings)
        # Provisioning must not trigger the reconnect callback's Program change.
        self._startup_scene_applied = dialog.prepare_obs_requested
        self._set_component_status("OBS", "pending", "○ OBS", "Reconectando…")
        self.obs.reconfigure(self._obs_config())
        if dialog.prepare_obs_requested:
            self.obs.prepare_stage(self.settings)

    def _on_obs_setup_finished(self, ok: bool, message: str) -> None:
        if ok:
            (self.settings.scene_background, self.settings.scene_speaker,
             self.settings.scene_media) = STANDARD_SCENES
            self.settings.obs_standard_scenes = True
            self.settings_service.save(self.settings)
        if self._setup_assistant is None:
            QMessageBox.information(self, "Preparação OBS", message)

    def _apply_assistant_settings(self, pending):
        from dataclasses import fields

        if self.state.automation_enabled or self.zoom_hall.active or self.zoom_hall.returning:
            raise ValueError("Pause a automação e retorne ao JWL antes de configurar o ambiente.")
        if pending.obs_start_at_logon != self.settings.obs_start_at_logon or (
            pending.obs_start_at_logon and pending.obs_executable != self.settings.obs_executable
        ):
            configure_obs_logon(pending.obs_start_at_logon, pending.obs_executable)
        previous_obs_config = self._obs_config()
        self.settings_service.save(pending)
        for field in fields(pending):
            setattr(self.settings, field.name, getattr(pending, field.name))
        self._startup_scene_applied = True
        if previous_obs_config != self._obs_config():
            self.obs.reconfigure(self._obs_config())

    def _open_setup_assistant(self):
        if self._setup_assistant is not None:
            self._setup_assistant.raise_()
            return
        if self.state.automation_enabled or self.zoom_hall.active or self.zoom_hall.returning:
            QMessageBox.information(
                self, "Configuração", "Pause a automação e retorne ao JWL antes de configurar."
            )
            return
        from meeting_assistant.ui.setup_assistant_dialog import SetupAssistantDialog

        dialog = SetupAssistantDialog(self)
        self._setup_assistant = dialog
        dialog.exec()
        self._setup_assistant = None
        dialog.deleteLater()
        self._refresh_yeartext_notice()

    def _hall_capture_target(self):
        if self.state.automation_enabled and self._latest_media_active:
            raise ValueError("O detector ainda indica mídia. Pare a mídia antes de capturar o Texto do Ano.")
        return verified_hall_target(
            self._hall_window_provider(), self._hall_display_provider(),
            self.zoom_hall.active or self.zoom_hall.returning,
            diagnostic=self.hall_capture_diagnostic.emit,
        )

    def _open_hall_setup(self, parent):
        dialog = HallSetupDialog(
            self.yeartext_store, self._hall_capture_target, self.obs, self.settings, parent
        )
        dialog.exec()
        dialog.deleteLater()
        self._refresh_yeartext_notice()

    def _refresh_yeartext_notice(self):
        from datetime import datetime

        current = self.yeartext_store.current()
        outdated = current is None or current["year"] != datetime.now().year
        if outdated:
            action = "Criar foto do Texto do Ano" if current is None else "Atualizar foto do Texto do Ano"
            self.yeartext_notice.setText(f'<a href="yeartext">{action}</a>')
            self.yeartext_notice.setToolTip(self.yeartext_store.status())
        else:
            self.yeartext_notice.setText("Operação local • OBS • Zoom • JW Library")
            self.yeartext_notice.setToolTip(self.yeartext_store.status())

    def _on_hall_task_finished(self, action, ok, message):
        if action == "yeartext":
            self._refresh_yeartext_notice()
        if action == "virtual_camera":
            self.zoom_output_label.setText(message + " • Selecione OBS Virtual Camera no Zoom.")

    def _show_diagnostics(self) -> None:
        display_lines = "\n".join(
            f"• {'Principal' if display.primary else 'Secundária'}: "
            f"{display.name} • {display.resolution} • {display.x},{display.y}"
            for display in self.display_snapshot
        ) or "• nenhum monitor detectado"
        jwl_lines = self._format_jwl_snapshot(self.jwl_snapshot)

        if not self.obs_connected:
            QMessageBox.information(
                self,
                "Verificação do sistema",
                "OBS WebSocket não está conectado.\n\n"
                "Abra o OBS e confira host, porta e senha em Ajustes.\n\n"
                f"Monitores detectados:\n{display_lines}\n\n"
                f"JW Library:\n{jwl_lines}",
            )
            return

        configured = {
            "Fundo": self.settings.scene_background,
            "Palco": self.settings.scene_speaker,
            "Mídia": self.settings.scene_media,
        }
        missing = [
            f"{label}: {scene}"
            for label, scene in configured.items()
            if scene not in self.obs_scenes
        ]
        scene_lines = "\n".join(f"• {scene}" for scene in self.obs_scenes) or "• nenhuma"
        missing_text = "\n".join(f"• {item}" for item in missing) or "• nenhuma"
        QMessageBox.information(
            self,
            "Verificação do sistema",
            f"Cena Program atual: {self.current_obs_scene or 'desconhecida'}\n\n"
            f"Cenas encontradas:\n{scene_lines}\n\n"
            f"Mapeamentos ausentes:\n{missing_text}\n\n"
            f"Monitores detectados:\n{display_lines}\n\n"
            f"JW Library:\n{jwl_lines}",
        )

    @staticmethod
    def _format_jwl_snapshot(snapshot: list[JwlWindowInfo]) -> str:
        if not snapshot:
            return "nenhuma janela candidata visível"

        lines: list[str] = []
        for item in snapshot:
            state = "minimizada" if item.minimized else "normal"
            title = item.title or "<sem título>"
            lines.append(
                f"HWND {item.hwnd} • PID {item.pid} • {item.process_name or '?'}\n"
                f"{item.class_name} • {item.size} • {state} • {title}"
            )
        return "\n\n".join(lines)

    def _obs_config(self) -> ObsConnectionConfig:
        return ObsConnectionConfig(
            host=self.settings.obs_host,
            port=self.settings.obs_port,
            password=self.settings.obs_password,
        )

    def _scene_for_mode(self, mode: OperatingMode) -> str:
        return {
            OperatingMode.BACKGROUND: self.settings.scene_background,
            OperatingMode.SPEAKER: self.settings.scene_speaker,
            OperatingMode.MEDIA: self.settings.scene_media,
            OperatingMode.ZOOM: self.settings.scene_speaker,
        }[mode]

    def _mode_for_scene(self, scene_name: str) -> OperatingMode | None:
        mappings = {
            self.settings.scene_background: OperatingMode.BACKGROUND,
            self.settings.scene_speaker: OperatingMode.SPEAKER,
            self.settings.scene_media: OperatingMode.MEDIA,
        }
        return mappings.get(scene_name)

    def _refresh_mode(self) -> None:
        if self.zoom_hall.active:
            for mode, button in self.mode_buttons.items():
                button.setChecked(mode is OperatingMode.ZOOM)
            self.mode_label.setText("Salão: Zoom")
            return

        actual_mode = None
        if self.obs_connected and self.current_obs_scene:
            actual_mode = self._mode_for_scene(self.current_obs_scene)
        elif self.state.simulation_enabled:
            actual_mode = self.state.current_mode

        for mode, button in self.mode_buttons.items():
            button.setChecked(mode == actual_mode)

        readable = {
            OperatingMode.BACKGROUND: "Texto do Ano",
            OperatingMode.SPEAKER: "Palco",
            OperatingMode.MEDIA: "Mídia",
            OperatingMode.ZOOM: "Zoom → Salão",
        }

        if self.obs_connected and self.current_obs_scene:
            if actual_mode is None:
                self.mode_label.setText(f"OBS Program: {self.current_obs_scene}")
            else:
                self.mode_label.setText(f"Salão: {readable[actual_mode]}")
            return

        self.mode_label.setText(f"Simulação: {readable[self.state.current_mode]}")

    def _update_window_title(self) -> None:
        if self.state.second_display_available:
            self.setWindowTitle("Meeting Assistant 3.0")
        else:
            self.setWindowTitle("Meeting Assistant 3.0 — Modo de Simulação")

    def _set_component_status(
        self,
        name: str,
        state: str,
        text: str,
        tooltip: str,
    ) -> None:
        label = self.status_labels[name]
        label.setText(text)
        label.setProperty("state", state)
        label.setToolTip(tooltip)
        self._repolish(label)

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #111318;
                color: #f2f4f8;
                font-family: 'Segoe UI';
            }
            QLabel#BrandIcon {
                background: #0d121a;
                border: 1px solid #2a3544;
                border-radius: 9px;
            }
            QLabel#Title {
                font-size: 19px;
                font-weight: 700;
            }
            QLabel#Subtitle, QLabel#Footer {
                color: #9ca6b5;
                font-size: 10px;
            }
            QLabel#SectionTitle {
                color: #92c5ff;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#StatusBadge {
                background: #1b2029;
                border: 1px solid #2c3440;
                border-radius: 6px;
                padding: 5px 7px;
                font-size: 10px;
            }
            QLabel#StatusBadge[state='ok'] {
                color: #73e6a2;
                border-color: #286743;
            }
            QLabel#StatusBadge[state='warning'] {
                color: #ffd166;
                border-color: #705b2a;
            }
            QLabel#StatusBadge[state='error'] {
                color: #ff9299;
                border-color: #74363d;
            }
            QLabel#StatusBadge[state='pending'] {
                color: #d4dae3;
            }
            QLabel#AutomationBadge {
                background: #3b3220;
                color: #ffd166;
                border-radius: 7px;
                padding: 6px 9px;
                font-size: 10px;
                font-weight: 700;
            }
            QLabel#AutomationBadge[active='true'] {
                background: #153924;
                color: #73e6a2;
            }
            QLabel#AutomationStatus {
                background: #10141a;
                color: #aeb7c4;
                border-radius: 6px;
                padding: 5px 7px;
                font-size: 10px;
            }
            QFrame#Card {
                background: #171b22;
                border: 1px solid #282f3a;
                border-radius: 9px;
            }
            QWidget#Preview {
                background: #080a0e;
                border: 1px solid #303844;
                border-radius: 7px;
                color: #758093;
                font-size: 12px;
            }
            QLabel#ZoomOutputLabel {
                background: #10141a;
                color: #9ca6b5;
                border-radius: 6px;
                padding: 5px 7px;
                font-size: 10px;
            }
            QPushButton {
                background: #252c36;
                border: 1px solid #343e4c;
                border-radius: 7px;
                padding: 6px 9px;
                font-size: 11px;
                font-weight: 600;
                text-align: left;
            }
            QPushButton:hover {
                background: #2d3744;
            }
            QPushButton:checked {
                background: #0b5cab;
                border-color: #2b8ce6;
            }
            QPushButton:disabled {
                color: #8b95a3;
                background: #1c222b;
            }
            QPushButton#DangerButton {
                background: #4a2528;
                border-color: #6b3036;
            }
            QLabel#ModeLabel {
                background: #10141a;
                border-radius: 6px;
                padding: 7px;
                font-size: 10px;
                font-weight: 600;
            }
            """
        )
