from pathlib import Path

from PySide6.QtGui import QImage

from meeting_assistant.services.hall_idle_reference import HallIdleReferenceStore


def test_idle_reference_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "state" / "idle.png"
    store = HallIdleReferenceStore(path)
    image = QImage(32, 18, QImage.Format.Format_RGB32)
    image.fill(0x00112233)

    assert store.save(image)

    loaded = store.load()
    assert loaded is not None
    assert loaded.width() == 32
    assert loaded.height() == 18
    assert path.exists()


def test_idle_reference_rejects_null_image(tmp_path: Path) -> None:
    store = HallIdleReferenceStore(tmp_path / "idle.png")

    assert not store.save(QImage())
    assert store.load() is None


def test_idle_reference_clear(tmp_path: Path) -> None:
    path = tmp_path / "idle.png"
    store = HallIdleReferenceStore(path)
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(0x00000000)
    assert store.save(image)

    store.clear()

    assert not path.exists()
    assert store.load() is None
