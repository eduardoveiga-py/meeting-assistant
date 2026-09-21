from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from meeting_assistant.services import jwl_fast_window_guard as module
from meeting_assistant.services.jwl_secondary_window import WindowRect


@pytest.mark.parametrize('minimized,visible,covered,expected', [
    (False, True, False, 0),
    (True, True, False, 1),
    (False, False, False, 1),
    (False, True, True, 1),
])
def test_startup_preserves_healthy_output_but_still_recovers(
    monkeypatch, minimized, visible, covered, expected,
):
    monkeypatch.setattr(module, 'win32gui', Mock())
    monkeypatch.setattr(module, 'win32con', Mock())
    candidate = SimpleNamespace(hwnd=7, monitor_primary=False)
    display = SimpleNamespace(primary=False)
    guard = module.JwlFastWindowGuard(lambda: candidate, lambda: display)
    target = WindowRect(-629, -1080, 1291, 0)
    guard._enabled = True
    guard._is_valid_hwnd = Mock(return_value=True)
    guard._remember_foreground = Mock()
    guard._native_target_rect = Mock(return_value=target)
    guard._window_rect = Mock(return_value=target)
    guard._is_minimized = Mock(return_value=minimized)
    guard._is_visible = Mock(return_value=visible)
    guard._cloak_state = Mock(return_value=0)
    guard._is_exposed_at_center = Mock(return_value=not covered)
    guard._normalize_maximized_without_activation = Mock()
    guard._restore_without_activation = Mock()
    guard._tick()
    guard._normalize_maximized_without_activation.assert_not_called()
    assert guard._restore_without_activation.call_count == expected
    if not expected:
        # A restart / re-enable must not introduce a show-state change either.
        guard.set_enabled(False)
        guard.set_enabled(True)
        guard._normalize_maximized_without_activation.assert_not_called()
        guard._restore_without_activation.assert_not_called()
    guard.stop()
