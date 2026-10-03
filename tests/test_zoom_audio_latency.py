import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from test_zoom_microphone import Button, Node, Window, install_pattern_exception, wait_until

from meeting_assistant.services.zoom_audio import ZoomAudio, perform
from meeting_assistant.services.zoom_audio_controls import MicrophoneError, find_control
from meeting_assistant.services.zoom_audio_session import ZoomAudioSession


def make_session(button, *, birth=None):
    birth = birth or [12.0]
    window = Window([button])
    window.descendants = Mock(wraps=window.descendants)
    windows = [window]
    discover = Mock(side_effect=lambda **kwargs: find_control(
        windows=windows, pids={7: birth[0]}, **kwargs
    ))
    session = ZoomAudioSession(discover, birth_reader=lambda _pid: birth[0])
    return session, window, windows, discover


def toggling_button():
    button = Button("Unmute my audio (Alt+A)")
    button.element_info.runtime_id = 0

    def invoke():
        button._name = (
            "Mute my audio (Alt+A)" if button._name.startswith("Unmute")
            else "Unmute my audio (Alt+A)"
        )

    button.iface_invoke.Invoke.side_effect = invoke
    return button


def test_inspection_and_repeated_toggles_only_discover_once(monkeypatch):
    install_pattern_exception(monkeypatch)
    sleep = Mock()
    monkeypatch.setattr("meeting_assistant.services.zoom_audio.time.sleep", sleep)
    button = toggling_button()
    session, window, _windows, discover = make_session(button)
    session.begin({})
    assert perform("inspect", session) == "muted"
    for expected in ("live", "muted", "live", "muted"):
        details = {}
        session.begin(details)
        assert perform("toggle", session, diagnostic=details) == expected
        assert details["discovery_calls"] == 0
        assert details["refresh_calls"] == 2
        assert details["lookup_path"] == "direct"
        assert all(details[key] >= 0 for key in ("read_state_ms", "invoke_ms", "confirmation_ms"))
    discover.assert_called_once()
    window.descendants.assert_called_once()
    assert button.iface_invoke.Invoke.call_count == 4
    sleep.assert_not_called()


