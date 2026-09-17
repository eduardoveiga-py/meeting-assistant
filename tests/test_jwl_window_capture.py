from meeting_assistant.services.display_service import DisplayInfo
from meeting_assistant.services.jwl_service import JwlWindowInfo
from meeting_assistant.services.jwl_window_capture import select_jwl_capture_target


def display(*, key: str, x: int, primary: bool) -> DisplayInfo:
    return DisplayInfo(
        key=key,
        name=key,
        manufacturer="",
        model="",
        serial="",
        x=x,
        y=0,
        width=1920,
        height=1080,
        primary=primary,
        device_pixel_ratio=1.0,
    )


def window(*, hwnd: int, left: int, top: int, right: int, bottom: int) -> JwlWindowInfo:
    return JwlWindowInfo(
        hwnd=hwnd,
        pid=100,
        process_name="ApplicationFrameHost.exe",
        title="JW Library",
        class_name="ApplicationFrameWindow",
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        visible=True,
        minimized=False,
        foreground=False,
    )


def test_physical_capture_targets_window_on_hall_display() -> None:
    hall = display(key="DISPLAY2", x=1920, primary=False)
    operator = window(hwnd=10, left=0, top=0, right=1920, bottom=1080)
    hall_output = window(hwnd=20, left=1920, top=0, right=3840, bottom=1080)

    target = select_jwl_capture_target([operator, hall_output], hall)

    assert target is not None
    assert target.window.hwnd == 20
    assert target.overlap_area == 1920 * 1080


def test_physical_capture_does_not_fall_back_to_operator_window() -> None:
    hall = display(key="DISPLAY2", x=1920, primary=False)
    operator = window(hwnd=10, left=0, top=0, right=1920, bottom=1080)

    target = select_jwl_capture_target([operator], hall)

    assert target is None


def test_diagnostic_fallback_uses_largest_visible_window() -> None:
    small = window(hwnd=10, left=0, top=0, right=800, bottom=600)
    large = window(hwnd=20, left=0, top=0, right=1600, bottom=900)

    target = select_jwl_capture_target([small, large], None)

    assert target is not None
    assert target.window.hwnd == 20
