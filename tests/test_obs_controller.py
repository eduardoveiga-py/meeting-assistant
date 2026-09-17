import base64

from meeting_assistant.services.obs_controller import (
    ObsController,
    decode_image_data,
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


def test_decode_image_data_accepts_data_url() -> None:
    expected = b"fake-jpeg"
    encoded = base64.b64encode(expected).decode("ascii")

    assert decode_image_data(f"data:image/jpeg;base64,{encoded}") == expected


def test_decode_image_data_rejects_invalid_base64() -> None:
    assert decode_image_data("data:image/jpeg;base64,not-valid-@@") is None


def test_handle_set_scene_uses_explicit_obs_request_after_fade_setup() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict | None, bool]] = []
            self.current_scene = "Palco"

        def send(self, request: str, data=None, *, raw: bool = False):
            self.calls.append((request, data, raw))
            if request == "GetSceneTransitionList":
                return {
                    "transitions": [
                        {
                            "transitionName": "Esmaecer",
                            "transitionKind": "fade_transition",
                        }
                    ]
                }
            if request in {
                "SetCurrentSceneTransition",
                "SetCurrentSceneTransitionDuration",
            }:
                return {}
            if request == "SetCurrentProgramScene":
                self.current_scene = data["sceneName"]
                return {}
            if request == "GetCurrentProgramScene":
                return {"currentProgramSceneName": self.current_scene}
            raise AssertionError(f"request inesperado: {request}")

    controller = ObsController()
    client = FakeClient()
    controller._client = client
    controller._last_scene = "Palco"

    controller._handle_set_scene("Mídias")

    assert (
        "SetCurrentProgramScene",
        {"sceneName": "Mídias"},
        True,
    ) in client.calls
    assert client.calls.index(
        ("SetCurrentSceneTransitionDuration", {"transitionDuration": 350}, True)
    ) < client.calls.index(
        ("SetCurrentProgramScene", {"sceneName": "Mídias"}, True)
    )
    assert controller._last_scene == "Mídias"
