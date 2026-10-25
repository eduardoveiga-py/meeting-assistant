from __future__ import annotations

import datetime
import io
import json
import sqlite3
import urllib.error
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from meeting_assistant.services.meeting_media_downloader import (
    CancelToken,
    CBSMediaEntry,
    download_file,
    extract_cbs_videos_from_mwb,
    extract_images_from_jwpub,
    extract_meeting_songs_from_jwpub,
    fetch_media_item_by_pub_track,
    fetch_midweek_meeting_media,
    fetch_songs_catalog,
    fetch_weekend_meeting_media,
    find_publication_db,
    normalize_meps_language,
    sanitize_filename,
)


def test_sanitize_filename() -> None:
    assert sanitize_filename('Cântico 14: "O Reino!"?') == "Cântico 14_ _O Reino!_"
    assert sanitize_filename("video/auxiliar\\teste") == "video_auxiliar_teste"
    assert sanitize_filename("   ") == "arquivo_midia"


def test_fetch_songs_catalog_mocked() -> None:
    fake_payload = {
        "files": {
            "T": {
                "MP4": [
                    {
                        "track": 14,
                        "title": "14. O Reino de Deus Já Domina!",
                        "label": "720p",
                        "filesize": 15000000,
                        "duration": 130.0,
                        "file": {"url": "https://example.com/sjj_014_720p.mp4"},
                    },
                    {
                        "track": 14,
                        "title": "14. O Reino de Deus Já Domina!",
                        "label": "240p",
                        "filesize": 4000000,
                        "duration": 130.0,
                        "file": {"url": "https://example.com/sjj_014_240p.mp4"},
                    },
                    {
                        "track": 88,
                        "title": "88. Filhos São uma Herança",
                        "label": "720p",
                        "filesize": 12000000,
                        "duration": 115.0,
                        "file": {"url": "https://example.com/sjj_088_720p.mp4"},
                    },
                ]
            }
        }
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(fake_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        catalog = fetch_songs_catalog(language="T", format_type="mp4", preferred_quality="720p")

        assert len(catalog) == 2
        assert 14 in catalog
        assert 88 in catalog

        item14 = catalog[14]
        assert item14.title == "14. O Reino de Deus Já Domina!"
        assert item14.url == "https://example.com/sjj_014_720p.mp4"
        assert item14.filesize == 15000000
        assert item14.duration_seconds == 130.0
        assert item14.track_num == 14
        assert item14.suggested_filename.startswith("sjj_014_")


def test_fetch_midweek_meeting_media_mocked() -> None:
    fake_payload = {
        "category": {
            "media": [
                {
                    "title": "Exemplo de Vídeo da Semana",
                    "duration": 210.0,
                    "files": [
                        {
                            "label": "720p",
                            "filesize": 25000000,
                            "progressiveDownloadURL": "https://example.com/mwb_video_720p.mp4",
                        }
                    ],
                }
            ]
        }
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(fake_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        items = fetch_midweek_meeting_media(language="T")

        assert len(items) == 1
        item = items[0]
        assert item.title == "Exemplo de Vídeo da Semana"
        assert item.url == "https://example.com/mwb_video_720p.mp4"
        assert item.filesize == 25000000
        assert item.duration_seconds == 210.0


def test_download_file_with_cancellation(tmp_path) -> None:
    token = CancelToken()
    token.cancel()

    target = tmp_path / "test_download.mp4"

    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Length": "1000"}
    mock_resp.read.return_value = b"some bytes"
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(InterruptedError):
            download_file("https://example.com/video.mp4", target, cancel_token=token)

    assert not target.exists()
    assert not target.with_suffix(".mp4.part").exists()


def test_download_file_success(tmp_path) -> None:
    target = tmp_path / "test_ok.mp4"

    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Length": "10"}
    stream = io.BytesIO(b"0123456789")
    mock_resp.read.side_effect = stream.read
    mock_resp.__enter__.return_value = mock_resp

    progress_calls = []

    def cb(curr, tot):
        progress_calls.append((curr, tot))

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = download_file("https://example.com/video.mp4", target, progress_cb=cb)
        assert res == target
        assert target.read_bytes() == b"0123456789"
        assert len(progress_calls) > 0
        assert progress_calls[-1] == (10, 10)


def test_normalize_meps_language() -> None:
    from meeting_assistant.services.meeting_media_downloader import normalize_meps_language

    assert normalize_meps_language("PT") == "T"
    assert normalize_meps_language("pt-br") == "T"
    assert normalize_meps_language("português") == "T"
    assert normalize_meps_language("en") == "E"
    assert normalize_meps_language("espanhol") == "S"
    assert normalize_meps_language("T") == "T"


def test_fetch_songs_catalog_robust_with_malformed_entries() -> None:
    fake_payload = {
        "files": {
            "T": {
                "MP4": [
                    {
                        "track": "14",  # String instead of int
                        "title": "Cântico 14",
                        "label": "720p",
                        "file": {"url": "https://example.com/14.mp4"},
                    },
                    {
                        "track": 15,
                        "title": "Cântico 15 (Sem File)",
                        "label": "720p",
                        "file": None,  # None instead of dict
                    },
                    {
                        "track": "invalid",  # Bad track value
                        "title": "Cântico Inválido",
                    },
                ]
            }
        }
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(fake_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        # Passing 'PT' should normalize to 'T'
        catalog = fetch_songs_catalog(language="PT", format_type="mp4")
        assert 14 in catalog
        assert 15 not in catalog  # Skipped because file was None
        assert "invalid" not in catalog


def test_download_file_with_empty_content_length(tmp_path) -> None:
    target = tmp_path / "test_no_length.mp4"

    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Length": ""}  # Empty string header
    stream = io.BytesIO(b"CHUNK_CONTENT")
    mock_resp.read.side_effect = stream.read
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = download_file("https://example.com/no_len.mp4", target)
        assert res.exists()
        assert res.read_bytes() == b"CHUNK_CONTENT"


def test_normalize_meps_language_ticuna_and_aliases() -> None:
    assert normalize_meps_language("Ticuna") == "TCN"
    assert normalize_meps_language("ticuna") == "TCN"
    assert normalize_meps_language("TCA") == "TCN"
    assert normalize_meps_language("TCB") == "TCN"
    assert normalize_meps_language("TCN") == "TCN"
    assert normalize_meps_language("tikuna") == "TCN"
    assert normalize_meps_language("Português do Brasil") == "T"
    assert normalize_meps_language("portugues do brasil") == "T"
    assert normalize_meps_language("espanhol") == "S"


def test_fetch_songs_catalog_http_400_and_404_handling() -> None:
    err_400 = urllib.error.HTTPError(
        url="https://example.com",
        code=400,
        msg="Bad Request",
        hdrs={},
        fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=err_400):
        with pytest.raises(RuntimeError, match="HTTP Error 400: Bad Request"):
            fetch_songs_catalog(language="INVALID")

    err_404 = urllib.error.HTTPError(
        url="https://example.com",
        code=404,
        msg="Not Found",
        hdrs={},
        fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=err_404):
        with pytest.raises(RuntimeError, match="HTTP Error 404: Not Found"):
            fetch_songs_catalog(language="T")


def test_fetch_midweek_meeting_media_fallback_to_vod() -> None:
    # First endpoint (MidweekMeeting) returns 404, second (VODMinistryMidweekMeeting) returns media
    err_404 = urllib.error.HTTPError(
        url="https://app.jw-cdn.org/apis/mediator/v1/categories/TCN/MidweekMeeting",
        code=404,
        msg="Not Found",
        hdrs={},
        fp=None,
    )

    vod_payload = {
        "category": {
            "media": [
                {
                    "title": "Vídeo Ticuna",
                    "duration": 180.0,
                    "files": [
                        {
                            "label": "720p",
                            "filesize": 12000000,
                            "progressiveDownloadURL": "https://example.com/tcn_video.mp4",
                        }
                    ],
                }
            ]
        }
    }
    mock_success = MagicMock()
    mock_success.read.return_value = json.dumps(vod_payload).encode("utf-8")
    mock_success.__enter__.return_value = mock_success

    with patch("urllib.request.urlopen", side_effect=[err_404, mock_success]):
        items = fetch_midweek_meeting_media(language="TCN")
        assert len(items) == 1
        assert items[0].title == "Vídeo Ticuna"
        assert items[0].url == "https://example.com/tcn_video.mp4"


def test_fetch_weekend_meeting_media_mocked() -> None:
    fake_payload = {
        "files": {
            "T": {
                "JWPUB": [
                    {
                        "title": "A Sentinela Outubro 2026",
                        "filesize": 4000000,
                        "file": {"url": "https://example.com/w_T_202610.jwpub"},
                    }
                ],
                "MP3": [
                    {
                        "title": "Artigo de Estudo 1",
                        "duration": 600.0,
                        "filesize": 8000000,
                        "file": {"url": "https://example.com/w_T_202610_01.mp3"},
                    }
                ],
            }
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(fake_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        items = fetch_weekend_meeting_media(language="T", issue="202610")
        assert len(items) == 2

        bundle = next(i for i in items if i.media_type == "bundle")
        assert bundle.suggested_filename == "w_T_202610.jwpub"
        assert bundle.category == "weekend"

        audio = next(i for i in items if i.media_type == "audio")
        assert audio.suggested_filename == "w_T_202610_01.mp3"


def test_extract_images_from_jwpub(tmp_path) -> None:
    # Build a simulated .jwpub with internal 'contents' zip archive holding .jpg images
    inner_buf = io.BytesIO()
    with zipfile.ZipFile(inner_buf, "w") as inner_z:
        inner_z.writestr("lesson_chart.jpg", b"JPEG_CHART_BYTES")
        inner_z.writestr("lesson_photo.png", b"PNG_PHOTO_BYTES")
        inner_z.writestr("article_text.html", b"<html>article</html>")

    jwpub_path = tmp_path / "sample.jwpub"
    with zipfile.ZipFile(jwpub_path, "w") as outer_z:
        outer_z.writestr("contents", inner_buf.getvalue())
        outer_z.writestr("manifest.json", b'{"version": 1}')

    extract_dir = tmp_path / "extracted_images"
    extracted = extract_images_from_jwpub(jwpub_path, extract_dir)

    assert len(extracted) == 2
    filenames = [p.name for p in extracted]
    assert "lesson_chart.jpg" in filenames
    assert "lesson_photo.png" in filenames
    assert "article_text.html" not in filenames


def test_fetch_midweek_meeting_bundle_mocked() -> None:
    from meeting_assistant.services.meeting_media_downloader import fetch_midweek_meeting_bundle

    fake_payload = {
        "files": {
            "T": {
                "JWPUB": [
                    {
                        "title": "Apostila mwb Novembro 2026",
                        "filesize": 5200000,
                        "file": {"url": "https://example.com/mwb_T_202611.jwpub", "checksum": "abc123chk"},
                    }
                ]
            }
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(fake_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        bundle = fetch_midweek_meeting_bundle(language="T", issue="202611")
        assert bundle is not None
        assert bundle.media_type == "bundle"
        assert bundle.category == "midweek"
        assert bundle.pub_symbol == "mwb"
        assert bundle.suggested_filename == "mwb_T_202611.jwpub"
        assert bundle.filesize == 5200000
        assert bundle.checksum == "abc123chk"


def test_extract_meeting_songs_from_jwpub_mwb(tmp_path) -> None:
    # 1. Create a simulated mwb publication SQLite DB
    db_file = tmp_path / "mwb_202610.db"
    conn = sqlite3.connect(db_file)
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

    # Week 1: 2026-10-12 to 2026-10-18 (doc 10)
    cur.execute("INSERT INTO DatedText VALUES (1, 10, 20261012, 20261018)")
    # Week 2: 2026-10-19 to 2026-10-25 (doc 20)
    cur.execute("INSERT INTO DatedText VALUES (2, 20, 20261019, 20261025)")

    cur.execute("INSERT INTO Document VALUES (10, '1', 'Semana 1')")
    cur.execute("INSERT INTO Document VALUES (20, '1', 'Semana 2')")

    # Songs: week 1 has sjjm 14, 88, 142. Week 2 has sjjm 5, 30, 99
    cur.execute("INSERT INTO Multimedia VALUES (1, 'sjjm', 14, 'Cântico 14')")
    cur.execute("INSERT INTO Multimedia VALUES (2, 'sjjm', 88, 'Cântico 88')")
    cur.execute("INSERT INTO Multimedia VALUES (3, 'sjjm', 142, 'Cântico 142')")
    cur.execute("INSERT INTO Multimedia VALUES (4, 'sjjm', 5, 'Cântico 5')")
    cur.execute("INSERT INTO Multimedia VALUES (5, 'sjjm', 30, 'Cântico 30')")
    cur.execute("INSERT INTO Multimedia VALUES (6, 'sjjm', 99, 'Cântico 99')")

    cur.execute("INSERT INTO DocumentMultimedia VALUES (1, 10, 1)")
    cur.execute("INSERT INTO DocumentMultimedia VALUES (2, 10, 2)")
    cur.execute("INSERT INTO DocumentMultimedia VALUES (3, 10, 3)")
    cur.execute("INSERT INTO DocumentMultimedia VALUES (4, 20, 4)")
    cur.execute("INSERT INTO DocumentMultimedia VALUES (5, 20, 5)")
    cur.execute("INSERT INTO DocumentMultimedia VALUES (6, 20, 6)")
    conn.commit()
    conn.close()

    # Package into a .jwpub with 'contents' zip
    inner_buf = io.BytesIO()
    with zipfile.ZipFile(inner_buf, "w") as inner_z:
        inner_z.writestr("mwb_202610.db", db_file.read_bytes())
    jwpub_path = tmp_path / "mwb_T_202610.jwpub"
    with zipfile.ZipFile(jwpub_path, "w") as outer_z:
        outer_z.writestr("contents", inner_buf.getvalue())
        outer_z.writestr("manifest.json", b'{"name": "mwb"}')

    # Test week 1 date
    songs_w1 = extract_meeting_songs_from_jwpub(
        jwpub_path,
        meeting_date=datetime.date(2026, 10, 14),
        current_week_only=True,
    )
    assert songs_w1 == [14, 88, 142]

    # Test week 2 date
    songs_w2 = extract_meeting_songs_from_jwpub(
        jwpub_path,
        meeting_date=datetime.date(2026, 10, 22),
        current_week_only=True,
    )
    assert songs_w2 == [5, 30, 99]

    # Test all distinct songs in publication
    all_songs = extract_meeting_songs_from_jwpub(
        jwpub_path,
        current_week_only=False,
    )
    assert all_songs == [14, 88, 142, 5, 30, 99]


def test_extract_meeting_songs_from_jwpub_watchtower(tmp_path) -> None:
    # 2. Watchtower schema: DatedText points to TOC Document 1, study articles have Class='40'
    db_file = tmp_path / "w_202610.db"
    conn = sqlite3.connect(db_file)
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

    # DatedText entries point to doc 1 (TOC)
    cur.execute("INSERT INTO DatedText VALUES (1, 1, 20261005, 20261011)")
    cur.execute("INSERT INTO DatedText VALUES (2, 1, 20261012, 20261018)")

    # Document 1 is TOC, Docs 2 and 3 are study articles (Class='40')
    cur.execute("INSERT INTO Document VALUES (1, '10', 'Sumário')")
    cur.execute("INSERT INTO Document VALUES (2, '40', 'Artigo de Estudo 1')")
    cur.execute("INSERT INTO Document VALUES (3, '40', 'Artigo de Estudo 2')")

    # Songs for article 1: 23, 75. Songs for article 2: 104, 110
    cur.execute("INSERT INTO Multimedia VALUES (1, 'sjjm', 23, 'Cântico 23')")
    cur.execute("INSERT INTO Multimedia VALUES (2, 'sjjm', 75, 'Cântico 75')")
    cur.execute("INSERT INTO Multimedia VALUES (3, 'sjjm', 104, 'Cântico 104')")
    cur.execute("INSERT INTO Multimedia VALUES (4, 'sjjm', 110, 'Cântico 110')")

    cur.execute("INSERT INTO DocumentMultimedia VALUES (1, 2, 1)")
    cur.execute("INSERT INTO DocumentMultimedia VALUES (2, 2, 2)")
    cur.execute("INSERT INTO DocumentMultimedia VALUES (3, 3, 3)")
    cur.execute("INSERT INTO DocumentMultimedia VALUES (4, 3, 4)")
    conn.commit()
    conn.close()

    # Pass directly as .db file
    songs_art1 = extract_meeting_songs_from_jwpub(
        db_file,
        meeting_date=datetime.date(2026, 10, 8),
        current_week_only=True,
    )
    assert songs_art1 == [23, 75]

    songs_art2 = extract_meeting_songs_from_jwpub(
        db_file,
        meeting_date=datetime.date(2026, 10, 15),
        current_week_only=True,
    )
    assert songs_art2 == [104, 110]


def test_extract_cbs_videos_from_mwb(tmp_path) -> None:
    db_file = tmp_path / "mwb_cbs.db"
    conn = sqlite3.connect(db_file)
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

    # Add songs (sjjm) and auxiliary video (pk track 10)
    cur.execute("INSERT INTO Multimedia VALUES (1, 'sjjm', 14, 'Cântico 14')")
    cur.execute("INSERT INTO Multimedia VALUES (2, 'pk', 10, 'Lição 10: Seja Feliz para Sempre')")

    cur.execute("INSERT INTO DocumentMultimedia VALUES (1, 10, 1)")
    cur.execute("INSERT INTO DocumentMultimedia VALUES (2, 10, 2)")
    conn.commit()
    conn.close()

    cbs_items = extract_cbs_videos_from_mwb(
        db_file,
        meeting_date=datetime.date(2026, 10, 14),
        current_week_only=True,
    )
    # Must only extract non-sjjm auxiliary videos
    assert len(cbs_items) == 1
    assert cbs_items[0] == ("pk", 10, "Lição 10: Seja Feliz para Sempre")


def test_fetch_media_item_by_pub_track_mocked() -> None:
    fake_payload = {
        "files": {
            "T": {
                "MP4": [
                    {
                        "title": "Lição 10: Por Que Estudar a Bíblia?",
                        "label": "720p",
                        "filesize": 18500000,
                        "duration": 182.0,
                        "file": {"url": "https://example.com/pk_10_720p.mp4", "checksum": "pk720chk"},
                    },
                    {
                        "title": "Lição 10: Por Que Estudar a Bíblia?",
                        "label": "360p",
                        "filesize": 5000000,
                        "duration": 182.0,
                        "file": {"url": "https://example.com/pk_10_360p.mp4", "checksum": "pk360chk"},
                    },
                ]
            }
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(fake_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        item = fetch_media_item_by_pub_track("pk", 10, language="T", preferred_quality="720p")
        assert item is not None
        assert item.title == "Lição 10: Por Que Estudar a Bíblia?"
        assert item.url == "https://example.com/pk_10_720p.mp4"
        assert item.category == "midweek"
        assert item.suggested_filename == "pk_10_720p.mp4"
        assert item.filesize == 18500000
        assert item.duration_seconds == 182.0
        assert item.checksum == "pk720chk"


def test_extract_meeting_songs_empty_and_error_handling(tmp_path) -> None:
    # Nonexistent path
    assert extract_meeting_songs_from_jwpub(tmp_path / "nonexistent.jwpub") == []
    # Empty file
    empty_file = tmp_path / "empty.db"
    empty_file.write_bytes(b"")
    assert extract_meeting_songs_from_jwpub(empty_file) == []
    assert extract_cbs_videos_from_mwb(empty_file) == []


def test_cbs_media_entry_dataclass_and_tuple_compatibility() -> None:
    entry = CBSMediaEntry("pk", 23, "Lição 23", issue_tag=0, document_id=1102025911)
    # Test backwards-compatible tuple behavior
    pub, track, label = entry
    assert pub == "pk"
    assert track == 23
    assert label == "Lição 23"
    assert len(entry) == 3
    assert entry == ("pk", 23, "Lição 23")

    # Test extended attributes
    assert entry.pub_symbol == "pk"
    assert entry.track_number == 23
    assert entry.title_or_label == "Lição 23"
    assert entry.issue_tag == 0
    assert entry.document_id == 1102025911


def test_find_publication_db(tmp_path) -> None:
    pub_dir = tmp_path / "Publications"
    pub_dir.mkdir()
    wcg_folder = pub_dir / "wcg_T"
    wcg_folder.mkdir()
    wcg_db = wcg_folder / "wcg_T.db"
    wcg_db.write_text("sqlite placeholder", encoding="utf-8")

    # Found in search_dirs
    found = find_publication_db("wcg", language="T", search_dirs=[pub_dir])
    assert found == wcg_db

    # Case insensitivity
    found_upper = find_publication_db("WCG", language="t", search_dirs=[pub_dir])
    assert found_upper == wcg_db

    # Nonexistent publication
    not_found = find_publication_db("nonexistent", language="T", search_dirs=[pub_dir])
    assert not_found is None


def test_extract_cbs_videos_from_mwb_via_publication_extract(tmp_path) -> None:
    # 1. Create auxiliary publication database (e.g. wcg_T.db)
    wcg_dir = tmp_path / "wcg_T"
    wcg_dir.mkdir()
    wcg_db = wcg_dir / "wcg_T.db"
    conn_wcg = sqlite3.connect(wcg_db)
    cur_wcg = conn_wcg.cursor()
    cur_wcg.execute(
        "CREATE TABLE Document (DocumentId INTEGER PRIMARY KEY, MepsDocumentId INTEGER, Title TEXT)"
    )
    cur_wcg.execute("""
        CREATE TABLE DocumentMultimedia (
            DocumentMultimediaId INTEGER PRIMARY KEY,
            DocumentId INTEGER,
            MultimediaId INTEGER,
            BeginParagraphOrdinal INTEGER,
            EndParagraphOrdinal INTEGER
        )
    """)
    cur_wcg.execute("""
        CREATE TABLE Multimedia (
            MultimediaId INTEGER PRIMARY KEY,
            MajorType INTEGER,
            MimeType TEXT,
            KeySymbol TEXT,
            Track INTEGER,
            IssueTagNumber INTEGER,
            Label TEXT,
            MepsDocumentId INTEGER
        )
    """)
    cur_wcg.execute("INSERT INTO Document VALUES (17, 1102025911, '“Apresente-se a Faraó”')")
    cur_wcg.execute("INSERT INTO Multimedia VALUES (166, 2, 'video/mp4', 'pk', 23, 0, 'Lição 23', 0)")
    cur_wcg.execute("INSERT INTO DocumentMultimedia VALUES (1, 17, 166, 1, 10)")
    conn_wcg.commit()
    conn_wcg.close()

    # 2. Create mwb publication database with extracts
    mwb_db = tmp_path / "mwb.db"
    conn_mwb = sqlite3.connect(mwb_db)
    cur_mwb = conn_mwb.cursor()
    cur_mwb.execute("""
        CREATE TABLE DatedText (
            DatedTextId INTEGER PRIMARY KEY,
            DocumentId INTEGER,
            FirstDateOffset INTEGER,
            LastDateOffset INTEGER
        )
    """)
    cur_mwb.execute("CREATE TABLE Document (DocumentId INTEGER PRIMARY KEY, Class TEXT, Title TEXT)")
    cur_mwb.execute("""
        CREATE TABLE RefPublication (
            RefPublicationId INTEGER PRIMARY KEY,
            Symbol TEXT,
            PublicationCategorySymbol TEXT,
            PublicationType TEXT
        )
    """)
    cur_mwb.execute("""
        CREATE TABLE Extract (
            ExtractId INTEGER PRIMARY KEY,
            Link TEXT,
            Caption TEXT,
            RefPublicationId INTEGER,
            RefMepsDocumentId INTEGER,
            RefBeginParagraphOrdinal INTEGER,
            RefEndParagraphOrdinal INTEGER
        )
    """)
    cur_mwb.execute("""
        CREATE TABLE DocumentExtract (
            DocumentExtractId INTEGER PRIMARY KEY,
            DocumentId INTEGER,
            ExtractId INTEGER,
            SortPosition INTEGER
        )
    """)
    cur_mwb.execute("""
        CREATE TABLE DocumentMultimedia (
            DocumentMultimediaId INTEGER PRIMARY KEY,
            DocumentId INTEGER,
            MultimediaId INTEGER
        )
    """)
    cur_mwb.execute("""
        CREATE TABLE Multimedia (
            MultimediaId INTEGER PRIMARY KEY,
            KeySymbol TEXT,
            Track INTEGER,
            Label TEXT
        )
    """)

    cur_mwb.execute("INSERT INTO DatedText VALUES (1, 5, 20261005, 20261011)")
    cur_mwb.execute("INSERT INTO Document VALUES (5, '1', '5-11 de outubro')")

    # Add RefPublications
    cur_mwb.execute("INSERT INTO RefPublication VALUES (1, 'sjj', 'bk', 'Book')")
    cur_mwb.execute("INSERT INTO RefPublication VALUES (9, 'wcg', 'bk', 'Book')")

    # Add Extracts: Song 1 (pos 100), Song 2 (pos 500), CBS wcg (pos 800), Song 3 (pos 900)
    cur_mwb.execute(
        "INSERT INTO Extract VALUES (1, 'p/T:1102016833/', 'sjj cântico 33', 1, NULL, NULL, NULL)"
    )
    cur_mwb.execute(
        "INSERT INTO Extract VALUES (2, 'p/T:1102016817/', 'sjj cântico 17', 1, NULL, NULL, NULL)"
    )
    cur_mwb.execute(
        "INSERT INTO Extract VALUES (3, 'p/T:1102025911/', 'wcg págs. 58-61', 9, 1102025911, 1, 10)"
    )
    cur_mwb.execute(
        "INSERT INTO Extract VALUES (4, 'p/T:1102016838/', 'sjj cântico 38', 1, NULL, NULL, NULL)"
    )

    cur_mwb.execute("INSERT INTO DocumentExtract VALUES (1, 5, 1, 100)")
    cur_mwb.execute("INSERT INTO DocumentExtract VALUES (2, 5, 2, 500)")
    cur_mwb.execute("INSERT INTO DocumentExtract VALUES (3, 5, 3, 800)")
    cur_mwb.execute("INSERT INTO DocumentExtract VALUES (4, 5, 4, 900)")

    conn_mwb.commit()
    conn_mwb.close()

    # Extract CBS videos passing tmp_path in search_dirs
    extracted = extract_cbs_videos_from_mwb(
        mwb_db,
        meeting_date=datetime.date(2026, 10, 8),
        current_week_only=True,
        language="T",
        search_dirs=[tmp_path],
    )

    assert len(extracted) == 1
    item = extracted[0]
    assert item[0] == "pk"
    assert item[1] == 23
    assert item.pub_symbol == "pk"
    assert item.track_number == 23
    assert item.title_or_label == "Lição 23"


def test_fetch_media_item_by_pub_track_with_issue() -> None:
    fake_payload = {
        "files": {
            "T": {
                "MP4": [
                    {
                        "pub": "jwb",
                        "track": 3,
                        "issue": 201911,
                        "title": "Moisés foi escondido",
                        "label": "720p",
                        "filesize": 22000000,
                        "duration": 150.0,
                        "file": {"url": "https://example.com/jwb_201911_03_720p.mp4", "checksum": "chk123"},
                    }
                ]
            }
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(fake_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        item = fetch_media_item_by_pub_track(
            "jwb",
            3,
            issue_tag=20191100,
            language="T",
            preferred_quality="720p",
        )
        assert item is not None
        assert item.pub_symbol == "jwb"
        assert item.track_num == 3
        assert item.issue_tag == 201911
        assert item.title == "Moisés foi escondido"

def test_find_publication_db_with_contents_zip(tmp_path) -> None:
    pub_dir = tmp_path / "Publications"
    pub_dir.mkdir()
    wcg_folder = pub_dir / "wcg_t"
    wcg_folder.mkdir()

    # Create dummy wcg_T.db inside a 'contents' zip
    inner_db = tmp_path / "wcg_temp.db"
    inner_db.write_text("sqlite contents placeholder", encoding="utf-8")
    contents_zip = wcg_folder / "contents"
    with zipfile.ZipFile(contents_zip, "w") as zf:
        zf.write(inner_db, arcname="wcg_T.db")

    found = find_publication_db("wcg", language="T", search_dirs=[pub_dir])
    assert found is not None
    assert found.name == "wcg_T.db"
    assert found.is_file()
    # Ensure contents file was extracted and unlinked
    assert not contents_zip.exists()


def test_extract_cbs_videos_from_mwb_multilingual_and_docid(tmp_path) -> None:
    # Test Spanish workbook (p/S:1102016) with brochure category and docid video
    mwb_db = tmp_path / "mwb_es.db"
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
        CREATE TABLE RefPublication (
            RefPublicationId INTEGER PRIMARY KEY,
            Symbol TEXT,
            PublicationCategorySymbol TEXT,
            PublicationType TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE Extract (
            ExtractId INTEGER PRIMARY KEY,
            Link TEXT,
            Caption TEXT,
            RefPublicationId INTEGER,
            RefMepsDocumentId INTEGER,
            RefBeginParagraphOrdinal INTEGER,
            RefEndParagraphOrdinal INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE DocumentExtract (
            DocumentExtractId INTEGER PRIMARY KEY,
            DocumentId INTEGER,
            ExtractId INTEGER,
            SortPosition INTEGER
        )
    """)
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
            MajorType INTEGER,
            MimeType TEXT,
            KeySymbol TEXT,
            Track INTEGER,
            IssueTagNumber INTEGER,
            Label TEXT,
            MepsDocumentId INTEGER
        )
    """)

    cur.execute("INSERT INTO DatedText VALUES (1, 10, 20261012, 20261018)")
    cur.execute("INSERT INTO Document VALUES (10, '1', 'Semana Española')")

    # Song 1 (pos 100), Song 2 (pos 500) with p/S:1102016, Song 3 (pos 900)
    cur.execute("INSERT INTO RefPublication VALUES (1, 'sjj', 'bk', 'Book')")
    cur.execute("INSERT INTO Extract VALUES (1, 'p/S:1102016801/', 'Canción 1', 1, NULL, NULL, NULL)")
    cur.execute("INSERT INTO Extract VALUES (2, 'p/S:1102016802/', 'Canción 2', 1, NULL, NULL, NULL)")
    cur.execute("INSERT INTO Extract VALUES (3, 'p/S:1102016803/', 'Canción 3', 1, NULL, NULL, NULL)")
    cur.execute("INSERT INTO DocumentExtract VALUES (1, 10, 1, 100)")
    cur.execute("INSERT INTO DocumentExtract VALUES (2, 10, 2, 500)")
    cur.execute("INSERT INTO DocumentExtract VALUES (3, 10, 3, 900)")

    # Direct auxiliary video with null track and docid (MajorType=2)
    cur.execute(
        "INSERT INTO Multimedia VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (5, 2, "video/mp4", "docid-1112024060", None, 0, "Informe 6", 1112024060),
    )
    cur.execute("INSERT INTO DocumentMultimedia VALUES (1, 10, 5)")

    conn.commit()
    conn.close()

    vids = extract_cbs_videos_from_mwb(
        mwb_db,
        meeting_date=datetime.date(2026, 10, 14),
        current_week_only=True,
        language="S",
    )
    assert len(vids) == 1
    assert vids[0].pub_symbol == "docid-1112024060"
    assert vids[0].document_id == 1112024060
    assert vids[0].title_or_label == "Informe 6"


def test_fetch_media_item_by_pub_track_with_docid() -> None:
    fake_payload = {
        "files": {
            "S": {
                "MP4": [
                    {
                        "pub": "docid-1112024060",
                        "docid": 1112024060,
                        "title": "Informe 6 del Cuerpo Gobernante",
                        "label": "720p",
                        "filesize": 35000000,
                        "duration": 420.0,
                        "file": {"url": "https://example.com/informe6_720p.mp4", "checksum": "inf6chk"},
                    }
                ]
            }
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(fake_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        item = fetch_media_item_by_pub_track(
            "docid-1112024060",
            track=0,
            docid=1112024060,
            language="S",
            preferred_quality="720p",
        )
        assert item is not None
        assert item.docid == 1112024060
        assert item.title == "Informe 6 del Cuerpo Gobernante"
        assert item.url == "https://example.com/informe6_720p.mp4"
        # Verify docid was included in requested URL
        call_req = mock_urlopen.call_args[0][0]
        assert "docid=1112024060" in call_req.full_url


def test_find_publication_db_language_priority(tmp_path) -> None:
    # Create two folders: lff_t (Portuguese) and lff_tcn (Ticuna)
    port_dir = tmp_path / "lff_t"
    port_dir.mkdir()
    port_db = port_dir / "lff_T.db"
    port_db.write_text("portuguese db placeholder")

    ticuna_dir = tmp_path / "lff_tcn"
    ticuna_dir.mkdir()
    ticuna_db = ticuna_dir / "lff_TCN.db"
    ticuna_db.write_text("ticuna db placeholder")

    # When querying for Ticuna (TCN), it must return the Ticuna db even if lff_t comes first alphabetically
    result = find_publication_db("lff", language="TCN", search_dirs=[tmp_path])
    assert result == ticuna_db

    # When querying for Portuguese (T), it must return the Portuguese db
    result_pt = find_publication_db("lff", language="T", search_dirs=[tmp_path])
    assert result_pt == port_db


def test_get_meeting_weeks_and_navigation(tmp_path) -> None:
    from meeting_assistant.services.meeting_media_downloader import get_meeting_weeks

    base_date = datetime.date(2026, 10, 12)
    weeks = get_meeting_weeks(base_date=base_date, past_weeks=2, future_weeks=4)

    assert len(weeks) >= 7

    cur_week = next(w for w in weeks if w.is_current)
    assert cur_week.monday == datetime.date(2026, 10, 12)
    assert cur_week.sunday == datetime.date(2026, 10, 18)
    assert cur_week.delta_weeks == 0
    assert "Semana Atual" in cur_week.label
    assert cur_week.mwb_issue == "202609"
    assert cur_week.w_issue == "202610"

    prev_week = next(w for w in weeks if w.delta_weeks == -1)
    assert prev_week.monday == datetime.date(2026, 10, 5)
    assert "atrás" in prev_week.label

    next_week = next(w for w in weeks if w.delta_weeks == 1)
    assert next_week.monday == datetime.date(2026, 10, 19)
    assert "+1 semana" in next_week.label

    mock_db = tmp_path / "mock_mwb.db"
    con = sqlite3.connect(mock_db)
    con.execute(
        "CREATE TABLE DatedText (DatedTextId INTEGER, FirstDateOffset INTEGER, LastDateOffset INTEGER)"
    )
    con.execute("INSERT INTO DatedText VALUES (1, 20261207, 20261213)")
    con.commit()
    con.close()

    weeks_with_pub = get_meeting_weeks(
        base_date=base_date, past_weeks=2, future_weeks=4, jwpub_sources=[mock_db]
    )
    dec_week = next((w for w in weeks_with_pub if w.monday == datetime.date(2026, 12, 7)), None)
    assert dec_week is not None
    assert dec_week.mwb_issue == "202611"
    assert dec_week.w_issue == "202612"


def test_fetch_publication_bundle_network(monkeypatch) -> None:
    from meeting_assistant.services.meeting_media_downloader import fetch_publication_bundle

    fake_json = {
        "files": {
            "T": {
                "JWPUB": [
                    {
                        "title": "Apostila mwb 202611",
                        "filesize": 1234567,
                        "file": {
                            "url": "https://example.com/mwb_T_202611.jwpub",
                            "checksum": "abc123hash",
                        },
                    }
                ]
            }
        }
    }

    class MockResponse:
        def read(self):
            return json.dumps(fake_json).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=6.0: MockResponse())

    bundle = fetch_publication_bundle("mwb", "202611", language="T")
    assert bundle is not None
    assert bundle.pub_symbol == "mwb"
    assert bundle.issue_tag == 202611
    assert bundle.suggested_filename == "mwb_T_202611.jwpub"
    assert bundle.filesize == 1234567
    assert bundle.url == "https://example.com/mwb_T_202611.jwpub"
