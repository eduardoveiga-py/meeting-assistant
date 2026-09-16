from meeting_assistant.services.media_automation_service import (
    MediaAutomationConfig,
    MediaAutomationService,
    MediaSignalDetector,
    MediaSignalEvent,
    pixel_difference,
    sensor_candidate_score,
    set_program_scene,
    should_restore_scene,
)
from meeting_assistant.services.obs_controller import ObsConnectionConfig


class FakeObsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object | None, bool]] = []

    def send(
        self,
        request_type: str,
        request_data: object | None = None,
        *,
        raw: bool = False,
    ) -> dict[str, object]:
        self.calls.append((request_type, request_data, raw))
        if request_type == "GetSceneTransitionList":
            return {
                "transitions": [
                    {
                        "transitionName": "Esmaecer",
                        "transitionKind": "fade_transition",
                    }
                ]
            }
        return {}


def test_pixel_difference_identical_frames_is_zero() -> None:
    assert pixel_difference(bytes([1, 2, 3]), bytes([1, 2, 3])) == 0.0


def test_pixel_difference_uses_pixel_threshold() -> None:
    changed = pixel_difference(bytes([0, 0, 0, 0]), bytes([0, 20, 0, 20]))
    assert changed == 50.0


def test_detector_requires_debounce_to_start_and_end() -> None:
    detector = MediaSignalDetector(
        start_threshold=5.0,
        end_threshold=1.5,
        start_hits_required=2,
        end_hits_required=3,
    )

    assert detector.update(0.0) is None
    assert detector.update(97.0) is None
    assert detector.update(96.0) == MediaSignalEvent.STARTED
    assert detector.active is True

    assert detector.update(0.5) is None
    assert detector.update(0.4) is None
    assert detector.update(0.3) == MediaSignalEvent.ENDED
    assert detector.active is False


def test_detector_resets_start_counter_after_noise() -> None:
    detector = MediaSignalDetector(start_hits_required=2)
    assert detector.update(10.0) is None
    assert detector.update(0.0) is None
    assert detector.update(10.0) is None
    assert detector.update(10.0) == MediaSignalEvent.STARTED


def test_detector_resets_end_counter_if_signal_returns() -> None:
    detector = MediaSignalDetector(start_hits_required=1, end_hits_required=2)
    assert detector.update(50.0) == MediaSignalEvent.STARTED
    assert detector.update(0.0) is None
    assert detector.update(50.0) is None
    assert detector.update(0.0) is None
    assert detector.update(0.0) == MediaSignalEvent.ENDED


def test_should_restore_only_when_automation_still_owns_media_scene() -> None:
    assert should_restore_scene(
        auto_switched=True,
        manual_override=False,
        return_scene="Palco",
        current_scene="Mídias",
        media_scene="Mídias",
    )
    assert not should_restore_scene(
        auto_switched=True,
        manual_override=True,
        return_scene="Palco",
        current_scene="Mídias",
        media_scene="Mídias",
    )
    assert not should_restore_scene(
        auto_switched=True,
        manual_override=False,
        return_scene="Palco",
        current_scene="Texto do Ano",
        media_scene="Mídias",
    )


def test_jw_library_window_capture_scores_above_monitor_capture() -> None:
    direct = sensor_candidate_score(
        "JW Library Real",
        "window_capture",
        {"window": "JW Library:Windows.UI.Core.CoreWindow:JWLibrary.exe"},
    )
    monitor = sensor_candidate_score(
        "JW Library",
        "monitor_capture",
        {"monitor_id": r"\\?\DISPLAY#MEIA296"},
    )
    assert direct > monitor
    assert direct >= 100


def test_set_program_scene_enforces_fade_then_switches() -> None:
    client = FakeObsClient()

    set_program_scene(client, "Mídias")  # type: ignore[arg-type]

    request_types = [call[0] for call in client.calls]
    assert "SetCurrentSceneTransition" in request_types
    assert "SetCurrentSceneTransitionDuration" in request_types
    assert client.calls[-1] == (
        "SetCurrentProgramScene",
        {"sceneName": "Mídias"},
        True,
    )


def test_media_automation_can_be_enabled_explicitly() -> None:
    config = MediaAutomationConfig(
        obs=ObsConnectionConfig(host="127.0.0.1", port=4455, password=""),
        sensor_source="Mídias",
        media_scene="Mídias",
        eligible_return_scenes=("Texto do Ano", "Palco"),
        preferred_return_scene="Palco",
    )
    service = MediaAutomationService(config_provider=lambda: config)

    assert service.enabled is False
    service.set_enabled(True)
    assert service.enabled is True
    service.set_enabled(False)
    assert service.enabled is False
