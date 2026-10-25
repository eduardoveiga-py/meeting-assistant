from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile

from meeting_assistant.services.jwl_media_importer import MediaImportItem
from meeting_assistant.services.jwlibrary_backup_exporter import (
    export_playlist_to_jwlibrary_backup,
)


def test_export_playlist_to_jwlibrary_backup(tmp_path) -> None:
    f1 = tmp_path / "slide1.jpg"
    f1.write_bytes(b"IMAGE_CONTENT_ABC")

    f2 = tmp_path / "video1.mp4"
    f2.write_bytes(b"VIDEO_CONTENT_DEF")

    items = [
        MediaImportItem(source_path=f1, label="Slide Inicial", duration_seconds=0.0),
        MediaImportItem(source_path=f2, label="Vídeo Ilustrativo", duration_seconds=60.0),
    ]

    out_file = tmp_path / "ExportTeste.jwlibrary"
    result_path = export_playlist_to_jwlibrary_backup(items, "Discurso 123", out_file)

    assert result_path.exists()
    assert result_path.suffix == ".jwlibrary"

    # Inspect zip contents
    with zipfile.ZipFile(result_path, "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "userData.db" in namelist
        assert "default_thumbnail.png" in namelist
        # Should contain media files and their thumbnails
        media_files = [
            n for n in namelist if n not in ("manifest.json", "userData.db", "default_thumbnail.png")
        ]
        assert len(media_files) >= 2

        # Validate manifest.json (strictly matches official JW Library schema)
        manifest_data = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest_data["name"] == out_file.name
        assert manifest_data["version"] == 1
        assert manifest_data["type"] == 0
        assert "userDataBackup" in manifest_data
        assert "userDataDb" not in manifest_data
        assert manifest_data["userDataBackup"]["databaseName"] == "userData.db"
        assert "lastModifiedDate" in manifest_data["userDataBackup"]
        import re
        # Validate .NET DateTimeOffset format (exact 7 fractional digits + timezone offset)
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{7}[+-]\d{2}:\d{2}$",
            manifest_data["creationDate"],
        ), f"Invalid creationDate format: {manifest_data['creationDate']}"
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$",
            manifest_data["userDataBackup"]["lastModifiedDate"],
        ), f"Invalid lastModifiedDate format: {manifest_data['userDataBackup']['lastModifiedDate']}"
        db_hash = manifest_data["userDataBackup"]["hash"]

        # Validate sha256 matches actual userData.db inside zip
        actual_db_bytes = zf.read("userData.db")
        assert hashlib.sha256(actual_db_bytes).hexdigest() == db_hash

        # Extract db and verify SQLite schema and content
        extracted_db = tmp_path / "extracted_userData.db"
        extracted_db.write_bytes(actual_db_bytes)

        con = sqlite3.connect(extracted_db.as_posix())
        try:
            cur = con.cursor()
            cur.execute("SELECT Name FROM Tag WHERE Type = 2")
            assert cur.fetchone()[0] == "Discurso 123"

            cur.execute("SELECT Label FROM PlaylistItem ORDER BY PlaylistItemId")
            labels = [r[0] for r in cur.fetchall()]
            assert labels == ["Slide Inicial", "Vídeo Ilustrativo"]
        finally:
            con.close()


def test_export_playlist_to_jwlplaylist(tmp_path) -> None:
    from meeting_assistant.services.jwlibrary_backup_exporter import (
        export_playlist_to_jwlplaylist,
    )

    f1 = tmp_path / "foto.jpg"
    f1.write_bytes(b"JPEG_TEST_DATA")
    items = [MediaImportItem(source_path=f1, label="Foto Teste", duration_seconds=0.0)]

    out_file = tmp_path / "MinhaPlaylist.jwlplaylist"
    result = export_playlist_to_jwlplaylist(items, "Playlist Orador", out_file)

    assert result.is_file()
    assert result.suffix == ".jwlplaylist"

    with zipfile.ZipFile(result, "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "userData.db" in namelist
        assert "default_thumbnail.png" in namelist
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["name"] == out_file.name
        assert manifest["type"] == 1
        assert manifest["version"] == 1
        assert "userDataDb" not in manifest
        assert manifest["userDataBackup"]["databaseName"] == "userData.db"
        assert manifest["userDataBackup"]["schemaVersion"] == 14
        db_sha256 = hashlib.sha256(zf.read("userData.db")).hexdigest()
        assert manifest["userDataBackup"]["hash"] == db_sha256

        # Verify SQLite schema completeness (all 17 official tables)
        extracted_db = tmp_path / "extracted_playlist_userData.db"
        extracted_db.write_bytes(zf.read("userData.db"))
        con = sqlite3.connect(extracted_db.as_posix())
        try:
            tables = {
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            assert len(tables) == 17
            assert "PlaylistItem" in tables
            assert "PlaylistItemAccuracy" in tables
            assert "IndependentMedia" in tables
            assert "Tag" in tables
            assert "TagMap" in tables

            # Verify tag name and items
            tag_name = con.execute("SELECT Name FROM Tag WHERE Type = 2").fetchone()[0]
            assert tag_name == "Playlist Orador"

            item_row = con.execute(
                "SELECT Label, ThumbnailFilePath FROM PlaylistItem"
            ).fetchone()
            assert item_row[0] == "Foto Teste"
            assert item_row[1] is not None
        finally:
            con.close()

        import re
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{7}[+-]\d{2}:\d{2}$",
            manifest["creationDate"],
        )


def test_format_dotnet_datetime_offset() -> None:
    from datetime import UTC, datetime, timedelta, timezone

    from meeting_assistant.services.jwlibrary_backup_exporter import (
        _format_dotnet_datetime_offset,
    )

    # Test UTC
    dt_utc = datetime(2026, 10, 13, 15, 30, 45, 123456, tzinfo=UTC)
    res_utc = _format_dotnet_datetime_offset(dt_utc)
    assert res_utc == "2026-10-13T15:30:45.1234560+00:00"

    # Test Brasilia time (-03:00)
    tz_br = timezone(timedelta(hours=-3))
    dt_br = datetime(2026, 10, 13, 12, 30, 45, 987654, tzinfo=tz_br)
    res_br = _format_dotnet_datetime_offset(dt_br)
    assert res_br == "2026-10-13T12:30:45.9876540-03:00"

    # Test zero microseconds (must still have 7 digits)
    dt_zero = datetime(2026, 10, 13, 12, 0, 0, 0, tzinfo=tz_br)
    res_zero = _format_dotnet_datetime_offset(dt_zero)
    assert res_zero == "2026-10-13T12:00:00.0000000-03:00"

