import ctypes
import sys
from types import SimpleNamespace

import pytest

from meeting_assistant.services.window_exposure import (
    first_covering_window,
    verify_visual_exposure,
    windows_above_target,
)


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
        GetWindow=lambda hwnd, command: 0,
        IsWindow=lambda hwnd: True,
    )
    # No WindowFromPoint API in this fake: disabled UWP input does not imply occlusion.
    monkeypatch.setitem(sys.modules, 'win32gui', gui)
    if not hasattr(ctypes, 'windll'):
        monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(), raising=False)
    evidence = []
    verify_visual_exposure(70, (0, -1080, 1920, 0), evidence.append)
    assert evidence == [{'hwnd': 70, 'root_hwnd': 7, 'visual_blocker': None,
                         'exposure_check': 'anchored_z_order', 'windows_checked': 1}]


@pytest.mark.parametrize('class_name', ['Shell_TrayWnd', 'Shell_SecondaryTrayWnd'])
def test_reported_full_taskbar_does_not_prevent_operator_photo_preview(class_name):
    target = (-629, -1080, 1291, 0)
    rows = [row(3, (-629, -60, 1291, 0), class_name=class_name), {'hwnd': 7}]
    assert first_covering_window(7, target, rows)['hwnd'] == 3
    assert first_covering_window(7, target, rows, allow_taskbar_preview=True) is None


def test_taskbar_exception_does_not_hide_real_window_above_jwl():
    rows = [row(3, class_name='Shell_SecondaryTrayWnd'),
            row(8, class_name='ConfMultiTabContentWndClass'), {'hwnd': 7}]
    assert first_covering_window(7, (0, 0, 1920, 1080), rows,
                                 allow_taskbar_preview=True)['hwnd'] == 8


@pytest.mark.parametrize('class_name', ['WorkerW', 'Progman'])
def test_shell_desktop_surface_does_not_block_confirmed_preview(class_name):
    rows = [row(3, (-629, -1080, 1920, 1080), class_name=class_name), {'hwnd': 7}]
    assert first_covering_window(7, (-629, -1080, 1291, 0), rows,
                                 allow_taskbar_preview=True) is None
    rows.insert(1, row(8, (-629, -1080, 1291, 0), class_name='Chrome_WidgetWin_1'))
    assert first_covering_window(7, (-629, -1080, 1291, 0), rows,
                                 allow_taskbar_preview=True)['hwnd'] == 8


def test_uwp_target_need_not_appear_in_enumwindows():
    # UWP target 7 is absent from a hypothetical desktop-app enumeration.
    # Its own Z-order links still give the actual windows above it.
    links = {7: 8, 8: 9, 9: 0}
    assert windows_above_target(7, links.get, lambda _: True) == [9, 8, 7]


@pytest.mark.parametrize('links', [{7: 8, 8: 7}, {7: 7}])
def test_z_order_cycle_cannot_loop_forever(links):
    with pytest.raises(ValueError, match='mudaram'):
        windows_above_target(7, links.get, lambda _: True)


def test_destroyed_window_and_traversal_limit_refuse_capture():
    with pytest.raises(ValueError, match='mudaram'):
        windows_above_target(7, lambda _: 8, lambda hwnd: hwnd != 8)
    with pytest.raises(ValueError, match='todas'):
        windows_above_target(7, lambda hwnd: hwnd + 1, lambda _: True, limit=4)
