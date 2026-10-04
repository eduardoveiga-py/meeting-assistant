"""Exercise the device-state format of the pinned pycaw release, including COM cleanup."""

from enum import Enum
from types import ModuleType, SimpleNamespace

import pytest
from test_obs_audio import FakeObs

from meeting_assistant.services.audio_routes import validate_route, virtual_outputs


class DeviceState(Enum):
    Active = 1
    Disabled = 2
    Unplugged = 8


def fake_windows_devices(monkeypatch, *, fail=False):
    devices = [
        SimpleNamespace(id="cable", FriendlyName="CABLE-A Input", state=DeviceState.Active),
        SimpleNamespace(id="second-cable", FriendlyName="CABLE-B Input", state=DeviceState.Active),
        SimpleNamespace(id="recording", FriendlyName="CABLE-B Output", state=DeviceState.Active),
        SimpleNamespace(id="disabled", FriendlyName="CABLE-C Input", state=DeviceState.Disabled),
        SimpleNamespace(id="unplugged", FriendlyName="Virtual unplugged", state=DeviceState.Unplugged),
        SimpleNamespace(id="legacy", FriendlyName="Virtual old wrapper", state=1),
        SimpleNamespace(id="speakers", FriendlyName="Speakers", state=DeviceState.Active),
    ]
    events = []
    pythoncom = ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: events.append("initialize")
    pythoncom.CoUninitialize = lambda: events.append("uninitialize")
    utilities = SimpleNamespace(GetAllDevices=lambda: devices)

    def flow(device_id, output_type):
        assert output_type == 1
        if fail:
            raise RuntimeError("Enumeration unavailable")
        return 1 if device_id == "recording" else 0

    utilities.GetEndpointDataFlow = flow
    pycaw = ModuleType("pycaw")
    pycaw.__path__ = []
    pycaw_module = ModuleType("pycaw.pycaw")
    pycaw_module.AudioUtilities = utilities
    monkeypatch.setitem(__import__("sys").modules, "pythoncom", pythoncom)
    monkeypatch.setitem(__import__("sys").modules, "pycaw", pycaw)
    monkeypatch.setitem(__import__("sys").modules, "pycaw.pycaw", pycaw_module)
    monkeypatch.setattr("meeting_assistant.services.audio_routes.sys.platform", "win32")
    return events


def test_active_enum_devices_are_listed_and_recording_disabled_and_physical_outputs_are_excluded(
    monkeypatch
):
    with monkeypatch.context() as patch:
        events = fake_windows_devices(patch)
        outputs = virtual_outputs()
    assert outputs == [
        {"itemName": "CABLE-A Input", "itemValue": "cable"},
        {"itemName": "CABLE-B Input", "itemValue": "second-cable"},
        {"itemName": "Virtual old wrapper", "itemValue": "legacy"},
    ]
    assert events == ["initialize", "uninitialize"]


def test_com_is_released_when_device_enumeration_fails(monkeypatch):
    with monkeypatch.context() as patch:
        events = fake_windows_devices(patch, fail=True)
        with pytest.raises(RuntimeError, match="Enumeration"):
            virtual_outputs()
    assert events == ["initialize", "uninitialize"]


def test_enum_second_cable_is_validated_without_mocking_the_output_discovery(
    monkeypatch, audio_monitor_profile
):
    with monkeypatch.context() as patch:
        events = fake_windows_devices(patch)
        route = validate_route(FakeObs(), {
            "profile": "whatsapp_zoom", "whatsapp_device": "second-cable",
            "applications": {"Zoom": "Playing:class:zoom.exe"}, "gains_db": {},
        })
    assert route == ("whatsapp_zoom", "second-cable")
    assert events == ["initialize", "uninitialize"]
