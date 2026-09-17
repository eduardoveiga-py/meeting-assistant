from meeting_assistant.services.display_service import DisplayInfo
from meeting_assistant.services.jwl_secondary_window import (
    JwlSecondaryWindowInfo,
    WindowRect,
    choose_secondary_candidate,
    is_explicit_jwl_secondary_title,
    is_fullscreen_on_display,
    normalize_window_title,
    rect_overlap_ratio,
    score_secondary_candidate,
)


def hall_display() -> DisplayInfo:
    return DisplayInfo(
        key="hall",
        name="TV",
        manufacturer="",
        model="",
        serial="",
        x=-1280,
        y=0,
        width=1280,
        height=720,
        primary=False,
        device_pixel_ratio=1.0,
    )


def make_candidate(*, hwnd: int, score: int) -> JwlSecondaryWindowInfo:
    return JwlSecondaryWindowInfo(
        hwnd=hwnd,
        pid=100,
        process_name="ApplicationFrameHost.exe",
        title="JW Library",
        class_name="ApplicationFrameWindow",
        rect=WindowRect(-1280, 0, 0, 720),
        visible=True,
        minimized=False,
        topmost=True,
        title_bar_visible=False,
        has_jwl_core_window=True,
        monitor_primary=False,
        score=score,
    )


def test_normalizes_invisible_direction_mark_in_secondary_title() -> None:
    title = "Second Display \u200e- JW Library"
    assert normalize_window_title(title) == "second display - jw library"
    assert is_explicit_jwl_secondary_title(title)


def test_secondary_window_matches_fullscreen_hall_display() -> None:
    display = hall_display()
    rect = WindowRect(-1280, 0, 0, 720)
    assert rect_overlap_ratio(rect, display) == 1.0
    assert is_fullscreen_on_display(rect, display)


def test_main_window_on_primary_is_penalized_even_with_jwl_core() -> None:
    display = hall_display()
    score = score_secondary_candidate(
        title="JW Library",
        class_name="ApplicationFrameWindow",
        rect=WindowRect(0, 0, 1920, 1080),
        minimized=False,
        topmost=False,
        title_bar_visible=True,
        has_jwl_core_window=True,
        monitor_primary=True,
        target_display=display,
    )
    assert score < 650


def test_fullscreen_borderless_jwl_core_on_hall_display_is_selected() -> None:
    display = hall_display()
    score = score_secondary_candidate(
        title="JW Library",
        class_name="ApplicationFrameWindow",
        rect=WindowRect(-1280, 0, 0, 720),
        minimized=False,
        topmost=True,
        title_bar_visible=False,
        has_jwl_core_window=True,
        monitor_primary=False,
        target_display=display,
    )
    assert score >= 650


def test_mixed_dpi_geometry_mismatch_keeps_native_secondary_candidate() -> None:
    display = hall_display()
    score = score_secondary_candidate(
        title="JW Library",
        class_name="ApplicationFrameWindow",
        rect=WindowRect(-1920, 0, 0, 1080),
        minimized=False,
        topmost=True,
        title_bar_visible=False,
        has_jwl_core_window=True,
        monitor_primary=False,
        target_display=display,
    )
    assert score >= 650


def test_unrelated_application_frame_host_is_never_a_candidate() -> None:
    display = hall_display()
    score = score_secondary_candidate(
        title="Calculadora",
        class_name="ApplicationFrameWindow",
        rect=WindowRect(-1280, 0, 0, 720),
        minimized=False,
        topmost=True,
        title_bar_visible=False,
        has_jwl_core_window=False,
        monitor_primary=False,
        target_display=display,
    )
    assert score < 0


def test_special_secondary_title_is_strongest_signal() -> None:
    display = hall_display()
    score = score_secondary_candidate(
        title="Second Display \u200e- JW Library",
        class_name="ApplicationFrameWindow",
        rect=WindowRect(-1280, 0, 0, 720),
        minimized=False,
        topmost=True,
        title_bar_visible=False,
        has_jwl_core_window=False,
        monitor_primary=False,
        target_display=display,
    )
    assert score >= 1000


def test_choose_secondary_candidate_requires_minimum_confidence() -> None:
    assert choose_secondary_candidate([make_candidate(hwnd=1, score=649)]) is None
    chosen = choose_secondary_candidate(
        [make_candidate(hwnd=1, score=700), make_candidate(hwnd=2, score=1200)]
    )
    assert chosen is not None
    assert chosen.hwnd == 2
