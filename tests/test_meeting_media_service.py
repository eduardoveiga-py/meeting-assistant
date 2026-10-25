from __future__ import annotations

import datetime
import io
import os
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

from meeting_assistant.services.jwl_media_importer import init_jwl_schema
from meeting_assistant.services.meeting_media_downloader import CBSMediaEntry, MediaDownloadItem
from meeting_assistant.services.meeting_media_service import MeetingMediaService
from meeting_assistant.services.settings import AppSettings


def test_meeting_media_service_coordination(tmp_path) -> None:
    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    media_dir = tmp_path / "MediaStorage"
    media_dir.mkdir()

    settings = AppSettings(
        meeting_media_folder=str(media_dir),
        jwl_userdata_db_path=str(db_file),
        congregation_language="T",
        meeting_media_quality="720p",
    )
    service = MeetingMediaService(settings)

    assert service.media_folder == media_dir
    assert service.jwl_db_path == db_file
    assert service.language == "T"
    assert service.preferred_quality == "720p"

    # Test manual backup and listing
    backup_file = service.create_manual_backup()
    assert backup_file.exists()
    backups = service.list_backups()
    assert len(backups) >= 1

    # Test download and import songs with mocked network
    mock_catalog = {
        14: MediaDownloadItem(
            title="14. O Reino de Deus Já Domina!",
            url="https://example.com/sjj_014.mp4",
            duration_seconds=120.0,
            suggested_filename="sjj_014.mp4",
        )
    }

    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Length": "12"}
    mock_resp.read.side_effect = io.BytesIO(b"VIDEO_SONG14").read
    mock_resp.__enter__.return_value = mock_resp

    with (
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_songs_catalog",
            return_value=mock_catalog,
        ),
        patch("urllib.request.urlopen", return_value=mock_resp),
    ):
        result = service.download_songs_and_import(
            [14],
            playlist_name="Cânticos Teste",
        )
        assert result.success is True
        assert result.imported_count == 1
        assert result.playlist_name == "Cânticos Teste"

    # Test local file import
    local_img = tmp_path / "slide.jpg"
    local_img.write_bytes(b"LOCAL_SLIDE")
    local_res = service.import_local_files([local_img], playlist_name="Discurso Teste")
    assert local_res.success is True
    assert local_res.imported_count == 1

    # Test export backup package
    pkg_file = tmp_path / "Export.jwlibrary"
    exported = service.export_backup_package([local_img], "Discurso Teste", pkg_file)
    assert exported.exists()
    assert exported.stat().st_size > 0


def test_meeting_media_service_midweek_download(tmp_path) -> None:
    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    media_dir = tmp_path / "MediaStorage"
    media_dir.mkdir()

    settings = AppSettings(
        meeting_media_folder=str(media_dir),
        jwl_userdata_db_path=str(db_file),
    )
    service = MeetingMediaService(settings)

    mock_items = [
        MediaDownloadItem(
            title="Video Midweek 1",
            url="https://example.com/midweek.mp4",
            duration_seconds=90.0,
            suggested_filename="midweek1.mp4",
        )
    ]
    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Length": "10"}
    mock_resp.read.side_effect = io.BytesIO(b"0123456789").read
    mock_resp.__enter__.return_value = mock_resp

    with (
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_midweek_meeting_media",
            return_value=mock_items,
        ),
        patch("urllib.request.urlopen", return_value=mock_resp),
    ):
        result = service.download_midweek_and_import("Semana 1")
        assert result.success is True
        assert result.imported_count == 1


def test_meeting_media_service_weekend_download(tmp_path) -> None:
    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    media_dir = tmp_path / "MediaStorage"
    media_dir.mkdir()

    settings = AppSettings(
        meeting_media_folder=str(media_dir),
        jwl_userdata_db_path=str(db_file),
        congregation_language="TCN",
    )
    service = MeetingMediaService(settings)
    assert service.language == "TCN"

    mock_items = [
        MediaDownloadItem(
            title="Pacote Sentinela",
            url="https://example.com/w_tcn_202610.jwpub",
            media_type="bundle",
            category="weekend",
            suggested_filename="w_tcn_202610.jwpub",
        ),
        MediaDownloadItem(
            title="Audio Sentinela Artigo 1",
            url="https://example.com/audio1.mp3",
            duration_seconds=300.0,
            media_type="audio",
            category="weekend",
            suggested_filename="audio1.mp3",
        ),
    ]

    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Length": "10"}
    mock_resp.read.side_effect = io.BytesIO(b"0123456789").read
    mock_resp.__enter__.return_value = mock_resp

    fake_extracted_img = tmp_path / "extracted_img.jpg"
    fake_extracted_img.write_bytes(b"FAKE_IMG")

    progress_calls = []

    def single_arg_progress(val: int) -> None:
        # Simulates Qt Signal(int).emit which only takes 1 argument
        assert isinstance(val, int)
        progress_calls.append(val)

    with (
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_weekend_meeting_media",
            return_value=mock_items,
        ),
        patch("urllib.request.urlopen", return_value=mock_resp),
        patch(
            "meeting_assistant.services.meeting_media_service.extract_images_from_jwpub",
            return_value=[fake_extracted_img],
        ),
    ):
        result = service.download_weekend_and_import(
            issue="202610",
            playlist_name="Estudo de A Sentinela",
            include_images=True,
            include_audio=True,
            progress_cb=single_arg_progress,
        )
        assert result.success is True
        assert result.imported_count == 2
        assert result.playlist_name == "Estudo de A Sentinela"
        assert len(progress_calls) > 0
        assert 100 in progress_calls


