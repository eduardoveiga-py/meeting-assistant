"""Unit and integration tests for obs_av_provisioner (Milestone 4, R4).

Verifies idempotent scene provisioning, audio monitoring device configuration,
anti-display-capture safety, native JW Library HWND capture, and application process audio.
"""

from __future__ import annotations

import configparser
from pathlib import Path
from typing import Any
from unittest.mock import patch

from obsws_python.error import OBSSDKRequestError

from meeting_assistant.services.obs_av_provisioner import (
    AUDIO_BUS_SCENE,
    DEFAULT_ZOOM_MONITOR_DEVICE_NAME,
    JWL_AUDIO_SOURCE,
    MANAGED_SCENES,
    MONITOR_NONE,
    MONITOR_ONLY,
    PROCESS_AUDIO_KIND,
    ZOOM_AUDIO_SOURCE,
    enforce_no_display_captures,
    provision_jwl_hwnd_capture,
    provision_obs_av,
    provision_process_audio,
    provision_scenes,
    set_obs_monitoring_device,
)
from meeting_assistant.services.obs_jwl_capture import (
    KIND as JWL_KIND,
)
from meeting_assistant.services.obs_jwl_capture import (
    SOURCE as JWL_SOURCE,
)


class StatefulMockObsClient:
    """Stateful in-memory mock of obs-websocket v5 protocol."""

    def __init__(self, current_profile: str = "Padrão"):
        self.current_profile = current_profile
        self.scenes: list[str] = []
        self.scene_items: dict[str, list[dict[str, Any]]] = {}  # scene -> list of items
        self.inputs: dict[str, dict[str, Any]] = {}  # name -> {"inputKind": ..., "settings": ...}
        self.input_monitor_types: dict[str, str] = {}
        self.input_tracks: dict[str, dict[str, bool]] = {}
        self.input_mutes: dict[str, bool] = {}
        self.profile_parameters: dict[tuple[str, str], str] = {}
        self.program_scene_calls: list[str] = []
        self.item_id_counter = 100

    def send(self, request: str, data: dict[str, Any] | None = None, raw: bool = True) -> dict[str, Any]:
        data = data or {}

        if request == "GetVersion":
            return {"obsVersion": "31.0.3", "obsWebSocketVersion": "5.5.0"}

        elif request == "GetProfileList":
            return {"currentProfileName": self.current_profile, "profiles": [self.current_profile]}

        elif request == "SetProfileParameter":
            cat = data.get("parameterCategory", "")
            name = data.get("parameterName", "")
            val = data.get("parameterValue", "")
            self.profile_parameters[(cat, name)] = val
            return {}

        elif request == "GetProfileParameter":
            cat = data.get("parameterCategory", "")
            name = data.get("parameterName", "")
            return {"parameterValue": self.profile_parameters.get((cat, name), "")}

        elif request == "GetSceneList":
            return {
                "currentProgramSceneName": self.scenes[0] if self.scenes else "",
                "scenes": [{"sceneName": s} for s in self.scenes],
            }

        elif request == "CreateScene":
            name = data["sceneName"]
            if name not in self.scenes:
                self.scenes.append(name)
                self.scene_items.setdefault(name, [])
            return {}

        elif request == "SetCurrentProgramScene":
            self.program_scene_calls.append(data.get("sceneName", ""))
            return {}

        elif request == "GetSceneItemList":
            scene = data["sceneName"]
            return {"sceneItems": list(self.scene_items.get(scene, []))}

        elif request == "CreateSceneItem":
            scene = data["sceneName"]
            source = data["sourceName"]
            self.item_id_counter += 1
            item = {
                "sceneItemId": self.item_id_counter,
                "sourceName": source,
                "sceneItemEnabled": data.get("sceneItemEnabled", True),
                "isGroup": False,
            }
            self.scene_items.setdefault(scene, []).append(item)
            return {"sceneItemId": self.item_id_counter}

        elif request == "SetSceneItemEnabled":
            scene = data["sceneName"]
            item_id = data["sceneItemId"]
            enabled = data["sceneItemEnabled"]
            for item in self.scene_items.get(scene, []):
                if item["sceneItemId"] == item_id:
                    item["sceneItemEnabled"] = enabled
                    break
            return {}

        elif request == "SetSceneItemTransform":
            return {}

        elif request == "SetSceneItemIndex":
            return {}

        elif request == "GetInputList":
            return {
                "inputs": [
                    {"inputName": name, "inputKind": info["inputKind"]}
                    for name, info in self.inputs.items()
                ]
            }

        elif request == "GetInputKindList":
            return {
                "inputKinds": [
                    "wasapi_input_capture",
                    PROCESS_AUDIO_KIND,
                    JWL_KIND,
                    "image_source",
                    "ffmpeg_source",
                    "monitor_capture",
                ]
            }

        elif request == "CreateInput":
            name = data["inputName"]
            kind = data["inputKind"]
            scene = data["sceneName"]
            if name in self.inputs:
                raise OBSSDKRequestError(601, f"Resource {name} already exists")
            self.inputs[name] = {"inputKind": kind, "settings": data.get("inputSettings", {})}
            self.item_id_counter += 1
            item = {
                "sceneItemId": self.item_id_counter,
                "sourceName": name,
                "sceneItemEnabled": data.get("sceneItemEnabled", True),
                "isGroup": False,
            }
            self.scene_items.setdefault(scene, []).append(item)
            return {"sceneItemId": self.item_id_counter}

        elif request == "GetInputSettings":
            name = data["inputName"]
            return {"inputSettings": self.inputs.get(name, {}).get("settings", {})}

        elif request == "SetInputSettings":
            name = data["inputName"]
            settings = data.get("inputSettings", {})
            if name in self.inputs:
                if data.get("overlay", False):
                    self.inputs[name]["settings"].update(settings)
                else:
                    self.inputs[name]["settings"] = settings
            return {}

        elif request == "GetInputAudioMonitorType":
            name = data["inputName"]
            return {"monitorType": self.input_monitor_types.get(name, MONITOR_NONE)}

        elif request == "SetInputAudioMonitorType":
            name = data["inputName"]
            self.input_monitor_types[name] = data["monitorType"]
            return {}

        elif request == "GetInputAudioTracks":
            name = data["inputName"]
            return {"inputAudioTracks": self.input_tracks.get(name, {str(i): False for i in range(1, 7)})}

        elif request == "SetInputAudioTracks":
            name = data["inputName"]
            self.input_tracks[name] = data["inputAudioTracks"]
            return {}

        elif request == "GetInputMute":
            name = data["inputName"]
            return {"inputMuted": self.input_mutes.get(name, False)}

        elif request == "SetInputMute":
            name = data["inputName"]
            self.input_mutes[name] = data["inputMuted"]
            return {}

        elif request == "GetVideoSettings":
            return {"baseWidth": 1920, "baseHeight": 1080, "outputWidth": 1920, "outputHeight": 1080}

        elif request == "GetVirtualCamStatus":
            return {"outputActive": False}

        return {}


