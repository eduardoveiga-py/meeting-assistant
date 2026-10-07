import json
from datetime import datetime

import pytest
from test_yeartext_store import png

from meeting_assistant.services.obs_controller import ObsController
from meeting_assistant.services.obs_hall_setup import (
    PHOTO_SOURCE,
    apply_yeartext,
    prepare_media,
    select_exact_window,
    virtual_camera_step,
)
from meeting_assistant.services.obs_jwl_capture import IDENTITY_KEYS, KIND, SOURCE, STATUS_PROPERTY
from meeting_assistant.services.yeartext_store import YeartextStore


def binding(hwnd="7"):
    return {"hwnd": hwnd, "pid": 123, "created": "10001", "jwl_hwnd": "8",
            "jwl_pid": 124, "jwl_created": "10002", "window_class": "ApplicationFrameWindow",
            "hall_left": -1920, "hall_top": 0, "hall_right": 0, "hall_bottom": 1080,
            "session": "a" * 32}


class FakeObs:
    def __init__(self):
        self.scenes = {}
        self.inputs = {}
        self.calls = []
        self.virtual = False
        self.confirm_start = True
        self.options = [{"itemValue": "JWL media:Class:JWLibrary.exe", "itemEnabled": True}]
        self.native_state = "active"
        self.native_identity = None
        self.kinds = ["image_source", "window_capture", KIND]

    def send(self, request, data=None, raw=True):
        self.calls.append((request, data))
        if request == "GetSceneList":
            return {"scenes": [{"sceneName": name} for name in self.scenes]}
        if request == "GetInputList":
            return {
                "inputs": [
                    {"inputName": name, "inputKind": entry["kind"]} for name, entry in self.inputs.items()
                ]
            }
        if request == "GetInputKindList":
            return {"inputKinds": self.kinds}
        if request == "CreateScene":
            self.scenes[data["sceneName"]] = []
        if request == "CreateInput":
            self.inputs[data["inputName"]] = {"kind": data["inputKind"], "settings": data["inputSettings"]}
            item_id = max((i["sceneItemId"] for i in self.scenes[data["sceneName"]]), default=0) + 1
            self.scenes[data["sceneName"]].append(
                {
                    "sourceName": data["inputName"],
                    "sceneItemId": item_id,
                    "sceneItemEnabled": data["sceneItemEnabled"],
                }
            )
        if request == "GetSceneItemList":
            return {"sceneItems": self.scenes[data["sceneName"]]}
        if request == "SetInputSettings":
            self.inputs[data["inputName"]]["settings"].update(data["inputSettings"])
        if request == "GetInputSettings":
            return {"inputSettings": self.inputs[data["inputName"]]["settings"]}
        if request == "GetVideoSettings":
            return {"baseWidth": 1920, "baseHeight": 1080}
        if request == "GetInputPropertiesListPropertyItems":
            if data.get("propertyName") == STATUS_PROPERTY:
                values = self.native_identity or self.inputs[data["inputName"]]["settings"]
                status = {k: values.get(k) for k in IDENTITY_KEYS}
                status.update(protocol=1, state=self.native_state, width=1920, height=1080)
                return {"propertyItems": [{"itemValue": json.dumps(status)}]}
            return {"propertyItems": self.options}
        if request == "GetVirtualCamStatus":
            return {"outputActive": self.virtual}
        if request == "StartVirtualCam":
            self.virtual = self.confirm_start
        if request == "SetSceneItemEnabled":
            for row in self.scenes[data["sceneName"]]:
                if row["sceneItemId"] == data["sceneItemId"]:
                    row["sceneItemEnabled"] = data["sceneItemEnabled"]
        return {}


def test_apply_photo_is_idempotent_and_does_not_switch_program(tmp_path):
    client = FakeObs()
    photo = YeartextStore(tmp_path).save(png(), datetime.now().year)
    apply_yeartext(client, photo, "Texto do Ano")
    apply_yeartext(client, photo, "Texto do Ano")
    assert len(client.scenes["Texto do Ano"]) == 1
    assert client.inputs[PHOTO_SOURCE]["settings"]["file"] == photo["path"]
    assert not any(request == "SetCurrentProgramScene" for request, _ in client.calls)


def test_media_uses_silent_native_hwnd_source_and_keeps_single_source():
    client = FakeObs()
    prepare_media(client, "Mídias", binding())
    prepare_media(client, "Mídias", binding())
    assert len(client.scenes["Mídias"]) == 1
    assert client.inputs[SOURCE]["kind"] == KIND
    assert client.inputs[SOURCE]["settings"]["hwnd"] == "7"
    assert not any(r in {"SetInputMute", "SetCurrentProgramScene"} for r, _ in client.calls)


def test_ambiguous_obs_title_is_not_used_by_native_capture():
    client = FakeObs()
    client.options.append({"itemValue": "JWL media:Other:JWLibrary.exe"})
    prepare_media(client, "Mídias", binding())
    assert client.scenes["Mídias"][0]["sceneItemEnabled"]
    assert client.inputs[SOURCE]["settings"]["hwnd"] == "7"
    assert not any(data and data.get("propertyName") == "window" for _, data in client.calls)


def test_zoom_is_never_used_as_fallback():
    with pytest.raises(ValueError):
        select_exact_window([{"itemValue": "Zoom:Class:Zoom.exe"}], ["JWL media:Class:JWLibrary.exe"])


def test_virtual_camera_requires_confirmation_and_never_toggles():
    client = FakeObs()
    client.confirm_start = False
    assert virtual_camera_step(client) is False
    client.virtual = True
    calls = len(client.calls)
    assert virtual_camera_step(client) is True
    assert [r for r, _ in client.calls[calls:]] == ["GetVirtualCamStatus"]
    assert not any(r == "ToggleVirtualCam" for r, _ in client.calls)


def test_disconnected_photo_stays_pending_then_applies(tmp_path):
    store = YeartextStore(tmp_path)
    store.save(png(), datetime.now().year)
    controller = ObsController()
    results = []
    controller.hall_task_finished.connect(lambda *args: results.append(args))
    data = {"directory": str(tmp_path), "scene": "Texto do Ano"}
    controller._handle_hall_task("yeartext", data)
    assert results[-1][1] is False
    assert store.current()["obs_pending"]
    controller._client = FakeObs()
    controller.local_connection = True
    controller._handle_hall_task("yeartext", data)
    assert results[-1][1] is True
    assert not store.current()["obs_pending"]