def test_meeting_media_service_midweek_bundle_and_images(tmp_path) -> None:
    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    media_dir = tmp_path / "MediaStorage"
    media_dir.mkdir()

    settings = AppSettings(
        meeting_media_folder=str(media_dir),
        jwl_userdata_db_path=str(db_file),
    )
    service = MeetingMediaService(settings)

    mock_bundle = MediaDownloadItem(
        title="Apostila mwb 2026.11",
        url="https://example.com/mwb_T_202611.jwpub",
        media_type="bundle",
        category="midweek",
        suggested_filename="mwb_T_202611.jwpub",
    )
    mock_videos = [
        MediaDownloadItem(
            title="Video 1",
            url="https://example.com/v1.mp4",
            duration_seconds=120.0,
            suggested_filename="v1.mp4",
        )
    ]

    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Length": "10"}
    mock_resp.read.side_effect = io.BytesIO(b"0123456789").read
    mock_resp.__enter__.return_value = mock_resp

    fake_img = tmp_path / "midweek_chart.jpg"
    fake_img.write_bytes(b"CHART_IMG")

    with (
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_midweek_meeting_bundle",
            return_value=mock_bundle,
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_midweek_meeting_media",
            return_value=mock_videos,
        ),
        patch("urllib.request.urlopen", return_value=mock_resp),
        patch(
            "meeting_assistant.services.meeting_media_service.extract_images_from_jwpub",
            return_value=[fake_img],
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.register_media_in_jwl_collection",
            return_value=True,
        ) as mock_register,
    ):
        result = service.download_midweek_and_import(
            playlist_name="Apostila Teste",
            issue="202611",
            include_images=True,
            include_videos=True,
        )
        assert result.success is True
        assert result.imported_count == 2
        assert result.playlist_name == "Apostila Teste"
        assert mock_register.called


def test_meeting_media_service_midweek_publication_install_trigger(tmp_path) -> None:
    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    service = MeetingMediaService(
        AppSettings(
            meeting_media_folder=str(tmp_path / "Media"),
            jwl_userdata_db_path=str(db_file),
        )
    )

    mock_bundle = MediaDownloadItem(
        title="Pacote Apostila",
        url="https://example.com/mwb_t_202611.jwpub",
        media_type="bundle",
        category="midweek",
        suggested_filename="mwb_t_202611.jwpub",
        issue_tag=202611,
        meps_language_index=5,
    )

    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Length": "8"}
    mock_resp.read.side_effect = io.BytesIO(b"FAKE_JWP").read
    mock_resp.__enter__.return_value = mock_resp

    with (
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_midweek_meeting_bundle",
            return_value=mock_bundle,
        ),
        patch("urllib.request.urlopen", return_value=mock_resp),
        patch(
            "meeting_assistant.services.meeting_media_service.extract_images_from_jwpub",
            return_value=[],
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.is_publication_installed",
            return_value=False,
        ) as mock_installed,
        patch(
            "meeting_assistant.services.meeting_media_service.install_jwpub_to_jwl",
            return_value=True,
        ) as mock_install,
    ):
        _ = service.download_midweek_and_import(
            include_images=True,
            include_videos=False,
        )
        assert mock_installed.called
        assert mock_install.called
        # Arguments to is_publication_installed
        mock_installed.assert_called_with(
            key_symbol="mwb",
            issue_tag=202611,
            meps_language_index=5,
        )


