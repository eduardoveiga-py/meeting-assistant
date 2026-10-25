import shutil
import sqlite3

import pytest

from meeting_assistant.services.jwl_media_importer import (
    MediaImportItem,
    backup_userdata_db,
    calculate_jwl_hash,
    detect_mime_type,
    import_media_to_jwl,
    init_jwl_schema,
    list_userdata_backups,
    restore_userdata_backup,
)


def test_calculate_jwl_hash_matches_unpadded_hex() -> None:
    # A byte sequence with leading zeroes in nibbles
    data = b"\x00\x0f\x10\xff\x05"
    import hashlib

    expected = hashlib.sha256(data).hexdigest().lower()

    assert calculate_jwl_hash(data) == expected
    assert len(calculate_jwl_hash(data)) == 64
    # Ensure it's lowercase and contains only hex characters
    assert all(c in "0123456789abcdef" for c in calculate_jwl_hash(data))


def test_detect_mime_type(tmp_path) -> None:
    assert detect_mime_type(tmp_path / "song.mp4") == "video/mp4"
    assert detect_mime_type(tmp_path / "song.m4v") == "video/mp4"
    assert detect_mime_type(tmp_path / "audio.mp3") == "audio/mp3"
    assert detect_mime_type(tmp_path / "audio.m4a") == "audio/mp4"
    assert detect_mime_type(tmp_path / "photo.jpg") == "image/jpeg"
    assert detect_mime_type(tmp_path / "photo.png") == "image/png"
    assert detect_mime_type(tmp_path / "unknown.xyz") == "application/octet-stream"


def test_init_jwl_schema(tmp_path) -> None:
    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)

    con = sqlite3.connect(db_file.as_posix())
    try:
        cur = con.cursor()
        rows = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {r[0] for r in rows}
        assert "IndependentMedia" in tables
        assert "PlaylistItem" in tables
        assert "PlaylistItemIndependentMediaMap" in tables
        assert "Tag" in tables
        assert "TagMap" in tables
        assert "LastModified" in tables
        assert "PlaylistItemAccuracy" in tables

        # Verify LastModified has initial timestamp
        cur.execute("SELECT LastModified FROM LastModified")
        assert cur.fetchone() is not None

        # Verify PRAGMA user_version
        cur.execute("PRAGMA user_version")
        assert cur.fetchone()[0] == 16
    finally:
        con.close()


def test_backup_and_restore_userdata_db(tmp_path) -> None:
    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)

    backup_dir = tmp_path / "backups"
    # Create multiple backups to verify rotation
    _ = backup_userdata_db(db_file, backup_dir=backup_dir, max_backups=2)
    _ = backup_userdata_db(db_file, backup_dir=backup_dir, max_backups=2)
    b3 = backup_userdata_db(db_file, backup_dir=backup_dir, max_backups=2)

    assert b3.exists()
    backups = list_userdata_backups(backup_dir=backup_dir)
    assert len(backups) == 2  # Pruned to max 2

    # Mutate db and test restore
    con = sqlite3.connect(db_file.as_posix())
    con.execute("INSERT INTO Tag (Type, Name) VALUES (2, 'Playlist Temporaria')")
    con.commit()
    con.close()

    # Restore from b3 (before mutation)
    restore_userdata_backup(b3, db_file)

    con2 = sqlite3.connect(db_file.as_posix())
    cur2 = con2.cursor()
    cur2.execute("SELECT count(*) FROM Tag WHERE Name = 'Playlist Temporaria'")
    assert cur2.fetchone()[0] == 0
    con2.close()


