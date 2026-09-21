from types import SimpleNamespace

import pytest

from meeting_assistant.services import zoom_hall_service as module


def setup_windows(monkeypatch, rows):
    monkeypatch.setattr(module, "activate_window", lambda _: False)
    def children(hwnd, callback, _):
        if rows[hwnd].get("controls"):
            callback(1000 + hwnd, None)

    def class_name(hwnd):
        if hwnd >= 1000:
            return "ZPControlPanelClass"
        return rows[hwnd].get("class", "ConfMultiTabContentWndClass")

    gui = SimpleNamespace(
        EnumWindows=lambda callback, _: [callback(hwnd, None) for hwnd in rows],
        EnumChildWindows=children,
        GetClassName=class_name,
        GetWindowText=lambda _: pytest.fail("Discovery must not depend on window titles"),
        IsWindowVisible=lambda hwnd: rows[hwnd].get("visible", True),
        GetWindowRect=lambda hwnd: (0, 0, 1280, 720),
    )
    monkeypatch.setattr(module, "win32gui", gui)
    monkeypatch.setattr(module, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (1, hwnd),
    ))

    def process(pid):
        if rows[pid].get("unreadable"):
            raise module.psutil.AccessDenied(pid)
        return SimpleNamespace(name=lambda: rows[pid].get("process", "Zoom.exe"))

    monkeypatch.setattr(module.psutil, "Process", process)
    service = module.ZoomHallService(lambda: None, lambda: None)
    records = []
    service.discovery_changed.connect(records.append)
    return service, records


def test_secondary_window_selected_without_english_title(monkeypatch):
    service, records = setup_windows(monkeypatch, {1: {"controls": True}, 2: {}})
    assert service._find_secondary_zoom_window().hwnd == 2
    assert records[-1]["result"] == "selected"
    assert all("title" not in row for row in records[-1]["windows"])


def test_main_window_and_other_processes_are_never_selected(monkeypatch):
    service, _ = setup_windows(monkeypatch, {
        1: {"controls": True}, 2: {"process": "other.exe"}, 3: {"unreadable": True},
    })
    assert service._find_secondary_zoom_window() is None


def test_ambiguous_windows_are_reported_not_guessed(monkeypatch):
    service, records = setup_windows(monkeypatch, {1: {}, 2: {}})
    assert service._find_secondary_zoom_window() is None
    assert records[-1]["result"] == "ambiguous"


def test_hidden_secondary_can_be_reused_after_returning_to_jwl(monkeypatch):
    service, _ = setup_windows(monkeypatch, {1: {"controls": True}, 2: {"visible": False}})
    # A fresh app instance must recover the window hidden by the previous one.
    assert service._zoom_hwnd == 0
    assert service._find_secondary_zoom_window().hwnd == 2


def test_cached_handle_revalidated_against_process_and_controls(monkeypatch):
    service, _ = setup_windows(monkeypatch, {1: {"controls": True}, 2: {"process": "other.exe"}})
    service._zoom_hwnd = 2
    assert service._find_secondary_zoom_window() is None


def test_unknown_zoom_window_class_is_included_in_diagnostics(monkeypatch):
    service, records = setup_windows(monkeypatch, {1: {"class": "NewZoomClass"}})
    assert service._find_secondary_zoom_window() is None
    assert records[-1]["windows"][0]["class_name"] == "NewZoomClass"