def test_meeting_media_service_weekend_video_download_and_install_trigger(tmp_path) -> None:
    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    fake_videos_dir = tmp_path / "JWL_Videos"
    fake_videos_dir.mkdir()

    service = MeetingMediaService(
        AppSettings(
            meeting_media_folder=str(tmp_path / "Media"),
            jwl_userdata_db_path=str(db_file),
        )
    )

    mock_items = [
        MediaDownloadItem(
            title="Pacote Sentinela",
            url="https://example.com/w_t_202610.jwpub",
            media_type="bundle",
            category="weekend",
            suggested_filename="w_t_202610.jwpub",
            issue_tag=202610,
            meps_language_index=5,
        ),
        MediaDownloadItem(
            title="Video Sentinela 1",
            url="https://example.com/w_video1.mp4",
            duration_seconds=180.0,
            media_type="video",
            category="weekend",
            suggested_filename="w_video1.mp4",
            issue_tag=202610,
            meps_language_index=5,
        ),
    ]

    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Length": "10"}
    mock_resp.read.side_effect = io.BytesIO(b"VIDEO_BYTES").read
    mock_resp.__enter__.return_value = mock_resp

    with (
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_weekend_meeting_media",
            return_value=mock_items,
        ),
        patch("urllib.request.urlopen", return_value=mock_resp),
        patch(
            "meeting_assistant.services.meeting_media_service.extract_images_from_jwpub",
            return_value=[],
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.detect_jwl_videos_dir",
            return_value=fake_videos_dir,
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.is_publication_installed",
            return_value=False,
        ) as mock_installed,
        patch(
            "meeting_assistant.services.meeting_media_service.install_jwpub_to_jwl",
            return_value=True,
        ) as mock_install,
        patch(
            "meeting_assistant.services.meeting_media_service.register_media_in_jwl_collection",
            return_value=True,
        ) as mock_register,
    ):
        result = service.download_weekend_and_import(
            include_images=True,
            include_audio=False,
            include_videos=True,
        )
        assert result.success is True
        assert result.imported_count == 1
        assert mock_installed.called
        assert mock_install.called
        assert mock_register.called
        # Video is copied into fake_videos_dir
        assert (fake_videos_dir / "w_video1.mp4").is_file()
        # Publications and images must NEVER be copied into fake_videos_dir
        assert not (fake_videos_dir / "w_tcn_202610.jwpub").exists()


def test_re_download_when_physical_destination_file_deleted(tmp_path) -> None:
    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    media_dir = tmp_path / "MediaStorage"
    media_dir.mkdir()
    fake_videos_dir = tmp_path / "JWLibraryVideos"
    fake_videos_dir.mkdir()

    settings = AppSettings(
        meeting_media_folder=str(media_dir),
        jwl_userdata_db_path=str(db_file),
    )
    service = MeetingMediaService(settings)

    mock_items = [
        MediaDownloadItem(
            title="Video Midweek 1",
            url="https://example.com/midweek1.mp4",
            duration_seconds=90.0,
            suggested_filename="midweek1.mp4",
        )
    ]
    def fake_urlopen(*args, **kwargs):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Length": "10"}
        stream = io.BytesIO(b"0123456789")
        mock_resp.read.side_effect = stream.read
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with (
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_midweek_meeting_media",
            return_value=mock_items,
        ),
        patch("urllib.request.urlopen", side_effect=fake_urlopen),
        patch(
            "meeting_assistant.services.meeting_media_service.detect_jwl_videos_dir",
            return_value=fake_videos_dir,
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_midweek_meeting_bundle",
            return_value=None,
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.register_media_in_jwl_collection",
            return_value=True,
        ) as mock_register,
    ):
        # 1. First download
        res1 = service.download_midweek_and_import("Semana 1", include_images=False, include_videos=True)
        assert res1.success is True
        assert res1.imported_count == 1
        video_dest = fake_videos_dir / "midweek1.mp4"
        assert video_dest.is_file()

        # 2. Operator deletes the physical file from JWLibrary videos folder
        video_dest.unlink()
        assert not video_dest.exists()

        # 3. Second download run: must detect missing destination file and restore it!
        res2 = service.download_midweek_and_import("Semana 1", include_images=False, include_videos=True)
        assert res2.success is True
        assert video_dest.is_file()
        assert video_dest.stat().st_size == 10
        assert mock_register.called
        # Because link was already in TagMap, it verified/synchronized the item
        assert res2.synchronized_count >= 1 or res2.imported_count >= 1


def test_safe_install_jwpub_prevents_process_collision_and_shell_launch(tmp_path, monkeypatch) -> None:
    from meeting_assistant.services.jwl_media_importer import install_jwpub_to_jwl

    pkg_dir = tmp_path / "Package"
    pkg_dir.mkdir()
    (pkg_dir / "LocalState" / "Publications").mkdir(parents=True)
    (pkg_dir / "LocalState" / "Data").mkdir(parents=True)

    jwpub_file = tmp_path / "sample.jwpub"
    import zipfile
    with zipfile.ZipFile(jwpub_file, "w") as zf:
        zf.writestr("manifest.json", '{"name":"sample.jwpub"}')

    monkeypatch.setattr(
        "meeting_assistant.services.jwl_media_importer.detect_jwl_package_dir",
        lambda: pkg_dir,
    )
    monkeypatch.setattr(
        "meeting_assistant.services.jwl_media_importer.is_jwlibrary_running",
        lambda: True,
    )

    shell_called = []
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", lambda p: shell_called.append(p))

    success = install_jwpub_to_jwl(jwpub_file)
    assert success is True
    # Crucial: os.startfile must NEVER be called when direct install succeeds
    # or when JW Library is actively running!
    assert len(shell_called) == 0


