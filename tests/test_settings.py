from meeting_assistant.services.settings import AppSettings, SettingsService


def test_settings_round_trip(tmp_path) -> None:
    path = tmp_path / "settings.json"
    service = SettingsService(path)
    original = AppSettings(simulation_enabled=False, obs_port=4456, scene_media="Midias Teste")

    service.save(original)
    loaded = service.load()

    assert loaded == original


def test_invalid_settings_fall_back_to_defaults(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{invalid json", encoding="utf-8")
    loaded = SettingsService(path).load()
    assert loaded == AppSettings()
