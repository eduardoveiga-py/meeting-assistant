from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from meeting_assistant.services.display_service import (
    DisplayInfo,
    display_info_from_screen,
)
from meeting_assistant.services.settings import AppSettings


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        available_scenes: list[str],
        parent=None,
        available_displays: list[DisplayInfo] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ajustes do Meeting Assistant")
        self.setModal(True)
        self.setMinimumWidth(520)

        if available_displays is None:
            app = QGuiApplication.instance()
            primary = app.primaryScreen() if app is not None else None
            available_displays = (
                [
                    display_info_from_screen(screen, primary=screen is primary)
                    for screen in app.screens()
                ]
                if app is not None
                else []
            )

        root = QVBoxLayout(self)

        output_group = QGroupBox("Saída do Salão")
        output_form = QFormLayout(output_group)

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

        self.zoom_join_edit = QLineEdit(settings.zoom_join_url)
        self.zoom_join_edit.setPlaceholderText(
            "https://...zoom.us/j/123456789?pwd=..."
        )
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
        root.addWidget(startup_group)

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

        scenes_form.addRow("Fundo", self.background_combo)
        scenes_form.addRow("Palco", self.speaker_combo)
        scenes_form.addRow("Mídia", self.media_combo)
        scenes_form.addRow("Zoom → Salão", self.zoom_combo)
        root.addWidget(scenes_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _scene_combo(current: str, available_scenes: list[str]) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        names = list(dict.fromkeys([current, *available_scenes]))
        combo.addItems([name for name in names if name])
        combo.setCurrentText(current)
        return combo

    def apply_to(self, settings: AppSettings) -> None:
        settings.simulation_enabled = self.simulation_check.isChecked()
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
