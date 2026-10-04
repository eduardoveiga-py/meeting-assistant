"""Exercise real Qt controls, discovery refreshes and the OBS audio contract."""

from copy import deepcopy
from os import environ
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow
from test_audio_ui_shortcuts import Controller
from test_obs_audio import FakeObs

from meeting_assistant.services.audio_routes import GAIN, WHATSAPP_MONITOR
from meeting_assistant.services.obs_audio import MIC, NONE, SOURCES, app_name, run_audio_task
from meeting_assistant.services.settings import AppSettings
from meeting_assistant.ui.audio_setup_dialog import AudioSetupDialog
from meeting_assistant.ui.main_window import MainWindow
from meeting_assistant.ui.window_geometry import fit_window


def prepared_result():
    return {
        "message": "Preparado, envio silenciado.",
        "microphones": [{"itemName": "Mesa USB", "itemValue": "physical"}],
        "outputs": [{"itemName": "CABLE-A Input", "itemValue": "second-cable"}],
        "applications": {
            label: [{"itemName": label, "itemValue": f"Playing:class:{label}.exe"}]
            for label in ("JW Library", "Zoom", "VLC", "Chrome", "Edge")
        },
        "selected": {name: {} for name in SOURCES},
    }


def click(dialog, widget):
    app = QApplication.instance()
    dialog.scroll.ensureWidgetVisible(widget, 50, 30)
    app.processEvents()
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    app.processEvents()


def select(dialog, combo, value):
    dialog.scroll.ensureWidgetVisible(combo, 50, 30)
    QApplication.instance().processEvents()
    index = combo.findData(value)
    assert index >= 0
    combo.setFocus()
    while combo.currentIndex() < index:
        QTest.keyClick(combo, Qt.Key.Key_Down)
    while combo.currentIndex() > index:
        QTest.keyClick(combo, Qt.Key.Key_Up)


def discover(dialog, controller, result):
    click(dialog, dialog.prepare_button)
    assert dialog.busy
    controller.audio_task_finished.emit(dialog.token, "prepare", True, result)
    QApplication.instance().processEvents()


def confirm(dialog):
    for check in dialog.confirmations:
        if not check.isChecked():
            click(dialog, check)


def test_checked_boxes_explain_missing_inputs_and_activation_reaches_controller():
    controller = Controller()
    dialog = AudioSetupDialog(controller, AppSettings(audio_profile="whatsapp_zoom"))
    dialog.show()
    try:
        discover(dialog, controller, prepared_result())
        confirm(dialog)
        assert all(check.isChecked() for check in dialog.confirmations)
        assert not dialog.activate_button.isEnabled()
        assert dialog.readiness.isVisible()
        assert "entrada física da mesa" in dialog.readiness.text()
        assert "segundo cabo virtual" in dialog.readiness.text()
        controller.audio_task.reset_mock()
        dialog.request("activate")
        controller.audio_task.assert_not_called()
        select(dialog, dialog.microphone, "physical")
        assert not dialog.activate_button.isEnabled()
        assert "entrada física" not in dialog.readiness.text()
        assert "segundo cabo virtual" in dialog.readiness.text()
        select(dialog, dialog.whatsapp_device, "second-cable")
        assert dialog.activate_button.isEnabled()
        assert not dialog.readiness.isVisible()
        QTest.mouseClick(dialog.activate_button, Qt.MouseButton.LeftButton)
        token, action, data = controller.audio_task.call_args.args
        assert token == dialog.token and action == "activate"
        assert data["microphone"] == "physical"
        assert data["whatsapp_device"] == "second-cable"
        assert data["routing_confirmed"] is True
        assert dialog.busy and not dialog.activate_button.isEnabled()
        controller.audio_task_finished.emit(token, action, False, {"message": "OBS desconectado."})
        assert not dialog.busy
        assert dialog.status.text() == "OBS desconectado."
    finally:
        dialog.reject()


