"""Real Qt interaction for routing, read-only refresh and independent volume changes."""

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
        "message": "Configuração lida; envio preservado.",
        "microphones": [{"itemName": "Mesa USB", "itemValue": "physical"}],
        "outputs": [
            {"itemName": "CABLE-A Input", "itemValue": "cable"},
            {"itemName": "CABLE-B Input", "itemValue": "second-cable"},
        ],
        "monitor": {"monitorDeviceId": "cable", "monitorDeviceName": "CABLE-A Input"},
        "applications": {
            label: [{"itemName": label, "itemValue": f"Playing:class:{label}.exe"}]
            for label in ("JW Library", "Zoom", "VLC", "Chrome", "Edge")
        },
        "selected": {name: {} for name in SOURCES},
        "source_states": {},
        "missing_sources": [],
        "needs_prepare": False,
    }


def expose(dialog, widget):
    for index, scroll in enumerate((dialog.scroll, dialog.volume_scroll, dialog.help_scroll)):
        if scroll.widget().isAncestorOf(widget):
            dialog.tabs.setCurrentIndex(index)
            if dialog.other_sources.isAncestorOf(widget):
                dialog.other_sources.setChecked(True)
            scroll.ensureWidgetVisible(widget, 50, 30)
            break
    QApplication.instance().processEvents()


def click(dialog, widget):
    expose(dialog, widget)
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    QApplication.instance().processEvents()


def select(dialog, combo, value):
    expose(dialog, combo)
    index = combo.findData(value)
    assert index >= 0
    combo.setFocus()
    current = combo.currentIndex()
    key = Qt.Key.Key_Down if current < index else Qt.Key.Key_Up
    for _ in range(abs(index - current)):
        QTest.keyClick(combo, key)
    assert combo.currentIndex() == index, (combo.isEnabled(), combo.isVisible(), value)


def discover(dialog, controller, result):
    QApplication.instance().processEvents()
    if not dialog.busy:
        click(dialog, dialog.refresh_button)
    assert dialog.busy
    assert controller.audio_task.call_args.args[1] == "inspect"
    controller.audio_task_finished.emit(dialog.token, "inspect", True, result)
    QApplication.instance().processEvents()


def confirm(dialog):
    if not dialog.route_confirmation.isChecked():
        click(dialog, dialog.route_confirmation)


def test_missing_second_cable_explained_by_a_real_click_and_activation_reaches_controller():
    controller = Controller()
    dialog = AudioSetupDialog(controller, AppSettings(audio_profile="whatsapp_zoom"))
    dialog.show()
    try:
        discover(dialog, controller, prepared_result())
        select(dialog, dialog.microphone, "physical")
        confirm(dialog)
        controller.audio_task.reset_mock()
        assert dialog.activate_button.isEnabled()
        click(dialog, dialog.activate_button)
        controller.audio_task.assert_not_called()
        assert "segundo cabo" in dialog.status.text()
        assert "segundo cabo" in dialog.readiness.text()
        assert dialog.whatsapp_device.hasFocus()
        assert dialog.whatsapp_device.findData("cable") == -1
        select(dialog, dialog.whatsapp_device, "second-cable")
        assert not dialog.route_confirmation.isChecked()
        confirm(dialog)
        click(dialog, dialog.activate_button)
        token, action, data = controller.audio_task.call_args.args
        assert token == dialog.token and action == "activate"
        assert data["microphone"] == "physical"
        assert data["whatsapp_device"] == "second-cable"
        assert data["routing_confirmed"] is True
        assert dialog.busy and not dialog.activate_button.isEnabled()
        controller.audio_task_finished.emit(token, action, False, {"message": "OBS desconectado."})
        assert not dialog.busy and dialog.status.text() == "OBS desconectado."
    finally:
        dialog.reject()


def test_missing_installed_cable_has_an_installation_step_and_never_sends_an_invalid_route():
    controller = Controller()
    dialog = AudioSetupDialog(controller, AppSettings(audio_profile="whatsapp_zoom"))
    dialog.show()
    try:
        result = prepared_result()
        result["outputs"] = result["outputs"][:1]
        discover(dialog, controller, result)
        select(dialog, dialog.microphone, "physical")
        confirm(dialog)
        controller.audio_task.reset_mock()
        click(dialog, dialog.activate_button)
        controller.audio_task.assert_not_called()
        assert "segundo cabo não encontrado" in dialog.status.text()
        assert "Ajuda" in dialog.status.text()
        assert "Instale" in dialog.second_hint.text()
    finally:
        dialog.reject()