def test_import_media_to_jwl(tmp_path) -> None:
    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    # Create dummy source files
    video_file = tmp_path / "cantico_014.mp4"
    video_file.write_bytes(b"FAKE_MP4_CONTENT_12345")

    image_file = tmp_path / "slide_discurso.jpg"
    image_file.write_bytes(b"FAKE_JPG_CONTENT_67890")

    items = [
        MediaImportItem(
            source_path=video_file,
            label="14. O Reino de Deus Já Domina!",
            duration_seconds=125.5,
            end_action=2,
        ),
        MediaImportItem(
            source_path=image_file,
            label="Slide 1 - Introdução",
            duration_seconds=0.0,
            end_action=2,
        ),
    ]

    result = import_media_to_jwl(items, playlist_name="Reunião de Meio de Semana", db_path=db_file)
    assert result.success is True
    assert result.imported_count == 2
    assert result.playlist_name == "Reunião de Meio de Semana"
    assert result.backup_path is not None
    assert result.backup_path.exists()

    # Verify SQLite rows
    con = sqlite3.connect(db_file.as_posix())
    try:
        cur = con.cursor()
        # Verify Tag
        cur.execute("SELECT TagId, Name, Type FROM Tag WHERE Name = 'Reunião de Meio de Semana'")
        tag_row = cur.fetchone()
        assert tag_row is not None
        tag_id = tag_row[0]
        assert tag_row[2] == 2  # Type 2 = Playlist

        # Verify TagMap has 2 items at positions 0 and 1
        cur.execute(
            "SELECT PlaylistItemId, Position FROM TagMap WHERE TagId = ? ORDER BY Position",
            (tag_id,),
        )
        tag_map_rows = cur.fetchall()
        assert len(tag_map_rows) == 2
        assert tag_map_rows[0][1] == 0
        assert tag_map_rows[1][1] == 1

        # Verify PlaylistItem labels
        item_id_1 = tag_map_rows[0][0]
        cur.execute(
            "SELECT Label, Accuracy, EndAction FROM PlaylistItem WHERE PlaylistItemId = ?",
            (item_id_1,),
        )
        item1_row = cur.fetchone()
        assert item1_row[0] == "14. O Reino de Deus Já Domina!"
        assert item1_row[1] == 1
        assert item1_row[2] == 2

        # Verify IndependentMedia and files in Userdata
        cur.execute("SELECT FilePath, Hash FROM IndependentMedia")
        media_rows = cur.fetchall()
        assert len(media_rows) == 2
        for fp, _h in media_rows:
            assert (userdata_dir / fp).is_file()

        # Verify duration ticks
        cur.execute(
            "SELECT DurationTicks FROM PlaylistItemIndependentMediaMap WHERE PlaylistItemId = ?",
            (item_id_1,),
        )
        ticks = cur.fetchone()[0]
        assert ticks == int(125.5 * 10_000_000)

        # Import identical file again into a different playlist (tests deduplication)
        items2 = [
            MediaImportItem(
                source_path=video_file,
                label="14. Cântico Repetido",
                duration_seconds=125.5,
            )
        ]
        result2 = import_media_to_jwl(items2, playlist_name="Outra Playlist", db_path=db_file)
        assert result2.success is True
        # IndependentMedia count should STILL be 2 because hash was identical
        cur.execute("SELECT count(*) FROM IndependentMedia")
        assert cur.fetchone()[0] == 2

    finally:
        con.close()


def test_import_media_skips_duplicates_in_same_playlist(tmp_path) -> None:
    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    sample_file = tmp_path / "slide.jpg"
    sample_file.write_bytes(b"TEST_SLIDE_DATA")

    item = MediaImportItem(source_path=sample_file, label="Slide A")

    # First import
    res1 = import_media_to_jwl([item], playlist_name="Minha Playlist", db_path=db_file)
    assert res1.success is True
    assert res1.imported_count == 1

    # Second import to the same playlist
    res2 = import_media_to_jwl([item], playlist_name="Minha Playlist", db_path=db_file)
    assert res2.success is True
    assert res2.imported_count == 0  # Skipped duplicate

    con = sqlite3.connect(db_file.as_posix())
    cur = con.cursor()
    cur.execute("SELECT count(*) FROM TagMap")
    assert cur.fetchone()[0] == 1  # No duplicate rows
    con.close()


