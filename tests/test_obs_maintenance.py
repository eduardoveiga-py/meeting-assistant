"""Exercise the maintenance plan against persistent OBS state, including retries."""

import json
import threading
from copy import deepcopy
from datetime import datetime

import pytest
from test_obs_audio import FakeObs, selection
from test_yeartext_store import png

from meeting_assistant.services import obs_maintenance as service
from meeting_assistant.services.obs_audio import BUS, MIC, MONITOR, NONE, SOURCES, activate, prepare
from meeting_assistant.services.obs_hall_setup import PHOTO_SOURCE
from meeting_assistant.services.obs_jwl_capture import KIND, SOURCE, STATUS_PROPERTY
from meeting_assistant.services.obs_setup import CAMERA_SOURCE, camera_source_settings
from meeting_assistant.services.settings import AppSettings
from meeting_assistant.services.yeartext_store import YeartextStore

pytestmark = pytest.mark.usefixtures("audio_monitor_profile")
TARGET = {
    "hwnd": "100",
    "pid": 11,
    "created": "1000",
    "jwl_hwnd": "101",
    "jwl_pid": 12,
    "jwl_created": "1001",
    "session": "unit-session",
}


class MaintenanceObs(FakeObs):
    def __init__(self, *, jwl_plugin=True):
        super().__init__()
        self.jwl_plugin = jwl_plugin

    def send(self, request, data=None, raw=True):
        data = data or {}
        if request in {
            "GetSourceFilterKindList",
            "GetInputKindList",
            "GetVideoSettings",
            "SetSceneItemTransform",
            "SetSceneItemIndex",
        } or (
            request == "GetInputPropertiesListPropertyItems" and data.get("propertyName") == STATUS_PROPERTY
        ):
            self.calls.append((request, deepcopy(data)))
            if request == "GetInputKindList":
                return {
                    "inputKinds": list(set(SOURCES.values()))
                    + ["image_source", "ffmpeg_source"]
                    + ([KIND] if self.jwl_plugin else [])
                }
            if request == "GetSourceFilterKindList":
                return {"sourceFilterKinds": ["audio_monitor"] if self.plugin_available else []}
            if request == "GetVideoSettings":
                return {"baseWidth": 1920, "baseHeight": 1080}
            if request == "GetInputPropertiesListPropertyItems":
                status = {
                    **self.sources[SOURCE]["settings"],
                    "protocol": 1,
                    "state": "active",
                    "width": 1280,
                    "height": 720,
                }
                return {"propertyItems": [{"itemValue": json.dumps(status)}]}
            if request == "SetSceneItemTransform":
                item = next(
                    r for r in self.scenes[data["sceneName"]] if r["sceneItemId"] == data["sceneItemId"]
                )
                item["transform"] = deepcopy(data["sceneItemTransform"])
            return {}
        return super().send(request, data, raw)

    def add_source(self, name, kind, values, scene):
        self.sources[name] = {"inputKind": kind, "settings": values, "mute": True, "monitor": NONE}
        self.scenes[scene].append(
            {"sourceName": name, "sceneItemId": len(self.scenes[scene]) + 1, "sceneItemEnabled": True}
        )


def configure(obs):
    prepare(obs)
    activate(obs, selection() | {"gains_db": {MIC: 5.0}})


def snapshot(obs):
    return deepcopy(obs.sources), deepcopy(obs.scenes), deepcopy(obs.filters)


def state(result, key):
    return next(row["state"] for row in result["rows"] if row["key"] == key)


def test_first_preparation_reports_prerequisites_and_second_run_is_read_only(tmp_path):
    obs = MaintenanceObs(jwl_plugin=False)
    del obs.scenes["Palco"]
    personal = deepcopy(obs.sources["Personal mic"])
    result = service.complete(obs, AppSettings(), tmp_path, lambda: TARGET, threading.Event(), True)
    assert "Palco" in obs.scenes and len(obs.scenes[BUS]) == len(SOURCES)
    assert all(obs.sources[name]["mute"] and obs.sources[name]["monitor"] == NONE for name in SOURCES)
    assert all(not item["sceneItemEnabled"] for item in obs.scenes[BUS])
    assert obs.sources["Personal mic"] == personal
    assert state(result, "photo") == state(result, "camera") == state(result, "media") == "blocked"
    assert not result["ready"] and not result["failures"]
    before, start = snapshot(obs), len(obs.calls)
    repeated = service.complete(obs, AppSettings(), tmp_path, lambda: TARGET, threading.Event(), True)
    assert not repeated["changes"] and snapshot(obs) == before
    assert all(request.startswith("Get") for request, _ in obs.calls[start:])