def test_position_failure_restores_jwl_and_releases_automation_pause(monkeypatch):
    service, _ = setup_windows(monkeypatch, {1: {"controls": True}, 2: {}})
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module, "win32con", SimpleNamespace(
        SW_RESTORE=1, SW_SHOW=2, SW_SHOWNOACTIVATE=4, SW_HIDE=0, SWP_NOACTIVATE=16,
        SWP_SHOWWINDOW=64, SWP_ASYNCWINDOWPOS=32, HWND_TOPMOST=-1, HWND_NOTOPMOST=-2,
        SWP_NOMOVE=2, SWP_NOSIZE=1,
    ))
    monkeypatch.setattr(module, "show_window_async", lambda *args: None)
    module.win32gui.IsWindow = lambda hwnd: hwnd in {1, 2}

    def fail_position(*args):
        raise OSError("window disappeared")

    module.win32gui.SetWindowPos = fail_position
    service._jwl_window_provider = lambda: jwl_info()
    service._display_provider = lambda: object()
    monkeypatch.setattr(service, "_native_target_rect", lambda _: module.WindowRect(0, 0, 1280, 720))
    changes = []
    service.about_to_show.connect(lambda: changes.append("paused"))
    service.active_changed.connect(lambda active, _: changes.append(active))
    monkeypatch.setattr(service, "_window_snapshot", lambda *_: {"ready": False})
    assert service.show_on_hall()
    assert changes == ["paused"]
    service._show_started -= 6
    service._poll_show()
    assert service.returning
    assert not service._show_timer.isActive()
    assert changes == ["paused"]
    service._return_timer.stop()


def jwl_info():
    return module.JwlSecondaryWindowInfo(
        hwnd=1, pid=1, process_name="JWLibrary.exe", title="", class_name="",
        rect=module.WindowRect(0, 0, 1280, 720), visible=True, minimized=False,
        topmost=True, title_bar_visible=False, has_jwl_core_window=True,
        monitor_primary=False, score=100,
    )


def test_enter_zoom_recovers_hidden_window_after_restart_and_keeps_jwl_visible(monkeypatch):
    service, _ = setup_windows(monkeypatch, {1: {"controls": True}, 2: {"visible": False}})
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module, "win32con", SimpleNamespace(
        SW_RESTORE=1, SW_SHOW=2, SW_SHOWNOACTIVATE=4, SWP_NOACTIVATE=16,
        SWP_SHOWWINDOW=64, SWP_ASYNCWINDOWPOS=32, HWND_TOPMOST=-1, HWND_NOTOPMOST=-2,
        SWP_NOMOVE=2, SWP_NOSIZE=1,
    ))
    calls = []
    module.win32gui.IsWindow = lambda hwnd: hwnd in {1, 2}
    monkeypatch.setattr(module, "show_window_async", lambda hwnd, mode: calls.append((hwnd, mode)))
    module.win32gui.SetWindowPos = lambda *args: None
    service._jwl_window_provider = lambda: jwl_info()
    service._display_provider = lambda: object()
    monkeypatch.setattr(service, "_native_target_rect", lambda _: module.WindowRect(0, 0, 1280, 720))
    assert service.show_on_hall()
    assert service.active
    assert service._jwl_hwnd == 1
    assert all(hwnd != 1 for hwnd, _ in calls)
    service._show_timer.stop()


def setup_return(monkeypatch):
    service, _ = setup_windows(monkeypatch, {1: {}, 2: {}})
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module, "win32con", SimpleNamespace(
        SW_SHOWNOACTIVATE=4, SW_HIDE=0, SWP_NOACTIVATE=16,
        SWP_SHOWWINDOW=64, SWP_ASYNCWINDOWPOS=32, HWND_TOPMOST=-1, HWND_NOTOPMOST=-2,
        SWP_NOMOVE=2, SWP_NOSIZE=1,
    ))
    state = {"cloaked": 0, "exposed": True, "zoom_visible": True, "valid": True}
    calls, events = [], []
    module.win32gui.IsWindow = lambda hwnd: hwnd == 2 or (hwnd == 1 and state["valid"])
    module.win32gui.IsIconic = lambda hwnd: False
    module.win32gui.IsWindowVisible = lambda hwnd: True if hwnd == 1 else state["zoom_visible"]
    module.win32gui.ShowWindow = lambda *args: pytest.fail("Synchronous show must never be called")
    monkeypatch.setattr(module, "show_window_async", lambda hwnd, mode: calls.append(("show", hwnd, mode)))
    module.win32gui.SetWindowPos = lambda *args: calls.append(("position", args[0], args[-1]))
    monkeypatch.setattr(module.JwlFastWindowGuard, "_cloak_state", lambda _: state["cloaked"])
    monkeypatch.setattr(module.JwlFastWindowGuard, "_is_exposed_at_center", lambda *_: state["exposed"])
    service._display_provider = lambda: object()
    monkeypatch.setattr(service, "_native_target_rect", lambda _: module.WindowRect(0, 0, 1280, 720))
    service._jwl_hwnd, service._zoom_hwnd, service._active = 1, 2, True
    service.transition_diagnostic.connect(events.append)
    return service, state, calls, events


