from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from meeting_assistant.services.settings import AppSettings


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        available_scenes: list[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ajustes do Meeting Assistant")
        self.setModal(True)
        self.setMinimumWidth(430)

        root = QVBoxLayout(self)

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
        scenes_form.addRow("Orador", self.speaker_combo)
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
        settings.obs_host = self.host_edit.text().strip() or "127.0.0.1"
        settings.obs_port = self.port_spin.value()
        settings.obs_password = self.password_edit.text()
        settings.scene_background = self.background_combo.currentText().strip()
        settings.scene_speaker = self.speaker_combo.currentText().strip()
        settings.scene_media = self.media_combo.currentText().strip()
        settings.scene_zoom = self.zoom_combo.currentText().strip()
