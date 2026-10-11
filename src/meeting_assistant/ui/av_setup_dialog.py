"""Standalone AV Setup Window and Dialog for Meeting Assistant.

Provides an operator-focused single-window interface for Windows Core Audio
device management (R1), Windows 11 transmission optimizations (R2), per-app
call routing and virtual cameras (R3), and OBS Studio scene provisioning (R4).
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from meeting_assistant.services.app_audio_router import (
    check_app_routes,
    configure_all_routes,
    get_virtual_cam_status,
    launch_apps_volume_settings,
    start_obs_virtual_cam,
    stop_obs_virtual_cam,
)
from meeting_assistant.services.obs_av_provisioner import (
    DEFAULT_ZOOM_MONITOR_DEVICE_NAME,
    OBSProvisionResult,
    connect_obs,
    provision_obs_av,
)
from meeting_assistant.services.windows_core_audio import (
    ROLE_BLACKMAGIC,
    ROLE_MESA_OUT_P2,
    ROLE_V_MIC_WAPP,
    ROLE_V_MIC_ZOOM,
    ROLE_V_OUT_WAPP,
    ROLE_V_OUT_ZOOM,
    ROLE_WEBCAM_MIC,
    AudioEndpoint,
    apply_device_modifications,
    enumerate_endpoints,
    is_user_admin,
    map_project_roles,
)
from meeting_assistant.services.windows_transmission_optimizer import (
    OptimizationStatus,
    apply_elevated_os_optimizations,
    check_all_optimizations,
)
from meeting_assistant.ui.window_geometry import ScreenFitController, fit_window

logger = logging.getLogger(__name__)

# Dark Theme Stylesheet for AV Setup Dialog
AV_SETUP_STYLESHEET = """
QDialog, QMainWindow, QWidget {
    background-color: #111318;
    color: #f2f4f8;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid #282f3a;
    background: #141820;
    border-radius: 4px;
}
QTabBar::tab {
    background: #1b212c;
    color: #aeb7c4;
    padding: 10px 18px;
    font-weight: 600;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #174a70;
    color: #ffffff;
    border-bottom: 3px solid #66c8ff;
}
QTabBar::tab:hover {
    background: #253346;
    color: #ffffff;
}
QGroupBox {
    background: #171b22;
    border: 1px solid #282f3a;
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 14px;
    font-weight: bold;
    color: #92c5ff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 10px;
    background: #171b22;
    border: 1px solid #282f3a;
    border-radius: 4px;
    color: #92c5ff;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}
QPushButton {
    background-color: #222a36;
    color: #f2f4f8;
    border: 1px solid #3b4657;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #2a3443;
    border-color: #506178;
}
QPushButton:pressed {
    background-color: #18202c;
}
QPushButton:disabled {
    background-color: #15181f;
    color: #5d6778;
    border-color: #242a35;
}
QPushButton#PrimaryButton {
    background-color: #0b5cab;
    color: #ffffff;
    border: 1px solid #2b8ce6;
}
QPushButton#PrimaryButton:hover {
    background-color: #126dc5;
    border-color: #52a8ff;
}
QTableWidget {
    background-color: #141820;
    alternate-background-color: #181d26;
    gridline-color: #282f3a;
    border: 1px solid #282f3a;
    border-radius: 6px;
    color: #f2f4f8;
    selection-background-color: #1b4b72;
    selection-color: #ffffff;
}
QHeaderView::section {
    background-color: #1b212c;
    color: #aeb7c4;
    padding: 6px 8px;
    border: 1px solid #282f3a;
    font-weight: 600;
}
QLineEdit, QTextEdit {
    background-color: #161b24;
    border: 1px solid #343e4c;
    border-radius: 5px;
    color: #f2f4f8;
    padding: 6px 8px;
}
QLineEdit:focus, QTextEdit:focus {
    border-color: #2b8ce6;
}
QCheckBox {
    spacing: 8px;
    color: #f2f4f8;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #4f5d71;
    background: #1c2530;
    border-radius: 4px;
}
QCheckBox::indicator:checked {
    background: #0b5cab;
    border: 2px solid #66c8ff;
}
QLabel#StatusBadge {
    border-radius: 6px;
    padding: 4px 8px;
    font-weight: bold;
    font-size: 11px;
}
QLabel#StatusBadge[state='ok'] {
    background-color: #153924;
    color: #73e6a2;
    border: 1px solid #286743;
}
QLabel#StatusBadge[state='warning'] {
    background-color: #3b3220;
    color: #ffd166;
    border: 1px solid #705b2a;
}
QLabel#StatusBadge[state='error'] {
    background-color: #4a2528;
    color: #ff9299;
    border: 1px solid #74363d;
}
QLabel#StatusBadge[state='pending'] {
    background-color: #1c222c;
    color: #aeb7c4;
    border: 1px solid #343e4c;
}
QLabel#ReadinessBanner {
    border-radius: 8px;
    padding: 12px 18px;
    font-size: 15px;
    font-weight: 700;
    qproperty-alignment: AlignCenter;
}
QLabel#ReadinessBanner[status='ready'] {
    background-color: #153924;
    color: #73e6a2;
    border: 1px solid #286743;
}
QLabel#ReadinessBanner[status='warning'] {
    background-color: #3b3220;
    color: #ffd166;
    border: 1px solid #705b2a;
}
QLabel#ReadinessBanner[status='error'] {
    background-color: #4a2528;
    color: #ff9299;
    border: 1px solid #74363d;
}
"""


# ---------------------------------------------------------------------------
# Background Workers for Non-Blocking Operations
# ---------------------------------------------------------------------------


class GenericWorker(QThread):
    """Generic background worker thread executing a task."""

    finished_result = Signal(object)
    failed_error = Signal(str)

    def __init__(self, task_fn, *args, parent: QObject | None = None, **kwargs) -> None:
        super().__init__(parent)
        self.task_fn = task_fn
        self.args = args
        self.kwargs = kwargs

    def run(self) -> None:
        need_com = sys.platform == "win32"
        if need_com:
            try:
                import pythoncom

                pythoncom.CoInitialize()
            except Exception:
                need_com = False
        try:
            if self.isInterruptionRequested():
                return
            result = self.task_fn(*self.args, **self.kwargs)
            if not self.isInterruptionRequested():
                self.finished_result.emit(result)
        except Exception as exc:
            if not self.isInterruptionRequested():
                logger.exception("Error executing background task: %s", exc)
                self.failed_error.emit(str(exc))
        finally:
            if need_com:
                try:
                    import pythoncom

                    pythoncom.CoUninitialize()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Main AVSetupDialog Window
# ---------------------------------------------------------------------------


class AVSetupDialog(QDialog):
    """Single-window AV Setup & Windows 11 Optimization tool."""

    def __init__(
        self,
        parent: QWidget | None = None,
        settings: Any = None,
        auto_refresh: bool = True,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Preparação AV e Otimizações do Windows 11 — Meeting Assistant")
        self.setMinimumSize(940, 640)
        self.resize(1020, 720)
        self.setStyleSheet(AV_SETUP_STYLESHEET)

        self._active_workers: list[QThread] = []
        self._endpoints: list[AudioEndpoint] = []
        self._role_map: dict[str, AudioEndpoint] = {}
        self._optimizations: list[OptimizationStatus] = []
        self._routes: dict[str, dict[str, Any]] = {}
        self._cameras: dict[str, Any] = {}
        self._diagnostic_text: str = ""

        self._build_ui()
        self._fit_controller = ScreenFitController(self)
        fit_window(self)

        # Initial background scan if auto_refresh is enabled
        if auto_refresh:
            self.refresh_all_diagnostics(blocking=False)

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(10)

        # Header Title Row
        header_row = QHBoxLayout()
        header_title = QLabel("🔧 Preparação AV e Otimizações de Transmissão")
        header_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        header_row.addWidget(header_title)

        header_row.addStretch()

        self.uac_indicator = QLabel("Usuário Padrão" if not is_user_admin() else "Administrador (UAC)")
        self.uac_indicator.setObjectName("StatusBadge")
        self.uac_indicator.setProperty("state", "ok" if is_user_admin() else "pending")
        header_row.addWidget(self.uac_indicator)

        root_layout.addLayout(header_row)

        # Tab Widget
        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs, stretch=1)

        # 5 Required Tabs
        self.tab_audio = self._create_audio_tab()
        self.tab_os = self._create_os_tab()
        self.tab_routing = self._create_routing_tab()
        self.tab_obs = self._create_obs_tab()
        self.tab_diag = self._create_diagnostics_tab()

        self.tabs.addTab(self.tab_audio, "1. Dispositivos de Áudio (R1)")
        self.tabs.addTab(self.tab_os, "2. Otimizações Windows 11 (R2)")
        self.tabs.addTab(self.tab_routing, "3. Roteamento & Câmeras (R3)")
        self.tabs.addTab(self.tab_obs, "4. OBS Studio (R4)")
        self.tabs.addTab(self.tab_diag, "5. Diagnóstico & Relatório")

        # Bottom Bar
        bottom_bar = QHBoxLayout()
        self.global_status_label = QLabel("Pronto.")
        self.global_status_label.setStyleSheet("color: #9ca6b5; font-size: 12px;")
        bottom_bar.addWidget(self.global_status_label)

        bottom_bar.addStretch()

        self.refresh_all_btn = QPushButton("🔄 Atualizar Tudo")
        self.refresh_all_btn.clicked.connect(lambda: self.refresh_all_diagnostics(blocking=False))
        bottom_bar.addWidget(self.refresh_all_btn)

        close_btn = QPushButton("Fechar")
        close_btn.clicked.connect(self.close)
        bottom_bar.addWidget(close_btn)

        root_layout.addLayout(bottom_bar)

    # -----------------------------------------------------------------------
    # Tab 1: Audio Devices
    # -----------------------------------------------------------------------

    def _create_audio_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Summary Bar
        self.audio_summary_label = QLabel("Carregando dispositivos de áudio...")
        self.audio_summary_label.setStyleSheet("color: #92c5ff; font-weight: 600;")
        layout.addWidget(self.audio_summary_label)

        # Table of Audio Devices
        self.audio_table = QTableWidget()
        self.audio_table.setColumnCount(6)
        self.audio_table.setHorizontalHeaderLabels([
            "Tipo",
            "Nome Atual no Windows",
            "Nome Padronizado Recomendado",
            "Taxa de Amostragem",
            "Status",
            "Papel Identificado",
        ])
        self.audio_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.audio_table.horizontalHeader().setStretchLastSection(True)
        self.audio_table.setAlternatingRowColors(True)
        self.audio_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.audio_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.audio_table, stretch=1)

        # Action Group Box
        actions_group = QGroupBox("Ações de Padronização e Limpeza de Dispositivos (UAC)")
        actions_layout = QVBoxLayout(actions_group)

        options_row = QHBoxLayout()
        self.disable_bm_checkbox = QCheckBox("Desativar áudio HDMI da Blackmagic (evita vazamento em TVs)")
        self.disable_bm_checkbox.setChecked(True)
        options_row.addWidget(self.disable_bm_checkbox)

        self.disable_webcam_mic_checkbox = QCheckBox(
            "Desativar microfone da webcam USB (evita seleção acidental)"
        )
        self.disable_webcam_mic_checkbox.setChecked(True)
        options_row.addWidget(self.disable_webcam_mic_checkbox)

        self.restart_audiosrv_checkbox = QCheckBox("Reiniciar serviço de áudio do Windows (Audiosrv)")
        self.restart_audiosrv_checkbox.setChecked(True)
        options_row.addWidget(self.restart_audiosrv_checkbox)
        actions_layout.addLayout(options_row)

        btn_row = QHBoxLayout()
        self.rename_btn = QPushButton("🛡️ Renomear Dispositivos com Nomes do Projeto (UAC)")
        self.rename_btn.setObjectName("PrimaryButton")
        self.rename_btn.clicked.connect(self._on_rename_devices_clicked)
        btn_row.addWidget(self.rename_btn)

        self.disable_endpoints_btn = QPushButton("🚫 Desativar Dispositivos Selecionados (UAC)")
        self.disable_endpoints_btn.clicked.connect(self._on_disable_endpoints_clicked)
        btn_row.addWidget(self.disable_endpoints_btn)

        self.refresh_audio_btn = QPushButton("🔄 Atualizar Lista")
        self.refresh_audio_btn.clicked.connect(lambda: self.refresh_audio_devices(blocking=False))
        btn_row.addWidget(self.refresh_audio_btn)

        actions_layout.addLayout(btn_row)
        layout.addWidget(actions_group)

        return widget

    # -----------------------------------------------------------------------
    # Tab 2: Windows 11 OS Transmission Optimizations
    # -----------------------------------------------------------------------

    def _create_os_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        desc_label = QLabel(
            "Verificação e aplicação de parâmetros críticos do Windows 11 "
            "para transmissão contínua e sem falhas."
        )
        desc_label.setStyleSheet("color: #9ca6b5;")
        layout.addWidget(desc_label)

        # Scrollable area for optimization checklist cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        self.os_checklist_layout = QVBoxLayout(scroll_content)
        self.os_checklist_layout.setSpacing(8)
        self.os_checklist_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, stretch=1)

        # Actions
        actions_row = QHBoxLayout()
        self.apply_os_btn = QPushButton("🚀 Aplicar Otimizações Recomendadas (UAC)")
        self.apply_os_btn.setObjectName("PrimaryButton")
        self.apply_os_btn.clicked.connect(self._on_apply_os_clicked)
        actions_row.addWidget(self.apply_os_btn)

        self.refresh_os_btn = QPushButton("🔄 Verificar Novamente")
        self.refresh_os_btn.clicked.connect(lambda: self.refresh_os_optimizations(blocking=False))
        actions_row.addWidget(self.refresh_os_btn)

        layout.addLayout(actions_row)
        return widget

    # -----------------------------------------------------------------------
    # Tab 3: App Audio Routing & Virtual Cameras
    # -----------------------------------------------------------------------

    def _create_routing_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        # Zoom Card
        zoom_group = QGroupBox("Roteamento de Áudio — Zoom (Zoom.exe)")
        zoom_layout = QVBoxLayout(zoom_group)

        z_mic = QLabel(f"• Microfone (Entrada): <b>{ROLE_V_MIC_ZOOM}</b> (Cable A Output)")
        z_spk = QLabel(f"• Alto-falante (Saída): <b>{ROLE_MESA_OUT_P2}</b>")
        self.zoom_status_label = QLabel("Status: Aguardando verificação...")
        self.zoom_status_label.setStyleSheet("color: #9ca6b5;")
        zoom_layout.addWidget(z_mic)
        zoom_layout.addWidget(z_spk)
        zoom_layout.addWidget(self.zoom_status_label)
        layout.addWidget(zoom_group)

        # WhatsApp Card
        wapp_group = QGroupBox("Roteamento de Áudio — WhatsApp (WhatsApp.exe)")
        wapp_layout = QVBoxLayout(wapp_group)

        w_mic = QLabel(f"• Microfone (Entrada): <b>{ROLE_V_MIC_WAPP}</b> (Cable B Output)")
        w_spk = QLabel(f"• Alto-falante (Saída): <b>{ROLE_MESA_OUT_P2}</b>")
        self.wapp_status_label = QLabel("Status: Aguardando verificação...")
        self.wapp_status_label.setStyleSheet("color: #9ca6b5;")
        wapp_layout.addWidget(w_mic)
        wapp_layout.addWidget(w_spk)
        wapp_layout.addWidget(self.wapp_status_label)
        layout.addWidget(wapp_group)

        # Routing Action Buttons
        route_actions_row = QHBoxLayout()
        self.auto_route_btn = QPushButton("⚡ Configurar Roteamento Automático (svcl)")
        self.auto_route_btn.clicked.connect(self._on_auto_route_clicked)
        route_actions_row.addWidget(self.auto_route_btn)

        self.open_settings_btn = QPushButton("⚙️ Abrir Configurações de Volume do Windows")
        self.open_settings_btn.clicked.connect(self._on_open_windows_volume_settings)
        route_actions_row.addWidget(self.open_settings_btn)

        self.refresh_routing_btn = QPushButton("🔄 Atualizar Rotas")
        self.refresh_routing_btn.clicked.connect(lambda: self.refresh_routing_and_cameras(blocking=False))
        route_actions_row.addWidget(self.refresh_routing_btn)
        layout.addLayout(route_actions_row)

        # Virtual Cameras Card
        cam_group = QGroupBox("Câmeras Virtuais (OBS & Windows 11 Nativa)")
        cam_layout = QVBoxLayout(cam_group)

        self.obs_cam_status_label = QLabel("Câmera Virtual OBS: Verificando...")
        self.native_cam_status_label = QLabel("Câmera Virtual Nativa: Verificando...")
        cam_layout.addWidget(self.obs_cam_status_label)
        cam_layout.addWidget(self.native_cam_status_label)

        cam_btn_row = QHBoxLayout()
        self.start_obs_cam_btn = QPushButton("📹 Iniciar Câmera Virtual do OBS")
        self.start_obs_cam_btn.setObjectName("PrimaryButton")
        self.start_obs_cam_btn.clicked.connect(self._on_start_obs_virtual_cam_clicked)
        cam_btn_row.addWidget(self.start_obs_cam_btn)

        self.stop_obs_cam_btn = QPushButton("⏹️ Parar Câmera Virtual do OBS")
        self.stop_obs_cam_btn.clicked.connect(self._on_stop_obs_virtual_cam_clicked)
        cam_btn_row.addWidget(self.stop_obs_cam_btn)

        cam_layout.addLayout(cam_btn_row)
        layout.addWidget(cam_group)

        layout.addStretch()
        return widget

    # -----------------------------------------------------------------------
    # Tab 4: OBS Studio AV Provisioning
    # -----------------------------------------------------------------------

    def _create_obs_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        # Connection Settings Group
        conn_group = QGroupBox("Conexão com OBS Studio (obs-websocket)")
        conn_layout = QHBoxLayout(conn_group)

        conn_layout.addWidget(QLabel("Host:"))
        self.obs_host_input = QLineEdit("127.0.0.1")
        self.obs_host_input.setFixedWidth(120)
        conn_layout.addWidget(self.obs_host_input)

        conn_layout.addWidget(QLabel("Porta:"))
        self.obs_port_input = QLineEdit("4455")
        self.obs_port_input.setFixedWidth(70)
        conn_layout.addWidget(self.obs_port_input)

        conn_layout.addWidget(QLabel("Senha:"))
        self.obs_password_input = QLineEdit()
        self.obs_password_input.setEchoMode(QLineEdit.Password)
        if self.settings and hasattr(self.settings, "obs_password"):
            self.obs_password_input.setText(self.settings.obs_password or "")
        conn_layout.addWidget(self.obs_password_input)

        self.test_obs_btn = QPushButton("🔌 Testar Conexão")
        self.test_obs_btn.clicked.connect(self._on_test_obs_connection_clicked)
        conn_layout.addWidget(self.test_obs_btn)
        layout.addWidget(conn_group)

        # Provisioning Card
        prov_group = QGroupBox("Provisionamento Automatizado de Cenas, Fontes e Áudio")
        prov_layout = QVBoxLayout(prov_group)

        desc = QLabel(
            "Cria e atualiza de forma idempotente as cenas 'Palco', 'Mídias', 'Texto do Ano', "
            "o barramento de áudio 'Meeting Assistant - Áudio', "
            "configura a captura HWND do JW Library na segunda tela, "
            "desativa fontes de captura de monitor para impedir eco no Zoom, "
            "e direciona o áudio de monitoramento para o Zoom."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aeb7c4;")
        prov_layout.addWidget(desc)

        mon_row = QHBoxLayout()
        mon_row.addWidget(QLabel("Dispositivo de Monitoramento (Zoom):"))
        self.obs_monitor_combo = QComboBox()
        self.obs_monitor_combo.addItem(f"{DEFAULT_ZOOM_MONITOR_DEVICE_NAME} (Recomendado)", "")
        mon_row.addWidget(self.obs_monitor_combo, stretch=1)
        prov_layout.addLayout(mon_row)

        self.provision_obs_btn = QPushButton("🚀 Provisionar Cenas e Fontes do OBS")
        self.provision_obs_btn.setObjectName("PrimaryButton")
        self.provision_obs_btn.clicked.connect(self._on_provision_obs_clicked)
        prov_layout.addWidget(self.provision_obs_btn)

        layout.addWidget(prov_group)

        # Log Result Box
        layout.addWidget(QLabel("Resultado do Provisionamento:"))
        self.obs_log_text = QTextEdit()
        self.obs_log_text.setReadOnly(True)
        self.obs_log_text.setPlaceholderText("Os logs do provisionamento aparecerão aqui...")
        layout.addWidget(self.obs_log_text, stretch=1)

        return widget

    # -----------------------------------------------------------------------
    # Tab 5: Full Diagnostics & Readiness Report
    # -----------------------------------------------------------------------

    def _create_diagnostics_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Readiness Banner
        self.readiness_banner = QLabel("VERIFICANDO PRONTIDÃO DA REUNIÃO...")
        self.readiness_banner.setObjectName("ReadinessBanner")
        self.readiness_banner.setProperty("status", "warning")
        layout.addWidget(self.readiness_banner)

        # Diagnostic Details Text Box
        self.diag_text_box = QTextEdit()
        self.diag_text_box.setReadOnly(True)
        self.diag_text_box.setFont(QFont("Consolas", 10))
        layout.addWidget(self.diag_text_box, stretch=1)

        # Action Buttons
        btn_row = QHBoxLayout()
        self.run_full_diag_btn = QPushButton("🔍 Executar Verificação Completa")
        self.run_full_diag_btn.setObjectName("PrimaryButton")
        self.run_full_diag_btn.clicked.connect(lambda: self.run_full_diagnostic(blocking=False))
        btn_row.addWidget(self.run_full_diag_btn)

        self.copy_diag_btn = QPushButton("📋 Copiar Relatório")
        self.copy_diag_btn.clicked.connect(self._on_copy_diagnostic_clicked)
        btn_row.addWidget(self.copy_diag_btn)

        self.save_diag_btn = QPushButton("💾 Salvar Relatório em Arquivo…")
        self.save_diag_btn.clicked.connect(self._on_save_diagnostic_clicked)
        btn_row.addWidget(self.save_diag_btn)

        layout.addLayout(btn_row)
        return widget

    # -----------------------------------------------------------------------
    # Refresh & Diagnostic Execution (Non-Blocking & Blocking)
    # -----------------------------------------------------------------------

    def refresh_all_diagnostics(self, blocking: bool = False) -> None:
        """Trigger update across all 4 sub-domains."""
        self.refresh_audio_devices(blocking=blocking)
        self.refresh_os_optimizations(blocking=blocking)
        self.refresh_routing_and_cameras(blocking=blocking)
        self.run_full_diagnostic(blocking=blocking)

    def refresh_audio_devices(self, blocking: bool = False) -> None:
        """Scan audio endpoints."""
        self.audio_summary_label.setText("Enumerando endpoints de áudio...")

        def _task():
            eps = enumerate_endpoints()
            roles = map_project_roles(eps)
            return eps, roles

        if blocking:
            eps, roles = _task()
            self._on_audio_scan_finished((eps, roles))
        else:
            worker = GenericWorker(_task, parent=self)
            worker.finished_result.connect(self._on_audio_scan_finished)
            worker.failed_error.connect(lambda err: self.audio_summary_label.setText(f"Erro: {err}"))
            self._start_worker(worker)

    def _on_audio_scan_finished(self, result: tuple[list[AudioEndpoint], dict[str, AudioEndpoint]]) -> None:
        eps, roles = result
        self._endpoints = eps
        self._role_map = roles

        active_count = sum(1 for ep in eps if ep.is_active)
        rate_48k_count = sum(1 for ep in eps if ep.sample_rate_hz == 48000)
        self.audio_summary_label.setText(
            f"Total: {len(eps)} dispositivos | Ativos: {active_count} | 48 kHz: {rate_48k_count} | "
            f"Papéis Identificados: {len(roles)}/{len(map_project_roles([])) if not roles else len(roles)}"
        )

        # Populate combo in OBS tab
        self.obs_monitor_combo.clear()
        self.obs_monitor_combo.addItem(f"{DEFAULT_ZOOM_MONITOR_DEVICE_NAME} (Padrão)", "")
        for ep in eps:
            if ep.flow == "eRender":
                self.obs_monitor_combo.addItem(f"{ep.friendly_name} ({ep.sample_rate_hz} Hz)", ep.id)

        # Select Cable A if mapped
        cable_a = roles.get(ROLE_V_OUT_ZOOM)
        if cable_a:
            for idx in range(self.obs_monitor_combo.count()):
                if self.obs_monitor_combo.itemData(idx) == cable_a.id:
                    self.obs_monitor_combo.setCurrentIndex(idx)
                    break

        # Populate Table
        self.audio_table.setRowCount(len(eps))
        for row, ep in enumerate(eps):
            # Tipo
            tipo = "🔊 Reprodução" if ep.flow == "eRender" else "🎙️ Gravação"
            self.audio_table.setItem(row, 0, QTableWidgetItem(tipo))

            # Nome Atual
            self.audio_table.setItem(row, 1, QTableWidgetItem(ep.friendly_name))

            # Nome Padronizado
            recommended_name = ep.detected_role or "-"
            self.audio_table.setItem(row, 2, QTableWidgetItem(recommended_name))

            # Taxa
            rate_str = f"{ep.sample_rate_hz} Hz"
            rate_item = QTableWidgetItem(rate_str)
            if ep.sample_rate_hz == 48000:
                rate_item.setForeground(QColor("#73e6a2"))
            elif ep.sample_rate_hz > 0:
                rate_item.setForeground(QColor("#ffd166"))
            self.audio_table.setItem(row, 3, rate_item)

            # Status
            status_str = "Ativo" if ep.is_active else "Desativado"
            status_item = QTableWidgetItem(status_str)
            status_item.setForeground(QColor("#73e6a2") if ep.is_active else QColor("#ff9299"))
            self.audio_table.setItem(row, 4, status_item)

            # Papel
            self.audio_table.setItem(row, 5, QTableWidgetItem(ep.detected_role or "Outro"))

        self.audio_table.resizeColumnsToContents()

    def refresh_os_optimizations(self, blocking: bool = False) -> None:
        """Scan OS transmission optimizations."""
        if blocking:
            opts = check_all_optimizations()
            self._on_os_scan_finished(opts)
        else:
            worker = GenericWorker(check_all_optimizations, parent=self)
            worker.finished_result.connect(self._on_os_scan_finished)
            self._start_worker(worker)

    def _on_os_scan_finished(self, opts: list[OptimizationStatus]) -> None:
        self._optimizations = opts

        # Clear existing checklist widgets
        while self.os_checklist_layout.count() > 1:
            child = self.os_checklist_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Add each item card
        for opt in opts:
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background-color: #171b22; border: 1px solid #282f3a; "
                "border-radius: 6px; padding: 6px; }"
            )
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)

            left_box = QVBoxLayout()
            title_lbl = QLabel(opt.name)
            title_lbl.setFont(QFont("Segoe UI", 12, QFont.Bold))
            title_lbl.setStyleSheet("color: #f2f4f8;")
            desc_lbl = QLabel(opt.description)
            desc_lbl.setStyleSheet("color: #9ca6b5; font-size: 11px;")
            desc_lbl.setWordWrap(True)

            val_str = f"Valor atual: <b>{opt.current_value}</b> | Recomendado: <b>{opt.recommended_value}</b>"
            val_lbl = QLabel(val_str)
            val_lbl.setStyleSheet("color: #aeb7c4; font-size: 11px;")

            left_box.addWidget(title_lbl)
            left_box.addWidget(desc_lbl)
            left_box.addWidget(val_lbl)
            card_layout.addLayout(left_box, stretch=1)

            # Status Badge
            badge = QLabel("OK" if opt.is_optimal else "PENDENTE")
            badge.setObjectName("StatusBadge")
            badge.setProperty("state", "ok" if opt.is_optimal else "warning")
            badge.setFixedWidth(80)
            badge.setAlignment(Qt.AlignCenter)
            card_layout.addWidget(badge)

            self.os_checklist_layout.insertWidget(self.os_checklist_layout.count() - 1, card)

    def refresh_routing_and_cameras(self, blocking: bool = False) -> None:
        """Scan routing and camera states."""

        def _task():
            routes = check_app_routes()
            cams = get_virtual_cam_status(obs_client=None)
            return routes, cams

        if blocking:
            routes, cams = _task()
            self._on_routing_scan_finished((routes, cams))
        else:
            worker = GenericWorker(_task, parent=self)
            worker.finished_result.connect(self._on_routing_scan_finished)
            self._start_worker(worker)

    def _on_routing_scan_finished(self, result: tuple[dict[str, Any], dict[str, Any]]) -> None:
        routes, cams = result
        self._routes = routes
        self._cameras = cams

        # Zoom status
        z_info = routes.get("Zoom.exe", {})
        z_status = z_info.get("status", "unconfigured")
        z_sessions = z_info.get("active_sessions", [])
        self.zoom_status_label.setText(
            f"Status: {z_status.upper()} | Sessões ativas de áudio: {len(z_sessions)} | "
            f"Detalhes: {z_info.get('details', '')}"
        )

        # WhatsApp status
        w_info = routes.get("WhatsApp.exe", {})
        w_status = w_info.get("status", "unconfigured")
        w_sessions = w_info.get("active_sessions", [])
        self.wapp_status_label.setText(
            f"Status: {w_status.upper()} | Sessões ativas de áudio: {len(w_sessions)} | "
            f"Detalhes: {w_info.get('details', '')}"
        )

        # Cameras
        obs_cam = cams.get("obs_virtual_cam", {})
        obs_active = obs_cam.get("active", False)
        self.obs_cam_status_label.setText(
            f"Câmera Virtual OBS: {'🟢 EM EXECUÇÃO' if obs_active else '⚪ PARADA / NÃO ATIVADA'}"
        )

        nat_cam = cams.get("native_virtual_cam", {})
        nat_sup = nat_cam.get("supported", False)
        nat_status = "🟢 SUPORTADA" if nat_sup else f"⚪ {nat_cam.get('reason')}"
        self.native_cam_status_label.setText(
            f"Câmera Virtual Nativa (Win11 MF): {nat_status}"
        )

    def run_full_diagnostic(self, blocking: bool = False) -> None:
        """Assemble complete diagnostic and update readiness."""
        self.global_status_label.setText("Executando verificação completa...")

        def _task():
            eps = enumerate_endpoints()
            roles = map_project_roles(eps)
            opts = check_all_optimizations()
            routes = check_app_routes()
            cams = get_virtual_cam_status(obs_client=None)

            # Test OBS connection if possible
            obs_conn_ok = False
            obs_scenes: list[str] = []
            try:
                host = self.obs_host_input.text().strip() or "127.0.0.1"
                port = int(self.obs_port_input.text().strip() or "4455")
                pwd = self.obs_password_input.text()
                client = connect_obs(host=host, port=port, password=pwd, timeout=1.5)
                res = client.send("GetSceneList", raw=True)
                obs_scenes = [s["sceneName"] for s in res.get("scenes", [])]
                obs_conn_ok = True
                if hasattr(client, "disconnect"):
                    client.disconnect()
            except Exception:
                obs_conn_ok = False

            return {
                "endpoints": eps,
                "roles": roles,
                "optimizations": opts,
                "routes": routes,
                "cameras": cams,
                "obs_connected": obs_conn_ok,
                "obs_scenes": obs_scenes,
            }

        if blocking:
            data = _task()
            self._on_full_diag_finished(data)
        else:
            worker = GenericWorker(_task, parent=self)
            worker.finished_result.connect(self._on_full_diag_finished)
            self._start_worker(worker)

    def _on_full_diag_finished(self, data: dict[str, Any]) -> None:
        opts: list[OptimizationStatus] = data["optimizations"]
        opts_ok = sum(1 for o in opts if o.is_optimal)
        all_opts_ok = opts_ok == len(opts)

        roles: dict[str, AudioEndpoint] = data["roles"]
        cable_a = roles.get(ROLE_V_OUT_ZOOM)
        cable_b = roles.get(ROLE_V_OUT_WAPP)

        obs_connected = data["obs_connected"]

        # Assess readiness
        if all_opts_ok and cable_a and cable_b:
            self.readiness_banner.setText("✅ PRONTO PARA TRANSMISSÃO — SISTEMA E ÁUDIO CONFORMES")
            self.readiness_banner.setProperty("status", "ready")
        elif cable_a and cable_b:
            self.readiness_banner.setText(
                "⚠️ ATENÇÃO — DISPOSITIVOS IDENTIFICADOS, MAS OTIMIZAÇÕES PENDENTES"
            )
            self.readiness_banner.setProperty("status", "warning")
        else:
            self.readiness_banner.setText(
                "❌ CONFIGURAÇÃO NECESSÁRIA — CABOS VIRTUAIS OU OTIMIZAÇÕES AUSENTES"
            )
            self.readiness_banner.setProperty("status", "error")

        self.readiness_banner.style().unpolish(self.readiness_banner)
        self.readiness_banner.style().polish(self.readiness_banner)

        # Build formatted report text
        lines = [
            "=" * 70,
            " RELATÓRIO DE DIAGNÓSTICO AV — MEETING ASSISTANT",
            "=" * 70,
            "",
            f"1. DISPOSITIVOS DE ÁUDIO ({len(data['endpoints'])} detectados):",
        ]
        for role_name, ep in roles.items():
            st_text = "Ativo" if ep.is_active else "Desativado"
            lines.append(f"   • [{role_name}]: {ep.friendly_name} ({ep.sample_rate_hz} Hz, {st_text})")

        lines.extend([
            "",
            f"2. OTIMIZAÇÕES DO WINDOWS 11 ({opts_ok}/{len(opts)} ideais):",
        ])
        for opt in opts:
            mark = "OK" if opt.is_optimal else "PENDENTE"
            c_val = opt.current_value
            r_val = opt.recommended_value
            lines.append(f"   [{mark:8s}] {opt.name}: atual={c_val} (recomendado={r_val})")

        z_rt = data["routes"].get("Zoom.exe", {})
        w_rt = data["routes"].get("WhatsApp.exe", {})
        obs_c = "Ativa" if data["cameras"].get("obs_virtual_cam", {}).get("active") else "Inativa"
        nat_c = (
            "Suportada"
            if data["cameras"].get("native_virtual_cam", {}).get("supported")
            else "Não suportada"
        )
        lines.extend([
            "",
            "3. ROTEAMENTO DE APLICATIVOS & CÂMERAS:",
            f"   • Zoom: {z_rt.get('status', 'unconfigured')} ({z_rt.get('details', '')})",
            f"   • WhatsApp: {w_rt.get('status', 'unconfigured')} ({w_rt.get('details', '')})",
            f"   • Câmera OBS: {obs_c}",
            f"   • Câmera Nativa: {nat_c}",
            "",
            "4. OBS STUDIO:",
            f"   • Conexão obs-websocket: {'Conectado' if obs_connected else 'Desconectado / Indisponível'}",
        ])
        if obs_connected:
            lines.append(f"   • Cenas encontradas: {', '.join(data['obs_scenes'])}")

        lines.append("\n" + "=" * 70)

        self._diagnostic_text = "\n".join(lines)
        self.diag_text_box.setText(self._diagnostic_text)
        self.global_status_label.setText("Diagnóstico concluído.")

    # -----------------------------------------------------------------------
    # Action Slots
    # -----------------------------------------------------------------------

    def _on_rename_devices_clicked(self, blocking: bool = False) -> None:
        """Trigger device renaming script generation and UAC execution."""
        renames: dict[str, str] = {}
        for role_name, ep in self._role_map.items():
            if ep.friendly_name != role_name:
                renames[ep.id] = role_name

        disables: list[str] = []
        if self.disable_bm_checkbox.isChecked():
            bm_ep = self._role_map.get(ROLE_BLACKMAGIC)
            if bm_ep and bm_ep.is_active:
                disables.append(bm_ep.id)

        if self.disable_webcam_mic_checkbox.isChecked():
            wc_ep = self._role_map.get(ROLE_WEBCAM_MIC)
            if wc_ep and wc_ep.is_active:
                disables.append(wc_ep.id)

        if not renames and not disables:
            QMessageBox.information(
                self,
                "Nenhuma Ação Necessária",
                "Todos os dispositivos identificados já possuem os nomes corretos.",
            )
            return

        restart_srv = self.restart_audiosrv_checkbox.isChecked()
        self.global_status_label.setText("Executando modificações de dispositivos (UAC)...")

        def _task():
            return apply_device_modifications(
                renames=renames,
                disables=disables,
                restart_audiosrv=restart_srv,
            )

        def _on_done(res: tuple[bool, str]):
            ok, msg = res
            if ok:
                QMessageBox.information(self, "Sucesso", msg)
            else:
                QMessageBox.warning(self, "Aviso / Erro", msg)
            self.refresh_audio_devices(blocking=blocking)

        if blocking:
            res = _task()
            _on_done(res)
            return

        worker = GenericWorker(_task, parent=self)
        worker.finished_result.connect(_on_done)
        self._start_worker(worker)

    def _on_disable_endpoints_clicked(self, blocking: bool = False) -> None:
        """Disable specifically selected endpoints (Blackmagic HDMI & Webcam mic)."""
        disables: list[str] = []
        if self.disable_bm_checkbox.isChecked():
            bm_ep = self._role_map.get(ROLE_BLACKMAGIC)
            if bm_ep:
                disables.append(bm_ep.id)

        if self.disable_webcam_mic_checkbox.isChecked():
            wc_ep = self._role_map.get(ROLE_WEBCAM_MIC)
            if wc_ep:
                disables.append(wc_ep.id)

        if not disables:
            QMessageBox.information(
                self,
                "Nenhum Dispositivo Selecionado",
                "Marque a opção da Blackmagic ou da Webcam para desativação.",
            )
            return

        def _task():
            return apply_device_modifications(
                renames={},
                disables=disables,
                restart_audiosrv=self.restart_audiosrv_checkbox.isChecked(),
            )

        def _on_done(res: tuple[bool, str]):
            ok, msg = res
            if ok:
                QMessageBox.information(self, "Sucesso", f"Dispositivos desativados: {msg}")
            else:
                QMessageBox.warning(self, "Aviso / Erro", msg)
            self.refresh_audio_devices(blocking=blocking)

        if blocking:
            res = _task()
            _on_done(res)
            return

        worker = GenericWorker(_task, parent=self)
        worker.finished_result.connect(_on_done)
        self._start_worker(worker)

    def _on_apply_os_clicked(self, blocking: bool = False) -> None:
        """Apply recommended OS optimizations via UAC."""
        self.global_status_label.setText("Aplicando otimizações do Windows 11...")

        def _task():
            return apply_elevated_os_optimizations()

        def _on_done(res: tuple[bool, str]):
            ok, msg = res
            if ok:
                QMessageBox.information(self, "Otimizações Aplicadas", msg)
            else:
                QMessageBox.warning(self, "Aviso / Falha", msg)
            self.refresh_os_optimizations(blocking=blocking)

        if blocking:
            res = _task()
            _on_done(res)
            return

        worker = GenericWorker(_task, parent=self)
        worker.finished_result.connect(_on_done)
        self._start_worker(worker)

    def _on_auto_route_clicked(self, blocking: bool = False) -> None:
        """Attempt automated per-app routing."""
        zoom_mic = self._role_map.get(ROLE_V_MIC_ZOOM)
        zoom_spk = self._role_map.get(ROLE_MESA_OUT_P2)
        wapp_mic = self._role_map.get(ROLE_V_MIC_WAPP)
        wapp_spk = self._role_map.get(ROLE_MESA_OUT_P2)

        def _task():
            return configure_all_routes(
                zoom_render_id=zoom_spk.id if zoom_spk else None,
                zoom_capture_id=zoom_mic.id if zoom_mic else None,
                whatsapp_render_id=wapp_spk.id if wapp_spk else None,
                whatsapp_capture_id=wapp_mic.id if wapp_mic else None,
            )

        def _on_done(results: dict[str, Any]):
            details = []
            for app, (ok, msg) in results.items():
                details.append(f"{app}: {'OK' if ok else 'Falha'} ({msg})")
            QMessageBox.information(self, "Roteamento Automático", "\n".join(details))
            self.refresh_routing_and_cameras(blocking=blocking)

        if blocking:
            res = _task()
            _on_done(res)
            return

        worker = GenericWorker(_task, parent=self)
        worker.finished_result.connect(_on_done)
        self._start_worker(worker)

    def _on_open_windows_volume_settings(self) -> None:
        ok, msg = launch_apps_volume_settings()
        if not ok:
            QMessageBox.warning(self, "Erro", msg)

    def _on_start_obs_virtual_cam_clicked(self, blocking: bool = False) -> None:
        self.global_status_label.setText("Iniciando Câmera Virtual do OBS...")

        def _task():
            host = self.obs_host_input.text().strip() or "127.0.0.1"
            port = int(self.obs_port_input.text().strip() or "4455")
            pwd = self.obs_password_input.text()
            client = connect_obs(host=host, port=port, password=pwd, timeout=3.0)
            return start_obs_virtual_cam(client)

        def _on_done(res: tuple[bool, str]):
            ok, msg = res
            if ok:
                QMessageBox.information(self, "Câmera Virtual", msg)
            else:
                QMessageBox.warning(self, "Falha na Câmera Virtual", msg)
            self.refresh_routing_and_cameras(blocking=blocking)

        if blocking:
            res = _task()
            _on_done(res)
            return

        worker = GenericWorker(_task, parent=self)
        worker.finished_result.connect(_on_done)
        self._start_worker(worker)

    def _on_stop_obs_virtual_cam_clicked(self, blocking: bool = False) -> None:
        self.global_status_label.setText("Parando Câmera Virtual do OBS...")

        def _task():
            host = self.obs_host_input.text().strip() or "127.0.0.1"
            port = int(self.obs_port_input.text().strip() or "4455")
            pwd = self.obs_password_input.text()
            client = connect_obs(host=host, port=port, password=pwd, timeout=3.0)
            return stop_obs_virtual_cam(client)

        def _on_done(res: tuple[bool, str]):
            ok, msg = res
            if ok:
                QMessageBox.information(self, "Câmera Virtual", msg)
            else:
                QMessageBox.warning(self, "Aviso", msg)
            self.refresh_routing_and_cameras(blocking=blocking)

        if blocking:
            res = _task()
            _on_done(res)
            return

        worker = GenericWorker(_task, parent=self)
        worker.finished_result.connect(_on_done)
        self._start_worker(worker)

    def _on_test_obs_connection_clicked(self, blocking: bool = False) -> None:
        host = self.obs_host_input.text().strip() or "127.0.0.1"
        port = int(self.obs_port_input.text().strip() or "4455")
        pwd = self.obs_password_input.text()

        def _task():
            client = connect_obs(host=host, port=port, password=pwd, timeout=2.0)
            version = client.send("GetVersion", raw=True)
            ver_str = (
                version.get("obsVersion", "desconhecida")
                if isinstance(version, dict)
                else "desconhecida"
            )
            return True, f"Conexão estabelecida com sucesso! OBS Studio versão {ver_str}."

        def _on_done(res: tuple[bool, str]):
            ok, msg = res
            QMessageBox.information(self, "Teste OBS", msg)

        def _on_fail(err: str):
            QMessageBox.warning(self, "Falha na Conexão", f"Não foi possível conectar ao OBS: {err}")

        if blocking:
            try:
                res = _task()
                _on_done(res)
            except Exception as exc:
                _on_fail(str(exc))
            return

        worker = GenericWorker(_task, parent=self)
        worker.finished_result.connect(_on_done)
        worker.failed_error.connect(_on_fail)
        self._start_worker(worker)

    def _on_provision_obs_clicked(self, blocking: bool = False) -> None:
        """Execute full OBS provisioning."""
        host = self.obs_host_input.text().strip() or "127.0.0.1"
        port = int(self.obs_port_input.text().strip() or "4455")
        pwd = self.obs_password_input.text()
        zoom_cable_id = self.obs_monitor_combo.currentData() or ""

        self.provision_obs_btn.setEnabled(False)
        self.obs_log_text.setText("Iniciando provisionamento do OBS Studio...")

        def _task():
            return provision_obs_av(
                host=host,
                port=port,
                password=pwd,
                zoom_cable_id=zoom_cable_id,
                zoom_cable_name=DEFAULT_ZOOM_MONITOR_DEVICE_NAME,
            )

        def _on_done(res: OBSProvisionResult):
            self.provision_obs_btn.setEnabled(True)
            mon_st = "Configurado" if res.monitoring_device_set else "Não configurado"
            sc_st = ", ".join(res.scenes_created) if res.scenes_created else "Nenhuma nova cena"
            jwl_st = "Configurada" if res.jwl_hwnd_capture_configured else "Pendente/Falha"
            log_lines = [
                f"Status Geral: {'✅ SUCESSO' if res.success else '⚠️ CONCLUÍDO COM AVISOS'}",
                f"Dispositivo de Monitoramento: {mon_st}",
                f"Cenas Criadas/Verificadas: {sc_st}",
                f"Captura HWND JW Library: {jwl_st}",
                f"Capturas de Monitor Desativadas: {len(res.display_captures_disabled)}",
                f"Fontes de Áudio de Processos: {', '.join(res.process_audio_configured)}",
            ]
            if res.errors:
                log_lines.append("\nAvisos / Erros:")
                for err in res.errors:
                    log_lines.append(f"  • {err}")

            self.obs_log_text.setText("\n".join(log_lines))
            if res.success:
                QMessageBox.information(
                    self, "Provisionamento OBS", "Cenas e fontes do OBS provisionadas com sucesso!"
                )
            else:
                QMessageBox.warning(
                    self, "Provisionamento OBS", "Provisionamento concluído com observações."
                )

        def _on_fail(err: str):
            self.provision_obs_btn.setEnabled(True)
            self.obs_log_text.setText(f"Erro crítico no provisionamento: {err}")
            QMessageBox.critical(self, "Erro OBS", f"Falha ao executar provisionamento: {err}")

        if blocking:
            try:
                res = _task()
                _on_done(res)
            except Exception as exc:
                _on_fail(str(exc))
            return

        worker = GenericWorker(_task, parent=self)
        worker.finished_result.connect(_on_done)
        worker.failed_error.connect(_on_fail)
        self._start_worker(worker)

    def _on_copy_diagnostic_clicked(self) -> None:
        if not self._diagnostic_text:
            self.run_full_diagnostic(blocking=True)
        clipboard = QApplication.clipboard()
        clipboard.setText(self._diagnostic_text)
        QMessageBox.information(
            self, "Copiado", "Relatório de diagnóstico copiado para a Área de Transferência com sucesso!"
        )

    def _on_save_diagnostic_clicked(self) -> None:
        if not self._diagnostic_text:
            self.run_full_diagnostic(blocking=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar Relatório de Diagnóstico",
            "diagnostico_av_meeting_assistant.txt",
            "Arquivos de Texto (*.txt);;Markdown (*.md);;Todos os Arquivos (*.*)",
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self._diagnostic_text)
                QMessageBox.information(self, "Salvo", f"Relatório salvo em: {path}")
            except Exception as exc:
                QMessageBox.critical(self, "Erro ao Salvar", str(exc))

    def _start_worker(self, worker: QThread) -> None:
        """Track and start a worker thread."""
        self._active_workers.append(worker)
        worker.finished.connect(lambda: self._on_worker_finished(worker))
        worker.start()

    def _on_worker_finished(self, worker: QThread) -> None:
        if worker in self._active_workers:
            self._active_workers.remove(worker)
        worker.deleteLater()

    def closeEvent(self, event) -> None:
        """Ensure running background workers terminate gracefully without unsafe aborts."""
        for worker in list(self._active_workers):
            if worker.isRunning():
                worker.requestInterruption()
                try:
                    worker.finished_result.disconnect()
                except Exception:
                    pass
                try:
                    worker.failed_error.disconnect()
                except Exception:
                    pass
                worker.wait(400)
        super().closeEvent(event)


# Alias AVSetupWindow to AVSetupDialog
AVSetupWindow = AVSetupDialog
