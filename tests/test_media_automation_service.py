from meeting_assistant.services.media_automation_service import (
    MediaSignalDetector,
    MediaSignalEvent,
    pixel_difference,
    should_restore_scene,
)


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