def test_set_obs_monitoring_device(tmp_path: Path):
    profile_dir = tmp_path / "profiles" / "Salão"
    profile_dir.mkdir(parents=True)
    ini_file = profile_dir / "basic.ini"

    config = configparser.ConfigParser()
    config["General"] = {"Name": "Salão"}
    config["Audio"] = {"MonitoringDeviceId": "default"}
    with open(ini_file, "w", encoding="utf-8-sig") as f:
        config.write(f)

    client = StatefulMockObsClient(current_profile="Salão")
    device_id = "{0.0.0.00000000}.{CABLE-A-GUID}"
    device_name = "V-OUT Zoom (Envio)"

    ok, msg = set_obs_monitoring_device(
        client=client,
        device_id=device_id,
        device_name=device_name,
        profiles_dir=tmp_path / "profiles",
    )
    assert ok is True
    assert "V-OUT Zoom (Envio)" in msg

    # Verify WebSocket profile parameters
    assert client.profile_parameters[("Audio", "MonitoringDeviceId")] == device_id
    assert client.profile_parameters[("Audio", "MonitoringDeviceName")] == device_name

    # Verify disk persistence
    updated = configparser.ConfigParser()
    updated.read(ini_file, encoding="utf-8-sig")
    assert updated.get("Audio", "MonitoringDeviceId") == device_id
    assert updated.get("Audio", "MonitoringDeviceName") == device_name