def test_refresh_after_recreation_preserves_edits_and_deliberate_deselection():
    controller = Controller()
    dialog = AudioSetupDialog(controller, AppSettings(audio_profile="whatsapp_zoom"))
    dialog.show()
    try:
        result = prepared_result()
        result["selected"][app_name("VLC")] = {"window": "Playing:class:VLC.exe"}
        result["source_states"][MIC] = {"gain_ready": True, "gain_db": 0.0}
        discover(dialog, controller, result)
        select(dialog, dialog.microphone, "physical")
        select(dialog, dialog.whatsapp_device, "second-cable")
        select(dialog, dialog.applications["JW Library"], "Playing:class:JW Library.exe")
        select(dialog, dialog.applications["Zoom"], "Playing:class:Zoom.exe")
        select(dialog, dialog.applications["VLC"], "")
        expose(dialog, dialog.gains[MIC])
        dialog.gains[MIC].setFocus()
        for _ in range(3):
            QTest.keyClick(dialog.gains[MIC], Qt.Key.Key_Up)
        confirm(dialog)
        discover(dialog, controller, result | {"selected": {name: {} for name in SOURCES}})
        assert dialog.microphone.currentData() == "physical"
        assert dialog.whatsapp_device.currentData() == "second-cable"
        assert dialog.applications["JW Library"].currentData() == "Playing:class:JW Library.exe"
        assert dialog.applications["Zoom"].currentData() == "Playing:class:Zoom.exe"
        assert dialog.applications["VLC"].currentData() == ""
        assert dialog.gains[MIC].value() == 3
        # Read-only refresh with unchanged choices does not require another physical confirmation.
        assert dialog.route_confirmation.isChecked()
        discover(dialog, controller, result)
        assert dialog.applications["VLC"].currentData() == ""
        assert not dialog.gains[app_name("VLC")].isEnabled()
    finally:
        dialog.reject()


def test_removed_device_clears_selection_and_confirmation_without_selecting_a_replacement():
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
        assert dialog.microphone.currentData() == "" and dialog.whatsapp_device.currentData() == ""
        assert not dialog.route_confirmation.isChecked()
        controller.audio_task.reset_mock()
        click(dialog, dialog.activate_button)
        controller.audio_task.assert_not_called()
        assert "entrada física da mesa" in dialog.status.text()
    finally:
        dialog.reject()


def test_existing_obs_destination_and_gains_are_restored_after_local_settings_are_empty():
    controller = Controller()
    dialog = AudioSetupDialog(controller, AppSettings(audio_profile="whatsapp_zoom"))
    dialog.show()
    try:
        result = prepared_result()
        result["selected"][MIC] = {"device_id": "physical"}
        result["whatsapp_device"] = "second-cable"
        result["source_states"][MIC] = {"gain_ready": True, "gain_db": 6.0}
        discover(dialog, controller, result)
        assert dialog.whatsapp_device.currentData() == "second-cable"
        assert dialog.microphone.currentData() == "physical"
        assert dialog.gains[MIC].value() == 6.0
        assert dialog.gains[MIC].isEnabled()
        assert not dialog.route_confirmation.isChecked()
    finally:
        dialog.reject()


def test_profile_switch_hides_unused_fields_and_keeps_unconfigured_zoom_gain_inactive():
    controller = Controller()
    dialog = AudioSetupDialog(controller, AppSettings())
    dialog.show()
    try:
        discover(dialog, controller, prepared_result())
        assert not dialog.whatsapp_device.isVisible()
        assert not dialog.applications["Zoom"].isVisible()
        select(dialog, dialog.microphone, "physical")
        confirm(dialog)
        select(dialog, dialog.profile, "whatsapp_zoom")
        assert dialog.whatsapp_device.isVisible()
        assert not dialog.route_confirmation.isChecked()
        assert not dialog.gains[app_name("Zoom")].isEnabled()
        select(dialog, dialog.applications["Zoom"], "Playing:class:Zoom.exe")
        assert not dialog.gains[app_name("Zoom")].isEnabled()  # No OBS filters configured yet.
        select(dialog, dialog.profile, "shared")
        assert dialog.applications["Zoom"].currentData() == ""
        assert not dialog.gains[app_name("Zoom")].isEnabled()
    finally:
        dialog.reject()