def test_return_waits_for_native_confirmation_before_resuming(monkeypatch):
    service, state, calls, events = setup_return(monkeypatch)
    assert service.restore_jwl()
    assert service.returning and service.active
    assert ("show", 2, 0) not in calls
    service._poll_return()
    assert ("show", 2, 0) not in calls
    assert state["zoom_visible"]
    assert not service.returning and not service.active
    assert events[-1]["phase"] == "return_confirmed"
    assert all(flags & 32 for kind, _, flags in calls if kind == "position")


@pytest.mark.parametrize("obstruction", ["cloaked", "exposed"])
def test_visible_but_cloaked_or_covered_jwl_is_not_success(monkeypatch, obstruction):
    service, state, calls, events = setup_return(monkeypatch)
    state[obstruction] = 2 if obstruction == "cloaked" else False
    service.restore_jwl()
    service._poll_return()
    assert service.active and service.returning
    assert ("show", 2, 0) not in calls
    assert not any(e["phase"] == "return_confirmed" for e in events)
    service._return_timer.stop()


def test_return_timeout_keeps_zoom_and_can_be_retried(monkeypatch):
    service, state, calls, events = setup_return(monkeypatch)
    state["cloaked"] = 2
    service.restore_jwl()
    service._return_started -= 6
    service._poll_return()
    assert service.active and not service.returning
    assert not service._return_timer.isActive()
    assert events[-1]["phase"] == "return_timeout"
    assert ("show", 2, 0) not in calls
    state["cloaked"] = 0
    service.restore_jwl()
    service._poll_return()
    assert state["zoom_visible"]
    assert not service.active


def test_repeated_stop_click_does_not_restart_deadline(monkeypatch):
    service, _, _, events = setup_return(monkeypatch)
    service.restore_jwl()
    started = service._return_started
    service.restore_jwl()
    assert service._return_started == started
    assert len(events) == 1
    service._return_timer.stop()


def test_missing_jwl_does_not_hide_zoom(monkeypatch):
    service, state, calls, _ = setup_return(monkeypatch)
    state["valid"] = False
    assert not service.restore_jwl()
    assert service.active
    assert calls == []


@pytest.mark.parametrize("enabled", [False, True])
def test_guard_and_media_policy_through_entire_zoom_cycle(enabled):
    assert module.hall_runtime_flags(enabled, False, False) == (True, enabled)
    assert module.hall_runtime_flags(enabled, False, False, True) == (False, False)
    assert module.hall_runtime_flags(enabled, True, False) == (False, False)
    assert module.hall_runtime_flags(enabled, True, True) == (True, False)
    assert module.hall_runtime_flags(enabled, False, False) == (True, enabled)


def test_multiple_hidden_secondaries_are_not_guessed(monkeypatch):
    service, records = setup_windows(monkeypatch, {1: {"visible": False}, 2: {"visible": False}})
    assert service._find_secondary_zoom_window() is None
    assert records[-1]["result"] == "ambiguous"