def test_set_obs_monitoring_device_empty_id():
    client = StatefulMockObsClient()
    ok, msg = set_obs_monitoring_device(client, device_id="")
    assert ok is False
    assert "não informado" in msg


def test_provision_scenes_idempotent():
    client = StatefulMockObsClient()

    # 1. First run: create scenes and nest audio bus
    created, errors = provision_scenes(client)
    assert not errors
    assert set(created) == {*MANAGED_SCENES, AUDIO_BUS_SCENE}
    assert client.program_scene_calls == []  # Never call SetCurrentProgramScene!

    # Verify audio bus nested in visual scenes
    for scene in MANAGED_SCENES:
        items = client.scene_items[scene]
        assert any(i["sourceName"] == AUDIO_BUS_SCENE and i["sceneItemEnabled"] for i in items)

    # 2. Second run: idempotency check (no re-creation)
    created_2, errors_2 = provision_scenes(client)
    assert not errors_2
    assert created_2 == []
    for scene in MANAGED_SCENES:
        items = client.scene_items[scene]
        bus_items = [i for i in items if i["sourceName"] == AUDIO_BUS_SCENE]
        assert len(bus_items) == 1  # No duplicate scene items!


def test_enforce_no_display_captures_disables_items():
    client = StatefulMockObsClient()
    provision_scenes(client)

    # Add a rogue monitor_capture in Mídias and Palco
    client.inputs["Captura Monitor"] = {"inputKind": "monitor_capture", "settings": {}}
    client.item_id_counter += 1
    client.scene_items["Mídias"].append({
        "sceneItemId": 991,
        "sourceName": "Captura Monitor",
        "sceneItemEnabled": True,
        "isGroup": False,
    })
    client.scene_items["Palco"].append({
        "sceneItemId": 992,
        "sourceName": "Captura Monitor",
        "sceneItemEnabled": True,
        "isGroup": False,
    })

    disabled, errors = enforce_no_display_captures(client)
    assert not errors
    assert len(disabled) == 2
    assert any("Mídias: Captura Monitor" in d for d in disabled)
    assert any("Palco: Captura Monitor" in d for d in disabled)

    # Check items are now disabled
    assert not client.scene_items["Mídias"][-1]["sceneItemEnabled"]
    assert not client.scene_items["Palco"][-1]["sceneItemEnabled"]


def test_provision_jwl_hwnd_capture():
    client = StatefulMockObsClient()
    provision_scenes(client)

    target_info = {"hwnd": "12345", "session": "test-session-uuid"}
    ok, msg = provision_jwl_hwnd_capture(client, scene="Mídias", target=target_info)
    assert ok is True
    assert "JWL por HWND configurada com sucesso" in msg

    # Input verified
    assert JWL_SOURCE in client.inputs
    assert client.inputs[JWL_SOURCE]["inputKind"] == JWL_KIND
    assert client.inputs[JWL_SOURCE]["settings"] == target_info

    # Scene item verified in Mídias
    items = client.scene_items["Mídias"]
    assert any(i["sourceName"] == JWL_SOURCE and i["sceneItemEnabled"] for i in items)


def test_provision_jwl_hwnd_capture_collision_with_other_kind():
    client = StatefulMockObsClient()
    provision_scenes(client)

    # Pre-existing source with conflicting kind
    client.inputs[JWL_SOURCE] = {"inputKind": "window_capture", "settings": {}}

    ok, msg = provision_jwl_hwnd_capture(client, scene="Mídias")
    assert ok is False
    assert "incompatível" in msg