def test_download_midweek_and_import_with_songs_and_cbs(tmp_path) -> None:
    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    media_dir = tmp_path / "MediaStorage"
    media_dir.mkdir()
    fake_videos_dir = tmp_path / "JWLibraryVideos"
    fake_videos_dir.mkdir()

    settings = AppSettings(
        meeting_media_folder=str(media_dir),
        jwl_userdata_db_path=str(db_file),
    )
    service = MeetingMediaService(settings)

    # 1. Create a simulated mwb publication DB and jwpub
    mwb_db = tmp_path / "mwb.db"
    conn = sqlite3.connect(mwb_db)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE DatedText (
            DatedTextId INTEGER PRIMARY KEY,
            DocumentId INTEGER,
            FirstDateOffset INTEGER,
            LastDateOffset INTEGER
        )
    """)
    cur.execute("CREATE TABLE Document (DocumentId INTEGER PRIMARY KEY, Class TEXT, Title TEXT)")
    cur.execute("""
        CREATE TABLE DocumentMultimedia (
            DocumentMultimediaId INTEGER PRIMARY KEY,
            DocumentId INTEGER,
            MultimediaId INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE Multimedia (
            MultimediaId INTEGER PRIMARY KEY,
            KeySymbol TEXT,
            Track INTEGER,
            Label TEXT
        )
    """)
    cur.execute("INSERT INTO DatedText VALUES (1, 10, 20261012, 20261018)")
    cur.execute("INSERT INTO Document VALUES (10, '1', 'Semana 1')")
    cur.execute("INSERT INTO Multimedia VALUES (1, 'sjjm', 14, 'Cântico 14')")
    cur.execute("INSERT INTO Multimedia VALUES (2, 'sjjm', 88, 'Cântico 88')")
    cur.execute("INSERT INTO Multimedia VALUES (3, 'sjjm', 142, 'Cântico 142')")
    cur.execute("INSERT INTO Multimedia VALUES (4, 'pk', 10, 'Lição 10: Seja Feliz para Sempre')")
    cur.execute("INSERT INTO DocumentMultimedia VALUES (1, 10, 1)")
    cur.execute("INSERT INTO DocumentMultimedia VALUES (2, 10, 2)")
    cur.execute("INSERT INTO DocumentMultimedia VALUES (3, 10, 3)")
    cur.execute("INSERT INTO DocumentMultimedia VALUES (4, 10, 4)")
    conn.commit()
    conn.close()

    inner_buf = io.BytesIO()
    import zipfile
    with zipfile.ZipFile(inner_buf, "w") as iz:
        iz.writestr("mwb.db", mwb_db.read_bytes())
    bundle_jwpub = tmp_path / "mwb_T_202610.jwpub"
    with zipfile.ZipFile(bundle_jwpub, "w") as oz:
        oz.writestr("contents", inner_buf.getvalue())
        oz.writestr("manifest.json", b'{"name": "mwb"}')

    bundle_item = MediaDownloadItem(
        title="Apostila Outubro 2026",
        url="https://example.com/mwb.jwpub",
        filesize=bundle_jwpub.stat().st_size,
        media_type="bundle",
        category="midweek",
        suggested_filename="mwb_T_202610.jwpub",
        pub_symbol="mwb",
    )

    mock_catalog = {
        14: MediaDownloadItem(
            title="14. O Reino de Deus Já Domina!",
            url="https://example.com/sjj_014.mp4",
            duration_seconds=120.0,
            suggested_filename="sjj_014.mp4",
            category="song",
        ),
        88: MediaDownloadItem(
            title="88. Filhos São uma Herança",
            url="https://example.com/sjj_088.mp4",
            duration_seconds=115.0,
            suggested_filename="sjj_088.mp4",
            category="song",
        ),
        142: MediaDownloadItem(
            title="142. Firmes e Inabaláveis!",
            url="https://example.com/sjj_142.mp4",
            duration_seconds=130.0,
            suggested_filename="sjj_142.mp4",
            category="song",
        ),
    }

    cbs_item = MediaDownloadItem(
        title="Lição 10: Seja Feliz para Sempre",
        url="https://example.com/pk_10.mp4",
        duration_seconds=180.0,
        suggested_filename="pk_10.mp4",
        category="midweek",
        pub_symbol="pk",
        track_num=10,
    )

    def fake_download_file(url, dest_path, **kwargs):
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if "mwb.jwpub" in url:
            dest_path.write_bytes(bundle_jwpub.read_bytes())
        else:
            dest_path.write_bytes(f"VIDEO_CONTENT_FOR_{url}".encode())

    with (
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_midweek_meeting_bundle",
            return_value=bundle_item,
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_midweek_meeting_media",
            return_value=[],
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_songs_catalog",
            return_value=mock_catalog,
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_media_item_by_pub_track",
            return_value=cbs_item,
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.download_file",
            side_effect=fake_download_file,
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.detect_jwl_videos_dir",
            return_value=fake_videos_dir,
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.register_media_in_jwl_collection",
            return_value=True,
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.is_publication_installed",
            return_value=True,
        ),
    ):
        result = service.download_midweek_and_import(
            playlist_name="Reunião de Meio de Semana",
            include_images=False,
            include_videos=False,
            include_songs=True,
            include_cbs_videos=True,
            meeting_date=datetime.date(2026, 10, 14),
        )

        assert result.success is True
        # 3 weekly songs + 1 CBS video = 4 items
        assert result.imported_count == 4
        assert result.playlist_name == "Reunião de Meio de Semana"

        # Check that files were placed in fake_videos_dir for JW Library recognition
        assert (fake_videos_dir / "sjj_014.mp4").is_file()
        assert (fake_videos_dir / "sjj_088.mp4").is_file()
        assert (fake_videos_dir / "sjj_142.mp4").is_file()
        assert (fake_videos_dir / "pk_10.mp4").is_file()


def test_download_weekend_and_import_with_songs(tmp_path) -> None:
    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    media_dir = tmp_path / "MediaStorage"
    media_dir.mkdir()
    fake_videos_dir = tmp_path / "JWLibraryVideos"
    fake_videos_dir.mkdir()

    settings = AppSettings(
        meeting_media_folder=str(media_dir),
        jwl_userdata_db_path=str(db_file),
    )
    service = MeetingMediaService(settings)

    # 1. Create simulated Watchtower DB and jwpub
    w_db = tmp_path / "w.db"
    conn = sqlite3.connect(w_db)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE DatedText (
            DatedTextId INTEGER PRIMARY KEY,
            DocumentId INTEGER,
            FirstDateOffset INTEGER,
            LastDateOffset INTEGER
        )
    """)
    cur.execute("CREATE TABLE Document (DocumentId INTEGER PRIMARY KEY, Class TEXT, Title TEXT)")
    cur.execute("""
        CREATE TABLE DocumentMultimedia (
            DocumentMultimediaId INTEGER PRIMARY KEY,
            DocumentId INTEGER,
            MultimediaId INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE Multimedia (
            MultimediaId INTEGER PRIMARY KEY,
            KeySymbol TEXT,
            Track INTEGER,
            Label TEXT
        )
    """)
    cur.execute("INSERT INTO DatedText VALUES (1, 1, 20261012, 20261018)")
    cur.execute("INSERT INTO Document VALUES (1, '10', 'Sumário')")
    cur.execute("INSERT INTO Document VALUES (2, '40', 'Artigo de Estudo 1')")
    cur.execute("INSERT INTO Multimedia VALUES (1, 'sjjm', 23, 'Cântico 23')")
    cur.execute("INSERT INTO Multimedia VALUES (2, 'sjjm', 75, 'Cântico 75')")
    cur.execute("INSERT INTO DocumentMultimedia VALUES (1, 2, 1)")
    cur.execute("INSERT INTO DocumentMultimedia VALUES (2, 2, 2)")
    conn.commit()
    conn.close()

    inner_buf = io.BytesIO()
    import zipfile
    with zipfile.ZipFile(inner_buf, "w") as iz:
        iz.writestr("w.db", w_db.read_bytes())
    bundle_jwpub = tmp_path / "w_T_202610.jwpub"
    with zipfile.ZipFile(bundle_jwpub, "w") as oz:
        oz.writestr("contents", inner_buf.getvalue())
        oz.writestr("manifest.json", b'{"name": "w"}')

    bundle_item = MediaDownloadItem(
        title="A Sentinela Outubro 2026",
        url="https://example.com/w.jwpub",
        filesize=bundle_jwpub.stat().st_size,
        media_type="bundle",
        category="weekend",
        suggested_filename="w_T_202610.jwpub",
        pub_symbol="w",
    )

    mock_catalog = {
        23: MediaDownloadItem(
            title="23. A Tua Palavra É a Verdade",
            url="https://example.com/sjj_023.mp4",
            duration_seconds=120.0,
            suggested_filename="sjj_023.mp4",
            category="song",
        ),
        75: MediaDownloadItem(
            title="75. Mostre Amor Leal",
            url="https://example.com/sjj_075.mp4",
            duration_seconds=125.0,
            suggested_filename="sjj_075.mp4",
            category="song",
        ),
    }

    def fake_download_file(url, dest_path, **kwargs):
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if "w.jwpub" in url:
            dest_path.write_bytes(bundle_jwpub.read_bytes())
        else:
            dest_path.write_bytes(f"VIDEO_CONTENT_FOR_{url}".encode())

    with (
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_weekend_meeting_media",
            return_value=[bundle_item],
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_songs_catalog",
            return_value=mock_catalog,
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.download_file",
            side_effect=fake_download_file,
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.detect_jwl_videos_dir",
            return_value=fake_videos_dir,
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.register_media_in_jwl_collection",
            return_value=True,
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.is_publication_installed",
            return_value=True,
        ),
    ):
        result = service.download_weekend_and_import(
            playlist_name="Estudo de A Sentinela",
            include_images=False,
            include_audio=False,
            include_videos=False,
            include_songs=True,
            meeting_date=datetime.date(2026, 10, 15),
        )

        assert result.success is True
        # 2 study songs = 2 items
        assert result.imported_count == 2
        assert result.playlist_name == "Estudo de A Sentinela"

        assert (fake_videos_dir / "sjj_023.mp4").is_file()
        assert (fake_videos_dir / "sjj_075.mp4").is_file()


