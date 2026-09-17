from pathlib import Path

from meeting_assistant.services.idle_reference_store import IdleReferenceStore


def test_idle_reference_roundtrip(tmp_path: Path) -> None:
    store = IdleReferenceStore(tmp_path / "idle.json")
    frame = bytes([0, 1, 2, 250])

    store.save("DISPLAY2|Mídias", frame)

    assert store.load("DISPLAY2|Mídias") == frame
    assert store.load("OTHER") is None


def test_invalid_idle_reference_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "idle.json"
    path.write_text('{"key":"DISPLAY2|Mídias","frame":"not-base64!"}', encoding="utf-8")

    store = IdleReferenceStore(path)

    assert store.load("DISPLAY2|Mídias") is None
