from inspect import signature

from meeting_assistant.ui.settings_dialog import SettingsDialog


def test_settings_dialog_keeps_existing_call_shape() -> None:
    parameters = list(signature(SettingsDialog.__init__).parameters)
    assert parameters[:4] == ["self", "settings", "available_scenes", "parent"]
    assert "available_displays" in parameters
