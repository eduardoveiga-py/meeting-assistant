from pathlib import Path

from meeting_assistant.services.jwl_idle_reference import (
    JwlIdleReference,
    JwlIdleReferenceStore,
)


def test_idle_reference_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "idle.json"
    store = JwlIdleReferenceStore(path)
    reference = JwlIdleReference(
        pixels=bytes([1, 2, 3, 4]),
        sample_width=2,
        sample_height=2,
    )

    store.save(reference)

    assert store.load() == reference


def test_invalid_idle_reference_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "idle.json"
    path.write_text('{"version": 1, "sample_width": 2}', encoding="utf-8")
    assert JwlIdleReferenceStore(path).load() is None


def test_idle_reference_clear(tmp_path: Path) -> None:
    path = tmp_path / "idle.json"
    store = JwlIdleReferenceStore(path)
    store.save(
        JwlIdleReference(
            pixels=bytes([0]),
            sample_width=1,
            sample_height=1,
        )
    )
    store.clear()
    assert not path.exists()
