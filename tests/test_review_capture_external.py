from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, Signal
from test_obs_hall_setup import FakeObs, binding
from test_review_windows import window

from meeting_assistant.services.external_media_service import ExternalMediaService, media_candidates
from meeting_assistant.services.obs_capture_safety import assert_safe_media, disable_managed_display_captures
from meeting_assistant.services.obs_external_media import (
    SCENE,
    SOURCE,
    prepare_external,
    restore_external,
    show_external,
)
from meeting_assistant.services.obs_hall_setup import MEDIA_SOURCE, prepare_media


class VisualObs(FakeObs):
    def __init__(self):
        super().__init__()
        self.scenes = {"Palco": [], "Mídias": [], "Operator capture": []}
        self.program = "Palco"

    def send(self, request, data=None, **kw):
        if request == "GetCurrentProgramScene":
            return {"currentProgramSceneName": self.program}
        if request == "SetCurrentProgramScene":
            self.program = data["sceneName"]
            self.calls.append((request, data))
            return {}
        if request in {"GetSceneItemList", "GetGroupSceneItemList"}:
            return {"sceneItems": self.scenes[data["sceneName"]]}
        if request == "SetSceneItemEnabled":
            for row in self.scenes[data["sceneName"]]:
                if row["sceneItemId"] == data["sceneItemId"]:
                    row["sceneItemEnabled"] = data["sceneItemEnabled"]
            return {}
        return super().send(request, data, **kw)


def test_legacy_monitor_disabled_only_in_managed_scene_and_no_sources_deleted():
    obs = VisualObs()
    obs.inputs["Whole desktop"] = {"kind": "monitor_capture", "settings": {}}
    for scene in ("Mídias", "Operator capture"):
        obs.scenes[scene] = [{"sourceName": "Whole desktop", "sceneItemId": 4, "sceneItemEnabled": True}]
    prepare_media(obs, "Mídias", binding())
    assert not obs.scenes["Mídias"][0]["sceneItemEnabled"]
    assert obs.scenes["Operator capture"][0]["sceneItemEnabled"]
    assert "Whole desktop" in obs.inputs
    assert_safe_media(obs, "Mídias")
    assert not any(request.startswith("Remove") for request, _ in obs.calls)


def test_nested_shared_capture_disables_parent_not_shared_group_children():
    obs = VisualObs()
    obs.inputs["Desktop"] = {"kind": "monitor_capture", "settings": {}}
    obs.scenes["Shared group"] = [{"sourceName": "Desktop", "sceneItemId": 1, "sceneItemEnabled": True}]
    obs.scenes["Mídias"] = [
        {"sourceName": "Shared group", "sceneItemId": 2, "sceneItemEnabled": True, "isGroup": True}
    ]
    disable_managed_display_captures(obs, ["Mídias"])
    assert not obs.scenes["Mídias"][0]["sceneItemEnabled"]
    assert obs.scenes["Shared group"][0]["sceneItemEnabled"]


def test_unsafe_media_rejected_before_program_switch(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(Path, "exists", lambda self: False)
    obs = VisualObs()
    obs.inputs["Desktop"] = {"kind": "monitor_capture", "settings": {}}
    obs.scenes["Mídias"] = [{"sourceName": "Desktop", "sceneItemId": 1, "sceneItemEnabled": True}]
    with pytest.raises(ValueError, match="Captura de monitor"):
        assert_safe_media(obs, "Mídias")
    assert obs.program == "Palco"


def test_external_capture_dedicated_and_operator_program_change_preserved():
    obs = VisualObs()
    obs.options = [{"itemValue": "VLC:Qt:vlc.exe", "itemEnabled": True}]
    obs.inputs[MEDIA_SOURCE] = {"kind": "window_capture", "settings": {"window": "Original JWL"}}
    result = prepare_external(obs, "VLC:Qt:vlc.exe")
    assert obs.program == "Palco"
    assert obs.inputs[MEDIA_SOURCE]["settings"]["window"] == "Original JWL"
    assert obs.inputs[SOURCE]["settings"]["capture_audio"] is False
    show_external(obs, result["prior"])
    assert obs.program == SCENE
    obs.program = "Operator selected scene"
    restore_external(obs, result["prior"])
    assert obs.program == "Operator selected scene"


def test_external_show_aborts_if_operator_changed_program_during_preparation():
    obs = VisualObs()
    obs.program = "New scene"
    with pytest.raises(ValueError, match="Operador mudou"):
        show_external(obs, "Palco")
    assert obs.program == "New scene"


def test_media_candidates_do_not_fallback_to_own_app_or_ambiguous_title():
    candidates = [
        window(1, process="python.exe", title="VLC app controls"),
        window(2, process="notepad.exe", title="VLC - notes"),
        window(3, process="vlc.exe", title="Video.mp4"),
        window(4, process="chrome.exe", title="Browser"),
        window(5, process="vlc.exe", title="", visible=False),
    ]
    assert [w.hwnd for w in media_candidates(candidates)] == [3, 4]


class Controller(QObject):
    external_task_finished = Signal(str, bool, object)

    def __init__(self):
        super().__init__()
        self.external_task = Mock()


class Zoom(QObject):
    returning_changed = Signal(bool)
    status_changed = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.active = False
        self.returning = False
        self.restore_jwl = Mock(return_value=True)


def service():
    controller, zoom = Controller(), Zoom()
    backend = Mock()
    return ExternalMediaService(lambda: None, controller, zoom, backend=backend), controller, zoom, backend


def test_manual_external_return_restores_jwl_even_without_automation():
    external, controller, zoom, backend = service()
    external.phase = "presenting"
    external.window = window(1, process="vlc.exe")
    external._prior = "Palco"
    # Perform the worker callback inline so this regression does not touch Win32.
    external._work = lambda action, callback: external._native_result(action, True, callback())
    external.stop_external_media()
    controller.external_task.assert_called_with("restore", {"prior": "Palco"})
    controller.external_task_finished.emit("restore", True, {})
    backend.restore_presentation.assert_called_once_with(external.window)
    zoom.restore_jwl.assert_called_once()
    assert external.phase == "returning"
    zoom.returning = True
    zoom.status_changed.emit(True, "Restaurando JWL…")
    assert external.active
    zoom.returning = False
    zoom.status_changed.emit(True, "JWL confirmado visível")
    assert not external.active


def test_failed_jwl_return_does_not_resume_automatic_sensor():
    external, _, zoom, _ = service()
    external.phase = "returning"
    zoom.status_changed.emit(False, "Janela ausente")
    assert external.active and external.phase == "return_failed"


def test_external_cancel_after_window_show_does_not_commit_program():
    external, controller, _, _ = service()
    external.phase = "showing"
    external._stop_after_show = True
    external._native_result("show", True, {})
    assert external.phase == "stopping"
    assert all(call.args[0] != "show" for call in controller.external_task.call_args_list)
