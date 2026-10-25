from __future__ import annotations

import os
import sqlite3

from meeting_assistant.services.jwl_media_importer import init_jwl_schema
from meeting_assistant.services.meeting_media_watch_folder import (
    convert_files_to_import_items,
    get_default_meeting_media_folder,
    open_folder_in_explorer,
    scan_watch_folder,
    sync_watch_folder_to_jwl,
)


def test_get_default_meeting_media_folder() -> None:
    folder = get_default_meeting_media_folder()
    assert folder.exists()
    assert folder.is_dir()


def test_scan_watch_folder(tmp_path) -> None:
    watch_dir = tmp_path / "MeetingMedia"
    watch_dir.mkdir()

    # Create various files
    (watch_dir / "slide1.jpg").write_bytes(b"JPG1")
    (watch_dir / "slide2.PNG").write_bytes(b"PNG2")
    (watch_dir / "video1.mp4").write_bytes(b"MP41")
    (watch_dir / "audio1.mp3").write_bytes(b"MP31")
    (watch_dir / "notes.txt").write_bytes(b"IGNORE")
    (watch_dir / "document.pdf").write_bytes(b"IGNORE")

    sub = watch_dir / "Discurso"
    sub.mkdir()
    (sub / "slide3.jpeg").write_bytes(b"JPG3")

    scanned = scan_watch_folder(watch_dir)
    assert len(scanned) == 5
    extensions = {p.suffix.lower() for p in scanned}
    assert extensions == {".jpg", ".png", ".mp4", ".mp3", ".jpeg"}


def test_sync_watch_folder_to_jwl(tmp_path) -> None:
    watch_dir = tmp_path / "WatchFolder"
    watch_dir.mkdir()
    (watch_dir / "slide_01.jpg").write_bytes(b"IMAGE_DATA_01")
    (watch_dir / "slide_02.jpg").write_bytes(b"IMAGE_DATA_02")

    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    items = convert_files_to_import_items(scan_watch_folder(watch_dir))
    assert len(items) == 2
    assert items[0].label == "slide 01"

    result = sync_watch_folder_to_jwl(watch_dir, playlist_name="Mídias Sincronizadas", db_path=db_file)
    assert result.success is True
    assert result.imported_count == 2
    assert result.playlist_name == "Mídias Sincronizadas"

    con = sqlite3.connect(db_file.as_posix())
    cur = con.cursor()
    cur.execute("SELECT count(*) FROM PlaylistItem")
    assert cur.fetchone()[0] == 2
    con.close()


def test_sync_watch_folder_idempotent_no_duplicates(tmp_path) -> None:
    watch_dir = tmp_path / "WatchFolder"
    watch_dir.mkdir()
    (watch_dir / "slide_01.jpg").write_bytes(b"DATA_01")
    (watch_dir / "slide_02.jpg").write_bytes(b"DATA_02")

    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    # First sync
    res1 = sync_watch_folder_to_jwl(watch_dir, playlist_name="Mídias", db_path=db_file)
    assert res1.success is True
    assert res1.imported_count == 2

    # Second sync immediately without changes
    res2 = sync_watch_folder_to_jwl(watch_dir, playlist_name="Mídias", db_path=db_file)
    assert res2.success is True
    assert res2.imported_count == 0

    con = sqlite3.connect(db_file.as_posix())
    cur = con.cursor()
    cur.execute("SELECT count(*) FROM TagMap")
    assert cur.fetchone()[0] == 2  # Exactly 2, no duplicates
    con.close()


def test_open_folder_in_explorer_safe(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        os, "startfile", lambda p: (_ for _ in ()).throw(OSError("mock error")), raising=False
    )
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: None)

    # Should not raise exception
    open_folder_in_explorer(tmp_path / "Folder")


def test_scan_watch_folder_jwpub_and_extract(tmp_path, monkeypatch) -> None:
    from unittest.mock import MagicMock

    from meeting_assistant.services.meeting_media_watch_folder import scan_watch_folder

    watch_dir = tmp_path / "WatchFolder"
    watch_dir.mkdir()
    jwpub_file = watch_dir / "mwb_T_202611.jwpub"
    jwpub_file.write_bytes(b"JWPUB_ZIP")

    scanned = scan_watch_folder(watch_dir)
    assert jwpub_file in scanned

    fake_extracted = tmp_path / "extracted_illustration.jpg"
    fake_extracted.write_bytes(b"ILLUSTRATION_BYTES")

    monkeypatch.setattr(
        "meeting_assistant.services.meeting_media_watch_folder.install_jwpub_to_jwl",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        "meeting_assistant.services.meeting_media_watch_folder.extract_images_from_jwpub",
        MagicMock(return_value=[fake_extracted]),
    )

    items = convert_files_to_import_items([jwpub_file])
    assert len(items) == 1
    assert items[0].source_path == fake_extracted


