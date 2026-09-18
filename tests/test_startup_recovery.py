import logging
from types import SimpleNamespace

import pytest
from obsws_python.error import OBSSDKRequestError

from meeting_assistant.services import meeting_launcher, obs_controller


def run_launcher(monkeypatch, *, initially_open=False, disappears_at=None):
    clock = [0.0]
    service = meeting_launcher.MeetingLauncherService(
        lambda: SimpleNamespace(zoom_join_url="", obs_executable="")
    )
    launches = []
    summaries = []
    messages = []
    service.finished.connect(summaries.append)
    service.progress_changed.connect(messages.append)

    def snapshot():
        processes = {1: "obs64.exe", 2: "Zoom.exe"}
        if (initially_open or launches) and (disappears_at is None or clock[0] < disappears_at):
            processes[3] = "JWLibrary.exe"
        return processes

    monkeypatch.setattr(meeting_launcher.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        meeting_launcher.time, "sleep", lambda duration: clock.__setitem__(0, clock[0] + duration)
    )
    monkeypatch.setattr(service, "_process_snapshot", snapshot)
    monkeypatch.setattr(service, "_launch_jwl", lambda: launches.append(True) or True)
    monkeypatch.setattr(service, "_zoom_meeting_active", lambda: True)
    service._run()
    return clock[0], launches, summaries[0], messages


def test_jwl_disappearance_after_28_seconds_is_reported_not_relaunched(monkeypatch):
    elapsed, launches, summary, messages = run_launcher(monkeypatch, disappears_at=28)
    assert 28 <= elapsed < 29
    assert len(launches) == 1
    assert not summary.jwl_running
    assert summary.jwl_exited_during_startup
    assert any("abriu e fechou" in note for note in summary.notes)
    assert "pendências" in messages[-1]


def test_new_jwl_launch_is_observed_beyond_initial_process_detection(monkeypatch):
    elapsed, launches, summary, _ = run_launcher(monkeypatch)
    assert 45 <= elapsed < 46
    assert len(launches) == 1
    assert summary.jwl_running
    assert not summary.jwl_exited_during_startup


def test_existing_apps_are_not_reopened_or_delayed(monkeypatch):
    elapsed, launches, summary, _ = run_launcher(monkeypatch, initially_open=True)
    assert elapsed == 0
    assert launches == []
    assert summary.zoom_meeting_active


@pytest.mark.parametrize("request_name", ["GetVersion", "GetSceneList", "GetCurrentProgramScene"])
def test_obs_not_ready_closes_socket_and_does_not_report_connected(monkeypatch, request_name):
    closed = []
    states = []

    class Client:
        base_client = SimpleNamespace(ws=SimpleNamespace(close=lambda: closed.append(True)))

        def send(self, name, *args, **kwargs):
            if name == request_name:
                raise OBSSDKRequestError(name, 207, "OBS is not ready to perform the request.")
            return {"obsVersion": "test", "scenes": [], "currentProgramSceneName": "Palco"}

    monkeypatch.setattr(obs_controller.obs, "ReqClient", lambda **kwargs: Client())
    controller = obs_controller.ObsController()
    controller._config = obs_controller.ObsConnectionConfig("localhost", 4455, "")
    controller.connected_changed.connect(lambda *args: states.append(args))
    assert not controller._connect()
    assert controller._client is None
    assert closed == [True]
    assert len(states) == 1 and states[0][0] is False
    assert "iniciando ou encerrando" in states[0][1]


def test_repeated_connection_status_is_deduplicated_but_recovery_is_reported():
    controller = obs_controller.ObsController()
    states = []
    controller.connected_changed.connect(lambda *args: states.append(args))
    controller._set_connected(False, "aguardando")
    controller._set_connected(False, "aguardando")
    controller._set_connected(True, "conectado")
    controller._set_connected(False, "aguardando")
    assert states == [(False, "aguardando"), (True, "conectado"), (False, "aguardando")]


@pytest.mark.parametrize("exc,expected", [
    (TimeoutError("timed out"), False),
    (ConnectionRefusedError("refused"), False),
    (OBSSDKRequestError("GetVersion", 207, "not ready"), False),
    (OBSSDKRequestError("GetVersion", 500, "unexpected"), True),
    (ValueError("authentication failed"), True),
])
def test_log_filter_only_removes_handled_transient_errors(exc, expected):
    record = logging.LogRecord("obs", logging.ERROR, "", 0, str(exc), (), (type(exc), exc, None))
    assert obs_controller._TransientObsLogFilter().filter(record) is expected


def test_preview_not_ready_stops_requests_until_reconnection():
    closed = []

    class Client:
        base_client = SimpleNamespace(ws=SimpleNamespace(close=lambda: closed.append(True)))

        def send(self, *args, **kwargs):
            raise OBSSDKRequestError("GetSourceScreenshot", 207, "not ready")

    controller = obs_controller.ObsController()
    controller._client = Client()
    controller._last_scene = "Palco"
    controller._refresh_preview()
    assert controller._client is None
    assert closed == [True]
