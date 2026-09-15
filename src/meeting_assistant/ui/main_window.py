from __future__ import annotations

from PySide6.QtCore import Qt
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
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self.setWindowTitle("Meeting Assistant 3.0")
        self.resize(1180, 760)
        self.setMinimumSize(980, 650)
        if self.state.simulation_enabled:
            self.setWindowTitle("Meeting Assistant 3.0 — Modo de Simulação")

        self._build_ui()
        self._apply_style()
        self._refresh_mode()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Meeting Assistant")
        title.setObjectName("Title")
        subtitle = QLabel("Mesa de operação • OBS • Zoom • JW Library")
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

        status_row = QHBoxLayout()
        self.status_labels: dict[str, QLabel] = {}
        for name in ("OBS", "JW Library", "Zoom", "Tela 2"):
            label = QLabel(f"● {name}: aguardando")
            label.setObjectName("StatusBadge")
            self.status_labels[name] = label
            status_row.addWidget(label)
        status_row.addStretch()
        root.addLayout(status_row)

        content = QHBoxLayout()
        content.setSpacing(16)

        preview_card = QFrame()
        preview_card.setObjectName("Card")
        preview_layout = QVBoxLayout(preview_card)
        preview_title = QLabel("RETORNO / PROGRAM")
        preview_title.setObjectName("SectionTitle")
        preview_layout.addWidget(preview_title)

        self.preview = QLabel("Retorno do OBS será exibido aqui\n\n16:9")
        self.preview.setObjectName("Preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(640, 360)
        preview_layout.addWidget(self.preview, 1)

        content.addWidget(preview_card, 3)

        controls_card = QFrame()
        controls_card.setObjectName("Card")
        controls = QVBoxLayout(controls_card)
        controls.addWidget(self._section_label("OPERAÇÃO"))

        grid = QGridLayout()
        self.mode_buttons: dict[OperatingMode, QPushButton] = {}
        button_specs = [
            (OperatingMode.BACKGROUND, "📖 Fundo", 0, 0),
            (OperatingMode.SPEAKER, "🎤 Orador", 0, 1),
            (OperatingMode.MEDIA, "🎥 Mídia", 1, 0),
            (OperatingMode.ZOOM, "💻 Zoom", 1, 1),
        ]
        for mode, text, row, col in button_specs:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked=False, m=mode: self._select_mode(m))
            self.mode_buttons[mode] = btn
            grid.addWidget(btn, row, col)
        controls.addLayout(grid)

        self.auto_button = QPushButton("🚥 Ativar automação")
        self.auto_button.clicked.connect(self._toggle_automation)
        controls.addWidget(self.auto_button)

        panic = QPushButton("🛟 Cena segura")
        panic.setObjectName("DangerButton")
        panic.clicked.connect(lambda: self._select_mode(OperatingMode.BACKGROUND))
        controls.addWidget(panic)

        controls.addSpacing(8)
        controls.addWidget(self._section_label("SISTEMA"))
        diagnostics = QPushButton("🩺 Verificar sistema")
        settings = QPushButton("⚙️ Configurações")
        controls.addWidget(diagnostics)
        controls.addWidget(settings)
        controls.addStretch()

        self.mode_label = QLabel()
        self.mode_label.setObjectName("ModeLabel")
        controls.addWidget(self.mode_label)

        content.addWidget(controls_card, 1)
        root.addLayout(content, 1)

        footer = QLabel(
            "Base 3.0 • integração real com OBS/JWL/Zoom será adicionada por módulos"
        )
        footer.setObjectName("Footer")
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
            OperatingMode.ZOOM: "Zoom",
        }
        self.mode_label.setText(f"Modo atual: {readable[self.state.current_mode]}")

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #111318;
                color: #f2f4f8;
                font-family: 'Segoe UI';
            }
            QLabel#Title {
                font-size: 28px;
                font-weight: 700;
            }
            QLabel#Subtitle, QLabel#Footer {
                color: #9ca6b5;
            }
            QLabel#SectionTitle {
                color: #92c5ff;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#StatusBadge {
                background: #1b2029;
                border: 1px solid #2c3440;
                border-radius: 8px;
                padding: 7px 10px;
            }
            QLabel#AutomationBadge {
                background: #3b3220;
                color: #ffd166;
                border-radius: 10px;
                padding: 9px 14px;
                font-weight: 700;
            }
            QLabel#AutomationBadge[active='true'] {
                background: #153924;
                color: #73e6a2;
            }
            QFrame#Card {
                background: #171b22;
                border: 1px solid #282f3a;
                border-radius: 14px;
            }
            QLabel#Preview {
                background: #080a0e;
                border: 1px solid #303844;
                border-radius: 10px;
                color: #758093;
                font-size: 18px;
            }
            QPushButton {
                background: #252c36;
                border: 1px solid #343e4c;
                border-radius: 9px;
                padding: 12px 14px;
                font-size: 14px;
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
                border-radius: 8px;
                padding: 10px;
                font-weight: 600;
            }
            """
        )
