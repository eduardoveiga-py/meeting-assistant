from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QScrollArea

from meeting_assistant.core.state import AppState
from meeting_assistant.services.meeting_launcher import LaunchSummary
from meeting_assistant.services.settings import AppSettings
from meeting_assistant.ui.main_window import MainWindow
from meeting_assistant.ui.settings_dialog import SettingsDialog
from meeting_assistant.ui.window_geometry import fit_window


class FakeCameraSession(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.supported = True
        self.state = "off"
        self.message = "Câmera desligada."
        self.start_calls = 0
        self.stop_calls = 0

    def start(self):
        self.start_calls += 1
        self.state = "running"
        self.message = "Câmera ativa."
        self.changed.emit()

    def stop(self):
        self.stop_calls += 1
        self.state = "off"
        self.message = "Câmera desligada."
        self.changed.emit()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("area", [QRect(0, 0, 1280, 680), QRect(-800, 0, 800, 560)])
def test_settings_buttons_stay_visible_and_content_scrolls(app, area):
    dialog = SettingsDialog(AppSettings(), [], available_displays=[])
    dialog.show()
    app.processEvents()
    fit_window(dialog, area)
    app.processEvents()
    try:
        assert area.contains(dialog.frameGeometry())
        buttons = dialog.findChild(QDialogButtonBox)
        assert dialog.rect().contains(buttons.geometry())
        scroll = dialog.findChild(QScrollArea)
        assert scroll.verticalScrollBar().maximum() > 0
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        app.processEvents()
        assert (
            scroll.viewport()
            .rect()
            .contains(dialog.zoom_combo.mapTo(scroll.viewport(), dialog.zoom_combo.rect().center()))
        )
    finally:
        dialog.close()


@pytest.mark.parametrize("height", [600, 680])
def test_main_window_shows_all_controls_without_scrolling(app, height):
    services = [MagicMock() for _ in range(7)]
    services[2].snapshot.return_value = []
    services[3].snapshot.return_value = []
    services[6].active = False
    window = MainWindow(AppState(), AppSettings(whatsapp_enabled=True), *services)
    window.show()
    app.processEvents()
    window.set_telemetry_session("MA-20260918-001933-25DE")
    area = QRect(0, 0, 800, height)
    fit_window(window, area)
    app.processEvents()
    try:
        assert area.contains(window.frameGeometry())
        scroll = window.centralWidget()
        assert scroll.verticalScrollBar().maximum() == 0
        assert scroll.horizontalScrollBar().maximum() == 0
        assert (
            scroll.viewport()
            .rect()
            .contains(window.footer.mapTo(scroll.viewport(), window.footer.rect().center()))
        )
    finally:
        window.close()


@pytest.mark.parametrize("height", [600, 680])
def test_launch_summary_does_not_expand_main_window_horizontally(app, height):
    services = [MagicMock() for _ in range(7)]
    services[2].snapshot.return_value = []
    services[3].snapshot.return_value = []
    services[6].active = False
    window = MainWindow(AppState(), AppSettings(whatsapp_enabled=True), *services)
    window.show()
    app.processEvents()
    fit_window(window, QRect(0, 0, 800, height))
    app.processEvents()
    width = window.width()
    try:
        window._on_launch_finished(
            LaunchSummary(
                obs_running=True,
                jwl_running=True,
                zoom_running=True,
                zoom_meeting_active=False,
                notes=(
                    "JW Library já estava aberto",
                    "Entrada na reunião do Zoom solicitada",
                    "Zoom aberto; entrada na reunião ainda não confirmada",
                ),
            )
        )
        for _ in range(5):
            app.processEvents()
        scroll = window.centralWidget()
        assert window.width() == width
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.verticalScrollBar().maximum() == 0
        assert (
            scroll.viewport()
            .rect()
            .contains(window.mode_label.mapTo(scroll.viewport(), window.mode_label.rect().bottomRight()))
        )
    finally:
        window.close()


def test_main_window_camera_button_and_auto_start(app):
    services = [MagicMock() for _ in range(7)]
    services[2].snapshot.return_value = []
    services[3].snapshot.return_value = []
    services[6].active = False
    camera = FakeCameraSession()
    window = MainWindow(AppState(), AppSettings(whatsapp_enabled=True), *services, camera_session=camera)
    window.show()
    app.processEvents()
    try:
        assert "Iniciar câmera" in window.camera_button.text()
        assert "WhatsApp" in window.camera_button.accessibleName()
        assert "WhatsApp" in window.camera_button.toolTip()
        assert window.mode_buttons[window.state.current_mode].text().startswith("📖 Texto do Ano")
        window._on_obs_connected(True, "OBS conectado")
        window._auto_start_camera()
        assert camera.start_calls == 1
        assert "Parar câmera" in window.camera_button.text()
        window.camera_button.click()
        assert camera.stop_calls == 1
        assert "Iniciar câmera" in window.camera_button.text()
    finally:
        window.close()
