import json

from meeting_assistant.services.jwl_idle_reference import (
    JwlIdleReference,
    JwlIdleReferenceStore,
    retain_confirmed_variants,
)
from meeting_assistant.services.media_automation_service import (
    MediaSignalDetector,
    MediaSignalEvent,
    idle_reference_difference,
    pixel_difference,
)


def test_confirmed_variants_survive_restart_and_return_media_to_palco(tmp_path):
    original = bytes([0] * 95 + [220] * 5)
    restored = bytes([220] * 5 + [0] * 95)
    assert pixel_difference(original, restored) > 3
    ref = retain_confirmed_variants(
        JwlIdleReference(original, 10, 10), JwlIdleReference(restored, 10, 10)
    )
    store = JwlIdleReferenceStore(tmp_path / "idle.json")
    store.save(ref)
    ref = store.load()
    detector = MediaSignalDetector()
    # Both appearances stay idle, even when alternated repeatedly.
    for frame in [original, restored] * 4:
        assert detector.update(idle_reference_difference(ref, frame)) is None
        assert not detector.active
    media = bytes([180] * 100)
    assert detector.update(idle_reference_difference(ref, media)) is None
    assert detector.update(idle_reference_difference(ref, media)) == MediaSignalEvent.STARTED
    assert detector.update(idle_reference_difference(ref, restored)) is None
    assert detector.update(idle_reference_difference(ref, restored)) is None
    assert detector.update(idle_reference_difference(ref, restored)) == MediaSignalEvent.ENDED


def test_existing_single_reference_files_remain_readable(tmp_path):
    store = JwlIdleReferenceStore(tmp_path / "idle.json")
    ref = JwlIdleReference(bytes(100), 10, 10)
    store.save(ref)
    data = json.loads(store.path.read_text())
    del data["alternate_pixels"]
    store.path.write_text(json.dumps(data))
    assert store.load() == ref


def test_duplicate_calibration_does_not_discard_alternates():
    ref = JwlIdleReference(bytes(100), 10, 10, alternate_pixels=(bytes([220] * 100),))
    assert retain_confirmed_variants(ref, JwlIdleReference(bytes(100), 10, 10)) == ref