def test_working_visual_sources_routes_custom_camera_and_filters_are_preserved(tmp_path):
    obs = MaintenanceObs()
    configure(obs)
    photo = tmp_path / "existing.png"
    photo.write_bytes(png())
    obs.add_source(PHOTO_SOURCE, "image_source", {"file": str(photo)}, "Texto do Ano")
    obs.add_source(
        CAMERA_SOURCE,
        "ffmpeg_source",
        {"input": "rtsp://custom-camera", "close_when_inactive": True},
        "Palco",
    )
    obs.add_source(SOURCE, KIND, dict(TARGET), "Mídias")
    before, start = snapshot(obs), len(obs.calls)
    result = service.complete(obs, AppSettings(), tmp_path, lambda: TARGET, threading.Event(), True)
    assert result["ready"] and not result["changes"] and not result["failures"]
    assert snapshot(obs) == before
    assert all(request.startswith("Get") for request, _ in obs.calls[start:])
    assert obs.sources[MIC]["monitor"] == MONITOR and not obs.sources[MIC]["mute"]


def test_missing_audio_item_is_completed_without_muting_or_rewriting_live_sources(tmp_path):
    obs = MaintenanceObs(jwl_plugin=False)
    configure(obs)
    obs.scenes[BUS] = [r for r in obs.scenes[BUS] if r["sourceName"] != MIC]
    sources, filters = deepcopy(obs.sources), deepcopy(obs.filters)
    start = len(obs.calls)
    result = service.complete(obs, AppSettings(), tmp_path, lambda: TARGET, threading.Event(), True)
    assert "Estrutura de áudio" in result["changes"]
    assert obs.sources == sources and obs.filters == filters
    assert len([r for r in obs.scenes[BUS] if r["sourceName"] == MIC]) == 1
    assert not next(r for r in obs.scenes[BUS] if r["sourceName"] == MIC)["sceneItemEnabled"]
    assert [r for r, _ in obs.calls[start:] if not r.startswith("Get")] == ["CreateSceneItem"]


def test_photo_camera_and_hwnd_capture_share_one_plan_without_a_program_change(tmp_path):
    obs = MaintenanceObs()
    settings = AppSettings(camera_username="operator", camera_password="private")
    store = YeartextStore(tmp_path)
    store.save(png(), datetime.now().year)
    result = service.complete(obs, settings, tmp_path, lambda: TARGET, threading.Event(), True)
    assert result["ready"] and not result["failures"]
    assert obs.sources[CAMERA_SOURCE]["settings"] == camera_source_settings(settings)
    assert obs.sources[CAMERA_SOURCE]["mute"]
    assert obs.sources[SOURCE]["settings"] == TARGET
    assert not store.current()["obs_pending"]
    assert not any(r in {"SetCurrentProgramScene", "RemoveInput", "SetSceneName"} for r, _ in obs.calls)
    assert "private" not in result["message"] and "private" not in json.dumps(result["rows"])


def test_missing_window_keeps_partial_success_and_retry_does_not_rebuild_audio(tmp_path):
    obs = MaintenanceObs()

    def missing():
        raise ValueError("Abra a segunda janela JWL.")

    result = service.complete(obs, AppSettings(), tmp_path, missing, threading.Event(), True)
    assert result["failures"] and SOURCE not in obs.sources
    assert state(result, "audio") == "ok"
    before = deepcopy(obs.sources)
    retry = service.complete(obs, AppSettings(), tmp_path, lambda: TARGET, threading.Event(), True)
    assert not retry["failures"] and state(retry, "media") == "ok"
    assert {n: obs.sources[n] for n in before} == before


def test_name_conflict_and_duplicate_audio_are_reported_without_replacement(tmp_path):
    obs = MaintenanceObs(jwl_plugin=False)
    configure(obs)
    obs.add_source(PHOTO_SOURCE, "window_capture", {"window": "personal"}, "Texto do Ano")
    obs.scenes[BUS].append(deepcopy(obs.scenes[BUS][0]))
    before = snapshot(obs)
    result = service.complete(obs, AppSettings(), tmp_path, lambda: TARGET, threading.Event(), True)
    assert state(result, "photo") == state(result, "audio") == "attention"
    assert not result["changes"] and snapshot(obs) == before


def test_explicit_camera_update_keeps_mapping_and_other_sources(tmp_path):
    obs = MaintenanceObs()
    obs.scenes["Minha câmera"] = obs.scenes.pop("Palco")
    before = deepcopy(obs.sources["Personal mic"])
    settings = AppSettings(scene_speaker="Minha câmera", camera_username="user", camera_password="secret")
    result = service.apply_camera(obs, settings)
    assert "confirmou" in result["message"] and "secret" not in result["message"]
    assert "Palco" not in obs.scenes and obs.sources["Personal mic"] == before
    assert obs.scenes["Minha câmera"][0]["sourceName"] == CAMERA_SOURCE
