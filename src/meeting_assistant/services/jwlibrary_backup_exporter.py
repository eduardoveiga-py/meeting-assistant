from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from meeting_assistant.services.jwl_media_importer import (
    DEFAULT_THUMBNAIL_BYTES,
    MediaImportItem,
    import_media_to_jwl,
    init_jwl_schema,
)


def _format_dotnet_datetime_offset(dt: datetime) -> str:
    """Formats a datetime matching .NET DateTimeOffset.ToString("o") (round-trip ISO 8601).
    JW Library Desktop (.NET Native UWP) expects exactly 7 fractional digits (.fffffffzzz)
    for creationDate in manifest.json. Python's default isoformat() produces only 6 digits,
    which triggers System.FormatException (0x80131537) in JW Library during package import.
    """
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    micro = f"{dt.microsecond:06d}0"
    tz = dt.strftime("%z")
    tz_formatted = f"{tz[:3]}:{tz[3:]}" if tz else "+00:00"
    return f"{base}.{micro}{tz_formatted}"


def export_playlist_to_jwlplaylist(
    items: list[MediaImportItem],
    playlist_name: str,
    output_path: Path,
) -> Path:
    """Creates an official .jwlplaylist package containing userData.db,
    manifest.json (type: 1), default_thumbnail.png, and media files.

    This format is recognized natively by JW Library's 'Import playlist' feature.
    If output_path has a .jwlibrary extension, it exports as a full backup package (type: 0).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    is_full_backup = output_path.suffix.lower() == ".jwlibrary"
    if not is_full_backup and output_path.suffix.lower() != ".jwlplaylist":
        output_path = output_path.with_suffix(".jwlplaylist")

    with tempfile.TemporaryDirectory(prefix="jwl_export_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        db_file = tmp_dir / "userData.db"

        # 1. Initialize complete official schema in temporary DB
        init_jwl_schema(db_file)

        # 2. Import items into this DB with automatic thumbnail generation
        result = import_media_to_jwl(
            items, playlist_name, db_path=db_file, backup=False, auto_thumbnails=True
        )
        if not result.success:
            raise RuntimeError(f"Falha ao preparar banco para exportação: {result.error_message}")

        # 3. Retrieve schema version, set WAL mode and checkpoint truncate
        # to match official JW Library package binary format version (2 2).
        con = sqlite3.connect(db_file.as_posix(), timeout=10.0)
        try:
            con.execute("PRAGMA busy_timeout = 10000;")
            row = con.execute("PRAGMA user_version;").fetchone()
            schema_version = int(row[0]) if row and row[0] else 16
            con.execute("PRAGMA journal_mode = WAL;")
            con.commit()
            con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        finally:
            con.close()

        for ext in ("-wal", "-shm"):
            sidecar = Path(f"{db_file.as_posix()}{ext}")
            if sidecar.exists():
                sidecar.unlink(missing_ok=True)

        # 4. Calculate SHA-256 hash of userData.db for manifest
        db_bytes = db_file.read_bytes()
        db_sha256 = hashlib.sha256(db_bytes).hexdigest()

        # 5. Write default_thumbnail.png into root of archive
        thumb_file = tmp_dir / "default_thumbnail.png"
        if not thumb_file.exists():
            thumb_file.write_bytes(DEFAULT_THUMBNAIL_BYTES)

        # 6. Build manifest.json matching official JW Library package schema
        # type 1 = Playlist (.jwlplaylist), type 0 = Full Backup (.jwlibrary)
        package_type = 0 if is_full_backup else 1
        now_local = datetime.now().astimezone()
        now_utc = datetime.now(UTC)
        manifest = {
            "name": output_path.name,
            "creationDate": _format_dotnet_datetime_offset(now_local),
            "version": 1,
            "type": package_type,
            "userDataBackup": {
                "lastModifiedDate": now_utc.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "deviceName": os.environ.get("COMPUTERNAME", "Meeting Assistant"),
                "databaseName": "userData.db",
                "hash": db_sha256,
                "schemaVersion": 14 if package_type == 1 else schema_version,
            },
        }
        manifest_file = tmp_dir / "manifest.json"
        manifest_file.write_text(
            json.dumps(manifest, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8"
        )

        # 7. Bundle all files in tmp_dir into DEFLATE zip archive
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(manifest_file, arcname="manifest.json")
            zf.write(db_file, arcname="userData.db")
            for item in tmp_dir.iterdir():
                if item.name not in ("manifest.json", "userData.db") and item.is_file():
                    zf.write(item, arcname=item.name)

    return output_path



def export_playlist_to_jwlibrary_backup(
    items: list[MediaImportItem],
    playlist_name: str,
    output_path: Path,
) -> Path:
    """Backward compatibility alias for exporting playlists."""
    return export_playlist_to_jwlplaylist(items, playlist_name, output_path)