def test_provision_process_audio():
    client = StatefulMockObsClient()
    provision_scenes(client)

    configured, errors = provision_process_audio(client)
    assert not errors
    assert set(configured) == {JWL_AUDIO_SOURCE, ZOOM_AUDIO_SOURCE}

    # Verify JW Library audio: wasapi_process_output_capture, MONITOR_ONLY, track 6
    assert JWL_AUDIO_SOURCE in client.inputs
    assert client.inputs[JWL_AUDIO_SOURCE]["inputKind"] == PROCESS_AUDIO_KIND
    assert client.input_monitor_types[JWL_AUDIO_SOURCE] == MONITOR_ONLY
    assert client.input_tracks[JWL_AUDIO_SOURCE]["6"] is True
    assert client.input_tracks[JWL_AUDIO_SOURCE]["1"] is False
    assert client.input_mutes[JWL_AUDIO_SOURCE] is False

    # Verify Zoom audio: wasapi_process_output_capture, MONITOR_NONE, track 6
    assert ZOOM_AUDIO_SOURCE in client.inputs
    assert client.inputs[ZOOM_AUDIO_SOURCE]["inputKind"] == PROCESS_AUDIO_KIND
    assert client.input_monitor_types[ZOOM_AUDIO_SOURCE] == MONITOR_NONE
    assert client.input_tracks[ZOOM_AUDIO_SOURCE]["6"] is True
    assert client.input_tracks[ZOOM_AUDIO_SOURCE]["1"] is False
    assert client.input_mutes[ZOOM_AUDIO_SOURCE] is False

    # Verify items in AUDIO_BUS_SCENE
    bus_items = client.scene_items[AUDIO_BUS_SCENE]
    assert any(i["sourceName"] == JWL_AUDIO_SOURCE and i["sceneItemEnabled"] for i in bus_items)
    assert any(i["sourceName"] == ZOOM_AUDIO_SOURCE and i["sceneItemEnabled"] for i in bus_items)


def test_provision_obs_av_master_end_to_end(tmp_path: Path):
    profile_dir = tmp_path / "profiles" / "Salão"
    profile_dir.mkdir(parents=True)
    ini_file = profile_dir / "basic.ini"

    config = configparser.ConfigParser()
    config["General"] = {"Name": "Salão"}
    config["Audio"] = {"MonitoringDeviceId": "default"}
    with open(ini_file, "w", encoding="utf-8-sig") as f:
        config.write(f)

    client = StatefulMockObsClient(current_profile="Salão")
    device_id = "{0.0.0.00000000}.{CABLE-A-INPUT-GUID}"

    result = provision_obs_av(
        zoom_cable_id=device_id,
        zoom_cable_name=DEFAULT_ZOOM_MONITOR_DEVICE_NAME,
        client=client,
        profiles_dir=tmp_path / "profiles",
        jwl_target={"hwnd": "67890", "session": "active-jwl"},
    )

    assert result.success is True
    assert result.errors == []
    assert result.monitoring_device_set is True
    assert set(result.scenes_created) == {*MANAGED_SCENES, AUDIO_BUS_SCENE}
    assert result.jwl_hwnd_capture_configured is True
    assert set(result.process_audio_configured) == {JWL_AUDIO_SOURCE, ZOOM_AUDIO_SOURCE}

    # Strict compliance: Program scene was NEVER changed!
    assert client.program_scene_calls == []


def test_provision_obs_av_connection_failure():
    with patch(
        "meeting_assistant.services.obs_av_provisioner.connect_obs",
        side_effect=ConnectionRefusedError("Connection refused on 4455"),
    ):
        result = provision_obs_av(host="127.0.0.1", port=4455, client=None)
        assert result.success is False
        assert len(result.errors) > 0
        assert "Não foi possível conectar ao OBS Studio" in result.errors[0]
