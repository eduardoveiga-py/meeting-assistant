import subprocess
from unittest.mock import Mock

import pytest

from meeting_assistant.services import setup_assistant
from meeting_assistant.services.preflight import inspect_obs
from meeting_assistant.services.settings import AppSettings


@pytest.mark.parametrize("failed", ["GetSceneList", "GetVirtualCamStatus"])
def test_partial_query_failure_preserves_connection_and_other_evidence(failed):
    client = Mock()

    def send(request, **kwargs):
        if request == failed:
            raise RuntimeError("password=secret")
        return {
            "GetVersion": {},
            "GetSceneList": {"scenes": [{"sceneName": "Palco"}]},
            "GetVirtualCamStatus": {"outputActive": True},
        }[request]

    client.send.side_effect = send
    client.disconnect.side_effect = OSError("cleanup failed")
    rows = inspect_obs(AppSettings(), Mock(return_value=client))
    assert rows[0].passed is True
    assert rows[-1].passed is (None if failed == "GetVirtualCamStatus" else True)
    scene_rows = [row for row in rows if row.category == "CONFIGURAÇÃO"]
    if failed == "GetSceneList":
        assert all(row.passed is None for row in scene_rows)
    else:
        assert any(row.passed is True for row in scene_rows)
        assert any(row.passed is False for row in scene_rows)
    assert "secret" not in "\n".join(row.render() for row in rows)
    client.disconnect.assert_called_once()
    assert all(call.args[0].startswith("Get") for call in client.send.call_args_list)


def test_unavailable_obs_does_not_claim_missing_configuration():
    rows = inspect_obs(AppSettings(), Mock(side_effect=OSError("token=secret")))
    assert rows[0].passed is False
    assert all(row.passed is None for row in rows[1:])
    assert "NÃO VERIFICADO" in rows[1].render()


def test_jwl_timeout_does_not_abort_remaining_checks(monkeypatch):
    monkeypatch.setattr(setup_assistant, "find_obs_executable", lambda _: None)
    monkeypatch.setattr(
        setup_assistant.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("powershell", 20))
    )
    probe = Mock(return_value=[])
    monkeypatch.setattr(setup_assistant, "inspect_obs", probe)
    rows = setup_assistant.inspect_environment(AppSettings())
    assert next(row for row in rows if row.name == "JW Library detectado").passed is None
    probe.assert_called_once()
