from meeting_assistant.services.display_service import DisplayInfo
from meeting_assistant.services.jwl_secondary_window import WindowRect
from meeting_assistant.services.jwl_uia_secondary_window import (
    choose_native_monitor_rect,
    desktop_top_level_windows,
    uia_media_candidate_score,
)


def hall_display() -> DisplayInfo:
    return DisplayInfo(
        key="hall",
        name="TV-monitor",
        manufacturer="",
        model="",
        serial="",
        x=-629,
        y=-1080,
        width=1280,
        height=720,
        primary=False,
        device_pixel_ratio=1.5,
    )


def test_desktop_enumeration_uses_windows_api() -> None:
    class FakeDesktop:
        def __init__(self) -> None:
            self.calls = 0

        def windows(self):
            self.calls += 1
            return ["jw", "other"]

    desktop = FakeDesktop()

    assert desktop_top_level_windows(desktop) == ["jw", "other"]
    assert desktop.calls == 1


def test_native_monitor_mapping_prefers_physical_size_and_role() -> None:
    monitors = [
        (True, WindowRect(0, 0, 1920, 1080)),
        (False, WindowRect(-1920, -1080, 0, 0)),
    ]

    selected = choose_native_monitor_rect(hall_display(), monitors)

    assert selected == WindowRect(-1920, -1080, 0, 0)


def test_native_monitor_mapping_falls_back_to_qt_geometry() -> None:
    selected = choose_native_monitor_rect(hall_display(), [])

    assert selected == WindowRect(-629, -1080, 651, -360)


def test_uia_topmost_verified_jwl_on_secondary_is_strong_candidate() -> None:
    score = uia_media_candidate_score(
        name="JW Library",
        class_name="ApplicationFrameWindow",
        topmost=True,
        core_verified=True,
        monitor_primary=False,
        target_display=hall_display(),
        rect=WindowRect(-629, -1080, 1291, 0),
    )
    assert score >= 2000


def test_uia_target_point_core_window_can_identify_untitled_output() -> None:
    score = uia_media_candidate_score(
        name="",
        class_name="Windows.UI.Core.CoreWindow",
        topmost=True,
        core_verified=True,
        monitor_primary=False,
        target_display=hall_display(),
        rect=WindowRect(-1920, -1080, 0, 0),
        target_point=True,
    )

    assert score >= 1300


def test_uia_main_jwl_on_primary_is_not_selected_as_hall_output() -> None:
    score = uia_media_candidate_score(
        name="JW Library",
        class_name="ApplicationFrameWindow",
        topmost=False,
        core_verified=True,
        monitor_primary=True,
        target_display=hall_display(),
        rect=WindowRect(905, 0, 1930, 1030),
    )
    assert score < 1300


def test_uia_non_jwl_name_is_rejected() -> None:
    score = uia_media_candidate_score(
        name="Configurações",
        class_name="ApplicationFrameWindow",
        topmost=True,
        core_verified=True,
        monitor_primary=False,
        target_display=hall_display(),
        rect=WindowRect(-629, -1080, 1291, 0),
    )
    assert score < 0
