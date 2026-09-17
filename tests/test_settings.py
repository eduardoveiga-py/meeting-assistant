from meeting_assistant.services.settings import AppSettings, SettingsService


def test_settings_round_trip(tmp_path) -> None:
    path = tmp_path / "settings.json"
    service = SettingsService(path)
    original = AppSettings(
        simulation_enabled=False,
        hall_display_key="secondary-display",
        obs_port=4456,
        scene_media="Midias Teste",
        scene_zoom="Zoom Salao",
    )

    service.save(original)
    loaded = service.load()

    assert loaded == original


def test_invalid_settings_fall_back_to_defaults(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{invalid json", encoding="utf-8")
    loaded = SettingsService(path).load()
    assert loaded == AppSettings()


def test_unknown_future_settings_are_ignored(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        '{"display_settings_version": 1, "obs_port": 4460, "future_option": true}',
        encoding="utf-8",
    )

    loaded = SettingsService(path).load()

    assert loaded.obs_port == 4460


def test_legacy_simulation_default_migrates_once_to_physical_output(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        '{"simulation_enabled": true, "obs_port": 4455}',
        encoding="utf-8",
    )

    loaded = SettingsService(path).load()

    assert loaded.simulation_enabled is False
    assert loaded.hall_display_key == ""
    assert loaded.display_settings_version == 1