def connected_dialog(obs, settings, persistence=None):
    controller = Controller()
    requests = []

    def execute(token, action, data):
        requests.append((action, deepcopy(data)))
        try:
            result = run_audio_task(obs, action, data)
        except ValueError as exc:
            controller.audio_task_finished.emit(token, action, False, {"message": str(exc)})
        else:
            controller.audio_task_finished.emit(token, action, True, result)

    controller.audio_task.side_effect = execute
    dialog = AudioSetupDialog(controller, settings, settings_service=persistence)
    dialog.show()
    QApplication.instance().processEvents()
    return dialog, requests


@pytest.mark.parametrize("profile", ["shared", "whatsapp_zoom"])
def test_actual_apply_click_configures_obs_filters_and_preserves_mix_minus(
    monkeypatch, audio_monitor_profile, profile
):
    outputs = [{"itemName": "CABLE-B Input", "itemValue": "second-cable"}]
    monkeypatch.setattr("meeting_assistant.services.obs_audio.virtual_outputs", lambda: outputs)
    monkeypatch.setattr("meeting_assistant.services.audio_routes.virtual_outputs", lambda: outputs)
    obs = FakeObs()
    settings = AppSettings(audio_profile=profile, audio_gains_db={app_name("JW Library"): 2.0})
    persistence = Mock()
    dialog, requests = connected_dialog(obs, settings, persistence)
    try:
        assert requests[0][0] == "inspect" and not dialog.busy
        click(dialog, dialog.prepare_button)
        select(dialog, dialog.microphone, "physical")
        select(dialog, dialog.applications["JW Library"], "Playing:class:jwlibrary.exe")
        if profile == "whatsapp_zoom":
            select(dialog, dialog.whatsapp_device, "second-cable")
            select(dialog, dialog.applications["Zoom"], "Playing:class:zoom.exe")
        confirm(dialog)
        click(dialog, dialog.activate_button)
        assert requests[-1][0] == "activate" and not dialog.busy
        assert "OBS confirmou" in dialog.status.text()
        persistence.save.assert_called_once_with(settings)
        assert settings.audio_gains_db[app_name("JW Library")] == 2
        gain = next(f for f in obs.filters[app_name("JW Library")] if f["filterName"] == GAIN)
        assert gain["filterSettings"]["db"] == 2
        zoom = app_name("Zoom")
        assert obs.sources[zoom]["monitor"] == NONE
        if profile == "whatsapp_zoom":
            route = next(f for f in obs.filters[zoom] if f["filterName"] == WHATSAPP_MONITOR)
            assert route["filterEnabled"] and route["filterSettings"]["device"] == "second-cable"
            assert all(not track for track in obs.sources[zoom]["tracks"].values())
        else:
            assert obs.sources[zoom]["mute"] and not obs.filters.get(zoom)
    finally:
        dialog.reject()


