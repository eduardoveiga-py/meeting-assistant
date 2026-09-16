from __future__ import annotations

from PySide6.QtCore import Qt
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
    QVBoxLayout,
    QWidget,
)

from meeting_assistant.core.state import AppState, OperatingMode
from meeting_assistant.services.obs_controller import ObsConnectionConfig, ObsController
from meeting_assistant.services.settings import AppSettings, SettingsService
from meeting_assistant.ui.settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(
        self,
        state: AppState,
        settings: AppSettings,
        settings_service: SettingsService,
        obs_controller: ObsController,
        app_icon: QIcon | None = None,
    ) -> None:
        super().__init__()
        self.state = state
        self.settings = settings
        self.settings_service = settings_service
        self.obs = obs_controller
        self.app_icon = app_icon or QIcon()
        self.obs_connected = False
        self.obs_scenes: list[str] = []
        self.current_obs_scene: str | None = None

        self.setWindowIcon(self.app_icon)
        self.setWindowTitle("Meeting Assistant 3.0")
        self.resize(520, 620)
        self.setMinimumSize(470, 560)
        if self.state.simulation_enabled:
            self.setWindowTitle("Meeting Assistant 3.0 — Modo de Simulação")

        self._build_ui()
        self._apply_style()
        self._connect_obs_signals()
        self._refresh_mode()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

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
            status_grid.addWidget(label, index // 2, index % 2)
        root.addLayout(status_grid)

        controls_card = QFrame()
        controls_card.setObjectName("Card")
        controls = QVBoxLayout(controls_card)
        controls.setContentsMargins(10, 9, 10, 10)
        controls.setSpacing(6)

        controls.addWidget(self._section_label("SAÍDA DO SALÃO"))

        mode_grid = QGridLayout()
        mode_grid.setHorizontalSpacing(6)
        mode_grid.setVerticalSpacing(6)
        self.mode_buttons: dict[OperatingMode, QPushButton] = {}
        button_specs = [
            (OperatingMode.BACKGROUND, "📖 Fundo", 0, 0),
            (OperatingMode.SPEAKER, "🎤 Orador", 0, 1),
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
        controls.addWidget(self.auto_button)

        panic = QPushButton("🛟 Cena segura")
        panic.setObjectName("DangerButton")
        panic.clicked.connect(lambda: self._select_mode(OperatingMode.BACKGROUND))
        controls.addWidget(panic)

        controls.addSpacing(2)
        controls.addWidget(self._section_label("SISTEMA"))

        system_grid = QGridLayout()
        system_grid.setHorizontalSpacing(6)
        diagnostics = QPushButton("🩺 Verificar")
        diagnostics.clicked.connect(self._show_diagnostics)
        settings_button = QPushButton("⚙️ Ajustes")
        settings_button.clicked.connect(self._show_settings)
        system_grid.addWidget(diagnostics, 0, 0)
        system_grid.addWidget(settings_button, 0, 1)
        controls.addLayout(system_grid)

        controls.addSpacing(2)
        controls.addWidget(self._section_label("RETORNO — SALÃO"))

        preview_row = QHBoxLayout()
        preview_row.addStretch()
        self.preview = QLabel("Conectando ao OBS…\n16:9")
        self.preview.setObjectName("Preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(280, 158)
        self.preview.setMaximumSize(320, 180)
        preview_row.addWidget(self.preview)
        preview_row.addStretch()
        controls.addLayout(preview_row)

        self.zoom_output_label = QLabel(
            "Zoom recebe: OBS Virtual Camera • saída independente"
        )
        self.zoom_output_label.setObjectName("ZoomOutputLabel")
        self.zoom_output_label.setAlignment(Qt.AlignCenter)
        self.zoom_output_label.setWordWrap(True)
        controls.addWidget(self.zoom_output_label)

        self.mode_label = QLabel()
        self.mode_label.setObjectName("ModeLabel")
        controls.addWidget(self.mode_label)

        root.addWidget(controls_card, 1)

        footer = QLabel("Painel compacto • OBS é a fonte de verdade das cenas")
        footer.setObjectName("Footer")
        footer.setAlignment(Qt.AlignCenter)
        root.addWidget(footer)

        self.setCentralWidget(central)

    def _connect_obs_signals(self) -> None:
        self.obs.connected_changed.connect(self._on_obs_connected)
        self.obs.scenes_changed.connect(self._on_obs_scenes)
        self.obs.scene_changed.connect(self._on_obs_scene)
        self.obs.error.connect(self._on_obs_error)

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def _select_mode(self, mode: OperatingMode) -> None:
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

    def _toggle_automation(self) -> None:
        self.state.automation_enabled = not self.state.automation_enabled
        if self.state.automation_enabled:
            self.automation_badge.setText("AUTOMAÇÃO ATIVA")
            self.automation_badge.setProperty("active", True)
            self.auto_button.setText("⏸️ Pausar automação")
        else:
            self.automation_badge.setText("AUTOMAÇÃO PAUSADA")
            self.automation_badge.setProperty("active", False)
            self.auto_button.setText("🚥 Ativar automação")
        self._repolish(self.automation_badge)

    def _on_obs_connected(self, connected: bool, message: str) -> None:
        self.obs_connected = connected
        if connected:
            self._set_component_status("OBS", "ok", "● OBS", message)
            self.preview.setText("OBS conectado\npreview real no próximo teste")
        else:
            self.current_obs_scene = None
            self._set_component_status("OBS", "error", "● OBS", message)
            self.preview.setText("OBS desconectado\n16:9")
            self.mode_label.setText("Salão: aguardando OBS")

    def _on_obs_scenes(self, scenes: list[str]) -> None:
        self.obs_scenes = scenes
        self.status_labels["OBS"].setToolTip(
            f"OBS conectado • {len(scenes)} cena(s) encontrada(s)"
        )

    def _on_obs_scene(self, scene_name: str) -> None:
        self.current_obs_scene = scene_name
        mode = self._mode_for_scene(scene_name)
        if mode is not None:
            self.state.set_mode(mode)
        self._refresh_mode()

    def _on_obs_error(self, message: str) -> None:
        self.mode_label.setText(message)

    def _show_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.obs_scenes, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        dialog.apply_to(self.settings)
        self.settings_service.save(self.settings)
        self._set_component_status("OBS", "pending", "○ OBS", "Reconectando…")
        self.obs.reconfigure(self._obs_config())

    def _show_diagnostics(self) -> None:
        if not self.obs_connected:
            QMessageBox.information(
                self,
                "Verificação do sistema",
                "OBS WebSocket não está conectado.\n\n"
                "Abra o OBS e confira host, porta e senha em Ajustes.",
            )
            return

        configured = {
            "Fundo": self.settings.scene_background,
            "Orador": self.settings.scene_speaker,
            "Mídia": self.settings.scene_media,
            "Zoom → Salão": self.settings.scene_zoom,
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
            "Verificação do OBS",
            f"Cena Program atual: {self.current_obs_scene or 'desconhecida'}\n\n"
            f"Cenas encontradas:\n{scene_lines}\n\n"
            f"Mapeamentos ausentes:\n{missing_text}",
        )

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
            OperatingMode.ZOOM: self.settings.scene_zoom,
        }[mode]

    def _mode_for_scene(self, scene_name: str) -> OperatingMode | None:
        mappings = {
            self.settings.scene_background: OperatingMode.BACKGROUND,
            self.settings.scene_speaker: OperatingMode.SPEAKER,
            self.settings.scene_media: OperatingMode.MEDIA,
            self.settings.scene_zoom: OperatingMode.ZOOM,
        }
        return mappings.get(scene_name)

    def _refresh_mode(self) -> None:
        actual_mode = None
        if self.obs_connected and self.current_obs_scene:
            actual_mode = self._mode_for_scene(self.current_obs_scene)
        elif self.state.simulation_enabled:
            actual_mode = self.state.current_mode

        for mode, button in self.mode_buttons.items():
            button.setChecked(mode == actual_mode)

        if self.obs_connected and self.current_obs_scene:
            readable = {
                OperatingMode.BACKGROUND: "Fundo",
                OperatingMode.SPEAKER: "Orador",
                OperatingMode.MEDIA: "Mídia",
                OperatingMode.ZOOM: "Zoom remoto",
            }
            if actual_mode is None:
                self.mode_label.setText(f"OBS Program: {self.current_obs_scene}")
            else:
                self.mode_label.setText(f"Salão: {readable[actual_mode]}")
            return

        readable = {
            OperatingMode.BACKGROUND: "Fundo",
            OperatingMode.SPEAKER: "Orador",
            OperatingMode.MEDIA: "Mídia",
            OperatingMode.ZOOM: "Zoom remoto",
        }
        self.mode_label.setText(f"Simulação: {readable[self.state.current_mode]}")

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
            QFrame#Card {
                background: #171b22;
                border: 1px solid #282f3a;
                border-radius: 9px;
            }
            QLabel#Preview {
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
                padding: 8px 9px;
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
