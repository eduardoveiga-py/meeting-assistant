import json
import threading
from unittest.mock import MagicMock, Mock

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog

from meeting_assistant.core.state import AppState
from meeting_assistant.services.audio_levels import summarize
from meeting_assistant.services.operator_profile import export_profile, import_profile
from meeting_assistant.services.preview_stream import PreviewStream
from meeting_assistant.services.settings import AppSettings, SettingsService
from meeting_assistant.services.stage_camera import USB_SOURCE, camera_health, contingency, prepare_camera
from meeting_assistant.services.zoom_audio import microphone_state, perform
from meeting_assistant.ui.main_window import MainWindow
from meeting_assistant.ui.setup_assistant_dialog import SetupAssistantDialog


@pytest.mark.parametrize(
    "state,expected",
    [
        ("OBS_MEDIA_STATE_PLAYING", True),
        ("OBS_MEDIA_STATE_ERROR", False),
        ("OBS_MEDIA_STATE_STOPPED", False),
        ("OBS_MEDIA_STATE_OPENING", None),
    ],
)
def test_camera_health_does_not_equate_configuration_with_playing(state, expected):
    client = Mock()
    client.send.side_effect = lambda request, *a, **kw: {
        "GetSceneItemList": {"sceneItems": [{"sourceName": "Cam", "sceneItemEnabled": True}]},
        "GetInputList": {"inputs": [{"inputName": "Cam", "inputKind": "ffmpeg_source"}]},
        "GetMediaInputStatus": {"mediaState": state},
    }[request]
    assert camera_health(client, "Palco", "Cam")[0] is expected


@pytest.mark.parametrize("health,target", [(True, "Palco"), (False, "Texto do Ano"), (None, "Texto do Ano")])
def test_contingency_selects_and_verifies_explicit_scene(monkeypatch, health, target):
    monkeypatch.setattr("meeting_assistant.services.stage_camera.camera_health", lambda *a: (health, "test"))
    client = Mock()
    client.send.side_effect = lambda request, *a, **kw: {
        "GetSceneList": {"scenes": [{"sceneName": x} for x in ("Palco", "Texto do Ano")]},
        "GetSceneItemList": {"sceneItems": [{"sceneItemEnabled": True}]},
        "SetCurrentProgramScene": {},
        "GetCurrentProgramScene": {"currentProgramSceneName": target},
    }[request]
    assert target in contingency(client, AppSettings())
    client.send.assert_any_call("SetCurrentProgramScene", {"sceneName": target}, raw=True)
    assert not any("Mute" in call.args[0] for call in client.send.call_args_list)


def test_usb_discovery_does_not_reset_existing_device():
    client = Mock()
    client.send.side_effect = lambda request, *a, **kw: {
        "GetInputList": {"inputs": [{"inputName": USB_SOURCE, "inputKind": "dshow_input"}]},
        "GetInputPropertiesListPropertyItems": {"propertyItems": [{"itemName": "Camera", "itemValue": "ID"}]},
    }[request]
    assert prepare_camera(client, "usb", "")["devices"][0]["itemValue"] == "ID"
    assert all(call.args[0].startswith("Get") for call in client.send.call_args_list)


def test_usb_removed_is_detected_even_with_old_frame_dimensions():
    client = Mock()
    client.send.side_effect = lambda request, *a, **kw: {
        "GetSceneItemList": {
            "sceneItems": [
                {
                    "sourceName": "USB",
                    "sceneItemEnabled": True,
                    "sceneItemTransform": {"sourceWidth": 1920, "sourceHeight": 1080},
                }
            ]
        },
        "GetInputList": {"inputs": [{"inputName": "USB", "inputKind": "dshow_input"}]},
        "GetInputSettings": {"inputSettings": {"video_device_id": "removed-camera"}},
        "GetInputPropertiesListPropertyItems": {"propertyItems": []},
    }[request]
    assert camera_health(client, "Palco", "USB")[0] is False


def test_contingency_missing_yeartext_never_sends_scene_change(monkeypatch):
    monkeypatch.setattr("meeting_assistant.services.stage_camera.camera_health", lambda *a: (False, "off"))
    client = Mock()
    client.send.return_value = {"scenes": [{"sceneName": "Palco"}]}
    with pytest.raises(ValueError):
        contingency(client, AppSettings())
    assert all(call.args[0].startswith("Get") for call in client.send.call_args_list)


