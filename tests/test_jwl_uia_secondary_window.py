from meeting_assistant.services.display_service import DisplayInfo
from meeting_assistant.services.jwl_secondary_window import WindowRect
from meeting_assistant.services.jwl_uia_secondary_window import uia_media_candidate_score


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
