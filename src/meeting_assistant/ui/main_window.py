from __future__ import annotations

import time
from dataclasses import replace

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSequentialAnimationGroup,
    QSize,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
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
from meeting_assistant.ui.program_preview import ProgramPreview
from meeting_assistant.ui.window_geometry import ScreenFitController


class ToggleSwitch(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track_path = QPainterPath()
        track_rect = QRectF(0, 0, self.width(), self.height())
        track_path.addRoundedRect(track_rect, 11, 11)
        if self.isChecked():
            painter.setBrush(QColor("#00a884"))
            painter.setPen(Qt.NoPen)
        else:
            painter.setBrush(QColor("#1e2530"))
            painter.setPen(QColor("#46546a"))
        painter.drawPath(track_path)
        knob_path = QPainterPath()
        if self.isChecked():
            knob_rect = QRectF(self.width() - 20, 2, 18, 18)
        else:
            knob_rect = QRectF(2, 2, 18, 18)
        knob_path.addEllipse(knob_rect)
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(Qt.NoPen)
        painter.drawPath(knob_path)

    def hitButton(self, pos):
        return self.rect().contains(pos)


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
        self.obs.media_scene = settings.scene_media
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
        self._meeting_active = False
        self._meeting_ending = False
        self.layout_service = None
        self.external_media = None
        self._external_popup = None
        self._close_after_external = False
        self._layout_save_pending = False

        if self.update_service:
            self.update_service.update_available.connect(self._on_update_available)
            self.update_service.status_changed.connect(self._update_status)
            self.update_service.install_ready.connect(self._install_update)
            self.update_service.activity_provider = self._update_blocked
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
        self._apply_whatsapp_visibility()
        self._apply_style()
        from meeting_assistant.ui.shortcuts import MainWindowShortcuts

        self._shortcuts = MainWindowShortcuts(
            self,
            [
                lambda: self._select_mode(OperatingMode.BACKGROUND),
                lambda: self._select_mode(OperatingMode.SPEAKER),
                lambda: self._select_mode(OperatingMode.MEDIA),
                lambda: self._select_mode(OperatingMode.ZOOM),
                self._toggle_automation,
                self._activate_safe_scene,
                self._start_meeting,
                self._show_diagnostics,
                self._show_settings,
            ],
        )
        self._connect_obs_signals()
        self._connect_display_signals()
        self._connect_jwl_signals()
        self._connect_launcher_signals()
        if self.camera_session is not None:
            self.camera_session.changed.connect(self._on_camera_state)
            self._on_camera_state()
        else:
            self.camera_button.setEnabled(False)
            self.camera_button.setText("📹 Câmera indisponível")
            self.camera_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            from pathlib import Path
            icon_root = Path(__file__).parent.parent / "resources"
            whatsapp_svg = icon_root / "whatsapp.svg"
            if whatsapp_svg.is_file():
                self.camera_button.setIcon(QIcon(str(whatsapp_svg)))
                self.camera_button.setIconSize(QSize(16, 16))
            self.camera_button.setAccessibleName("Câmera virtual WhatsApp indisponível")
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
        from meeting_assistant.services.zoom_audio import ZoomAudio

        self.zoom_audio = ZoomAudio(self)
        self.zoom_audio.result.connect(self._zoom_audio_result)
        self.zoom_audio.activity.connect(self._zoom_microphone_activity)
        self.zoom_audio.command_finished.connect(self._zoom_microphone_finished)
        self._zoom_audio_state = "unknown"
        self._zoom_audio_seen = 0.0
        self._zoom_audio_message = "Controla seu microfone no Zoom; não silencia participantes."
        self._operator_timer = QTimer(self)
        self._operator_timer.setInterval(3000)
        self._operator_timer.timeout.connect(self._operator_tick)
        from meeting_assistant.services.global_hotkeys import GlobalHotkeys

        self.global_keys = GlobalHotkeys(self)
        self.global_keys.pressed.connect(self._global_key)
        self.global_keys.status.connect(self.automation_status.setToolTip)
        self._operator_timer.start()
        self.obs.preview_age.connect(self._preview_age)
        self.obs.operator_finished.connect(self._operator_result)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        self._root_layout = root
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(5)

        header = QHBoxLayout()
        header.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        brand_row.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        brand_icon = QLabel()
        brand_icon.setObjectName("BrandIcon")
        brand_icon.setFixedSize(32, 32)
        brand_icon.setAlignment(Qt.AlignCenter)
        if not self.app_icon.isNull():
            brand_icon.setPixmap(self.app_icon.pixmap(28, 28))
        brand_row.addWidget(brand_icon, alignment=Qt.AlignVCenter)

        title = QLabel("Meeting Assistant")
        title.setObjectName("Title")
        title.setWordWrap(False)
        title.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        brand_row.addWidget(title, alignment=Qt.AlignVCenter)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title_box.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        title_box.addLayout(brand_row)

        subtitle = QLabel("")
        subtitle.setObjectName("Subtitle")
        subtitle.setWordWrap(True)
        subtitle.setMinimumWidth(0)
        subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.yeartext_notice = subtitle
        subtitle.linkActivated.connect(lambda _: self._open_hall_setup(self))
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        # Right control stack: Automation Badge on top, WhatsApp toggle row below
        right_box = QVBoxLayout()
        right_box.setSpacing(3)
        right_box.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.automation_badge = QLabel("AUTOMAÇÃO PAUSADA")
        self.automation_badge.setObjectName("AutomationBadge")
        self.automation_badge.setAlignment(Qt.AlignCenter)
        self.automation_badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        right_box.addWidget(self.automation_badge, alignment=Qt.AlignmentFlag.AlignHCenter)

        wa_row = QHBoxLayout()
        wa_row.setSpacing(6)
        wa_row.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        from pathlib import Path
        icon_root = Path(__file__).parent.parent / "resources"

        self.congregation_label = QLabel()
        self.congregation_label.hide()

        self.whatsapp_icon = QLabel()
        whatsapp_svg = icon_root / "whatsapp.svg"
        if whatsapp_svg.is_file():
            self.whatsapp_icon.setPixmap(QIcon(str(whatsapp_svg)).pixmap(18, 18))
        else:
            self.whatsapp_icon.setText("WA")

        self.whatsapp_toggle = ToggleSwitch()
        self.whatsapp_toggle.setChecked(self.settings.whatsapp_enabled)
        self.whatsapp_toggle.setToolTip("Usar WhatsApp")
        self.whatsapp_toggle.toggled.connect(self._on_whatsapp_toggle)

        wa_row.addWidget(self.whatsapp_icon)
        wa_row.addWidget(self.whatsapp_toggle)
        right_box.addLayout(wa_row)

        header.addLayout(right_box)
        root.addLayout(header)

        status_grid = QGridLayout()
        status_grid.setHorizontalSpacing(5)
        status_grid.setVerticalSpacing(2)
        self.status_labels: dict[str, QLabel] = {}
        status_items = [
            ("OBS", "obs.png", "OBS"),
            ("JW Library", "jwlibrary.svg", "JW Library"),
            ("Zoom", "zoom.svg", "Zoom"),
            ("Tela 2", "display2.svg", "Tela 2"),
        ]
        for index, (name, icon_file, tip_name) in enumerate(status_items):
            label = QLabel()
            label.setObjectName("StatusBadge")
            label.setProperty("state", "pending")
            label.setFixedHeight(28)
            label.setAlignment(Qt.AlignCenter)
            svg_path = icon_root / icon_file
            if svg_path.is_file():
                label.setPixmap(QIcon(str(svg_path)).pixmap(20, 20))
            else:
                label.setText(name[:3])
            label.setToolTip(f"{tip_name}: aguardando verificação")
            self.status_labels[name] = label
            status_grid.addWidget(label, 0, index)
            status_grid.setColumnStretch(index, 1)
        root.addLayout(status_grid)

        controls_card = QFrame()
        controls_card.setObjectName("Card")
        controls = QVBoxLayout(controls_card)
        self._controls_layout = controls
        controls.setContentsMargins(10, 8, 10, 8)
        controls.setSpacing(4)

        controls.addWidget(self._section_label("CONTROLE DA APRESENTAÇÃO"))

        mode_grid = QGridLayout()
        self._mode_grid = mode_grid
        mode_grid.setHorizontalSpacing(6)
        mode_grid.setVerticalSpacing(4)
        self.mode_buttons: dict[OperatingMode, QPushButton] = {}
        button_specs = [
            (OperatingMode.BACKGROUND, "yeartext.svg", "Texto do Ano (Repouso do JW Library)", 0, 0),
            (OperatingMode.SPEAKER, "stage.svg", "Palco (Câmera do orador no OBS)", 0, 1),
            (OperatingMode.MEDIA, "media.svg", "Mídia (Vídeos e imagens do JW Library)", 0, 2),
            (OperatingMode.ZOOM, "zoom_hall.svg", "Zoom → Salão (Exibir participantes na 2ª tela)", 0, 3),
        ]
        for mode, icon_file, tooltip, row, col in button_specs:
            button = QPushButton()
            button.setObjectName("ModeButton")
            button.setCheckable(True)
            svg_path = icon_root / icon_file
            if svg_path.is_file():
                button.setIcon(QIcon(str(svg_path)))
                if mode is OperatingMode.ZOOM:
                    button.setIconSize(QSize(40, 20))
                else:
                    button.setIconSize(QSize(24, 24))
            button.setToolTip(tooltip)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setMinimumHeight(44)
            button.setMinimumWidth(0)
            button.clicked.connect(lambda checked=False, m=mode: self._manual_select(m))
            self.mode_buttons[mode] = button
            mode_grid.addWidget(button, row, col)
            mode_grid.setColumnStretch(col, 1)
        controls.addLayout(mode_grid)

        self.auto_button = QPushButton("🚥 Ativar")
        self.auto_button.setToolTip("Ativar automação de mídias e guardião do JWL.")
        self.auto_button.clicked.connect(self._toggle_automation)
        automation_row = QHBoxLayout()
        automation_row.addWidget(self.auto_button, 1)
        controls.addLayout(automation_row)

        self.automation_status = QLabel("Automação pausada")
        self.automation_status.setObjectName("AutomationStatus")
        self.automation_status.setWordWrap(True)
        self.automation_status.setMinimumWidth(0)
        self.automation_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.automation_status.setAlignment(Qt.AlignCenter)
        controls.addWidget(self.automation_status)

        panic = QPushButton("🚨 Emergência (Texto do Ano)")
        panic.setObjectName("DangerButton")
        panic.setToolTip("Corta o vídeo para o Texto do Ano. Usa-se em caso de pânico ou erro inesperado.")
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

        self.power_button = QPushButton("▶️ Iniciar reunião")
        self.power_button.setToolTip(
            "Abre OBS, JW Library e Zoom. Se o link estiver configurado, o Zoom entra diretamente na reunião."
        )
        self.power_button.clicked.connect(self._start_meeting)

        system_grid = QGridLayout()
        self._system_grid = system_grid
        system_grid.setHorizontalSpacing(6)
        system_grid.setVerticalSpacing(6)
        diagnostics = QPushButton("🩺 Operação")
        diagnostics.clicked.connect(self._show_diagnostics)

        # Row 0
        self.power_button = QPushButton("🟢 Iniciar reunião")
        self.power_button.setToolTip("Abre OBS, JW Library e Zoom. Clique novamente para encerrar.")
        self.power_button.clicked.connect(self._toggle_meeting)
        system_grid.addWidget(self.power_button, 0, 0)

        self.force_jwl_button = QPushButton("🛡️ JW na 2ª Tela")
        self.force_jwl_button.setToolTip(
            "Solicita o retorno ao JW Library sem ativar a automação. "
            "Encerra primeiro a mídia externa ou o modo Zoom local, se ativo."
        )
        self.force_jwl_button.clicked.connect(self._force_jwl)
        system_grid.addWidget(self.force_jwl_button, 0, 1)
        self.volume_button = QPushButton("Volumes")
        icon_root = Path(__file__).parent.parent / "resources"
        self.volume_button.setIcon(QIcon(str(icon_root / "volumes.svg")))
        self.volume_button.setIconSize(QSize(14, 14))
        self.volume_button.setToolTip("Ajusta o áudio enviado às chamadas sem refazer as fontes.")
        self.volume_button.clicked.connect(self._open_audio_setup)
        settings_button = self.settings_button = QPushButton("Ajustes")
        settings_button.setIcon(QIcon(str(icon_root / "settings.svg")))
        settings_button.setIconSize(QSize(14, 14))
        settings_button.clicked.connect(self._show_settings)
        settings_cell = QWidget()
        settings_row = QHBoxLayout(settings_cell)
        settings_row.setContentsMargins(0, 0, 0, 0)
        settings_row.setSpacing(4)
        settings_row.addWidget(self.volume_button, 1)
        settings_row.addWidget(settings_button, 1)

        # Row 1
        self.camera_button = QPushButton("📹 Iniciar câmera")
        self.camera_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        whatsapp_svg = icon_root / "whatsapp.svg"
        if whatsapp_svg.is_file():
            self.camera_button.setIcon(QIcon(str(whatsapp_svg)))
            self.camera_button.setIconSize(QSize(16, 16))
        self.camera_button.setToolTip(
            "Inicia ou para a câmera virtual nativa que transmite o Program do OBS ao WhatsApp."
        )
        self.camera_button.clicked.connect(self._toggle_camera)
        system_grid.addWidget(self.camera_button, 1, 0)

        self.zoom_mic_button = QPushButton("🎙 Mic Zoom")
        self.zoom_mic_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.zoom_mic_button.setMinimumWidth(0)
        self.zoom_mic_button.setObjectName("ZoomMic")
        self.zoom_mic_button.setToolTip("Controla seu microfone no Zoom; não silencia participantes.")
        self.zoom_mic_button.clicked.connect(self._zoom_microphone)
        system_grid.addWidget(self.zoom_mic_button, 1, 1)

        # Row 2
        self.ext_media_button = QPushButton("🎬 Mídia Externa")
        self.ext_media_button.setCheckable(True)
        self.ext_media_button.setToolTip(
            "Apresenta o player ou navegador escolhido no Salão e nas chamadas. "
            "Clique novamente para voltar ao JWL."
        )
        self.ext_media_button.clicked.connect(self._toggle_ext_media)
        system_grid.addWidget(self.ext_media_button, 2, 0)
        system_grid.addWidget(settings_cell, 2, 1)

        # Two equal columns accommodate native Windows font/emoji metrics
        # without widening the window or truncating action names.
        for column in range(2):
            system_grid.setColumnStretch(column, 1)
        for button in (
            self.power_button,
            self.power_button,
            settings_button,
            self.volume_button,
            self.ext_media_button,
            self.camera_button,
            self.zoom_mic_button,
        ):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        controls.addLayout(system_grid)

        # Probe command lives in Settings; no local button needed here.
        controls.addSpacing(2)
        controls.addWidget(self._section_label("PREVIEW DO OBS"))

        preview_row = QHBoxLayout()
        self.preview = ProgramPreview(self)
        self.preview.setObjectName("Preview")
        self.preview.setMaximumSize(480, 270)
        preview_row.addWidget(self.preview, 1)
        controls.addLayout(preview_row, 1)

        self.pause_preview_button = QPushButton("⏸️ Pausar Prévia")
        self.pause_preview_button.setObjectName("PausePreviewButton")
        self.pause_preview_button.setToolTip("Pausa a prévia de vídeo para economizar CPU e memória")
        self.pause_preview_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.pause_preview_button.clicked.connect(self._toggle_preview_pause)
        controls.addWidget(self.pause_preview_button)

        self.zoom_output_label = QLabel("Zoom recebe: OBS Virtual Camera • transições feitas pelo OBS")
        self.zoom_output_label.setObjectName("ZoomOutputLabel")
        self.zoom_output_label.setAlignment(Qt.AlignCenter)
        self.zoom_output_label.setWordWrap(True)
        self.zoom_output_label.setMinimumWidth(0)
        self.zoom_output_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        controls.addWidget(self.zoom_output_label)

        self.mode_label = QLabel()
        self.mode_label.setObjectName("ModeLabel")
        self.mode_label.setAlignment(Qt.AlignCenter)
        self.mode_label.setWordWrap(True)
        self.mode_label.setMinimumWidth(0)
        self.mode_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        controls.addWidget(self.mode_label)

        root.addWidget(controls_card, 1)

        self.footer = QLabel()
        self.footer.hide()  # Hidden as requested
        self.footer.setObjectName("Footer")
        self.footer.setAlignment(Qt.AlignCenter)
        self.footer.setWordWrap(True)
        root.addWidget(self.footer)

        self.update_banner = QPushButton()
        self.update_banner.setObjectName("UpdateBanner")
        self.update_banner.hide()
        self.update_banner.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.update_banner.clicked.connect(self._trigger_update)
        root.addWidget(self.update_banner)

        scroll = QScrollArea()
        scroll.setObjectName("MainContentScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(central)
        self.setCentralWidget(scroll)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_root_layout") and hasattr(self, "_system_grid"):
            self._update_layout_spacing()

    def _update_layout_spacing(self) -> None:
        # Full HD at 200% has about 500 logical pixels of usable height.
        # Compress gaps rather than fonts or button heights; restore them
        # when the window grows or moves to a screen with more logical space.
        tight = self.height() < 560
        if tight == getattr(self, "_tight_operator_layout", None):
            return
        self._tight_operator_layout = tight
        vertical_margin = 6 if tight else 10
        self._root_layout.setContentsMargins(12, vertical_margin, 12, vertical_margin)
        self._root_layout.setSpacing(3 if tight else 5)
        self._controls_layout.setContentsMargins(10, 5 if tight else 9, 10, 6 if tight else 10)
        self._controls_layout.setSpacing(2 if tight else 4)
        self._mode_grid.setVerticalSpacing(4 if tight else 6)
        self._system_grid.setVerticalSpacing(4 if tight else 6)

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
        self.launcher.end_finished.connect(self._on_end_finished)
        self.zoom_hall.status_changed.connect(self._on_zoom_hall_status)
        self.zoom_hall.active_changed.connect(self._on_zoom_hall_active)

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        return label

    def _toggle_preview_pause(self) -> None:
        new_paused = not self.preview.is_paused
        self.preview.set_paused(new_paused)
        if new_paused:
            self.pause_preview_button.setText("▶️ Retomar Prévia")
            self.pause_preview_button.setToolTip("Retoma a transmissão da prévia na tela")
        else:
            self.pause_preview_button.setText("⏸️ Pausar Prévia")
            self.pause_preview_button.setToolTip("Pausa a prévia de vídeo para economizar CPU e memória")


    def _select_mode(self, mode: OperatingMode) -> None:
        if self.external_media and self.external_media.active:
            self.mode_label.setText("Encerre a mídia externa antes de trocar a saída do salão.")
            return
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
        if self.zoom_hall.active:
            self.zoom_hall.restore_jwl()
        self.obs.operator_task("contingency", replace(self.settings))

    def _preview_age(self, age):
        if age < 0:
            text = "Preview aguardando imagem • recepção remota não verificada"
        elif age > 1:
            text = f"Preview atrasado {age:.0f}s • não indica a fluidez recebida no Zoom"
        else:
            text = "Preview OBS 480×270 · até 20 FPS • confira a recepção no Zoom"
        self.zoom_output_label.setText(text)

    def _manual_select(self, mode):
        if mode is not OperatingMode.ZOOM and self.state.automation_enabled:
            self._toggle_automation()
            self.automation_status.setText("Controle manual. Use Ativar automação para retomar.")
        self._select_mode(mode)

    def _global_key(self, key):
        from PySide6.QtWidgets import QApplication

        if QApplication.activeModalWidget() is not None:
            return
        modes = {
            2: OperatingMode.BACKGROUND,
            3: OperatingMode.SPEAKER,
            4: OperatingMode.MEDIA,
            5: OperatingMode.ZOOM,
        }
        if key == 7:
            self._activate_safe_scene()
        elif key in modes:
            self._manual_select(modes[key])

    def _operator_tick(self):
        self.global_keys.set_enabled(self.settings.global_shortcuts)
        if self.zoom_audio.command_pending:
            return
        if time.monotonic() - self._zoom_audio_seen > 5:
            self._zoom_audio_state = "unknown"
            self._zoom_audio_message = (
                "Estado expirado. Clique para consultar e alternar seu microfone no Zoom."
            )
            self._render_zoom_microphone()
        self.zoom_audio.request()

    def _zoom_microphone(self):
        # Cached/unknown state is presentation only. The worker reads the
        # current own microphone before deciding which action to invoke.
        self.zoom_audio.request("toggle")

    @Slot(bool)
    def _zoom_microphone_activity(self, _active):
        # Ignore a late idle signal from an older worker if a new command began.
        pending = self.zoom_audio.command_pending
        self.zoom_mic_button.setEnabled(not pending)
        if pending:
            self.zoom_mic_button.setText("🎙 Verificando…")
        else:
            self._render_zoom_microphone()

    @Slot(str, str)
    def _zoom_microphone_finished(self, _state, message):
        self.mode_label.setText(message)

    @Slot(str, str)
    def _zoom_audio_result(self, state, message):
        if state in {"live", "muted"}:
            self._meeting_active = True
        self._zoom_audio_state = state
        self._zoom_audio_seen = time.monotonic()
        self._zoom_audio_message = message
        self._render_zoom_microphone()

    def _render_zoom_microphone(self):
        state = self._zoom_audio_state
        self.zoom_mic_button.setText(
            {
                "live": "🎙 Silenciar Zoom",
                "muted": "🔇 Ativar mic Zoom",
            }.get(state, "🎙 Mic Zoom ?")
            if not self.zoom_audio.command_pending else "🎙 Verificando…"
        )
        self.zoom_mic_button.setProperty("state", state)
        self.zoom_mic_button.setToolTip(self._zoom_audio_message)
        self.zoom_mic_button.setAccessibleDescription(self._zoom_audio_message)
        self.zoom_mic_button.setAccessibleName(self.zoom_mic_button.text())
        self._repolish(self.zoom_mic_button)

    def _operator_result(self, action, ok, result):
        if action == "contingency":
            self.automation_status.setText(str(result))

    def _set_automation_ui(self, enabled: bool) -> None:
        if enabled:
            self.automation_badge.setText("AUTOMAÇÃO ATIVA")
            self.automation_badge.setProperty("active", True)
            self.auto_button.setText("⏸️ Pausar")
            self.auto_button.setAccessibleName("Pausar automação e guardião do JWL")
            self.auto_button.setToolTip("Pausar automação de mídias e guardião do JWL.")
            self.automation_status.setText("Automação ativada; calibrando Mídias…")
        else:
            self.automation_badge.setText("AUTOMAÇÃO PAUSADA")
            self.automation_badge.setProperty("active", False)
            self.auto_button.setText("🚥 Ativar")
            self.auto_button.setAccessibleName("Ativar automação e guardião do JWL")
            self.auto_button.setToolTip("Ativar automação de mídias e guardião do JWL.")
            self.automation_status.setText("Automação pausada")
        self._repolish(self.automation_badge)

    def set_automation_status(self, message: str) -> None:
        self.automation_status.setText(message)
        self.automation_badge.setToolTip(message)
        self.auto_button.setToolTip(message)

    def set_telemetry_session(self, session_id: str) -> None:
        self.telemetry_session_id = session_id
        pass

    def closeEvent(self, event) -> None:
        if self.external_media and self.external_media.active:
            self._close_after_external = True
            self.external_media.stop_external_media()
            event.ignore()
            return
        self._operator_timer.stop()
        self.global_keys.set_enabled(False)
        self.zoom_audio.stop()
        self.launcher.stop()
        if self.update_service:
            self.update_service.stop()
        self._persist_layout()
        if self.layout_service:
            self.layout_service.stop()
        super().closeEvent(event)

    def _persist_layout(self, capture=False):
        if not self.layout_service:
            return
        from meeting_assistant.services.window_layout import encode_rect

        screen = self.screen()
        roles = dict(self.settings.window_layouts.get("roles", {}))
        roles.update(self.layout_service.latest.get("roles", {}))
        if screen is not None:
            area = screen.availableGeometry()
            frame = self.frameGeometry()
            roles["app"] = encode_rect(
                (frame.x(), frame.y(), frame.x() + frame.width(), frame.y() + frame.height()),
                {
                    "name": screen.name(),
                    "work": (area.x(), area.y(), area.x() + area.width(), area.y() + area.height()),
                },
            )
        self.settings.window_layouts = {"version": 2, "roles": roles}
        try:
            self.settings_service.save(self.settings)
            if capture:
                self._layout_save_pending = True
                self.layout_service.capture()
                self.mode_label.setText("Disposição do app salva; verificando a janela principal JWL…")
        except OSError:
            self.mode_label.setText("Não foi possível salvar a disposição das janelas.")

    def _layout_captured(self, payload):
        if not self._layout_save_pending:
            return
        self._layout_save_pending = False
        self.settings.window_layouts.setdefault("roles", {}).update(payload.get("roles", {}))
        try:
            self.settings_service.save(self.settings)
            self.mode_label.setText("Disposição salva por função; tela secundária JWL preservada.")
        except OSError:
            self.mode_label.setText("Não foi possível salvar a disposição do JWL.")

    def _restore_layout(self):
        if self.layout_service:
            from meeting_assistant.ui.app_layout import operator_fraction

            self.layout_service.restore(operator_fraction(self))

    def set_telemetry_status(self, ok: bool, message: str) -> None:
        session_id = self.telemetry_session_id or "sessão atual"
        self.footer.setText(f"OBS é a fonte de verdade • Zoom → Salão é local • {message} • {session_id}")
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
        self.automation_status.setText(f"Sensor: {source_name} • sinal {changed_percent:.1f}% • {state_text}")

    def _on_obs_connected(self, connected: bool, message: str) -> None:
        if not connected:
            self.remote_confirmation = "pendente após desconexão OBS"
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
            if current and current.get("obs_pending") and self.obs.local_connection is True:
                self.obs.hall_task(
                    "yeartext",
                    {
                        "directory": str(self.yeartext_store.directory),
                        "scene": self.settings.scene_background,
                    },
                )
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
        self.status_labels["OBS"].setToolTip(f"OBS conectado • {len(scenes)} cena(s) encontrada(s)")

    def _on_obs_scene(self, scene_name: str) -> None:
        self.current_obs_scene = scene_name
        mode = self._mode_for_scene(scene_name)
        if mode is not None and not self.zoom_hall.active:
            self.state.set_mode(mode)
        self._refresh_mode()
        # Do not animate opacity over incoming video frames.
        self.obs.refresh_preview()

    def _start_preview_fade(self) -> None:
        if self._preview_fade_group is not None:
            self._preview_fade_group.stop()

        fade_out = QPropertyAnimation(self.preview_opacity, b"opacity", self)
        fade_out.setDuration(120)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.20)
        fade_out.setEasingCurve(QEasingCurve.Type.InOutQuad)

        fade_in = QPropertyAnimation(self.preview_opacity, b"opacity", self)
        fade_in.setDuration(230)
        fade_in.setStartValue(0.20)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.InOutQuad)

        group = QSequentialAnimationGroup(self)
        group.addAnimation(fade_out)
        group.addAnimation(fade_in)
        self._preview_fade_group = group
        group.start()

    def _on_obs_preview(self, image_bytes: bytes) -> None:
        pixmap = QPixmap()
        if not pixmap.loadFromData(image_bytes):
            self.preview.clear()
            self.preview.setText("Preview inválido")
            return
        scaled = pixmap.scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(scaled)
        self.preview.setToolTip(f"Preview leve do OBS Program • {self.current_obs_scene or 'cena atual'}")

    def _on_obs_preview_error(self, message: str) -> None:
        if not self.obs_connected:
            return
        self.preview.clear()
        self.preview.setText("Preview indisponível\nverifique o diagnóstico")
        self.preview.setToolTip(message)

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

        self.mode_label.setText("Teste JWL: toque uma mídia e depois pare-a durante os próximos 20 segundos.")

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

    def _toggle_ext_media(self, _checked=False):
        if not self.external_media:
            self.ext_media_button.blockSignals(True)
            self.ext_media_button.setChecked(False)
            self.ext_media_button.blockSignals(False)
            self.mode_label.setText("Serviço de mídia externa indisponível.")
            return
        # The service owns the lifecycle; Qt's transient checked flag is only
        # presentation. A click during an active cycle always means return.
        if self.external_media.active:
            self.external_media.stop_external_media()
        else:
            self.external_media.start_external_media()

    def _choose_external_media(self, candidates):
        from meeting_assistant.ui.external_media_dialog import ExternalMediaDialog

        if not self.external_media or self.external_media.phase != "choosing":
            return
        dialog = ExternalMediaDialog(candidates, self)
        def cancelled(active, _message):
            if not active:
                dialog.reject()
        self.external_media.state_changed.connect(cancelled)
        try:
            accepted = dialog.exec() == ExternalMediaDialog.DialogCode.Accepted
        finally:
            self.external_media.state_changed.disconnect(cancelled)
        if self.external_media.phase == "choosing":
            self.external_media.select(dialog.selected_window() if accepted else None)

    def _external_state(self, active, message):
        if (
            self.external_media
            and self.external_media.phase == "return_failed"
            and (self._close_after_external or self._meeting_ending)
        ):
            self.external_media.stop()
            return
        self.ext_media_button.blockSignals(True)
        self.ext_media_button.setChecked(active)
        self.ext_media_button.blockSignals(False)
        phase = self.external_media.phase if self.external_media else "idle"
        stop_pending = bool(getattr(self.external_media, "_stop_after_show", False))
        returning = phase in {"stopping_media", "stopping", "returning"} or stop_pending
        self.ext_media_button.setEnabled(not returning)
        if not active:
            title = "🎬 Mídia Externa"
        elif returning:
            title = "Retornando…"
        elif phase == "return_failed":
            title = "Repetir retorno"
        elif phase == "presenting":
            title = "■ Parar mídia"
        else:
            title = "✕ Cancelar mídia"
        self.ext_media_button.setText(title)
        self.mode_label.setText(message)
        if active and self.external_media.window is not None:
            if self._external_popup is None:
                from meeting_assistant.ui.external_media_controls import ExternalMediaControls

                self._external_popup = ExternalMediaControls(self.external_media.window.process, self)
                self._external_popup.command_requested.connect(self.external_media.command)
                self._external_popup.stop_requested.connect(self.external_media.stop_external_media)
                self._external_popup.show_on_operator_monitor()
            self._external_popup.update_phase("stopping_media" if stop_pending else phase, message)
        elif self._external_popup is not None:
            self._external_popup.finish()
            self._external_popup = None
        if not active and self._close_after_external:
            self._close_after_external = False
            QTimer.singleShot(0, self.close)
        if not active and self._meeting_ending:
            self._request_end_programs()

    def _external_control_status(self, busy, message):
        if self._external_popup is not None:
            self._external_popup.control_status(busy, message)

    def _external_operator_layout(self):
        if self._close_after_external or self._meeting_ending:
            return
        from meeting_assistant.ui.app_layout import restore_app

        self.showNormal()
        restore_app(self, self.settings.window_layouts)

    def _update_blocked(self):
        return bool(
            self._meeting_active
            or self._meeting_ending
            or self.state.automation_enabled
            or self.zoom_hall.active
            or self.zoom_hall.returning
            or self.launcher.busy
            or (getattr(self, "external_media", None) and self.external_media.active)
        )

    def _update_status(self, message, busy):
        self.update_banner.setEnabled(not busy)
        self.update_banner.setToolTip(message)
        if self.update_banner.isVisible():
            self.mode_label.setText(message)

    def _on_update_available(self, version, download_url, release_notes):
        self.update_banner.setText(f"Atualização v{version} · detalhes")
        self.update_banner.setToolTip(release_notes)
        self.update_banner.show()

    def _trigger_update(self):
        if self.update_service:
            from meeting_assistant.ui.update_dialog import UpdateDialog

            UpdateDialog(self.update_service, self).exec()

    def _install_update(self, path, version, checksum):
        from PySide6.QtWidgets import QApplication

        try:
            if self._update_blocked():
                raise ValueError("Encerre a reunião antes de instalar.")
            self.update_service.launch_after_exit(path, checksum)
            self.close()
            QApplication.instance().quit()
        except (ValueError, OSError) as exc:
            self._update_status(str(exc), False)

    def _toggle_meeting(self):
        if self._meeting_active:
            self._end_meeting()
        else:
            self._start_meeting()

    def _force_jwl(self):
        # A manual return is one request, not permission to enable the guardian.
        # The presentation service owns rollback and verified JWL visibility.
        if self.external_media and self.external_media.active:
            self.external_media.stop_external_media()
            return
        message = "Solicitando retorno do JW Library; aguarde a confirmação na Tela do Salão."
        self.mode_label.setText(message)
        if not self.zoom_hall.restore_jwl() and self.mode_label.text() == message:
            # Preserve a more specific synchronous failure from status_changed.
            self.mode_label.setText(
                "Retorno do JW Library não iniciado. Confira a segunda tela e a saída do JWL."
            )

    def _start_meeting(self) -> None:
        self._meeting_active = True
        if self.camera_session:
            self.camera_session.start()
        if not self.settings.zoom_join_url.strip():
            self.mode_label.setText("Abrindo programas; configure o link da reunião do Zoom em Ajustes.")
        self.power_button.setEnabled(False)
        self.power_button.setText("⏳ Iniciando…")
        if not self.launcher.start_meeting():
            self.power_button.setEnabled(True)
            self.power_button.setText("▶️ Iniciar reunião")

    def _end_meeting(self):
        if self._meeting_ending:
            return
        self._meeting_ending = True
        if self.state.automation_enabled:
            self._toggle_automation()
        if self.camera_session:
            self.camera_session.stop()
        self.obs.operator_task("stop_virtual")
        self.power_button.setEnabled(False)
        self.power_button.setText("⏳ Encerrando…")
        self.mode_label.setText("Solicitando fechamento; confirme o encerramento no Zoom se solicitado.")
        if self.external_media and self.external_media.active:
            self.external_media.stop_external_media()
            return
        self._request_end_programs()

    def _request_end_programs(self):
        if not self.launcher.end_meeting():
            self._on_end_finished(None)

    def _on_end_finished(self, summary):
        self._meeting_ending = False
        complete = bool(summary and summary.complete)
        self._meeting_active = not complete
        if self._meeting_active:
            self.power_button.setText("🔴 Encerrar reunião")
        else:
            self.power_button.setText("🟢 Iniciar reunião")
        self.power_button.setEnabled(True)
        self.mode_label.setText(
            summary.message if summary else "Encerramento não confirmado. Confira os programas."
        )

    def _on_launch_progress(self, message: str) -> None:
        self.mode_label.setText(message)

    def _on_launch_finished(self, payload: object) -> None:
        if not isinstance(payload, LaunchSummary):
            self.mode_label.setText("Inicialização concluída.")
            self.power_button.setEnabled(True)
            self.power_button.setText("🟢 Iniciar reunião")
            return

        self._meeting_active = bool(payload.zoom_running or payload.jwl_running)
        if payload.obs_running:
            self.obs.ensure_virtual_camera()

        if self._meeting_active:
            self.power_button.setText("🔴 Encerrar reunião")
        else:
            self.power_button.setText("🟢 Iniciar reunião")
        self.power_button.setEnabled(True)

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

        # The launcher requests the role-specific layout service after readiness.
        # No native enumeration or physical screen math runs in this GUI slot.

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
        self.zoom_output_label.setText("Envio previsto: OBS Virtual Camera • confira a recepção no Zoom")
        self.zoom_output_label.setText("Zoom recebe: OBS Virtual Camera • transições feitas pelo OBS")
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
        if getattr(self.settings, "whatsapp_enabled", True) is False:
            return
        if not self.obs_connected or self.camera_session is None:
            return
        if self.camera_session.state == "off":
            self.camera_session.start()

    def _toggle_camera(self) -> None:
        if self.camera_session is None or not getattr(self.settings, "whatsapp_enabled", True):
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
            text = "⏹️ Parar câmera"
        elif state == "error":
            text = "📹 Tentar câmera"
        else:
            text = "📹 Iniciar câmera"
        self.camera_button.setText(text)
        self.camera_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        from pathlib import Path
        icon_root = Path(__file__).parent.parent / "resources"
        whatsapp_svg = icon_root / "whatsapp.svg"
        if whatsapp_svg.is_file():
            self.camera_button.setIcon(QIcon(str(whatsapp_svg)))
            self.camera_button.setIconSize(QSize(16, 16))
        enabled = bool(self.camera_session.supported) and not busy and \
            getattr(self.settings, "whatsapp_enabled", True)
        self.camera_button.setEnabled(enabled)
        self.camera_button.setToolTip("Câmera virtual WhatsApp: " + self.camera_session.message)
        self.camera_button.setAccessibleName("Câmera virtual WhatsApp: " + text)

    def _on_whatsapp_toggle(self, checked: bool) -> None:
        self.settings.whatsapp_enabled = checked
        if hasattr(self, "settings_service"):
            self.settings_service.save(self.settings)
        self._apply_whatsapp_visibility()
        if not checked and getattr(self, "camera_session", None):
            if self.camera_session.state in ("running", "starting"):
                self.camera_session.stop()

    def _apply_whatsapp_visibility(self) -> None:
        enabled = self.settings.whatsapp_enabled
        if hasattr(self, "whatsapp_toggle") and self.whatsapp_toggle:
            self.whatsapp_toggle.blockSignals(True)
            self.whatsapp_toggle.setChecked(enabled)
            self.whatsapp_toggle.blockSignals(False)
        if hasattr(self, "whatsapp_audio_button"):
            self.whatsapp_audio_button.setEnabled(enabled)
            self.whatsapp_audio_button.setToolTip(
                "Silencia ou libera o áudio do WhatsApp." 
                if enabled else "WhatsApp desativado no perfil atual."
            )
        if hasattr(self, "camera_button"):
            self.camera_button.setEnabled(enabled)
            self.camera_button.setToolTip(
                "Câmera virtual WhatsApp" if enabled else "Câmera desativada no perfil atual."
            )
            
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
        self.whatsapp_audio_button.setText("🔇 WhatsApp" if muted else "🔊 WhatsApp")
        self.whatsapp_audio_button.setToolTip(message)
        self.whatsapp_audio_button.blockSignals(False)
        self.mode_label.setText(message)

    def _open_virtual_camera(self, parent=None) -> None:
        self._open_settings_workspace("video", video_tab=3)

    def _open_audio_setup(self, parent=None) -> None:
        self._open_settings_workspace("audio")

    def _show_settings(self) -> None:
        self._open_settings_workspace("meeting")

    def _open_settings_workspace(self, page, *, video_tab=None):
        if self._setup_assistant is not None:
            self._setup_assistant.select_page(page)
            if video_tab is not None:
                self._setup_assistant.video_tabs.setCurrentIndex(video_tab)
            self._setup_assistant.raise_()
            return
        from meeting_assistant.ui.setup_assistant_dialog import SetupAssistantDialog

        dialog = SetupAssistantDialog(self, page=page)
        self._setup_assistant = dialog
        if video_tab is not None:
            dialog.video_tabs.setCurrentIndex(video_tab)
        dialog.exec()
        self._setup_assistant = None
        if dialog.deferred_action:
            QTimer.singleShot(0, dialog.deferred_action)
        dialog.deleteLater()
        self._refresh_yeartext_notice()

    def _on_obs_setup_finished(self, ok: bool, message: str) -> None:
        if ok:
            (self.settings.scene_background, self.settings.scene_speaker, self.settings.scene_media) = (
                STANDARD_SCENES
            )
            self.settings.obs_standard_scenes = True
            self.settings.camera_source_name = "Meeting Assistant - Câmera IP"
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
        from meeting_assistant.services.setup_assistant import validate_settings

        validate_settings(pending)
        previous_obs_config = self._obs_config()
        self.settings_service.save(pending)
        for field in fields(pending):
            setattr(self.settings, field.name, getattr(pending, field.name))
        self._startup_scene_applied = True
        self.obs.media_scene = self.settings.scene_media
        if previous_obs_config != self._obs_config():
            self._set_component_status("OBS", "pending", "○ OBS", "Reconectando…")
            self.obs.reconfigure(self._obs_config())

    def _open_setup_assistant(self):
        self._open_settings_workspace("installation")

    def _hall_capture_target(self):
        if self.external_media and self.external_media.active:
            raise ValueError("Encerre a mídia externa antes de capturar o Texto do Ano.")
        if self.state.automation_enabled and self._latest_media_active:
            raise ValueError("O detector ainda indica mídia. Pare a mídia antes de capturar o Texto do Ano.")
        return verified_hall_target(
            self._hall_window_provider(),
            self._hall_display_provider(),
            self.zoom_hall.active or self.zoom_hall.returning,
            diagnostic=self.hall_capture_diagnostic.emit,
        )

    def _open_hall_setup(self, parent):
        self._open_settings_workspace("video", video_tab=2)

    def _refresh_yeartext_notice(self):
        from datetime import datetime

        current = self.yeartext_store.current()
        outdated = current is None or current["year"] != datetime.now().year
        if outdated:
            action = "Criar foto do Texto do Ano" if current is None else "Atualizar foto do Texto do Ano"
            self.yeartext_notice.setText(f'<a href="yeartext">{action}</a>')
            self.yeartext_notice.setToolTip(self.yeartext_store.status())
        else:
            self.yeartext_notice.setText("")
            self.yeartext_notice.setToolTip(self.yeartext_store.status())

    def _on_hall_task_finished(self, action, ok, message):
        if action == "yeartext":
            self._refresh_yeartext_notice()
        if action == "virtual_camera":
            self.zoom_output_label.setText(message + " • Selecione OBS Virtual Camera no Zoom.")

    def _show_diagnostics(self) -> None:
        from meeting_assistant.ui.operator_dialog import OperatorDialog

        dialog = OperatorDialog(self)
        dialog.exec()
        dialog.deleteLater()

    def _legacy_diagnostics(self) -> None:
        display_lines = (
            "\n".join(
                f"• {'Principal' if display.primary else 'Secundária'}: "
                f"{display.name} • {display.resolution} • {display.x},{display.y}"
                for display in self.display_snapshot
            )
            or "• nenhum monitor detectado"
        )
        display_lines = (
            "\n".join(
                f"• {'Principal' if display.primary else 'Secundária'}: "
                f"{display.name} • {display.resolution} • {display.x},{display.y}"
                for display in self.display_snapshot
            )
            or "• nenhum monitor detectado"
        )
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
            "Texto do Ano": self.settings.scene_background,
            "Palco": self.settings.scene_speaker,
            "Mídia": self.settings.scene_media,
        }
        missing = [f"{label}: {scene}" for label, scene in configured.items() if scene not in self.obs_scenes]
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
        label.setProperty("state", state)
        label.setToolTip(tooltip or f"{name}: {state}")
        self._repolish(label)

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QTabWidget::pane { border: 1px solid #46546a; background: #11151c; }
            QTabBar::tab { background: #222c3b; color: #edf2fa; padding: 8px 10px; }
            QTabBar::tab:selected { background: #174a70; color: #ffffff; border-bottom: 3px solid #66c8ff; }
            QTabBar::tab:hover { background: #31465c; }
            QTabBar::tab:disabled { background: #1e2530; color: #9ca9b9; }
            QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #8da1bb;
                                   background: #1c2530; border-radius: 3px; }
            QCheckBox::indicator:checked { background: #2b92d2; border: 2px solid #b5e4ff; }
            QLineEdit { border: 1px solid #46546a; padding: 3px; border-radius: 3px; }
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
                qproperty-alignment: AlignCenter;
            }
            QLabel#StatusBadge {
                background: #1b2029;
                border: 1px solid #2c3440;
                border-radius: 6px;
                padding: 2px 4px;
                font-size: 13px;
                qproperty-alignment: AlignCenter;
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
            QPushButton#ModeButton {
                text-align: center;
                font-size: 20px;
                padding: 6px 0px;
                background: #252c36;
                border: 1px solid #3d4959;
                border-radius: 8px;
            }
            QPushButton#ModeButton:hover {
                background: #313c4a;
                border-color: #54667d;
            }
            QPushButton#ModeButton:checked {
                background: #0b5cab;
                border: 2px solid #58a6ff;
            }
            QPushButton#PausePreviewButton {
                text-align: center;
                background: #1c222b;
                border: 1px solid #2e3846;
                font-size: 11px;
                padding: 5px 8px;
                border-radius: 6px;
                color: #b0bccd;
            }
            QPushButton#PausePreviewButton:hover {
                background: #252c38;
                color: #ffffff;
                border-color: #415064;
            }
            QPushButton#ZoomMic { background: #174a70; border: 2px solid #4da6de; padding: 8px; }
            QPushButton#ZoomMic[state='live'] { background: #612c31; border-color: #f09b9b; }
            QPushButton#ZoomMic[state='muted'] { background: #16452d; border-color: #70c797; }
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
