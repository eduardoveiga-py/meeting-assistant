from meeting_assistant.services.jwl_screen_sensor import (
    choose_capture_regions,
    window_center_inside_display,
)
from meeting_assistant.services.jwl_service import JwlWindowInfo


def _window(
    *,
    hwnd: int,
    left: int,
    top: int,
    right: int,
    bottom: int,
    foreground: bool = False,
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
        minimized=False,
        foreground=foreground,
    )


def test_window_center_identifies_hall_display() -> None:
    window = _window(hwnd=2, left=1920, top=0, right=3840, bottom=1080)

    assert window_center_inside_display(window, (1920, 0, 1920, 1080))
    assert not window_center_inside_display(window, (0, 0, 1920, 1080))


def test_physical_mode_only_captures_jw_window_on_selected_hall_display() -> None:
    operator_window = _window(
        hwnd=1,
        left=0,
        top=0,
        right=1920,
        bottom=1080,
        foreground=True,
    )
    hall_output = _window(
        hwnd=2,
        left=1920,
        top=0,
        right=3840,
        bottom=1080,
    )

    regions = choose_capture_regions(
        [operator_window, hall_output],
        preferred_display_bounds=(1920, 0, 1920, 1080),
    )

    assert [region.hwnd for region in regions] == [2]


def test_physical_mode_does_not_fall_back_to_operator_window() -> None:
    operator_window = _window(
        hwnd=1,
        left=0,
        top=0,
        right=1920,
        bottom=1080,
        foreground=True,
    )

    regions = choose_capture_regions(
        [operator_window],
        preferred_display_bounds=(1920, 0, 1920, 1080),
    )

    assert regions == []