def test_meeting_media_service_cbs_download_with_metadata(tmp_path) -> None:
    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    media_dir = tmp_path / "MediaStorage"
    media_dir.mkdir()

    fake_videos_dir = tmp_path / "Videos" / "JWLibrary"
    fake_videos_dir.mkdir(parents=True)

    settings = AppSettings(
        meeting_media_folder=str(media_dir),
        jwl_userdata_db_path=str(db_file),
    )
    service = MeetingMediaService(settings)

    cbs_entry = CBSMediaEntry("jwb", 3, "Moisés foi escondido", issue_tag=20191100, document_id=1102025909)

    download_item = MediaDownloadItem(
        title="Moisés foi escondido",
        url="https://example.com/jwb_video.mp4",
        filesize=15000000,
        duration_seconds=180.0,
        suggested_filename="jwb_201911_03_r720P.mp4",
        pub_symbol="jwb",
        track_num=3,
        issue_tag=20191100,
        docid=1102025909,
    )

    def fake_download_file(url, target, **kwargs):
        target.write_bytes(b"JWB_VIDEO_DATA")
        return target

    registered_calls = []

    def fake_register(*args, **kwargs):
        registered_calls.append(kwargs)
        return True

    with (
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_media_item_by_pub_track",
            return_value=download_item,
        ) as mock_fetch,
        patch(
            "meeting_assistant.services.meeting_media_service.download_file",
            side_effect=fake_download_file,
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.detect_jwl_videos_dir",
            return_value=fake_videos_dir,
        ),
        patch(
            "meeting_assistant.services.meeting_media_service.register_media_in_jwl_collection",
            side_effect=fake_register,
        ),
    ):
        result_items = service._download_and_register_cbs_items(
            [cbs_entry],
            dest_dir=media_dir,
        )

        assert len(result_items) == 1
        mock_fetch.assert_called_once_with(
            pub="jwb",
            track=3,
            issue_tag=20191100,
            docid=1102025909,
            language="T",
            preferred_quality="720p",
        )
        assert len(registered_calls) == 1
        reg = registered_calls[0]
        assert reg["key_symbol"] == "jwb"
        assert reg["track"] == 3
        assert reg["issue_tag_number"] == 20191100
        assert reg["document_id"] == 1102025909
        assert (fake_videos_dir / "jwb_201911_03_r720P.mp4").is_file()