def test_repeated_zoom_cycles_never_hide_secondary(monkeypatch):
    service, state, calls, _ = setup_return(monkeypatch)
    module.win32con.SW_RESTORE = 9
    module.win32con.SW_SHOW = 5
    service._jwl_window_provider = jwl_info
    monkeypatch.setattr(service, "_find_secondary_zoom_window", lambda: module.ZoomHallWindow(
        2, 2, module.WindowRect(0, 0, 1280, 720),
    ))
    for _ in range(3):
        assert service.restore_jwl()
        service._poll_return()
        assert not service.active
        assert state["zoom_visible"]
        assert service.show_on_hall()
        assert service.active
    assert ("show", 2, 0) not in calls


def test_zoom_is_demoted_and_promoted_symmetrically_and_confirmed(monkeypatch):
    service, state, _, events = setup_return(monkeypatch)
    positions = []
    module.win32gui.SetWindowPos = lambda hwnd, order, *args: positions.append((hwnd, order))
    service._active = False
    service._jwl_window_provider = jwl_info
    monkeypatch.setattr(service, "_find_secondary_zoom_window", lambda: module.ZoomHallWindow(
        2, 2, module.WindowRect(0, 0, 1280, 720),
    ))
    changes = []
    service.active_changed.connect(lambda active, _: changes.append(active))
    state["exposed"] = False
    assert service.show_on_hall()
    assert positions[:2] == [(1, -2), (2, -1)]
    service._poll_show()
    assert not changes
    assert not any(e["phase"] == "show_confirmed" for e in events)
    state["exposed"] = True
    service._poll_show()
    assert changes == [True]
    assert events[-1]["phase"] == "show_confirmed"
    assert service.restore_jwl()
    assert not service._show_timer.isActive()
    assert positions[-2:] == [(2, -2), (1, -1)]
    service._poll_return()
    assert changes == [True, False]


def test_zoom_guard_recovers_late_jwl_reordering(monkeypatch):
    service, state, calls, _ = setup_return(monkeypatch)
    service._show_rect = module.WindowRect(0, 0, 1280, 720)
    service._show_started = module.time.monotonic()
    service._show_confirmed = True
    state["exposed"] = False
    service._poll_show()
    assert ("position", 1, 51) in calls
    assert ("position", 2, 112) in calls


def test_stale_uia_cycle_cannot_raise_jwl_after_guard_disabled(monkeypatch):
    from meeting_assistant.services import jwl_uia_secondary_window as uia
    service = uia.JwlUiaSecondaryWindowService(display_provider=lambda: None)
    monkeypatch.setattr(uia, "win32gui", SimpleNamespace(
        IsWindow=lambda _: pytest.fail("Disabled guard must not mutate a window"),
    ))
    monkeypatch.setattr(uia, "win32con", object())
    item = jwl_info()
    assert service._ensure_window(item, object()) is item


def test_covered_zoom_requests_activation_once_and_waits_for_exposure(monkeypatch):
    service, state, _, events = setup_return(monkeypatch)
    service._show_rect = module.WindowRect(0, 0, 1280, 720)
    service._show_started = module.time.monotonic()
    state["exposed"] = False
    activated = []
    monkeypatch.setattr(module, "activate_window", lambda hwnd: activated.append(hwnd) or True)
    service._poll_show()
    service._poll_show()
    assert activated == [2]
    assert not service._show_confirmed
    assert any(e["phase"] == "show_activation" and e["accepted"] for e in events)
    state["exposed"] = True
    service._poll_show()
    assert service._show_confirmed
    assert events[-1]["phase"] == "show_confirmed"


def test_already_exposed_zoom_never_steals_focus(monkeypatch):
    service, _, _, _ = setup_return(monkeypatch)
    service._show_rect = module.WindowRect(0, 0, 1280, 720)
    service._show_started = module.time.monotonic()
    monkeypatch.setattr(module, "activate_window", lambda _: pytest.fail("No activation needed"))
    service._poll_show()
    assert service._show_confirmed
