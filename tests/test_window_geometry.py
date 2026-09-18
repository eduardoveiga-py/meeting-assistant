from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QScrollArea

from meeting_assistant.core.state import AppState
from meeting_assistant.services.settings import AppSettings
from meeting_assistant.ui.main_window import MainWindow
from meeting_assistant.ui.settings_dialog import SettingsDialog
from meeting_assistant.ui.window_geometry import fit_window


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
        assert scroll.viewport().rect().contains(
            dialog.zoom_combo.mapTo(scroll.viewport(), dialog.zoom_combo.rect().center())
        )
    finally:
        dialog.close()


def test_main_window_fits_small_work_area_and_footer_is_reachable(app):
    services = [MagicMock() for _ in range(7)]
    services[2].snapshot.return_value = []
    services[3].snapshot.return_value = []
    services[6].active = False
    window = MainWindow(AppState(), AppSettings(), *services)
    window.show()
    app.processEvents()
    area = QRect(0, 0, 800, 560)
    fit_window(window, area)
    app.processEvents()
    try:
        assert area.contains(window.frameGeometry())
        scroll = window.centralWidget()
        assert scroll.verticalScrollBar().maximum() > 0
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        app.processEvents()
        assert scroll.viewport().rect().contains(
            window.footer.mapTo(scroll.viewport(), window.footer.rect().center())
        )
    finally:
        window.close()