@pytest.mark.parametrize(
    "label,state",
    [
        ("Mute my audio (Alt+A)", "live"),
        ("Unmute (Alt+A)", "muted"),
        ("Desativar som (Alt+A)", "live"),
        ("Ativar áudio", "muted"),
        ("Mute all", None),
        ("Silenciar todos", None),
        ("Join Audio", None),
    ],
)
def test_zoom_audio_labels_distinguish_self_from_everyone(label, state):
    assert microphone_state(label) == state


def test_zoom_mute_is_idempotent_and_checks_result():
    button = Mock()
    assert perform("mute", lambda: (button, "muted")) == "muted"
    button.invoke.assert_not_called()
    finder = Mock(side_effect=[(button, "live"), (button, "muted")])
    assert perform("mute", finder) == "muted"
    button.invoke.assert_called_once()


def test_profile_preserves_local_credentials_and_rejects_injected_fields(tmp_path):
    path = tmp_path / "profile.json"
    settings = AppSettings(obs_password="private", camera_password="private", zoom_join_url="private")
    export_profile(settings, path)
    assert "private" not in path.read_text(encoding="utf-8")
    loaded = import_profile(settings, path)
    assert loaded.obs_password == "private"
    data = json.loads(path.read_text())
    data["preferences"]["obs_password"] = "changed"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        import_profile(settings, path)


def test_latest_frame_is_consumed_once_without_backlog():
    stream = PreviewStream()
    stream.frame = (1.0, b"old")
    stream.frame = (2.0, b"new")
    assert stream.take() == (2.0, b"new")
    assert stream.take() is None


def test_slow_preview_does_not_block_obs_commands(monkeypatch):
    from meeting_assistant.services.obs_controller import ObsConnectionConfig, ObsController

    controller = ObsController()
    entered, release, handled = threading.Event(), threading.Event(), threading.Event()

    def slow_factory(**kwargs):
        entered.set()
        release.wait(2)
        raise OSError("test disconnect")

    controller._preview_stream.factory = slow_factory
    controller._preview_stream.scene = "Palco"
    monkeypatch.setattr(controller, "_connect", lambda: False)
    monkeypatch.setattr(controller, "_handle_set_scene", lambda scene: handled.set())
    controller.start(ObsConnectionConfig("localhost", 4455, ""))
    try:
        assert entered.wait(1)
        controller.set_program_scene("Texto do Ano")
        assert handled.wait(1), "Preview request blocked operational commands"
    finally:
        release.set()
        controller.stop()


def test_audio_levels_only_report_managed_sources():
    from meeting_assistant.services.obs_audio import MIC, app_name

    voice, media = summarize(
        [
            {"inputName": MIC, "inputLevelsMul": [[0, 1, 1]]},
            {"inputName": app_name("JW Library"), "inputLevelsMul": [[0, 0.1, 0.1]]},
            {"inputName": "Zoom return", "inputLevelsMul": [[0, 1, 1]]},
        ]
    )
    assert voice == 0 and media == pytest.approx(-20)


def make_owner(tmp_path):
    services = [MagicMock() for _ in range(6)]
    services[1].snapshot.return_value = []
    services[2].snapshot.return_value = []
    services[5].active = services[5].returning = False
    return MainWindow(AppState(), AppSettings(), SettingsService(tmp_path / "settings.json"), *services)


@pytest.mark.parametrize("action", ["close", "reject"])
def test_setup_x_and_continue_both_end_modal_loop(tmp_path, monkeypatch, action):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(SetupAssistantDialog, "_inspect", lambda self: None)
    owner = make_owner(tmp_path)
    dialog = SetupAssistantDialog(owner)
    assert not dialog.editor.isModal()
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    timed_out = []
    watchdog.timeout.connect(lambda: (timed_out.append(True), dialog.done(QDialog.Rejected)))
    watchdog.start(1500)
    QTimer.singleShot(20, getattr(dialog, action))
    assert dialog.exec() == QDialog.Rejected
    watchdog.stop()
    assert not timed_out
    assert owner.isEnabled()
    dialog.deleteLater()
    owner.close()
    app.processEvents()


def test_close_during_setup_worker_completes_without_blocking_gui(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(SetupAssistantDialog, "_inspect", lambda self: None)
    owner = make_owner(tmp_path)
    dialog = SetupAssistantDialog(owner)
    release = threading.Event()
    dialog._run(lambda: (release.wait(1), "done")[1])
    QTimer.singleShot(10, dialog.close)
    QTimer.singleShot(50, release.set)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: dialog.done(99))
    timer.start(2000)
    assert dialog.exec() == QDialog.Rejected
    timer.stop()
    owner.close()
    app.processEvents()
