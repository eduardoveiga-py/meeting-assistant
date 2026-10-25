from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from meeting_assistant.core.state import AppState
from meeting_assistant.services.settings import AppSettings
from meeting_assistant.ui.main_window import MainWindow


class DummyCameraSession(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.supported = True
        self.state = "off"
        self.message = "Câmera desligada."
        self.start_count = 0
        self.stop_count = 0

    def start(self):
        self.start_count += 1
        self.state = "running"
        self.message = "Câmera ativa."
        self.changed.emit()

    def stop(self):
        self.stop_count += 1
        self.state = "off"
        self.message = "Câmera desligada."
        self.changed.emit()


def _make_window(camera=None, whatsapp_enabled=True):
    app = QApplication.instance() or QApplication([])
    services = [MagicMock() for _ in range(7)]
    services[1].active = False
    services[1].returning = False
    services[2].snapshot.return_value = []
    services[3].snapshot.return_value = []
    services[6].active = False
    services[6].returning = False
    settings = AppSettings(whatsapp_enabled=whatsapp_enabled)
    win = MainWindow(
        AppState(),
        settings,
        *services,
        camera_session=camera,
    )
    win.settings_service = MagicMock()
    return app, win


def test_main_window_compact_width_and_no_horizontal_scroll():
    app, win = _make_window()
    win.resize(380, 760)
    win.show()
    app.processEvents()

    try:
        assert win.width() <= 400
        assert win.minimumWidth() <= 380
        scroll = win.centralWidget()
        assert not scroll.horizontalScrollBar().isVisible()
        assert scroll.horizontalScrollBar().maximum() == 0
    finally:
        win.close()


def test_main_window_camera_status_and_recovery():
    camera = DummyCameraSession()
    app, win = _make_window(camera=camera)
    win.show()
    app.processEvents()

    try:
        # Initial state: off
        assert "Iniciar câmera" in win.camera_button.text()
        assert win.camera_button.isEnabled()

        # Simulate error state
        camera.state = "error"
        camera.message = "Erro de teste na câmera"
        camera.changed.emit()
        app.processEvents()

        assert "Tentar câmera" in win.camera_button.text()
        assert "Erro de teste na câmera" in win.camera_button.toolTip()

        # When OBS connects, camera in error state should auto-start
        win._on_obs_connected(True, "OBS conectado")
        win._auto_start_camera()
        app.processEvents()
        assert camera.start_count == 1
        assert camera.state == "running"
        assert "Parar câmera" in win.camera_button.text()

        # Click to stop
        win.camera_button.click()
        app.processEvents()
        assert camera.stop_count == 1
        assert camera.state == "off"
        assert "Iniciar câmera" in win.camera_button.text()
    finally:
        win.close()


def test_main_window_camera_disabled_with_whatsapp():
    camera = DummyCameraSession()
    app, win = _make_window(camera=camera, whatsapp_enabled=False)
    win.show()
    app.processEvents()

    try:
        assert not win.camera_button.isEnabled()
        assert "desativad" in win.camera_button.toolTip().lower()

        # Toggle whatsapp back on -> auto-starts camera
        win._on_whatsapp_toggle(True)
        app.processEvents()
        assert win.camera_button.isEnabled()
        assert camera.start_count == 1
        assert camera.state == "running"
        assert "Parar câmera" in win.camera_button.text()

        # Toggle whatsapp off -> stops camera and disables button
        win._on_whatsapp_toggle(False)
        app.processEvents()
        assert not win.camera_button.isEnabled()
        assert camera.stop_count == 1
        assert camera.state == "off"
    finally:
        win.close()


def test_main_window_apply_assistant_settings_camera_lifecycle():
    camera = DummyCameraSession()
    app, win = _make_window(camera=camera, whatsapp_enabled=False)
    win.show()
    app.processEvents()

    try:
        assert camera.state == "off"
        assert camera.start_count == 0

        # Apply settings with whatsapp_enabled = True
        new_settings = AppSettings(whatsapp_enabled=True)
        win._apply_assistant_settings(new_settings)
        app.processEvents()
        assert win.settings.whatsapp_enabled is True
        assert camera.start_count == 1
        assert camera.state == "running"

        # Apply settings with whatsapp_enabled = False
        off_settings = AppSettings(whatsapp_enabled=False)
        win._apply_assistant_settings(off_settings)
        app.processEvents()
        assert win.settings.whatsapp_enabled is False
        assert camera.stop_count == 1
        assert camera.state == "off"
    finally:
        win.close()


def test_main_window_camera_button_click_toggles_whatsapp_state():
    camera = DummyCameraSession()
    app, win = _make_window(camera=camera, whatsapp_enabled=True)
    win.show()
    app.processEvents()

    try:
        assert win.whatsapp_toggle.isChecked() is True
        assert win.camera_button.isEnabled() is True

        # Click camera button to stop running camera
        camera.start()
        app.processEvents()
        assert "Parar câmera" in win.camera_button.text()

        win.camera_button.click()
        app.processEvents()
        # Stopping camera must NOT wipe out whatsapp_enabled setting or toggle
        assert win.settings.whatsapp_enabled is True
        assert win.whatsapp_toggle.isChecked() is True
        assert camera.state == "off"
        assert camera.stop_count == 1
        assert "Iniciar câmera" in win.camera_button.text()
        assert win.camera_button.isEnabled() is True

        # Turn toggle off via switch -> updates settings and disables camera
        win.whatsapp_toggle.setChecked(False)
        app.processEvents()
        assert win.settings.whatsapp_enabled is False
        assert not win.camera_button.isEnabled()
    finally:
        win.close()


def test_main_window_rapid_whatsapp_toggling_and_thread_resilience():
    camera = DummyCameraSession()
    app, win = _make_window(camera=camera, whatsapp_enabled=True)
    win.show()
    app.processEvents()

    try:
        # Rapidly flip toggle 10 times
        for i in range(10):
            target_state = (i % 2 == 0)
            win.whatsapp_toggle.setChecked(target_state)
            app.processEvents()

        # Final state check: i=9 -> target_state=False
        assert win.whatsapp_toggle.isChecked() is False
        assert win.settings.whatsapp_enabled is False
        assert camera.state == "off"

        # One more flip back to True
        win.whatsapp_toggle.setChecked(True)
        app.processEvents()
        assert win.whatsapp_toggle.isChecked() is True
        assert win.settings.whatsapp_enabled is True
        assert camera.state == "running"
    finally:
        win.close()