def test_refresh_after_recreation_preserves_valid_edits_and_deliberate_deselection():
    controller = Controller()
    settings = AppSettings(audio_profile="whatsapp_zoom")
    dialog = AudioSetupDialog(controller, settings)
    dialog.show()
    try:
        result = prepared_result()
        result["selected"][app_name("VLC")] = {"window": "Playing:class:VLC.exe"}
        discover(dialog, controller, result)
        select(dialog, dialog.microphone, "physical")
        select(dialog, dialog.whatsapp_device, "second-cable")
        select(dialog, dialog.applications["JW Library"], "Playing:class:JW Library.exe")
        select(dialog, dialog.applications["Zoom"], "Playing:class:Zoom.exe")
        select(dialog, dialog.applications["VLC"], "")
        dialog.gains[MIC].setValue(3)
        confirm(dialog)
        assert dialog.activate_button.isEnabled()
        # Recreated OBS inputs have no saved device/window. Pending UI choices
        # take precedence if those devices/applications are still available.
        discover(dialog, controller, result | {"selected": {name: {} for name in SOURCES}})
        assert dialog.microphone.currentData() == "physical"
        assert dialog.whatsapp_device.currentData() == "second-cable"
        assert dialog.applications["JW Library"].currentData() == "Playing:class:JW Library.exe"
        assert dialog.applications["Zoom"].currentData() == "Playing:class:Zoom.exe"
        assert dialog.applications["VLC"].currentData() == ""
        assert dialog.gains[MIC].value() == 3
        assert not any(check.isChecked() for check in dialog.confirmations)
        assert not dialog.activate_button.isEnabled()
        confirm(dialog)
        assert dialog.activate_button.isEnabled()
        # A saved VLC selection must not override deliberate deselection when
        # refreshing inputs which still have their earlier OBS settings.
        discover(dialog, controller, result)
        assert dialog.applications["VLC"].currentData() == ""
        assert not dialog.gains[app_name("VLC")].isEnabled()
    finally:
        dialog.reject()


def test_refresh_does_not_select_a_replacement_device_or_cable():
    controller = Controller()
    dialog = AudioSetupDialog(controller, AppSettings(audio_profile="whatsapp_zoom"))
    dialog.show()
    try:
        result = prepared_result()
        discover(dialog, controller, result)
        select(dialog, dialog.microphone, "physical")
        select(dialog, dialog.whatsapp_device, "second-cable")
        confirm(dialog)
        result["microphones"] = [{"itemName": "Another mic", "itemValue": "another-mic"}]
        result["outputs"] = [{"itemName": "Other cable", "itemValue": "another-cable"}]
        discover(dialog, controller, result)
        confirm(dialog)
        assert dialog.microphone.currentData() == ""
        assert dialog.whatsapp_device.currentData() == ""
        assert not dialog.activate_button.isEnabled()
        assert "entrada física da mesa" in dialog.readiness.text()
        assert "segundo cabo virtual" in dialog.readiness.text()
    finally:
        dialog.reject()


def test_profile_switch_keeps_zoom_gain_inactive_until_its_source_is_selected():
    controller = Controller()
    dialog = AudioSetupDialog(controller, AppSettings())
    dialog.show()
    try:
        discover(dialog, controller, prepared_result())
        assert not dialog.gains[MIC].isEnabled()
        assert not dialog.gains[app_name("Zoom")].isEnabled()
        select(dialog, dialog.microphone, "physical")
        confirm(dialog)
        assert dialog.activate_button.isEnabled()
        assert dialog.gains[MIC].isEnabled()
        select(dialog, dialog.profile, "whatsapp_zoom")
        assert not dialog.activate_button.isEnabled()
        assert not any(check.isChecked() for check in dialog.confirmations)
        assert not dialog.gains[app_name("Zoom")].isEnabled()
        select(dialog, dialog.applications["Zoom"], "Playing:class:Zoom.exe")
        assert dialog.gains[app_name("Zoom")].isEnabled()
        select(dialog, dialog.profile, "shared")
        assert dialog.applications["Zoom"].currentData() == ""
        assert not dialog.gains[app_name("Zoom")].isEnabled()
    finally:
        dialog.reject()


