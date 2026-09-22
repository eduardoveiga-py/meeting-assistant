import re

from meeting_assistant.services.telemetry_service import (
    new_session_id,
    sanitize_text,
    sanitize_value,
)


def test_sanitize_value_redacts_sensitive_keys() -> None:
    payload = {
        "obs_password": "secret",
        "token": "abc",
        "nested": {"pwd": "123", "ok": True},
    }

    sanitized = sanitize_value(payload)

    assert sanitized["obs_password"] == "[REDACTED]"
    assert sanitized["token"] == "[REDACTED]"
    assert sanitized["nested"]["pwd"] == "[REDACTED]"
    assert sanitized["nested"]["ok"] is True


def test_sanitize_text_redacts_zoom_password_and_meeting_id() -> None:
    value = "https://example.zoom.us/j/12345678901?pwd=supersecret"

    sanitized = sanitize_text(value)

    assert "/j/[REDACTED]" in sanitized
    assert "pwd=[REDACTED]" in sanitized
    assert "12345678901" not in sanitized
    assert "supersecret" not in sanitized


def test_session_id_is_short_and_searchable() -> None:
    session_id = new_session_id()

    assert re.fullmatch(r"MA-\d{8}-\d{6}-[0-9A-F]{4}", session_id)