def test_import_media_restores_missing_physical_file_when_hash_exists(tmp_path) -> None:
    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    sample_file = tmp_path / "video.mp4"
    sample_file.write_bytes(b"VIDEO_CONTENT_123")

    item = MediaImportItem(source_path=sample_file, label="Video 1")
    _ = import_media_to_jwl([item], playlist_name="Playlist 1", db_path=db_file)

    # Locate and delete the physical file in Userdata
    con = sqlite3.connect(db_file.as_posix())
    cur = con.cursor()
    cur.execute("SELECT FilePath FROM IndependentMedia")
    stored_name = cur.fetchone()[0]
    con.close()

    stored_file = userdata_dir / stored_name
    assert stored_file.is_file()
    stored_file.unlink()
    assert not stored_file.exists()

    # Re-importing into Playlist 2 must restore the physical file
    res2 = import_media_to_jwl([item], playlist_name="Playlist 2", db_path=db_file)
    assert res2.success is True
    assert stored_file.is_file()
    assert stored_file.read_bytes() == b"VIDEO_CONTENT_123"


def test_restore_userdata_backup_permission_error_message(tmp_path, monkeypatch) -> None:
    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    backup_file = tmp_path / "backup.db"
    backup_file.write_bytes(db_file.read_bytes())

    def mock_copy2(*args, **kwargs):
        raise PermissionError("Access is denied")

    monkeypatch.setattr(shutil, "copy2", mock_copy2)
    with pytest.raises(PermissionError) as exc_info:
        restore_userdata_backup(backup_file, db_file)
    assert "Feche o aplicativo JW Library" in str(exc_info.value)


