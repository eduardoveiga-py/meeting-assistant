from meeting_assistant.services.display_service import (
    DisplayInfo,
    build_display_key,
    resolve_hall_display,
)


def make_display(key: str, *, primary: bool, x: int) -> DisplayInfo:
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


def test_display_key_prefers_hardware_identity() -> None:
    key = build_display_key(
        name="DISPLAY1",
        manufacturer="Dell",
        model="P2419H",
        serial="ABC123",
        x=0,
        y=0,
        width=1920,
        height=1080,
    )

    assert key == "Dell|P2419H|ABC123"


def test_display_key_falls_back_to_geometry() -> None:
    key = build_display_key(
        name="DISPLAY2",
        manufacturer="",
        model="",
        serial="",
        x=1920,
        y=0,
        width=1920,
        height=1080,
    )

    assert key == "DISPLAY2|1920,0|1920x1080"


def test_hall_display_defaults_to_first_non_primary_screen() -> None:
    primary = make_display("DISPLAY1", primary=True, x=0)
    secondary = make_display("DISPLAY2", primary=False, x=1920)

    assert resolve_hall_display([primary, secondary], "") == secondary


def test_hall_display_respects_explicit_selection() -> None:
    primary = make_display("DISPLAY1", primary=True, x=0)
    secondary = make_display("DISPLAY2", primary=False, x=1920)

    assert resolve_hall_display([primary, secondary], "DISPLAY1") == primary


def test_missing_explicit_display_does_not_fall_back_silently() -> None:
    primary = make_display("DISPLAY1", primary=True, x=0)
    secondary = make_display("DISPLAY2", primary=False, x=1920)

    assert resolve_hall_display([primary, secondary], "MISSING") is None
