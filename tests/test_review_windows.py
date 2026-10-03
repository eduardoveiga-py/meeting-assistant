from dataclasses import replace
from types import SimpleNamespace

import pytest

from meeting_assistant.services.hall_policy import hall_runtime_flags
from meeting_assistant.services.local_host import is_local_host
from meeting_assistant.services.meeting_shutdown import MeetingShutdownService
from meeting_assistant.services.window_inventory import NativeWindow, main_jwl
from meeting_assistant.services.window_layout import decode_rect, encode_rect
from meeting_assistant.services.zoom_audio import ZoomAudio, microphone_state, perform


@pytest.mark.parametrize(
    "label",
    ["Unmute all", "Mute all", "Ativar áudio de todos", "Desativar áudio de todos", "Unmute participants"],
)
def test_collective_zoom_controls_never_control_operator_microphone(label):
    assert microphone_state(label) is None


def test_zoom_import_failure_releases_busy_flag(monkeypatch):
    import builtins

    original = builtins.__import__

    def import_failure(name, *args, **kwargs):
        if name == "pythoncom":
            raise ImportError("missing COM")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_failure)
    service = ZoomAudio(platform="win32")
    service.request()
    service._thread.join(1)
    assert not service.busy
    assert not service._thread.is_alive()


def test_zoom_cancel_during_verification_does_not_click_twice():
    import threading
    from unittest.mock import Mock

    event = threading.Event()
    event.set()
    button = Mock()
    with pytest.raises(RuntimeError, match="cancelada"):
        perform("mute", lambda: (button, "live"), event)
    # A cancellation before starting should never invoke a button.
    button.invoke.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_guardian_off_during_each_transition_and_external_presentation(enabled):
    assert hall_runtime_flags(enabled, False, False) == (enabled, enabled)
    assert hall_runtime_flags(enabled, True, False) == (False, False)
    assert hall_runtime_flags(enabled, False, True) == (False, False)
    assert hall_runtime_flags(enabled, False, False, True) == (False, False)
    assert hall_runtime_flags(enabled, False, False, external_active=True) == (False, False)


def test_local_obs_all_interfaces_ipv6_and_alias_resolution():
    interfaces = {
        "ethernet": [SimpleNamespace(address="192.168.1.8")],
        "wifi": [SimpleNamespace(address="10.0.0.8"), SimpleNamespace(address="fe80::8%13")],
    }
    assert is_local_host("10.0.0.8", interfaces=interfaces)
    assert is_local_host("[::ffff:192.168.1.8]", interfaces=interfaces)
    assert is_local_host("[fe80::8%13]", interfaces=interfaces)
    assert not is_local_host("10.0.0.9", interfaces=interfaces)

    def resolver(*a):
        return [(0, 0, 0, "", ("10.0.0.8", 0)), (0, 0, 0, "", ("192.168.1.8", 0))]

    assert is_local_host("my-notebook", interfaces=interfaces, resolver=resolver)

    def mixed(*a):
        return [(0, 0, 0, "", ("10.0.0.8", 0)), (0, 0, 0, "", ("10.0.0.9", 0))]

    assert not is_local_host("ambiguous", interfaces=interfaces, resolver=mixed)


def window(hwnd, rect=(520, 0, 1920, 1040), process="jwlibrary.exe", title="JW Library", visible=True):
    return NativeWindow(
        hwnd,
        hwnd + 100,
        1.0,
        process,
        title,
        "Windows.UI.Core.CoreWindow",
        rect,
        (0, 1, (0, 0), (0, 0), rect),
        visible,
        False,
    )


def test_secondary_jwl_cannot_overwrite_primary_role_even_with_same_title():
    primary, secondary = window(1), window(2, (1920, 0, 3840, 1080))
    assert main_jwl([secondary, primary], (0, 0, 1920, 1040), secondary_hwnd=2) == primary
    assert main_jwl([primary, replace(primary, hwnd=3)], (0, 0, 1920, 1040)) is None


def test_layout_relative_coordinates_handle_dpi_change_and_disconnected_monitor():
    old = {"name": "second", "work": (1920, 0, 3840, 1040), "primary": False}
    record = encode_rect((2880, 0, 3840, 1040), old)
    now = [{"name": "primary", "work": (0, 0, 1280, 680), "primary": True}]
    assert decode_rect(record, now) == (640, 0, 1280, 680)
    assert decode_rect({"relative": [float("nan"), 0, 1, 1]}, now) is None


class ShutdownBackend:
    def __init__(self, pending=False):
        self.pending = pending
        self.closed = []
        self.rows = [
            window(1),
            replace(window(2, (1920, 0, 3840, 1080)), pid=101),
            replace(
                window(3, process="obs64.exe", title="OBS Studio", visible=False), class_name="Qt6QWindowIcon"
            ),
            window(4, process="notepad.exe", title="Operator notes"),
        ]

    def windows(self):
        return self.rows

    def monitors(self):
        return [{"name": "primary", "work": (0, 0, 1920, 1040), "primary": True}]

    def close(self, window):
        self.closed.append(window)

    def same_process(self, window):
        return self.pending


def test_shutdown_closes_hidden_obs_and_primary_jwl_preserving_operator_apps():
    backend = ShutdownBackend()
    service = MeetingShutdownService(backend=backend, timeout=0)
    results = []
    service.finished.connect(results.append)
    service._run()
    assert {w.hwnd for w in backend.closed} == {1, 3}
    assert results[-1].complete


def test_shutdown_confirmation_prompt_reported_pending_never_terminated():
    backend = ShutdownBackend(pending=True)
    service = MeetingShutdownService(backend=backend, timeout=0)
    results = []
    service.finished.connect(results.append)
    service._run()
    assert not results[-1].complete
    assert "obs64.exe" in results[-1].pending
    assert "pendente" in results[-1].message