def test_check_and_install_new_publications(tmp_path, monkeypatch) -> None:
    pkg_dir = tmp_path / "Package"
    pkg_dir.mkdir()
    (pkg_dir / "LocalState" / "Publications").mkdir(parents=True)
    (pkg_dir / "LocalState" / "Data").mkdir(parents=True)

    media_dir = tmp_path / "AppMedia"
    media_dir.mkdir()

    settings = AppSettings(
        meeting_media_folder=str(media_dir),
        congregation_language="T",
    )
    service = MeetingMediaService(settings)

    fake_item = MediaDownloadItem(
        title="Apostila mwb 202611",
        url="https://example.com/mwb_T_202611.jwpub",
        suggested_filename="mwb_T_202611.jwpub",
        pub_symbol="mwb",
        issue_tag=202611,
    )

    def mock_fetch_bundle(pub, issue, language="T", timeout=6.0):
        if pub == "mwb" and issue == "202611":
            return fake_item
        return None

    monkeypatch.setattr(
        "meeting_assistant.services.meeting_media_service.fetch_publication_bundle",
        mock_fetch_bundle,
    )

    def mock_is_installed(key_symbol, issue_tag=0, meps_language_index=-1):
        return not (key_symbol == "mwb" and issue_tag == 202611)

    monkeypatch.setattr(
        "meeting_assistant.services.meeting_media_service.is_publication_installed",
        mock_is_installed,
    )

    def mock_download(url, dest, **kwargs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("fake jwpub bytes")

    monkeypatch.setattr(
        "meeting_assistant.services.meeting_media_service.download_file",
        mock_download,
    )

    installed_calls = []

    def mock_install_jwpub(path):
        installed_calls.append(Path(path))
        return True

    monkeypatch.setattr(
        "meeting_assistant.services.meeting_media_service.install_jwpub_to_jwl",
        mock_install_jwpub,
    )

    res = service.check_and_install_new_publications()
    assert res.success is True
    assert len(res.newly_installed) == 1
    assert res.newly_installed[0].issue == "202611"
    assert len(installed_calls) == 1
    assert installed_calls[0].name == "mwb_T_202611.jwpub"


def test_cleanup_app_cache_and_protect_custom_playlists(tmp_path) -> None:
    media_dir = tmp_path / "AppMedia"
    media_dir.mkdir()

    midweek_dir = media_dir / "MeioDeSemana"
    midweek_dir.mkdir()
    (midweek_dir / "temp_video.mp4").write_text("temp video")
    (midweek_dir / "images_dir").mkdir()
    (midweek_dir / "images_dir" / "img1.jpg").write_text("img")

    weekend_dir = media_dir / "Sentinela"
    weekend_dir.mkdir()
    (weekend_dir / "article.mp3").write_text("audio")

    # Custom playlists folder and watch folder must NOT be touched!
    custom_dir = media_dir / "Playlists"
    custom_dir.mkdir()
    (custom_dir / "Discurso_Especial.json").write_text("custom playlist")

    watch_dir = media_dir / "WatchFolder"
    watch_dir.mkdir()
    (watch_dir / "slide1.jpg").write_text("slide")

    settings = AppSettings(meeting_media_folder=str(media_dir))
    service = MeetingMediaService(settings)

    deleted, freed, errors = service.cleanup_app_cache(keep_weeks=0)
    assert len(errors) == 0
    assert len(deleted) >= 2
    assert not (midweek_dir / "temp_video.mp4").exists()
    assert not (weekend_dir / "article.mp3").exists()

    # Verify custom playlists and watch folder are preserved intact!
    assert (custom_dir / "Discurso_Especial.json").is_file()
    assert (watch_dir / "slide1.jpg").is_file()


def test_cleanup_jwl_storage_purges_orphans_and_old_videos(tmp_path, monkeypatch) -> None:
    from meeting_assistant.services.jwl_media_importer import (
        cleanup_jwl_storage,
        init_jwl_schema,
    )

    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    # 1. Setup orphan IndependentMedia in Userdata
    orphan_file = userdata_dir / "ORPHAN1.jpg"
    orphan_file.write_text("orphan image content")

    con = sqlite3.connect(db_file)
    con.execute(
        "INSERT INTO IndependentMedia (IndependentMediaId, OriginalFilename, FilePath, MimeType, Hash) "
        "VALUES (99, 'orphan.jpg', 'ORPHAN1.jpg', 'image/jpeg', 'hash1')"
    )
    con.commit()
    con.close()

    # 2. Setup old video and new video in Videos\\JWLibrary
    videos_dir = tmp_path / "Videos" / "JWLibrary"
    videos_dir.mkdir(parents=True)

    old_video = videos_dir / "mwbv_t_202501_01_r720P.mp4"
    old_video.write_text("old video content")
    old_time = os.path.getmtime(old_video) - 60 * 86400
    os.utime(old_video, (old_time, old_time))

    new_video = videos_dir / "mwbv_t_202611_01_r720P.mp4"
    new_video.write_text("new video content")

    song_video = videos_dir / "sjjm_t_014_r720P.mp4"
    song_video.write_text("song content")
    os.utime(song_video, (old_time, old_time))

    monkeypatch.setattr(
        "meeting_assistant.services.jwl_media_importer.detect_jwl_videos_dir",
        lambda: videos_dir,
    )

    deleted, freed, errors = cleanup_jwl_storage(
        keep_weeks=2,
        db_path=db_file,
        remove_old_videos=True,
        remove_orphan_userdata=True,
    )

    assert len(errors) == 0
    # Orphan file in Userdata was deleted
    assert not orphan_file.exists()
    assert "Userdata/ORPHAN1.jpg" in deleted

    # Old video was deleted
    assert not old_video.exists()
    assert "Videos/mwbv_t_202501_01_r720P.mp4" in deleted

    # New video and songs MUST be preserved!
    assert new_video.is_file()
    assert song_video.is_file()

    # Verify IndependentMedia row in db was deleted
    con = sqlite3.connect(db_file)
    cur = con.cursor()
    cur.execute("SELECT count(*) FROM IndependentMedia WHERE IndependentMediaId = 99")
    assert cur.fetchone()[0] == 0
    con.close()


def test_cleanup_jwl_storage_preserves_advance_downloads_and_cleans_media_collection(
    tmp_path, monkeypatch
) -> None:
    from meeting_assistant.services.jwl_media_importer import (
        cleanup_jwl_storage,
        init_jwl_schema,
    )

    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    videos_dir = tmp_path / "Videos" / "JWLibrary"
    videos_dir.mkdir(parents=True)

    # Setup mediaCollection.db
    media_col_dir = tmp_path / "MediaCollectionDir"
    media_col_dir.mkdir()
    col_db_path = media_col_dir / "mediaCollection.db"
    mcon = sqlite3.connect(col_db_path)
    mcon.executescript("""
        CREATE TABLE MediaKey (MediaKeyId INTEGER PRIMARY KEY, KeySymbol TEXT, IssueTagNumber INTEGER);
        CREATE TABLE Video (VideoId INTEGER PRIMARY KEY, MediaKeyId INTEGER, FilePath TEXT);
        CREATE TABLE Audio (AudioId INTEGER PRIMARY KEY, MediaKeyId INTEGER, FilePath TEXT);
    """)

    old_time = os.path.getmtime(media_col_dir) - 45 * 86400  # 45 days ago

    # 1. Old video (expired issue 202401)
    old_video = videos_dir / "mwbv_t_202401_01_r720P.mp4"
    old_video.write_text("old 2024 video")
    os.utime(old_video, (old_time, old_time))
    mcon.execute("INSERT INTO MediaKey VALUES (1, 'mwbv', 20240101)")
    mcon.execute("INSERT INTO Video VALUES (10, 1, ?)", (str(old_video),))

    # 2. Advance download video: issue in the future (202711), but downloaded 45 days ago!
    advance_video = videos_dir / "mwbv_t_202711_02_r720P.mp4"
    advance_video.write_text("future meeting downloaded 45 days ago")
    os.utime(advance_video, (old_time, old_time))
    mcon.execute("INSERT INTO MediaKey VALUES (2, 'mwbv', 20271102)")
    mcon.execute("INSERT INTO Video VALUES (20, 2, ?)", (str(advance_video),))

    mcon.commit()
    mcon.close()

    monkeypatch.setattr(
        "meeting_assistant.services.jwl_media_importer.detect_jwl_videos_dir",
        lambda: videos_dir,
    )
    monkeypatch.setattr(
        "meeting_assistant.services.jwl_media_importer.detect_jwl_media_collection_db",
        lambda: col_db_path,
    )

    deleted, freed, errors = cleanup_jwl_storage(
        keep_weeks=2,
        db_path=db_file,
        remove_old_videos=True,
    )

    assert len(errors) == 0
    # Old video was deleted
    assert not old_video.exists()
    assert "Videos/mwbv_t_202401_01_r720P.mp4" in deleted

    # Advance download MUST BE PRESERVED even with 45 days old mtime!
    assert advance_video.is_file()

    # Check mediaCollection.db: old video removed, orphaned MediaKey purged, advance Video intact
    mcon = sqlite3.connect(col_db_path)
    cur = mcon.cursor()
    cur.execute("SELECT count(*) FROM Video WHERE VideoId = 10")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT count(*) FROM MediaKey WHERE MediaKeyId = 1")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT count(*) FROM Video WHERE VideoId = 20")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT count(*) FROM MediaKey WHERE MediaKeyId = 2")
    assert cur.fetchone()[0] == 1
    mcon.close()