@pytest.mark.parametrize("profile", ["shared", "whatsapp_zoom"])
def test_actual_apply_click_configures_obs_filters_and_preserves_mix_minus(
    monkeypatch, audio_monitor_profile, profile
):
    outputs = [{"itemName": "CABLE-A Input", "itemValue": "second-cable"}]
    monkeypatch.setattr("meeting_assistant.services.obs_audio.virtual_outputs", lambda: outputs)
    monkeypatch.setattr("meeting_assistant.services.audio_routes.virtual_outputs", lambda: outputs)
    obs = FakeObs()
    controller = Controller()
    settings = AppSettings(audio_profile=profile)
    persistence = Mock()
    requests = []

    def execute(token, action, data):
        requests.append((action, deepcopy(data)))
        result = run_audio_task(obs, action, data)
        controller.audio_task_finished.emit(token, action, True, result)

    controller.audio_task.side_effect = execute
    dialog = AudioSetupDialog(controller, settings, settings_service=persistence)
    dialog.show()
    try:
        click(dialog, dialog.prepare_button)
        assert not dialog.busy
        confirm(dialog)
        assert not dialog.activate_button.isEnabled()
        select(dialog, dialog.microphone, "physical")
        select(dialog, dialog.applications["JW Library"], "Playing:class:jwlibrary.exe")
        dialog.gains[app_name("JW Library")].setValue(2)
        if profile == "whatsapp_zoom":
            select(dialog, dialog.whatsapp_device, "second-cable")
            select(dialog, dialog.applications["Zoom"], "Playing:class:zoom.exe")
        assert dialog.activate_button.isEnabled()
        QTest.mouseClick(dialog.activate_button, Qt.MouseButton.LeftButton)
        assert requests[-1][0] == "activate"
        assert not dialog.busy
        assert "OBS confirmou" in dialog.status.text()
        persistence.save.assert_called_once_with(settings)
        assert settings.audio_gains_db[app_name("JW Library")] == 2
        gain = next(f for f in obs.filters[app_name("JW Library")] if f["filterName"] == GAIN)
        assert gain["filterSettings"]["db"] == 2
        zoom = app_name("Zoom")
        assert obs.sources[zoom]["monitor"] == NONE
        if profile == "whatsapp_zoom":
            route = next(f for f in obs.filters[zoom] if f["filterName"] == WHATSAPP_MONITOR)
            assert route["filterEnabled"]
            assert route["filterSettings"]["device"] == "second-cable"
            assert all(not track for track in obs.sources[zoom]["tracks"].values())
        else:
            assert obs.sources[zoom]["mute"]
            assert not obs.filters.get(zoom)
    finally:
        dialog.reject()


@pytest.mark.parametrize("width,height,points", [(590, 690, 10), (520, 520, 12), (390, 410, 12)])
def test_missing_input_message_and_buttons_fit_with_the_operator_style(width, height, points):
    app = QApplication.instance()
    original_font = app.font()
    # The inherited stylesheet can reset child fonts to the application font;
    # changing only the dialog font does not exercise the intended text scale.
    app.setFont(QFont("Segoe UI", points))
    owner = QMainWindow()
    MainWindow._apply_style(owner)
    controller = Controller()
    dialog = AudioSetupDialog(controller, AppSettings(audio_profile="whatsapp_zoom"), owner)
    dialog.setFont(QFont("Segoe UI", points))
    # Isolate the synthetic work area from the runner's real screen size.
    dialog.removeEventFilter(dialog._screen_fit)
    dialog._screen_fit._timer.stop()
    dialog.show()
    app.processEvents()
    area = QRect(0, 0, width, height)
    dialog.resize(width, height)
    fit_window(dialog, area)
    app.processEvents()
    try:
        discover(dialog, controller, prepared_result())
        confirm(dialog)
        assert dialog.readiness.isVisible()
        assert "entrada física da mesa" in dialog.readiness.text()
        assert "segundo cabo virtual" in dialog.readiness.text()
        assert area.contains(dialog.frameGeometry())
        for widget in (
            dialog.status, dialog.readiness, dialog.levels,
            dialog.activate_button, dialog.mute_button, dialog.close_button,
        ):
            assert dialog.rect().contains(widget.geometry())
            if hasattr(widget, "heightForWidth"):
                assert widget.height() >= widget.heightForWidth(widget.width())
        assert dialog.scroll.horizontalScrollBar().maximum() == 0
        for label in dialog.scroll.widget().findChildren(QLabel):
            assert label.width() > 0
            assert label.height() >= label.heightForWidth(label.width())
        capture_directory = environ.get("MEETING_ASSISTANT_LAYOUT_CAPTURE_DIRECTORY")
        if capture_directory:
            folder = Path(capture_directory)
            folder.mkdir(parents=True, exist_ok=True)
            assert dialog.grab().save(str(folder / f"audio-pending-{width}-{height}-{points}.png"))
    finally:
        dialog.reject()
        owner.close()
        app.setFont(original_font)
