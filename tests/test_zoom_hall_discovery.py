from types import SimpleNamespace

import pytest

from meeting_assistant.services import zoom_hall_service as module


def setup_windows(monkeypatch, rows):
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
    assert service._find_secondary_zoom_window() is None
    service._zoom_hwnd = 2
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
        SW_RESTORE=1, SW_SHOW=2, SW_HIDE=0, SWP_NOACTIVATE=16,
        SWP_SHOWWINDOW=64, SWP_FRAMECHANGED=32, HWND_TOPMOST=-1,
    ))
    module.win32gui.ShowWindow = lambda *args: None
    module.win32gui.IsWindow = lambda hwnd: hwnd in {1, 2}

    def fail_position(*args):
        raise OSError("window disappeared")

    module.win32gui.SetWindowPos = fail_position
    service._display_provider = lambda: object()
    monkeypatch.setattr(service, "_native_target_rect", lambda _: module.WindowRect(0, 0, 1280, 720))
    changes = []
    service.about_to_show.connect(lambda: changes.append("paused"))
    service.active_changed.connect(lambda active, _: changes.append(active))
    assert not service.show_on_hall()
    assert not service.active
    assert changes == ["paused", False]