def test_download_and_import_preserves_cache_for_custom_playlists(tmp_path, monkeypatch) -> None:
    from meeting_assistant.services.jwl_media_importer import MediaImportItem, init_jwl_schema
    from meeting_assistant.services.meeting_media_service import MeetingMediaService
    from meeting_assistant.services.settings import AppSettings

    userdata_dir = tmp_path / "Userdata"
    userdata_dir.mkdir()
    db_file = userdata_dir / "userData.db"
    init_jwl_schema(db_file)

    media_folder = tmp_path / "AppMedia"
    midweek_dir = media_folder / "MeioDeSemana"
    midweek_dir.mkdir(parents=True)
    custom_cached_file = midweek_dir / "custom_sample.mp4"
    custom_cached_file.write_text("custom sample")

    settings = AppSettings(
        jwl_userdata_db_path=str(db_file),
        meeting_media_folder=str(media_folder),
        meeting_media_cleanup_after_import=True,
    )
    service = MeetingMediaService(settings)

    dummy_item = MediaImportItem(
        source_path=custom_cached_file,
        label="Custom Sample",
        duration_seconds=10.0,
        end_action=2,
    )
    monkeypatch.setattr(service, "download_midweek_items", lambda **kw: [dummy_item])

    # Download with a non-standard playlist name: "Playlist Especial dos Pioneiros"
    result = service.download_midweek_and_import(
        playlist_name="Playlist Especial dos Pioneiros",
    )
    assert result.success is True

    # Cache file MUST NOT BE DELETED because it's a custom playlist, not standard meeting!
    assert custom_cached_file.is_file()






