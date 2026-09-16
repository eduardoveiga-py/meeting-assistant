from meeting_assistant.services.jwl_service import looks_like_jw_library


def test_matches_jw_library_process_name() -> None:
    assert looks_like_jw_library("JWLibrary.exe", "")


def test_matches_jw_library_window_title() -> None:
    assert looks_like_jw_library("ApplicationFrameHost.exe", "JW Library")


def test_rejects_unrelated_window() -> None:
    assert not looks_like_jw_library("ApplicationFrameHost.exe", "Configurações")


def test_rejects_sign_language_variant() -> None:
    assert not looks_like_jw_library("JWLibrarySignLanguage.exe", "JW Library Sign Language")
