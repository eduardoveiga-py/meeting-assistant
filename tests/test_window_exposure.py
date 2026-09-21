import ctypes
import sys
from types import SimpleNamespace

import pytest

from meeting_assistant.services.window_exposure import first_covering_window, verify_visual_exposure


def row(hwnd, rect=(0, 0, 1920, 1080), **kwargs):
    return dict(hwnd=hwnd, rect=rect, visible=True, cloaked=False, transparent=False, **kwargs)


def test_behind_and_adjacent_windows_do_not_cover_target():
    assert first_covering_window(7, (0, 0, 1920, 1080), [
        row(3, (0, 1080, 1920, 2160)), {'hwnd': 7}, row(8),
    ]) is None


def test_visible_overlap_is_blocked_even_for_thin_strip():
    assert first_covering_window(7, (0, 0, 1920, 1080), [
        row(8, (0, 0, 1920, 7)), {'hwnd': 7},
    ])['hwnd'] == 8


def test_cloaked_or_alpha_zero_overlay_is_not_visible():
    a, b = row(2), row(3)
    a['cloaked'], b['transparent'] = True, True
    assert first_covering_window(7, (0, 0, 1920, 1080), [a, b, {'hwnd': 7}]) is None


def test_missing_root_is_not_assumed_safe():
    with pytest.raises(ValueError, match='ordem'):
        first_covering_window(7, (0, 0, 1920, 1080), [])


def test_disabled_jwl_and_child_handle_do_not_need_mouse_hit_test(monkeypatch):
    gui = SimpleNamespace(
        GetAncestor=lambda hwnd, _: 7,
        EnumWindows=lambda callback, _: [callback(hwnd, None) for hwnd in (7, 8)],
    )
    # No WindowFromPoint API in this fake: disabled UWP input does not imply occlusion.
    monkeypatch.setitem(sys.modules, 'win32gui', gui)
    if not hasattr(ctypes, 'windll'):
        monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(), raising=False)
    evidence = []
    verify_visual_exposure(70, (0, -1080, 1920, 0), evidence.append)
    assert evidence == [{'hwnd': 70, 'root_hwnd': 7, 'visual_blocker': None}]