def test_register_media_in_jwl_collection_video_and_aliases(tmp_path) -> None:
    from meeting_assistant.services.jwl_media_importer import register_media_in_jwl_collection

    db_path = tmp_path / "mediaCollection.db"
    con = sqlite3.connect(db_path.as_posix())
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE MediaKey (
            MediaKeyId INTEGER PRIMARY KEY AUTOINCREMENT,
            KeySymbol TEXT,
            MediaType INTEGER,
            DocumentId INTEGER,
            MepsLanguageIndex INTEGER,
            IssueTagNumber INTEGER,
            Track INTEGER,
            BookNumber INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE Video (
            VideoId INTEGER PRIMARY KEY AUTOINCREMENT,
            MediaKeyId INTEGER UNIQUE,
            Title TEXT,
            Version INTEGER,
            MimeType TEXT,
            BitRate REAL,
            FrameRate REAL,
            Duration REAL,
            Checksum TEXT,
            FileSize INTEGER,
            FrameHeight INTEGER,
            FrameWidth INTEGER,
            Label TEXT,
            FilePath TEXT,
            Source INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE Audio (
            AudioId INTEGER PRIMARY KEY AUTOINCREMENT,
            MediaKeyId INTEGER UNIQUE,
            Title TEXT,
            Version INTEGER,
            MimeType TEXT,
            BitRate REAL,
            Duration REAL,
            Checksum TEXT,
            FileSize INTEGER,
            FilePath TEXT,
            Source INTEGER
        )
        """
    )
    con.commit()
    con.close()

    video_file = tmp_path / "sjjm_TCN_001_r240P.mp4"
    video_file.write_bytes(b"TEST_VIDEO")

    # Register song 1 in Ticuna (meps_language_index=733)
    ok = register_media_in_jwl_collection(
        db_path=db_path,
        file_path=video_file,
        key_symbol="sjjm",
        media_type=1,
        meps_language_index=733,
        track=1,
        title="1. Cântico 1",
        duration=180.0,
        filesize=1000000,
        checksum="hash123",
        label="240p",
    )
    assert ok is True

    con = sqlite3.connect(db_path.as_posix())
    cur = con.cursor()
    # sjjm and sjj aliases should both be registered
    cur.execute("SELECT KeySymbol, Track, MepsLanguageIndex FROM MediaKey")
    keys = cur.fetchall()
    assert ("sjjm", 1, 733) in keys
    assert ("sjj", 1, 733) in keys
    assert len(keys) == 2

    cur.execute("SELECT FilePath, Label, Checksum FROM Video")
    videos = cur.fetchall()
    assert len(videos) == 2
    for vpath, vlabel, vchk in videos:
        assert vpath == str(video_file)
        assert vlabel == "240p"
        assert vchk == "hash123"

    con.close()


def test_register_media_in_jwl_collection_audio(tmp_path) -> None:
    from meeting_assistant.services.jwl_media_importer import register_media_in_jwl_collection

    db_path = tmp_path / "mediaCollection.db"
    con = sqlite3.connect(db_path.as_posix())
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE MediaKey (
            MediaKeyId INTEGER PRIMARY KEY AUTOINCREMENT,
            KeySymbol TEXT,
            MediaType INTEGER,
            DocumentId INTEGER,
            MepsLanguageIndex INTEGER,
            IssueTagNumber INTEGER,
            Track INTEGER,
            BookNumber INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE Audio (
            AudioId INTEGER PRIMARY KEY AUTOINCREMENT,
            MediaKeyId INTEGER UNIQUE,
            Title TEXT,
            Version INTEGER,
            MimeType TEXT,
            BitRate REAL,
            Duration REAL,
            Checksum TEXT,
            FileSize INTEGER,
            FilePath TEXT,
            Source INTEGER
        )
        """
    )
    con.commit()
    con.close()

    audio_file = tmp_path / "w_T_202610_01.mp3"
    audio_file.write_bytes(b"TEST_AUDIO")

    ok = register_media_in_jwl_collection(
        db_path=db_path,
        file_path=audio_file,
        key_symbol="w",
        media_type=2,
        meps_language_index=5,
        track=1,
        issue_tag_number=202610,
        title="Artigo 1",
        duration=600.0,
        filesize=5000000,
    )
    assert ok is True

    con = sqlite3.connect(db_path.as_posix())
    cur = con.cursor()
    cur.execute("SELECT KeySymbol, MediaType, Track, IssueTagNumber FROM MediaKey")
    assert cur.fetchone() == ("w", 2, 1, 202610)
    cur.execute("SELECT FilePath, Duration, FileSize FROM Audio")
    assert cur.fetchone() == (str(audio_file), 600.0, 5000000)
    con.close()


def test_import_official_publication_media_uses_location(tmp_path) -> None:
    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    song_file = tmp_path / "sjjm_TCN_001_r240P.mp4"
    song_file.write_bytes(b"TICUNA_SONG_VIDEO_BYTES")

    official_item = MediaImportItem(
        source_path=song_file,
        label="1. Yeuwacũmagʉ",
        duration_seconds=170.0,
        end_action=2,
        key_symbol="sjjm",
        track=1,
        meps_language_index=733,
        issue_tag_number=0,
    )

    res = import_media_to_jwl([official_item], playlist_name="Cânticos da Reunião", db_path=db_file)
    assert res.success is True
    assert res.imported_count == 1

    con = sqlite3.connect(db_file.as_posix())
    try:
        cur = con.cursor()
        # Verify Location row
        cur.execute(
            "SELECT LocationId, KeySymbol, Track, MepsLanguage, Type, Title FROM Location"
        )
        loc = cur.fetchone()
        assert loc is not None
        assert loc[1] == "sjjm"
        assert loc[2] == 1
        assert loc[3] == 733
        assert loc[4] == 3  # Type 3 = media
        assert loc[5] == "1. Yeuwacũmagʉ"

        # Verify PlaylistItemLocationMap
        cur.execute(
            "SELECT PlaylistItemId, LocationId, MajorMultimediaType, BaseDurationTicks "
            "FROM PlaylistItemLocationMap"
        )
        plm = cur.fetchone()
        assert plm is not None
        assert plm[1] == loc[0]
        assert plm[2] == 2  # MajorMultimediaType 2 = Video
        assert plm[3] == 170 * 10_000_000

        # Verify IndependentMedia is NOT used for this official publication media
        cur.execute("SELECT count(*) FROM IndependentMedia")
        assert cur.fetchone()[0] == 0

        # Verify deduplication for official publication media
        res_dup = import_media_to_jwl([official_item], playlist_name="Cânticos da Reunião", db_path=db_file)
        assert res_dup.success is True
        assert res_dup.imported_count == 0
    finally:
        con.close()


def test_register_media_in_jwl_collection_video_specialty(tmp_path) -> None:
    from meeting_assistant.services.jwl_media_importer import register_media_in_jwl_collection

    db_path = tmp_path / "mediaCollection.db"
    con = sqlite3.connect(db_path.as_posix())
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE MediaKey (
            MediaKeyId INTEGER PRIMARY KEY AUTOINCREMENT,
            KeySymbol TEXT,
            MediaType INTEGER,
            DocumentId INTEGER,
            MepsLanguageIndex INTEGER,
            IssueTagNumber INTEGER,
            Track INTEGER,
            BookNumber INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE Video (
            VideoId INTEGER PRIMARY KEY AUTOINCREMENT,
            MediaKeyId INTEGER UNIQUE,
            Title TEXT,
            Version INTEGER,
            MimeType TEXT,
            BitRate REAL,
            FrameRate REAL,
            Duration REAL,
            Checksum TEXT,
            FileSize INTEGER,
            FrameHeight INTEGER,
            FrameWidth INTEGER,
            Label TEXT,
            SpecialtyDescription TEXT,
            Specialty TEXT,
            Edition TEXT,
            FilePath TEXT,
            Source INTEGER
        )
        """
    )
    con.commit()
    con.close()

    video_file = tmp_path / "sjjm_TCN_001_r720P.mp4"
    video_file.write_bytes(b"TEST_VIDEO_BYTES")

    ok = register_media_in_jwl_collection(
        db_path=db_path,
        file_path=video_file,
        key_symbol="sjjm",
        media_type=1,
        meps_language_index=733,
        track=1,
        title="1. Yeuwacũmagʉ",
        duration=170.0,
        filesize=2000000,
        checksum="chk789",
        label="720p",
    )
    assert ok is True

    con = sqlite3.connect(db_path.as_posix())
    cur = con.cursor()
    cur.execute("SELECT SpecialtyDescription, Specialty, Edition, FilePath FROM Video")
    row = cur.fetchone()
    assert row == ("", "", "", str(video_file))
    con.close()


def test_is_publication_installed(tmp_path) -> None:
    from meeting_assistant.services.jwl_media_importer import is_publication_installed

    # Missing database returns False
    assert is_publication_installed("mwb", issue_tag=202609, db_path=tmp_path / "missing.db") is False

    db_path = tmp_path / "pub_collections.db"
    con = sqlite3.connect(db_path.as_posix())
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE Publication (
            PublicationId INTEGER PRIMARY KEY AUTOINCREMENT,
            LanguageIndex INTEGER,
            KeySymbol TEXT,
            IssueTagNumber INTEGER,
            DatabasePath TEXT,
            JwPub TEXT
        )
        """
    )
    fake_pub_db = tmp_path / "mwb_T_202609.db"
    fake_pub_db.write_bytes(b"FAKE_PUB_SQLITE")

    cur.execute(
        """
        INSERT INTO Publication (LanguageIndex, KeySymbol, IssueTagNumber, DatabasePath, JwPub)
        VALUES (5, 'mwb', 20260900, ?, 'mwb_T_202609.jwpub')
        """,
        (str(fake_pub_db),),
    )
    con.commit()
    con.close()

    # Query with 6-digit issue tag (202609) matches 8-digit row (20260900)
    assert is_publication_installed("mwb", issue_tag=202609, meps_language_index=5, db_path=db_path) is True
    # Query with 8-digit issue tag matches
    assert is_publication_installed("mwb", issue_tag=20260900, meps_language_index=5, db_path=db_path) is True
    # Case insensitivity
    assert is_publication_installed("MWB", issue_tag=202609, meps_language_index=5, db_path=db_path) is True
    # Different issue tag returns False
    assert is_publication_installed("mwb", issue_tag=202701, meps_language_index=5, db_path=db_path) is False
    # Different key symbol returns False
    assert is_publication_installed("w", issue_tag=202609, meps_language_index=5, db_path=db_path) is False


def test_install_jwpub_to_jwl(tmp_path) -> None:
    from unittest.mock import patch

    from meeting_assistant.services.jwl_media_importer import install_jwpub_to_jwl

    # Nonexistent file returns False
    assert install_jwpub_to_jwl(tmp_path / "nonexistent.jwpub") is False

    valid_file = tmp_path / "sample.jwpub"
    valid_file.write_bytes(b"ZIP_JWPUB_CONTENT")

    with patch("os.startfile", create=True) as mock_startfile:
        assert install_jwpub_to_jwl(valid_file) is True
        mock_startfile.assert_called_once_with(str(valid_file))


def test_register_media_in_jwl_collection_mwbv_registers_both_symbols(tmp_path) -> None:
    from meeting_assistant.services.jwl_media_importer import register_media_in_jwl_collection

    db_path = tmp_path / "mediaCollection.db"
    con = sqlite3.connect(db_path.as_posix())
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE MediaKey (
            MediaKeyId INTEGER PRIMARY KEY AUTOINCREMENT,
            KeySymbol TEXT,
            MediaType INTEGER,
            DocumentId INTEGER,
            MepsLanguageIndex INTEGER,
            IssueTagNumber INTEGER,
            Track INTEGER,
            BookNumber INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE Video (
            VideoId INTEGER PRIMARY KEY AUTOINCREMENT,
            MediaKeyId INTEGER UNIQUE,
            Title TEXT,
            Version INTEGER,
            MimeType TEXT,
            BitRate REAL,
            FrameRate REAL,
            Duration REAL,
            Checksum TEXT,
            FileSize INTEGER,
            FrameHeight INTEGER,
            FrameWidth INTEGER,
            Label TEXT,
            FilePath TEXT,
            Source INTEGER
        )
        """
    )
    con.commit()
    con.close()

    video_file = tmp_path / "mwbv_video.mp4"
    video_file.write_bytes(b"VIDEO_MIDWEEK")

    ok = register_media_in_jwl_collection(
        db_path=db_path,
        file_path=video_file,
        key_symbol="mwbv",
        media_type=1,
        meps_language_index=5,
        track=1,
        issue_tag_number=202611,
        title="Midweek Video 1",
    )
    assert ok is True

    con = sqlite3.connect(db_path.as_posix())
    cur = con.cursor()
    cur.execute("SELECT KeySymbol, Track, IssueTagNumber FROM MediaKey ORDER BY KeySymbol")
    rows = cur.fetchall()
    # Both mwb and mwbv are registered
    assert len(rows) == 2
    assert ("mwb", 1, 202611) in rows
    assert ("mwbv", 1, 202611) in rows
    con.close()


def test_import_official_media_with_document_id(tmp_path) -> None:
    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    video_file = tmp_path / "1112024060_S_cnt_1_r720P.mp4"
    video_file.write_bytes(b"DOCID_VIDEO_BYTES")

    official_item = MediaImportItem(
        source_path=video_file,
        label="Informe 6 do Corpo Gobernante",
        key_symbol="docid-1112024060",
        track=None,
        document_id=1112024060,
        meps_language_index=1,
    )

    result = import_media_to_jwl([official_item], playlist_name="Meio de Semana", db_path=db_file)
    assert result.success is True
    assert result.imported_count == 1

    con = sqlite3.connect(db_file.as_posix())
    cur = con.cursor()
    cur.execute("SELECT KeySymbol, DocumentId, Track, Type FROM Location WHERE DocumentId = 1112024060")
    loc = cur.fetchone()
    assert loc is not None
    assert loc == ("docid-1112024060", 1112024060, None, 3)

    cur.execute("SELECT count(*) FROM PlaylistItemLocationMap")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT count(*) FROM IndependentMedia")
    assert cur.fetchone()[0] == 0
    con.close()