def test_slow_confirmation_lookup_does_not_schedule_more_scans_past_deadline(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("meeting_assistant.services.zoom_audio.time.monotonic", lambda: clock[0])
    button = Mock()
    calls = []

    def finder():
        calls.append(True)
        if len(calls) == 1:
            return button, "muted"
        clock[0] += 3.0  # A synchronous provider call used the whole observation budget.
        raise MicrophoneError("control_not_found", "Unavailable")

    details = {}
    with pytest.raises(MicrophoneError) as caught:
        perform("toggle", finder, diagnostic=details)
    assert caught.value.code == "not_confirmed"
    assert len(calls) == 2
    assert details["confirmation_ms"] == 3000
    button.invoke.assert_called_once()


def test_direct_refresh_discards_pywinauto_property_cache_before_reading(monkeypatch):
    install_pattern_exception(monkeypatch)
    button = toggling_button()
    memoized = [True]
    button.window_text = lambda: "Unmute my audio (Alt+A)" if memoized[0] else button._name
    setter = Mock(side_effect=lambda cached: memoized.__setitem__(0, cached))
    button.element_info.set_cache_strategy = setter
    session, _window, _windows, discover = make_session(button)
    session.begin({})
    assert perform("inspect", session) == "muted"
    # The operator opened the mic directly in Zoom since the previous inspection.
    button._name = "Mute my audio (Alt+A)"
    session.begin({})
    assert perform("toggle", session) == "muted"
    button.iface_invoke.Invoke.assert_called_once()
    assert setter.call_args_list and all(call.args == (False,) for call in setter.call_args_list)
    discover.assert_called_once()


def test_destroyed_or_hidden_cached_button_is_rediscovered_before_dispatch(monkeypatch):
    install_pattern_exception(monkeypatch)
    old = toggling_button()
    session, window, _windows, discover = make_session(old)
    session.begin({})
    assert perform("inspect", session) == "muted"
    replacement = toggling_button()
    old._visible = False
    window.buttons = [replacement]
    details = {}
    session.begin(details)
    assert perform("toggle", session, diagnostic=details) == "live"
    assert discover.call_count == 2
    assert details["cache_invalidations"] == 1
    old.iface_invoke.Invoke.assert_not_called()
    replacement.iface_invoke.Invoke.assert_called_once()


def test_zoom_restart_invalidates_cached_process_and_window_before_dispatch(monkeypatch):
    install_pattern_exception(monkeypatch)
    old, replacement = toggling_button(), toggling_button()
    birth = [12.0]
    session, _old_window, windows, discover = make_session(old, birth=birth)
    session.begin({})
    assert perform("inspect", session) == "muted"
    birth[0] = 13.0
    windows[0] = Window([replacement])
    session.begin({})
    assert perform("toggle", session) == "live"
    assert discover.call_count == 2
    old.iface_invoke.Invoke.assert_not_called()
    replacement.iface_invoke.Invoke.assert_called_once()


def test_cached_control_that_becomes_a_participant_action_is_never_clicked(monkeypatch):
    install_pattern_exception(monkeypatch)
    button = toggling_button()
    session, _window, _windows, _discover = make_session(button)
    session.begin({})
    assert perform("inspect", session) == "muted"
    button._parent = Node("ListItem", "participant", Node())
    session.begin({})
    with pytest.raises(MicrophoneError):
        perform("toggle", session)
    button.iface_invoke.Invoke.assert_not_called()


def test_replacement_after_dispatch_cannot_confirm_another_meeting(monkeypatch):
    install_pattern_exception(monkeypatch)
    old, other = toggling_button(), toggling_button()
    other._name = "Mute my audio (Alt+A)"
    session, _window, windows, _discover = make_session(old)
    session.begin({})
    assert perform("inspect", session) == "muted"

    def invoke():
        old._visible = False
        windows[0] = Window([other])

    old.iface_invoke.Invoke.side_effect = invoke
    session.begin({})
    with pytest.raises(MicrophoneError) as caught:
        perform("toggle", session)
    assert caught.value.code == "control_changed"
    old.iface_invoke.Invoke.assert_called_once()
    other.iface_invoke.Invoke.assert_not_called()


def test_persistent_worker_reuses_one_thread_and_records_latency_phases():
    threads, reports = [], []
    button = Mock()

    def finder():
        threads.append(threading.get_ident())
        return button, "muted"

    service = ZoomAudio(finder=finder)
    service.diagnostic.connect(reports.append)
    workers = []
    try:
        for action in ("inspect", "mute", "inspect", "mute"):
            assert service.request(action)
            wait_until(lambda: not service.busy)
            workers.append(service._thread)
        assert len({id(worker) for worker in workers}) == 1
        assert all(value == workers[0].ident != threading.get_ident() for value in threads)
        assert len(reports) == 3  # One unchanged poll suppressed, both commands retained.
        assert all(report["queue_wait_ms"] >= 0 for report in reports)
        assert all(report["backend_setup_ms"] >= 0 for report in reports)
        assert all(report["request_elapsed_ms"] >= report["elapsed_ms"] for report in reports)
    finally:
        worker = service._thread
        service.stop()
        worker.join(1)
    assert not worker.is_alive()


def test_com_initialization_failure_can_retry_without_leaking_an_apartment(monkeypatch):
    com = SimpleNamespace(
        CoInitializeEx=Mock(side_effect=[RuntimeError("private COM setup"), None]),
        COINIT_MULTITHREADED=0, CoUninitialize=Mock(),
    )
    monkeypatch.setitem(sys.modules, "pythoncom", com)
    monkeypatch.setattr("meeting_assistant.services.zoom_audio.find_control", lambda **_: (Mock(), "muted"))
    service = ZoomAudio(platform="win32")
    reports = []
    service.diagnostic.connect(reports.append)
    try:
        service.request()
        wait_until(lambda: not service.busy)
        assert reports[-1]["code"] == "backend_error"
        com.CoUninitialize.assert_not_called()
        service.request()
        wait_until(lambda: not service.busy)
        assert reports[-1]["state"] == "muted"
        assert "private" not in str(reports)
    finally:
        worker = service._thread
        service.stop()
        worker.join(1)
    assert com.CoInitializeEx.call_count == 2
    com.CoUninitialize.assert_called_once()


@pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")
def test_destroying_idle_qobject_wakes_and_stops_its_persistent_worker():
    import shiboken6

    service = ZoomAudio(finder=lambda: (Mock(), "muted"))
    service.request()
    wait_until(lambda: not service.busy)
    worker = service._thread
    service.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(service)
    worker.join(1)
    assert not worker.is_alive()
