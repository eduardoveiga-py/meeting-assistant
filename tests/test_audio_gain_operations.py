"""Volume changes must never silence, enable or redirect an existing audio source."""

from copy import deepcopy

import pytest
from test_obs_audio import FakeObs, selection

from meeting_assistant.services.audio_routes import GAIN, LIMITER, WHATSAPP_MONITOR, NOISE_GATE, COMPRESSOR
from meeting_assistant.services.obs_audio import MIC, SOURCES, app_name, run_audio_task

pytestmark = pytest.mark.usefixtures("audio_monitor_profile")


def configured(monkeypatch, profile="shared"):
    outputs = [
        {"itemName": "CABLE Input", "itemValue": "cable"},
        {"itemName": "CABLE-B Input", "itemValue": "second-cable"},
    ]
    monkeypatch.setattr("meeting_assistant.services.obs_audio.virtual_outputs", lambda: outputs)
    monkeypatch.setattr("meeting_assistant.services.audio_routes.virtual_outputs", lambda: outputs)
    obs = FakeObs()
    run_audio_task(obs, "prepare", {})
    data = selection() | {"gains_db": {MIC: 2.0, app_name("JW Library"): 1.0}}
    if profile == "whatsapp_zoom":
        data.update(profile=profile, whatsapp_device="second-cable")
        data["applications"]["Zoom"] = "Playing:class:zoom.exe"
    run_audio_task(obs, "activate", data)
    return obs


@pytest.mark.parametrize("profile", ["shared", "whatsapp_zoom"])
def test_read_only_discovery_preserves_all_live_sources_filters_and_scenes(monkeypatch, profile):
    obs = configured(monkeypatch, profile)
    before = deepcopy(obs.sources), deepcopy(obs.scenes), deepcopy(obs.filters)
    start = len(obs.calls)
    snapshot = run_audio_task(obs, "inspect", {})
    assert (obs.sources, obs.scenes, obs.filters) == before
    assert all(r.startswith("Get") for r, _ in obs.calls[start:])
    assert not snapshot["needs_prepare"]
    assert snapshot["source_states"][MIC] == {"gain_ready": True, "gain_db": 2.0}
    assert snapshot["selected"][MIC]["device_id"] == "physical"
    assert snapshot["selected"][app_name("JW Library")]["window"] == "Playing:class:jwlibrary.exe"
    assert snapshot["selected"][app_name("Edge")]["window"] == ""
    if profile == "whatsapp_zoom":
        assert snapshot["whatsapp_device"] == "second-cable"


def test_inspect_without_sources_does_not_create_or_mute_anything(monkeypatch):
    obs = FakeObs()
    monkeypatch.setattr("meeting_assistant.services.obs_audio.virtual_outputs", lambda: [])
    start = len(obs.calls)
    result = run_audio_task(obs, "inspect", {})
    assert result["needs_prepare"] and result["missing_sources"] == list(SOURCES)
    assert all(r.startswith("Get") for r, _ in obs.calls[start:])
    assert not obs.sources["Personal mic"]["mute"]


@pytest.mark.parametrize("profile", ["shared", "whatsapp_zoom"])
def test_single_gain_write_preserves_routes_tracks_other_filters_and_mutes(monkeypatch, profile):
    obs = configured(monkeypatch, profile)
    before_sources, before_scenes = deepcopy(obs.sources), deepcopy(obs.scenes)
    before_filters = deepcopy(obs.filters)
    start = len(obs.calls)
    result = run_audio_task(obs, "gains", {"gains_db": {MIC: 5.0}})
    assert result["gains_db"] == {MIC: 5.0}
    assert obs.sources == before_sources and obs.scenes == before_scenes
    gain = next(f for f in before_filters[MIC] if f["filterName"] == GAIN)
    gain["filterSettings"]["db"] = 5.0
    assert obs.filters == before_filters
    writes = [(r, d) for r, d in obs.calls[start:] if not r.startswith("Get")]
    assert [r for r, _ in writes] == ["SetSourceFilterSettings"]
    assert writes[0][1]["sourceName"] == MIC


