from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from meeting_assistant.core.state import AppState, OperatingMode


class MainWindow(QMainWindow):
    def __init__(self, state: AppState, app_icon: QIcon | None = None) -> None:
        super().__init__()
        self.state = state
        self.app_icon = app_icon or QIcon()
        self.setWindowIcon(self.app_icon)
        self.setWindowTitle("Meeting Assistant 3.0")
        self.resize(520, 620)
        self.setMinimumSize(470, 560)
        if self.state.simulation_enabled:
            self.setWindowTitle("Meeting Assistant 3.0 — Modo de Simulação")

        self._build_ui()
        self._apply_style()
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
            label = QLabel(f"● {name}")
            label.setObjectName("StatusBadge")
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
        settings = QPushButton("⚙️ Ajustes")
        system_grid.addWidget(diagnostics, 0, 0)
        system_grid.addWidget(settings, 0, 1)
        controls.addLayout(system_grid)

        controls.addSpacing(2)
        controls.addWidget(self._section_label("RETORNO — SALÃO"))

        preview_row = QHBoxLayout()
        preview_row.addStretch()
        self.preview = QLabel("Retorno da Tela 2\n16:9")
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

        footer = QLabel("Painel compacto • preview apenas para conferência")
        footer.setObjectName("Footer")
        footer.setAlignment(Qt.AlignCenter)
        root.addWidget(footer)

        self.setCentralWidget(central)

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def _select_mode(self, mode: OperatingMode) -> None:
        self.state.set_mode(mode)
        self._refresh_mode()

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
        self.automation_badge.style().unpolish(self.automation_badge)
        self.automation_badge.style().polish(self.automation_badge)

    def _refresh_mode(self) -> None:
        for mode, button in self.mode_buttons.items():
            button.setChecked(mode == self.state.current_mode)
        readable = {
            OperatingMode.BACKGROUND: "Fundo",
            OperatingMode.SPEAKER: "Orador",
            OperatingMode.MEDIA: "Mídia",
            OperatingMode.ZOOM: "Zoom remoto",
        }
        self.mode_label.setText(f"Salão: {readable[self.state.current_mode]}")

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
