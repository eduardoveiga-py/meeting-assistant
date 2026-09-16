from meeting_assistant.services.obs_controller import (
    extract_current_scene,
    extract_scene_names,
)


def test_extract_scene_names_from_obs_payload() -> None:
    payload = {
        "scenes": [
            {"sceneName": "Texto do Ano"},
            {"sceneName": "Palco"},
            {"sceneName": "Mídias"},
        ]
    }

    assert extract_scene_names(payload) == ["Texto do Ano", "Palco", "Mídias"]


def test_extract_current_scene_prefers_modern_scene_name() -> None:
    payload = {
        "sceneName": "Palco",
        "currentProgramSceneName": "Texto antigo",
    }

    assert extract_current_scene(payload) == "Palco"


def test_extract_current_scene_accepts_legacy_field() -> None:
    payload = {"currentProgramSceneName": "Mídias"}

    assert extract_current_scene(payload) == "Mídias"