def test_real_volume_click_works_without_reconfirming_routes_or_a_second_cable(
    monkeypatch, audio_monitor_profile
):
    from test_obs_audio import selection

    obs = FakeObs()
    run_audio_task(obs, "prepare", {})
    # Native/manual settings can have more precision than the displayed control.
    run_audio_task(obs, "activate", selection() | {"gains_db": {MIC: 2.1234, app_name("JW Library"): 1}})
    monkeypatch.setattr("meeting_assistant.services.obs_audio.virtual_outputs", lambda: [])
    # Reproduce the operator's missing-second-cable profile while an existing source has a gain.
    settings = AppSettings(audio_profile="whatsapp_zoom", audio_gains_db={app_name("Edge"): 4})
    persistence = Mock()
    before = deepcopy(obs.sources), deepcopy(obs.scenes)
    dialog, requests = connected_dialog(obs, settings, persistence)
    try:
        assert requests == [("inspect", requests[0][1])]
        assert (obs.sources, obs.scenes) == before
        assert not dialog.route_confirmation.isChecked()
        assert dialog.whatsapp_device.currentData() == ""
        assert not dialog.prepare_button.isVisible()
        dialog.tabs.setCurrentIndex(1)
        gain = dialog.gains[app_name("JW Library")]
        expose(dialog, gain)
        gain.setFocus()
        QTest.keyClick(gain, Qt.Key.Key_Up)
        assert gain.value() == 2 and dialog.gain_button.isEnabled()
        assert not dialog.readiness.isVisible()
        start = len(obs.calls)
        click(dialog, dialog.gain_button)
        assert requests[-1] == ("gains", {"gains_db": {app_name("JW Library"): 2.0}})
        assert "OBS confirmou os volumes" in dialog.status.text()
        assert (obs.sources, obs.scenes) == before
        mutations = [(r, d) for r, d in obs.calls[start:] if not r.startswith("Get")]
        assert [r for r, _ in mutations] == ["SetSourceFilterSettings"]
        assert settings.audio_gains_db[app_name("JW Library")] == 2
        assert settings.audio_gains_db[app_name("Edge")] == 4
        persistence.save.assert_called_once_with(settings)
        assert not dialog.gain_button.isEnabled()
    finally:
        dialog.reject()


@pytest.mark.parametrize("width,height,points", [(590, 690, 10), (520, 520, 12), (390, 410, 12)])
def test_all_audio_tabs_fit_small_work_areas_and_large_fonts(width, height, points):
    app = QApplication.instance()
    owner = QMainWindow()
    MainWindow._apply_style(owner)
    controller = Controller()
    dialog = AudioSetupDialog(controller, AppSettings(audio_profile="whatsapp_zoom"), owner)
    dialog.setFont(QFont("Segoe UI", points))
    dialog.setStyleSheet(f"QLabel, QComboBox, QDoubleSpinBox {{ font-size: {points}pt; }}")
    dialog.removeEventFilter(dialog._screen_fit)
    dialog._screen_fit._timer.stop()
    dialog.show()
    app.processEvents()
    area = QRect(0, 0, width, height)
    dialog.resize(width, height)
    fit_window(dialog, area)
    app.processEvents()
    try:
        result = prepared_result()
        result["outputs"] = result["outputs"][:1]
        discover(dialog, controller, result)
        select(dialog, dialog.microphone, "physical")
        confirm(dialog)
        dialog.scroll.verticalScrollBar().setValue(0)
        for tab, scroll in enumerate((dialog.scroll, dialog.volume_scroll, dialog.help_scroll)):
            dialog.tabs.setCurrentIndex(tab)
            app.processEvents()
            capture_directory = environ.get("MEETING_ASSISTANT_LAYOUT_CAPTURE_DIRECTORY")
            if capture_directory:
                folder = Path(capture_directory)
                folder.mkdir(parents=True, exist_ok=True)
                assert dialog.grab().save(str(folder / f"audio-tab{tab}-{width}-{height}-{points}.png"))
            assert area.contains(dialog.frameGeometry())
            assert scroll.horizontalScrollBar().maximum() == 0, (
                tab, scroll.viewport().size().toTuple(), scroll.widget().minimumSizeHint().toTuple()
            )
            for widget in (dialog.status, dialog.readiness, dialog.levels, dialog.activate_button,
                           dialog.gain_button, dialog.mute_button, dialog.close_button):
                if not widget.isVisible():
                    continue
                assert dialog.rect().contains(widget.geometry()), (tab, widget)
                if isinstance(widget, QLabel):
                    assert widget.height() >= widget.heightForWidth(widget.width()), widget.text()
                elif hasattr(widget, "minimumSizeHint"):
                    assert widget.width() >= widget.minimumSizeHint().width(), widget.text()
            for label in scroll.widget().findChildren(QLabel):
                if label.isVisible() and label.wordWrap():
                    assert label.width() > 0 and label.hasHeightForWidth()
                    assert label.height() >= label.heightForWidth(label.width()), label.text()
    finally:
        dialog.reject()
        owner.close()