@pytest.mark.parametrize("change", [
    {"gain": -1}, {"gain": 19}, {"gain": True}, {"gain": float("nan")},
    {"gain": "8"}, {"source": "Personal mic"}, {"source": "missing"},
    {"missing": True}, {"limiter_disabled": True}, {"gain_disabled": True}, {"wrong_order": True},
])
def test_invalid_volume_request_has_no_side_effects(monkeypatch, change):
    obs = configured(monkeypatch)
    if change.get("missing"):
        del obs.sources[MIC]
    if change.get("limiter_disabled"):
        next(f for f in obs.filters[MIC] if f["filterName"] == LIMITER)["filterEnabled"] = False
    if change.get("gain_disabled"):
        next(f for f in obs.filters[MIC] if f["filterName"] == GAIN)["filterEnabled"] = False
    if change.get("wrong_order"):
        obs.filters[MIC].reverse()
    before = deepcopy(obs.sources), deepcopy(obs.scenes), deepcopy(obs.filters)
    start = len(obs.calls)
    data = {change.get("source", MIC): change.get("gain", 3.0)}
    with pytest.raises(ValueError):
        run_audio_task(obs, "gains", {"gains_db": data})
    # A GetSourceFilterList may allocate an empty fake bucket but must not mutate real filters.
    assert obs.sources == before[0] and obs.scenes == before[1]
    assert obs.filters == before[2]
    assert all(r.startswith("Get") for r, _ in obs.calls[start:])


def test_partial_failure_rolls_back_only_attempted_gains_without_muting(monkeypatch):
    obs = configured(monkeypatch)
    before = deepcopy(obs.sources), deepcopy(obs.scenes), deepcopy(obs.filters)
    send = obs.send
    failed = False
    media = app_name("JW Library")

    def fail_once(request, data=None, **kwargs):
        nonlocal failed
        if request == "SetSourceFilterSettings" and data["sourceName"] == media and not failed:
            failed = True
            raise RuntimeError("Injected second-write failure")
        return send(request, data, **kwargs)

    obs.send = fail_once
    start = len(obs.calls)
    with pytest.raises(ValueError, match="anteriores restaurados"):
        run_audio_task(obs, "gains", {"gains_db": {MIC: 6.0, media: 4.0}})
    assert (obs.sources, obs.scenes, obs.filters) == before
    assert all(r.startswith("Get") or r == "SetSourceFilterSettings" for r, _ in obs.calls[start:])


def test_failed_readback_is_reported_without_success_or_route_changes(monkeypatch):
    obs = configured(monkeypatch)
    before = deepcopy(obs.sources), deepcopy(obs.scenes), deepcopy(obs.filters)
    obs.ignore_filter_updates = True
    with pytest.raises(ValueError, match="não confirmou"):
        run_audio_task(obs, "gains", {"gains_db": {MIC: 8.0}})
    assert (obs.sources, obs.scenes, obs.filters) == before


def test_missing_bus_offers_repair_while_existing_gains_remain_available(monkeypatch):
    from meeting_assistant.services.obs_audio import BUS

    obs = configured(monkeypatch)
    del obs.scenes[BUS]
    snapshot = run_audio_task(obs, "inspect", {})
    assert snapshot["needs_prepare"] and not snapshot["missing_sources"]
    assert snapshot["source_states"][MIC]["gain_ready"]
    # The volume operation intentionally does not rebuild or reactivate that scene.
    run_audio_task(obs, "gains", {"gains_db": {MIC: 3.0}})
    assert BUS not in obs.scenes


def test_whatsapp_filter_remains_after_limiter_when_adjusting_zoom_volume(monkeypatch):
    obs = configured(monkeypatch, "whatsapp_zoom")
    zoom = app_name("Zoom")
    filters = deepcopy(obs.filters[zoom])
    run_audio_task(obs, "gains", {"gains_db": {zoom: 3.0}})
    actual = obs.filters[zoom]
    assert [f["filterName"] for f in actual] == [NOISE_GATE, COMPRESSOR, GAIN, LIMITER, WHATSAPP_MONITOR]
    assert actual[-1] == filters[-1] and actual[1] == filters[1]
