from meeting_assistant.services.jwl_fast_window_guard import window_needs_recovery
from meeting_assistant.services.jwl_secondary_window import WindowRect


def test_minimized_window_needs_immediate_recovery() -> None:
    target = WindowRect(-1920, -1080, 0, 0)

    assert window_needs_recovery(
        minimized=True,
        visible=True,
        current_rect=target,
        target_rect=target,
    )


def test_hidden_window_needs_immediate_recovery() -> None:
    target = WindowRect(-1920, -1080, 0, 0)

    assert window_needs_recovery(
        minimized=False,
        visible=False,
        current_rect=target,
        target_rect=target,
    )


def test_wrong_geometry_needs_recovery() -> None:
    assert window_needs_recovery(
        minimized=False,
        visible=True,
        current_rect=WindowRect(-1280, -720, 0, 0),
        target_rect=WindowRect(-1920, -1080, 0, 0),
    )


def test_healthy_window_does_not_need_recovery() -> None:
    target = WindowRect(-1920, -1080, 0, 0)

    assert not window_needs_recovery(
        minimized=False,
        visible=True,
        current_rect=WindowRect(-1918, -1079, -1, -1),
        target_rect=target,
    )


def test_dwm_cloaked_window_needs_recovery() -> None:
    target = WindowRect(-1920, -1080, 0, 0)

    assert window_needs_recovery(
        minimized=False,
        visible=True,
        cloaked=True,
        current_rect=target,
        target_rect=target,
    )


def test_covered_window_needs_recovery_even_if_win32_state_looks_healthy() -> None:
    target = WindowRect(-1920, -1080, 0, 0)

    assert window_needs_recovery(
        minimized=False,
        visible=True,
        cloaked=False,
        covered=True,
        current_rect=target,
        target_rect=target,
    )
