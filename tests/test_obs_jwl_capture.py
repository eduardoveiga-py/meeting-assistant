import json
import threading
from types import SimpleNamespace

import pytest
from test_obs_hall_setup import FakeObs, binding
from test_review_capture_external import VisualObs

from meeting_assistant.services import jwl_capture_target
from meeting_assistant.services.obs_capture_safety import assert_safe_media
from meeting_assistant.services.obs_hall_setup import MEDIA_SOURCE, prepare_media
from meeting_assistant.services.obs_jwl_capture import (
    KIND,
    SOURCE,
    JwlCaptureRuntime,
    confirmed_status,
)


def prepared():
    obs = VisualObs()
    prepare_media(obs, "Mídias", binding())
    return obs


def test_missing_plugin_does_not_create_or_enable_wrong_source():
    obs = FakeObs()
    obs.kinds.remove(KIND)
    with pytest.raises(ValueError, match="Plugin.*ausente"):
        prepare_media(obs, "Mídias", binding())
    assert obs.inputs == {} and obs.scenes == {}


def test_wrong_native_source_type_is_preserved_and_rejected():
    obs = FakeObs()
    obs.inputs[SOURCE] = {"kind": "window_capture", "settings": {"window": "Zoom:Class:Zoom.exe"}}
    with pytest.raises(ValueError, match="outro tipo"):
        prepare_media(obs, "Mídias", binding())
    assert obs.inputs[SOURCE]["settings"]["window"] == "Zoom:Class:Zoom.exe"


def test_legacy_jwl_preserved_elsewhere_and_disabled_only_after_native_image():
    obs = VisualObs()
    obs.inputs[MEDIA_SOURCE] = {"kind": "window_capture", "settings": {"window": "original"}}
    for scene in ("Mídias", "Operator capture"):
        obs.scenes[scene] = [{"sourceName": MEDIA_SOURCE, "sceneItemId": 4, "sceneItemEnabled": True}]
    prepare_media(obs, "Mídias", binding())
    assert obs.inputs[MEDIA_SOURCE]["settings"] == {"window": "original"}
    assert not obs.scenes["Mídias"][0]["sceneItemEnabled"]
    assert obs.scenes["Operator capture"][0]["sceneItemEnabled"]
    assert obs.program == "Palco"
    assert not any(request.startswith("Remove") for request, _ in obs.calls)


def test_settings_acknowledgement_without_frame_is_not_success():
    obs = VisualObs()
    obs.native_state = "waiting"
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(ValueError, match="Captura"):
        prepare_media(obs, "Mídias", binding(), cancelled)
    assert not obs.scenes["Mídias"][0]["sceneItemEnabled"]
    assert obs.program == "Palco"


@pytest.mark.parametrize("field,value", [("hwnd", "99"), ("created", "20000"), ("session", "b" * 32)])
def test_native_stale_image_rejected_even_if_settings_acknowledged(field, value):
    obs = prepared()
    obs.native_identity = binding()
    obs.native_identity[field] = value
    with pytest.raises(ValueError, match="não corresponde"):
        assert_safe_media(obs, "Mídias")


@pytest.mark.parametrize("state", ["waiting", "capture_failed", "invalid_target", "unbound"])
def test_only_native_active_state_is_success(state):
    obs = prepared()
    obs.native_state = state
    with pytest.raises(ValueError, match=state):
        confirmed_status(obs)


def test_simulation_cannot_bypass_monitor_loop_safety(tmp_path, monkeypatch):
    settings = tmp_path / "MeetingAssistant"
    settings.mkdir()
    (settings / "settings.json").write_text(json.dumps({"simulation_enabled": True}))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    obs = prepared()
    obs.inputs["Desktop"] = {"kind": "monitor_capture", "settings": {}}
    obs.scenes["Mídias"].append({"sourceName": "Desktop", "sceneItemId": 2, "sceneItemEnabled": True})
    with pytest.raises(ValueError, match="Captura de monitor"):
        assert_safe_media(obs, "Mídias")


def test_renamed_zoom_source_cannot_impersonate_native_jwl():
    obs = prepared()
    obs.inputs[SOURCE] = {"kind": "window_capture", "settings": {"window": "Zoom:Class:Zoom.exe"}}
    with pytest.raises(ValueError, match="por HWND não preparada"):
        assert_safe_media(obs, "Mídias")


def test_zoom_window_in_nested_scene_still_blocked_and_preserved():
    obs = prepared()
    obs.inputs["Zoom return"] = {"kind": "window_capture", "settings": {"window": "Zoom:Class:Zoom.exe"}}
    obs.scenes["Shared"] = [{"sourceName": "Zoom return", "sceneItemId": 3, "sceneItemEnabled": True}]
    obs.scenes["Mídias"].append({"sourceName": "Shared", "sceneItemId": 2, "sceneItemEnabled": True})
    with pytest.raises(ValueError, match="Outra captura"):
        assert_safe_media(obs, "Mídias")
    assert obs.scenes["Shared"][0]["sceneItemEnabled"] and obs.program == "Palco"


