from unittest.mock import Mock

import pytest

from meeting_assistant.services.ndi_output import OUTPUT_KIND, OUTPUT_NAME, NdiUnavailable, control_output
from meeting_assistant.ui.ndi_dialog import NdiDialog, NdiRequest


def client_for(active=False, transition=True):
    client = Mock()
    state = {"active": active}

    def send(name, args=None, raw=False):
        assert raw
        if name == "GetOutputList":
            return {"outputs": [
                {"outputName": "recording", "outputKind": "ffmpeg_muxer"},
                {"outputName": "NDI Preview Output", "outputKind": OUTPUT_KIND},
                {"outputName": OUTPUT_NAME, "outputKind": OUTPUT_KIND},
            ]}
        assert args == {"outputName": OUTPUT_NAME}
        if name == "GetOutputStatus":
            return {"outputActive": state["active"]}
        if name == "GetOutputSettings":
            return {"outputSettings": {"ndi_name": "Meeting Assistant", "secret": "not exported"}}
        assert name in {"StartOutput", "StopOutput"}
        if transition:
            state["active"] = name == "StartOutput"
        return {}

    client.send.side_effect = send
    return client


def test_start_stop_only_program_output_and_preserve_other_outputs():
    client = client_for()
    started = control_output(client, "start")
    assert started["active"] and started["confirmed"]
    assert started["source_name"] == "Meeting Assistant"
    assert "secret" not in str(started)
    assert not started["whatsapp_video_confirmed"]
    control_output(client, "start")  # Idempotent, no duplicate start.
    assert [c.args[0] for c in client.send.call_args_list].count("StartOutput") == 1
    stopped = control_output(client, "stop")
    assert not stopped["active"] and stopped["confirmed"]


@pytest.mark.parametrize("outputs", [[], [{"outputName": OUTPUT_NAME, "outputKind": "ffmpeg_muxer"}]])
def test_missing_or_wrong_output_never_changes_obs(outputs):
    client = Mock()
    client.send.return_value = {"outputs": outputs}
    with pytest.raises(NdiUnavailable):
        control_output(client, "start")
    client.send.assert_called_once_with("GetOutputList", raw=True)


def test_pending_transition_not_reported_as_success():
    result = control_output(client_for(transition=False), "start")
    assert not result["active"] and not result["confirmed"]


def test_inspect_does_not_mutate():
    client = client_for(True)
    control_output(client)
    assert all(c.args[0].startswith("Get") for c in client.send.call_args_list)


def test_ndi_ui_keeps_output_and_waits_for_worker_before_close(qt_application):
    dialog = NdiDialog()
    dialog.worker = Mock()
    dialog.reject()
    assert "Aguarde" in dialog.status.text()
    dialog.worker = None
    dialog.received(control_output(client_for(True)), "")
    assert "ATIVA" in dialog.status.text()
    assert not dialog.report["whatsapp_video_confirmed"]
    dialog.reject()  # No implicit StopOutput.


def test_failure_redacts_connection_details(monkeypatch, qt_application):
    monkeypatch.setattr("meeting_assistant.ui.ndi_dialog.run_action",
                        Mock(side_effect=RuntimeError("password=private")))
    worker = NdiRequest("inspect")
    observed = []
    worker.result.connect(lambda report, error: observed.append((report, error)))
    worker.run()
    assert observed[0][0] is None
    assert "private" not in observed[0][1]
