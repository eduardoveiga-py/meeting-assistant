import time
from unittest.mock import Mock

import pytest

from meeting_assistant.services.local_host import is_local_host
from meeting_assistant.services.obs_controller import ObsController
from meeting_assistant.services.obs_monitor_device import monitoring_device


def client():
    obs = Mock()
    obs.send.return_value = {"currentProfileName": "Salão"}
    return obs


def test_monitor_device_uses_saved_current_profile_not_invented_websocket_request(tmp_path):
    directory = tmp_path / "profile"
    directory.mkdir()
    (directory / "basic.ini").write_text(
        "[General]\nName=Salão\n[Audio]\nMonitoringDeviceId=actual-cable\nMonitoringDeviceName=CABLE Input\n",
        encoding="utf-8",
    )
    obs = client()
    snapshot = monitoring_device(obs, tmp_path)
    assert snapshot["monitorDeviceId"] == "actual-cable"
    assert snapshot["measurement"] == "saved_local_profile_operator_confirmation_required"
    obs.send.assert_called_once_with("GetProfileList", raw=True)


def test_ambiguous_or_missing_profile_does_not_claim_monitoring_verified(tmp_path):
    obs = client()
    with pytest.raises(ValueError):
        monitoring_device(obs, tmp_path)
    for folder in ("one", "two"):
        profile = tmp_path / folder
        profile.mkdir()
        (profile / "basic.ini").write_text("[General]\nName=Salão\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ambíguo"):
        monitoring_device(obs, tmp_path)


def test_interface_enumeration_permission_failure_is_not_local(monkeypatch):
    def denied():
        raise PermissionError("interface enumeration denied")

    monkeypatch.setattr("psutil.net_if_addrs", denied)
    assert not is_local_host("10.0.0.40")
    assert is_local_host("127.0.0.1")


def test_audio_meter_delivery_does_not_start_or_request_jpeg_preview():
    obs = ObsController()
    received = []
    obs.audio_levels_changed.connect(received.append)
    obs.audio_levels.latest = (time.monotonic(), -12.0, -8.0)
    obs._deliver_audio_levels()
    assert received[-1] == (-12.0, -8.0)
    assert not obs._preview_delivery.isActive()
    assert obs._commands.empty()
    obs.audio_levels.latest = (time.monotonic() - 5, -1.0, -1.0)
    obs._deliver_audio_levels()
    assert received[-1] == (None, None)
