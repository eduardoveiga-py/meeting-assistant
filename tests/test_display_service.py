from meeting_assistant.services.display_service import build_display_key


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