def test_runtime_rebinds_restarted_jwl_once_without_scene_or_window_commands(monkeypatch):
    obs = prepared()
    runtime = JwlCaptureRuntime()
    current = binding()
    monkeypatch.setattr(runtime, "target", lambda: dict(current))
    runtime.sync(obs)
    count = sum(r == "SetInputSettings" for r, _ in obs.calls)
    assert runtime.sync(obs) is None
    assert sum(r == "SetInputSettings" for r, _ in obs.calls) == count
    current.update(hwnd="77", pid=222, created="20000", jwl_hwnd="78", jwl_pid=223, jwl_created="20001")
    status = runtime.sync(obs)
    assert status["hwnd"] == "77"
    assert sum(r == "SetInputSettings" for r, _ in obs.calls) == count + 1
    assert obs.program == "Palco"


def test_missing_jwl_invalidates_old_hwnd_without_selecting_zoom(monkeypatch):
    obs = prepared()
    runtime = JwlCaptureRuntime()

    def missing():
        raise ValueError("JWL ausente")

    monkeypatch.setattr(runtime, "target", missing)
    assert runtime.sync(obs)["state"] == "unavailable"
    assert obs.inputs[SOURCE]["settings"]["hwnd"] == "0"
    assert not any(data and data.get("propertyName") == "window" for _, data in obs.calls)


def observation():
    return {"hwnd": 7, "pid": 123, "created": "10001", "process": "ApplicationFrameHost.exe",
            "class": "ApplicationFrameWindow", "jwl": (8, 124, "10002"), "visible": True,
            "minimized": False, "cloaked": False, "monitor": (-1920, 0, 0, 1080), "primary": False,
            "target": (-1920, 0, 0, 1080), "rect": (-1920, 0, 0, 1080)}


def candidate():
    return SimpleNamespace(hwnd=7, pid=123, class_name="ApplicationFrameWindow", title="")


def test_untitled_uwp_child_and_negative_monitor_coordinates_use_exact_hwnd(monkeypatch):
    monkeypatch.setattr(jwl_capture_target, "_observe", lambda *args: observation())
    result = jwl_capture_target.capture_binding(candidate(), object(), "a" * 32)
    assert result == binding()
    assert "title" not in result and "window" not in result


@pytest.mark.parametrize("field,value", [("pid", 999), ("process", "Zoom.exe"), ("primary", True),
                                       ("cloaked", True), ("monitor", (0, 0, 1920, 1080)),
                                       ("rect", (-100, 0, 0, 100))])
def test_wrong_identity_or_monitor_role_is_rejected(field, value, monkeypatch):
    observed = observation()
    observed[field] = value
    monkeypatch.setattr(jwl_capture_target, "_observe", lambda *args: observed)
    with pytest.raises(ValueError):
        jwl_capture_target.capture_binding(candidate(), object(), "a" * 32)


def test_obs_capture_failure_does_not_disconnect_working_audio_connection(monkeypatch):
    from meeting_assistant.services.obs_controller import ObsController

    controller = ObsController()
    controller._client = prepared()
    controller.local_connection = True
    client = controller._client
    statuses = []
    controller.jwl_capture_status.connect(statuses.append)

    def failed(*args):
        raise RuntimeError("Plugin deleted")

    monkeypatch.setattr(controller.jwl_capture, "sync", failed)
    controller._sync_jwl_capture()
    assert controller._client is client
    assert statuses[-1]["state"] == "unavailable"


def test_program_changes_to_media_only_after_current_runtime_identity_is_confirmed(monkeypatch):
    from meeting_assistant.services.obs_controller import ObsController

    controller = ObsController()
    obs = prepared()
    controller._client = obs
    controller.local_connection = True
    monkeypatch.setattr(controller.jwl_capture, "target", lambda: binding())
    controller._handle_set_scene("Mídias")
    assert obs.program == "Mídias"
    status_calls = [i for i, (r, _) in enumerate(obs.calls) if r == "GetInputPropertiesListPropertyItems"]
    program_call = next(i for i, (r, _) in enumerate(obs.calls) if r == "SetCurrentProgramScene")
    assert status_calls and max(status_calls) < program_call


def test_new_runtime_generation_cannot_switch_program_with_old_native_image(monkeypatch):
    from meeting_assistant.services.obs_controller import ObsController

    controller = ObsController()
    obs = prepared()
    obs.native_identity = binding()
    controller._client = obs
    controller.local_connection = True
    # Make the bounded frame wait stop immediately, while still allowing sync.
    controller._stop_event.set()
    monkeypatch.setattr(controller.jwl_capture, "target", lambda: binding("77"))
    controller._handle_set_scene("Mídias")
    assert obs.program == "Palco"
    assert not any(r == "SetCurrentProgramScene" for r, _ in obs.calls)
