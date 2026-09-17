from meeting_assistant.services.meeting_launcher import (
    looks_like_jwl_process,
    looks_like_obs_process,
    looks_like_zoom_process,
    zoom_join_uri,
)


def test_zoom_join_uri_converts_standard_invite_link() -> None:
    uri = zoom_join_uri(
        "https://example.zoom.us/j/12345678901?pwd=secret-token"
    )

    assert uri.startswith("zoommtg://zoom.us/join?")
    assert "confno=12345678901" in uri
    assert "pwd=secret-token" in uri


def test_zoom_join_uri_keeps_native_scheme() -> None:
    native = "zoommtg://zoom.us/join?confno=123456789&pwd=abc"

    assert zoom_join_uri(native) == native


def test_zoom_join_uri_falls_back_for_nonstandard_zoom_link() -> None:
    link = "https://example.zoom.us/my/congregation"

    assert zoom_join_uri(link) == link


def test_process_classification() -> None:
    assert looks_like_obs_process("obs64.exe")
    assert looks_like_zoom_process("Zoom.exe")
    assert looks_like_jwl_process("JWLibrary.exe")
    assert not looks_like_jwl_process("JWLibrary.SignLanguage.exe")
