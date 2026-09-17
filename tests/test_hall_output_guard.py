from meeting_assistant.services.hall_output_guard import select_hall_window
from meeting_assistant.services.jwl_service import JwlWindowInfo


def _window(
    *,
    hwnd: int,
    left: int,
    top: int,
    right: int,
    bottom: int,
    minimized: bool = False,
) -> JwlWindowInfo:
    return JwlWindowInfo(
        hwnd=hwnd,
        pid=1000 + hwnd,
        process_name="ApplicationFrameHost.exe",
        title="JW Library",
        class_name="ApplicationFrameWindow",
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        visible=True,
        minimized=minimized,
        foreground=False,
    )


def test_guard_selects_only_window_on_hall_display() -> None:
    operator = _window(hwnd=1, left=0, top=0, right=1920, bottom=1080)
    hall = _window(hwnd=2, left=1920, top=0, right=3840, bottom=1080)

    selected = select_hall_window(
        [operator, hall],
        (1920, 0, 1920, 1080),
    )

    assert selected == hall


def test_guard_keeps_tracked_window_after_it_is_minimized() -> None:
    operator = _window(hwnd=1, left=0, top=0, right=1920, bottom=1080)
    minimized_hall = _window(
        hwnd=2,
        left=-32000,
        top=-32000,
        right=-31840,
        bottom=-31972,
        minimized=True,
    )

    selected = select_hall_window(
        [operator, minimized_hall],
        (1920, 0, 1920, 1080),
        tracked_hwnd=2,
    )

    assert selected == minimized_hall


def test_guard_does_not_mistake_operator_window_for_hall_output() -> None:
    operator = _window(hwnd=1, left=0, top=0, right=1920, bottom=1080)

    selected = select_hall_window(
        [operator],
        (1920, 0, 1920, 1080),
    )

    assert selected is None
