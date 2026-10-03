import pytest
from test_obs_audio import FakeObs, selection

from meeting_assistant.services.audio_routes import GAIN, LIMITER, WHATSAPP_MONITOR
from meeting_assistant.services.obs_audio import (
    MIC,
    MONITOR,
    NONE,
    SOURCES,
    activate,
    app_name,
    mute_managed,
    prepare,
)

pytestmark = pytest.mark.usefixtures("audio_monitor_profile")


@pytest.fixture
def separate_devices(monkeypatch):
    monkeypatch.setattr(
        "meeting_assistant.services.audio_routes.virtual_outputs",
        lambda: [{"itemName": "CABLE-A Input", "itemValue": "second-cable"}],
    )


def advanced():
    data = selection()
    data.update(profile="whatsapp_zoom", whatsapp_device="second-cable")
    data["applications"]["Zoom"] = "Meeting:class:Zoom.exe"
    return data


def test_shared_mix_refuses_remote_zoom_and_silences_previous_route():
    obs = FakeObs()
    prepare(obs)
    activate(obs, selection())
    data = selection()
    data["applications"]["Zoom"] = "Meeting:class:Zoom.exe"
    with pytest.raises(ValueError, match="próprio Zoom"):
        activate(obs, data)
    assert all(obs.sources[name]["mute"] for name in SOURCES)


@pytest.mark.parametrize("device", ["cable", "default", "physical", "removed"])
def test_separate_mix_rejects_same_cable_and_nonvirtual_devices(separate_devices, device):
    obs = FakeObs()
    prepare(obs)
    with pytest.raises(ValueError, match="segunda entrada"):
        activate(obs, advanced() | {"whatsapp_device": device})
    assert all(obs.sources[n]["mute"] for n in SOURCES)


def test_zoom_is_sent_only_to_second_cable_and_all_routes_can_be_muted(separate_devices):
    obs = FakeObs()
    prepare(obs)
    result = activate(obs, advanced())
    assert result["profile"] == "whatsapp_zoom"
    zoom = app_name("Zoom")
    assert obs.sources[zoom]["monitor"] == NONE
    assert obs.sources[MIC]["monitor"] == MONITOR
    for source in (MIC, zoom, app_name("JW Library")):
        assert all(not enabled for enabled in obs.sources[source]["tracks"].values())
        last = obs.filters[source][-1]
        assert last["filterName"] == WHATSAPP_MONITOR
        assert last["filterSettings"]["device"] == "second-cable"
        assert last["filterSettings"]["mute"] == 2
        assert last["filterEnabled"]
    mute_managed(obs)
    assert all(obs.sources[n]["mute"] for n in SOURCES)
    assert all(
        not f["filterEnabled"]
        for filters in obs.filters.values()
        for f in filters
        if f["filterName"] == WHATSAPP_MONITOR
    )


def test_plugin_missing_fails_closed_without_success_message(separate_devices):
    obs = FakeObs()
    prepare(obs)
    obs.plugin_available = False
    with pytest.raises(RuntimeError):
        activate(obs, advanced())
    assert all(obs.sources[n]["mute"] and obs.sources[n]["monitor"] == NONE for n in SOURCES)


def test_gain_is_adjustable_verified_and_before_limiter():
    obs = FakeObs()
    prepare(obs)
    activate(obs, selection() | {"gains_db": {MIC: 6.0, app_name("JW Library"): 2.0}})
    assert obs.filters[MIC][-2]["filterName"] == GAIN
    assert obs.filters[MIC][-2]["filterSettings"]["db"] == 6.0
    assert obs.filters[MIC][-1]["filterName"] == LIMITER
    assert obs.filters[MIC][-1]["filterSettings"]["threshold"] == -3.0
    obs.ignore_filter_updates = True
    with pytest.raises(ValueError, match="confirmou o filtro"):
        activate(obs, selection() | {"gains_db": {MIC: 8.0}})
    assert all(obs.sources[n]["mute"] for n in SOURCES)


@pytest.mark.parametrize("gain", [-1, 19, True, float("nan"), "8"])
def test_invalid_gain_does_not_reactivate_route(gain):
    obs = FakeObs()
    prepare(obs)
    with pytest.raises(ValueError):
        activate(obs, selection() | {"gains_db": {MIC: gain}})
    assert all(obs.sources[n]["mute"] for n in SOURCES)


def test_filter_failure_does_not_prevent_independent_mute_and_monitor_off():
    obs = FakeObs()
    prepare(obs)
    activate(obs, selection())
    send = obs.send

    def fail_filter(request, data=None, **kw):
        if request == "GetSourceFilterList" and data["sourceName"] == MIC:
            raise RuntimeError("Missing filter response")
        return send(request, data, **kw)

    obs.send = fail_filter
    with pytest.raises(ValueError, match="Silêncio"):
        mute_managed(obs)
    assert obs.sources[MIC]["mute"] and obs.sources[MIC]["monitor"] == NONE
