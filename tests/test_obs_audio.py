from copy import deepcopy

import pytest

from meeting_assistant.services.obs_audio import (
    APP_KIND,
    APPS,
    BUS,
    MIC,
    MIC_KIND,
    MONITOR,
    NONE,
    SOURCES,
    activate,
    app_name,
    mute_managed,
    prepare,
)


class FakeObs:
    def __init__(self):
        self.sources = {
            "Personal mic": {"inputKind": MIC_KIND, "settings": {}, "mute": False, "monitor": NONE}
        }
        self.scenes = {"Texto do Ano": [], "Palco": [], "Mídias": []}
        self.calls = []
        self.failure_name = None

    def send(self, request, data, raw=True):
        self.calls.append((request, deepcopy(data)))
        name = data.get("inputName")
        if request == "GetInputKindList":
            return {"inputKinds": [MIC_KIND, APP_KIND]}
        if request == "GetInputList":
            return {
                "inputs": [{"inputName": n, "inputKind": s["inputKind"]} for n, s in self.sources.items()]
            }
        if request == "GetSceneList":
            return {"scenes": [{"sceneName": n} for n in self.scenes]}
        if request == "CreateScene":
            self.scenes[data["sceneName"]] = []
        elif request in ("CreateInput", "CreateSceneItem"):
            if request == "CreateInput":
                self.sources[name] = {
                    "inputKind": data["inputKind"],
                    "settings": data["inputSettings"],
                    "mute": False,
                    "monitor": NONE,
                }
            rows = self.scenes[data["sceneName"]]
            rows.append(
                {
                    "sourceName": name or data["sourceName"],
                    "sceneItemId": len(rows) + 1,
                    "sceneItemEnabled": data["sceneItemEnabled"],
                }
            )
        elif request == "GetSceneItemList":
            return {"sceneItems": deepcopy(self.scenes[data["sceneName"]])}
        elif request == "SetSceneItemEnabled":
            for row in self.scenes[data["sceneName"]]:
                if row["sceneItemId"] == data["sceneItemId"]:
                    row["sceneItemEnabled"] = data["sceneItemEnabled"]
        elif request == "SetInputMute":
            if name == self.failure_name and not data["inputMuted"]:
                raise RuntimeError("Injected activation failure")
            self.sources[name]["mute"] = data["inputMuted"]
        elif request == "GetInputMute":
            return {"inputMuted": self.sources[name]["mute"]}
        elif request == "SetInputAudioMonitorType":
            self.sources[name]["monitor"] = data["monitorType"]
        elif request == "GetInputAudioMonitorType":
            return {"monitorType": self.sources[name]["monitor"]}
        elif request == "SetInputSettings":
            self.sources[name]["settings"].update(data["inputSettings"])
        elif request == "GetInputSettings":
            return {"inputSettings": deepcopy(self.sources[name]["settings"])}
        elif request == "GetInputPropertiesListPropertyItems":
            if name == MIC:
                choices = [("Mesa USB", "physical"), ("Default", "default"), ("CABLE Output", "cable")]
            else:
                choices = [
                    ("Zoom", "Meeting:class:Zoom.exe"),
                    *[(label, f"Playing:class:{exe}") for label, exe in APPS.items()],
                ]
            return {
                "propertyItems": [{"itemName": n, "itemValue": v, "itemEnabled": True} for n, v in choices]
            }
        else:
            raise AssertionError(request)
        return {}


def selection():
    return {
        "microphone": "physical",
        "applications": {"JW Library": "Playing:class:jwlibrary.exe"},
        "routing_confirmed": True,
        "scenes": ["Texto do Ano", "Palco", "Mídias"],
    }


def test_preparation_idempotent_muted_and_filtered():
    obs = FakeObs()
    result = prepare(obs)
    prepare(obs)
    assert len(obs.scenes[BUS]) == len(SOURCES)
    assert all(obs.sources[n]["mute"] for n in SOURCES)
    assert all(not x["sceneItemEnabled"] for x in obs.scenes[BUS])
    assert result["microphones"][0]["itemValue"] == "physical"
    assert len(result["microphones"]) == 1
    for label, choices in result["applications"].items():
        assert len(choices) == 1
        assert choices[0]["itemValue"].endswith(APPS[label])
    assert not obs.scenes["Palco"]
    assert not obs.sources["Personal mic"]["mute"]


def test_activation_keeps_program_and_personal_sources_and_reuses_bus():
    obs = FakeObs()
    prepare(obs)
    activate(obs, selection())
    activate(obs, selection())
    for scene in selection()["scenes"]:
        assert len(obs.scenes[scene]) == 1
        assert obs.scenes[scene][0]["sourceName"] == BUS
    assert obs.sources[MIC]["monitor"] == MONITOR
    assert not obs.sources[MIC]["mute"]
    assert not obs.sources[app_name("JW Library")]["mute"]
    assert obs.sources[app_name("VLC")]["mute"]
    assert obs.sources["Personal mic"]["monitor"] == NONE
    assert not any(r == "SetCurrentProgramScene" for r, _ in obs.calls)
    mute_managed(obs)
    assert all(obs.sources[n]["mute"] for n in SOURCES)


@pytest.mark.parametrize(
    "change",
    [
        {"microphone": "cable"},
        {"routing_confirmed": False},
        {"applications": {"JW Library": "Meeting:class:Zoom.exe"}},
        {"applications": {"Zoom": "Meeting:class:Zoom.exe"}},
        {"scenes": ["Palco", "Palco", "Mídias"]},
    ],
)
def test_invalid_route_never_unmutes(change):
    obs = FakeObs()
    prepare(obs)
    data = selection() | change
    with pytest.raises(ValueError):
        activate(obs, data)
    assert all(obs.sources[n]["mute"] for n in SOURCES)


def test_failure_halfway_through_activation_silences_all_managed_sources():
    obs = FakeObs()
    prepare(obs)
    obs.failure_name = app_name("JW Library")
    with pytest.raises(RuntimeError):
        activate(obs, selection())
    assert all(obs.sources[n]["mute"] and obs.sources[n]["monitor"] == NONE for n in SOURCES)


def test_unrelated_monitor_blocks_activation_without_changing_it():
    obs = FakeObs()
    prepare(obs)
    obs.sources["Personal mic"]["monitor"] = MONITOR
    with pytest.raises(ValueError, match="Personal mic"):
        activate(obs, selection())
    assert obs.sources["Personal mic"]["monitor"] == MONITOR
    assert all(obs.sources[n]["mute"] for n in SOURCES)


def test_name_collision_does_not_reconfigure_foreign_source():
    obs = FakeObs()
    obs.sources[MIC] = {"inputKind": "image_source", "settings": {}, "mute": False, "monitor": NONE}
    with pytest.raises(ValueError, match="Nome reservado"):
        prepare(obs)
    assert not obs.sources[MIC]["mute"]
    assert obs.sources[MIC]["inputKind"] == "image_source"
