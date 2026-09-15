import pytest

from meeting_assistant.core.state import AppState, OperatingMode


def test_default_state_is_safe_background() -> None:
    state = AppState()
    assert state.current_mode is OperatingMode.BACKGROUND
    assert state.automation_enabled is False
    assert state.can_use_audience_output is True


def test_mode_transition() -> None:
    state = AppState()
    state.set_mode(OperatingMode.MEDIA)
    assert state.current_mode is OperatingMode.MEDIA


def test_invalid_mode_is_rejected() -> None:
    state = AppState()
    with pytest.raises(TypeError):
        state.set_mode("media")  # type: ignore[arg-type]


def test_audience_output_requires_display_or_simulation() -> None:
    state = AppState(simulation_enabled=False, second_display_available=False)
    assert state.can_use_audience_output is False
    state.second_display_available = True
    assert state.can_use_audience_output is True
