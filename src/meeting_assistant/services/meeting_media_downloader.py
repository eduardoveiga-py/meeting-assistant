from __future__ import annotations

import datetime
import io
import json
import os
import re
import sqlite3
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from meeting_assistant.services.jwl_media_importer import (
    detect_jwl_publications_dir,
    resolve_meps_language_index,
)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MeetingAssistant/1.0"

SUPPORTED_MEPS_LANGUAGES: list[tuple[str, str]] = [
    ("Português do Brasil", "T"),
    ("Espanhol", "S"),
    ("Ticuna", "TCN"),
]


@dataclass(slots=True)
class MediaDownloadItem:
    title: str
    url: str
    filesize: int = 0
    duration_seconds: float = 0.0
    media_type: str = "video"
    category: str = "song"
    track_num: int | None = None
    suggested_filename: str = ""
    checksum: str = ""
    pub_symbol: str = ""
    docid: int = 0
    issue_tag: int = 0
    book_num: int = 0
    meps_language_index: int = 5
    frame_width: int = 0
    frame_height: int = 0
    bit_rate: float = 0.0
    frame_rate: float = 0.0
    label: str = ""
    thumbnail_url: str = ""


@dataclass(slots=True)
class MeetingWeekInfo:
    monday: datetime.date
    sunday: datetime.date
    label: str
    is_current: bool
    delta_weeks: int
    mwb_issue: str
    w_issue: str


class CancelToken:
    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled


def sanitize_filename(name: str) -> str:
    """Sanitizes a string for use as a Windows file name."""
    sanitized = re.sub(r'[\\/*?:"<>|]', "_", name)
    sanitized = re.sub(r"_+", "_", sanitized).strip()
    return sanitized or "arquivo_midia"


def normalize_meps_language(lang: str) -> str:
    """Normalizes ISO, aliases or human language names to JW.org MEPS language codes."""
    code = lang.strip().upper()
    mapping = {
        "PT": "T",
        "PT-BR": "T",
        "PORTUGUES": "T",
        "PORTUGUÊS": "T",
        "PORTUGUÊS DO BRASIL": "T",
        "PORTUGUES DO BRASIL": "T",
        "BRAZILIAN PORTUGUESE": "T",
        "EN": "E",
        "EN-US": "E",
        "ENGLISH": "E",
        "INGLES": "E",
        "INGLÊS": "E",
        "ES": "S",
        "ES-ES": "S",
        "SPANISH": "S",
        "ESPANHOL": "S",
        "IT": "I",
        "FR": "F",
        "DE": "X",
        "TCN": "TCN",
        "TCA": "TCN",
        "TCB": "TCN",
        "TICUNA": "TCN",
        "TIKUNA": "TCN",
    }
    return mapping.get(code, code or "T")


def fetch_songs_catalog(
    language: str = "T",
    format_type: str = "mp4",
    preferred_quality: str = "720p",
    timeout: float = 10.0,
) -> dict[int, MediaDownloadItem]:
    """Fetches song media download info (tracks 1-151) from official pub-media API.

    format_type: 'mp4' (lyrics video) or 'mp3' (vocal audio).
    preferred_quality: '720p', '480p', or '240p'.
    """
    lang = normalize_meps_language(language)
    # The modern official publication for song tracks (1-151) containing both MP4 and MP3 is 'sjjm'
    pub = "sjjm"
    url = (
        f"https://b.jw-cdn.org/apis/pub-media/GETPUBMEDIALINKS"
        f"?output=json&pub={pub}&fileformat={format_type}&alllangs=0&langwritten={lang}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    catalog: dict[int, MediaDownloadItem] = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 400:
            raise RuntimeError(
                f"Erro ao consultar catálogo de cânticos do JW.org: HTTP Error 400: Bad Request "
                f"(Parâmetros inválidos ou código de idioma '{lang}' não suportado)."
            ) from exc
        if exc.code == 404:
            raise RuntimeError(
                f"Erro ao consultar catálogo de cânticos do JW.org: HTTP Error 404: Not Found "
                f"(Cânticos não encontrados para o idioma '{lang}')."
            ) from exc
        raise RuntimeError(f"Erro ao consultar catálogo de cânticos do JW.org: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Erro ao consultar catálogo de cânticos do JW.org: {exc}") from exc

    files_by_lang = data.get("files", {}).get(lang, {})
    file_list = files_by_lang.get(format_type.upper(), [])

    # Group tracks and select preferred quality
    by_track: dict[int, list[dict]] = {}
    for entry in file_list:
        track_val = entry.get("track")
        try:
            track = int(track_val)
        except (ValueError, TypeError):
            continue
        by_track.setdefault(track, []).append(entry)

    quality_target = preferred_quality.lower()
    for track_num, entries in by_track.items():
        # Find best matching entry according to quality
        selected = None
        for e in entries:
            label = str(e.get("label", "")).lower()
            file_info = e.get("file") or {}
            file_url = file_info.get("url", "")
            if quality_target in label or quality_target in file_url.lower():
                selected = e
                break
        if not selected and entries:
            selected = entries[0]

        if not selected:
            continue

        file_info = selected.get("file") or {}
        raw_url = file_info.get("url", "")
        if not raw_url:
            continue

        title = selected.get("title") or f"Cântico {track_num}"
        duration = float(selected.get("duration", 0.0) or 0.0)
        filesize = int(selected.get("filesize", 0) or 0)
        url_file = Path(urllib.parse.urlsplit(raw_url).path).name
        ext = ".mp4" if format_type.lower() == "mp4" else ".mp3"
        filename = url_file if url_file else f"sjj_{track_num:03d}_{sanitize_filename(title)}{ext}"

        catalog[track_num] = MediaDownloadItem(
            title=title,
            url=raw_url,
            filesize=filesize,
            duration_seconds=duration,
            media_type="video" if format_type.lower() == "mp4" else "audio",
            category="song",
            track_num=track_num,
            suggested_filename=filename,
            checksum=str(file_info.get("checksum") or ""),
            pub_symbol=str(selected.get("pub") or "sjjm"),
            docid=int(selected.get("docid") or 0),
            issue_tag=int(selected.get("issue") or 0),
            book_num=int(selected.get("booknum") or 0),
            meps_language_index=resolve_meps_language_index(lang),
            frame_width=int(selected.get("frameWidth") or 0),
            frame_height=int(selected.get("frameHeight") or 0),
            bit_rate=float(selected.get("bitRate") or 0.0),
            frame_rate=float(selected.get("frameRate") or 0.0),
            label=str(selected.get("label") or ""),
        )

    return catalog


def fetch_midweek_meeting_media(
    language: str = "T",
    timeout: float = 10.0,
) -> list[MediaDownloadItem]:
    """Fetches midweek meeting videos from mediator categories API with resilient fallback and aggregation."""
    lang = normalize_meps_language(language)
    endpoints = [
        f"https://app.jw-cdn.org/apis/mediator/v1/categories/{lang}/MidweekMeeting",
        f"https://app.jw-cdn.org/apis/mediator/v1/categories/{lang}/VODMinistryMidweekMeeting",
        f"https://app.jw-cdn.org/apis/mediator/v1/categories/{lang}/VODMinistryBibleStudy",
    ]
    raw_media_entries: list[dict] = []
    seen_keys: set[str] = set()
    last_exc = None

    for url in endpoints:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                candidate = json.loads(resp.read().decode("utf-8"))
                media_list = candidate.get("category", {}).get("media", [])
                for entry in media_list:
                    k = entry.get("naturalKey") or entry.get("guid") or entry.get("title")
                    if k and k not in seen_keys:
                        seen_keys.add(k)
                        raw_media_entries.append(entry)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code == 404:
                continue
            if not raw_media_entries and url == endpoints[0]:
                raise RuntimeError(f"Erro ao consultar mídias da Reunião de Meio de Semana: {exc}") from exc
        except Exception as exc:
            last_exc = exc
            continue

    if not raw_media_entries:
        if last_exc and isinstance(last_exc, urllib.error.HTTPError) and last_exc.code == 404:
            return []
        if last_exc and not isinstance(last_exc, urllib.error.HTTPError):
            msg = f"Erro ao consultar mídias da Reunião de Meio de Semana: {last_exc}"
            raise RuntimeError(msg) from last_exc
        return []

    results: list[MediaDownloadItem] = []
    seen_urls: set[str] = set()
    media_list = raw_media_entries

    for entry in media_list:
        title = entry.get("title") or "Vídeo da Reunião"
        files = entry.get("files", [])
        if not files:
            continue

        # Choose best resolution (prefer 720p or highest available progressive download)
        selected_file = None
        for f in files:
            label = str(f.get("label", "")).lower()
            if "720p" in label:
                selected_file = f
                break
        if not selected_file:
            selected_file = files[-1]

        download_url = selected_file.get("progressiveDownloadURL")
        if not download_url or download_url in seen_urls:
            continue
        seen_urls.add(download_url)

        duration = float(selected_file.get("duration", 0.0) or entry.get("duration", 0.0) or 0.0)
        filesize = int(selected_file.get("filesize", 0) or 0)
        url_file = Path(urllib.parse.urlsplit(download_url).path).name
        filename = url_file if url_file else f"{sanitize_filename(title)}.mp4"

        pub_sym = "mwbv"
        issue_tag = 0
        track_num = None
        nat_key = entry.get("naturalKey") or ""
        key_parts = nat_key.replace("pub-", "").replace("_VIDEO", "").split("_")
        if len(key_parts) >= 3:
            pub_sym = key_parts[0]
            if len(key_parts) >= 4:
                try:
                    issue_tag = int(key_parts[2])
                    track_num = int(key_parts[3])
                except ValueError:
                    pass
            else:
                try:
                    track_num = int(key_parts[2])
                except ValueError:
                    pass
        elif url_file:
            fname_parts = url_file.split(".")[0].split("_")
            if len(fname_parts) >= 3:
                pub_sym = fname_parts[0]
                if len(fname_parts) >= 4 and fname_parts[2].isdigit():
                    issue_tag = int(fname_parts[2])
                    if fname_parts[3].isdigit():
                        track_num = int(fname_parts[3])
                elif fname_parts[2].isdigit():
                    track_num = int(fname_parts[2])

        results.append(
            MediaDownloadItem(
                title=title,
                url=download_url,
                filesize=filesize,
                duration_seconds=duration,
                media_type="video",
                category="midweek",
                suggested_filename=filename,
                checksum=str(selected_file.get("checksum") or ""),
                pub_symbol=pub_sym,
                track_num=track_num,
                issue_tag=issue_tag,
                meps_language_index=resolve_meps_language_index(lang),
                frame_width=int(selected_file.get("frameWidth") or 0),
                frame_height=int(selected_file.get("frameHeight") or 0),
                bit_rate=float(selected_file.get("bitRate") or 0.0),
                frame_rate=float(selected_file.get("frameRate") or 0.0),
                label=str(selected_file.get("label") or ""),
            )
        )

    return results


POPULAR_VIDEO_CATEGORIES: list[tuple[str, str]] = [
    ("VODMinistryTools", "🎬 Ajudas para a Pregação (Por que Estudar a Bíblia?, Salão do Reino...)"),
    ("BJF", "👶 Crianças — Lições em Vídeo (Pedro e Sofia)"),
    ("ChildrenSongs", "🎶 Crianças — Músicas"),
    ("VODMinistryTeachings", "📖 Ensinos Básicos e A Bíblia"),
    ("VODFamily", "👨‍👩‍👧 Família e Casamento"),
    ("VODMarriage", "💍 Casamento e Família"),
    ("VODTeenagers", "🎒 Jovens e Adolescentes"),
    ("VODWhiteboardAnimations", "✏️ Animações no Quadro Branco"),
    ("VODPgmEvtMorningWorship", "☀️ Adoração Matinal (Betel)"),
    ("VODIntvExp", "🎙️ Entrevistas e Experiências"),
    ("SeriesTheStoryOfJesus", "✝️ A História de Jesus (Série)"),
    ("MeetingsConventions", "🏛️ Reuniões e Congressos"),
    ("VOXDramas", "🎥 Filmes e Dramas Bíblicos"),
    ("VODMusicVideos", "🎵 Músicas e Clipes"),
    ("MidweekMeeting", "📅 Reunião de Meio de Semana"),
]


def fetch_category_videos(
    category_key: str,
    language: str = "T",
    preferred_quality: str = "720p",
    timeout: float = 10.0,
) -> list[MediaDownloadItem]:
    """Fetches media items from a JW.org mediator category with resilient fallback."""
    lang = normalize_meps_language(language)
    url = f"https://b.jw-cdn.org/apis/mediator/v1/categories/{lang}/{category_key}?detailed=1"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    cat_data = data.get("category", {})
    raw_media = list(cat_data.get("media", []))
    if not raw_media:
        for subcat in cat_data.get("subcategories", []):
            raw_media.extend(subcat.get("media", []))

    results: list[MediaDownloadItem] = []
    seen_urls: set[str] = set()
    quality_target = preferred_quality.lower()

    for entry in raw_media:
        title = entry.get("title") or "Vídeo"
        files = entry.get("files", [])
        if not files:
            continue

        selected_file = None
        for f in files:
            lbl = str(f.get("label", "")).lower()
            url_str = str(f.get("progressiveDownloadURL", "")).lower()
            if quality_target in lbl or quality_target in url_str:
                selected_file = f
                break
        if not selected_file:
            selected_file = files[-1]

        download_url = selected_file.get("progressiveDownloadURL")
        if not download_url or download_url in seen_urls:
            continue
        seen_urls.add(download_url)

        duration = float(selected_file.get("duration", 0.0) or entry.get("duration", 0.0) or 0.0)
        filesize = int(selected_file.get("filesize", 0) or 0)
        url_file = Path(urllib.parse.urlsplit(download_url).path).name
        filename = url_file if url_file else f"{sanitize_filename(title)}.mp4"

        images = entry.get("images", {})
        thumb_url = ""
        for img_type in ("wss", "pnr", "lsr", "sqr"):
            type_dict = images.get(img_type, {})
            if isinstance(type_dict, dict):
                thumb_url = type_dict.get("sm") or type_dict.get("md") or type_dict.get("lg") or ""
                if thumb_url:
                    break

        pub_sym = "jwb"
        track_num = None
        issue_tag = 0
        docid = 0
        nat_key = entry.get("naturalKey") or ""
        key_parts = nat_key.replace("pub-", "").replace("_VIDEO", "").split("_")
        if len(key_parts) >= 2:
            pub_sym = key_parts[0]
            if len(key_parts) >= 3 and key_parts[2].isdigit():
                track_num = int(key_parts[2])

        results.append(
            MediaDownloadItem(
                title=title,
                url=download_url,
                filesize=filesize,
                duration_seconds=duration,
                media_type="video",
                category="video",
                suggested_filename=filename,
                checksum=str(selected_file.get("checksum") or ""),
                pub_symbol=pub_sym,
                track_num=track_num,
                issue_tag=issue_tag,
                docid=docid,
                meps_language_index=resolve_meps_language_index(lang),
                frame_width=int(selected_file.get("frameWidth") or 0),
                frame_height=int(selected_file.get("frameHeight") or 0),
                bit_rate=float(selected_file.get("bitRate") or 0.0),
                frame_rate=float(selected_file.get("frameRate") or 0.0),
                label=str(selected_file.get("label") or ""),
                thumbnail_url=thumb_url,
            )
        )

    return results


def fetch_midweek_meeting_bundle(
    language: str = "T",
    issue: str | None = None,
    timeout: float = 10.0,
) -> MediaDownloadItem | None:
    """Fetches midweek meeting workbook (.jwpub) bundle containing illustrations and images."""
    lang = normalize_meps_language(language)
    chosen_issue = issue.strip() if issue else ""

    if not chosen_issue:
        now = datetime.date.today()
        # Bimonthly odd months: 1, 3, 5, 7, 9, 11
        curr_odd = now.month if now.month % 2 == 1 else now.month - 1
        candidates = []
        for delta_m in (0, 2, -2, 4, -4):
            m = curr_odd + delta_m
            y = now.year
            while m <= 0:
                m += 12
                y -= 1
            while m > 12:
                m -= 12
                y += 1
            candidates.append(f"{y}{m:02d}")

        for cand in candidates:
            probe_url = (
                f"https://b.jw-cdn.org/apis/pub-media/GETPUBMEDIALINKS"
                f"?output=json&pub=mwb&issue={cand}&fileformat=JWPUB&alllangs=0&langwritten={lang}"
            )
            req = urllib.request.Request(probe_url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=min(timeout, 4.0)) as resp:
                    pdata = json.loads(resp.read().decode("utf-8"))
                    if pdata.get("files", {}).get(lang, {}).get("JWPUB"):
                        chosen_issue = cand
                        break
            except Exception:
                continue

        if not chosen_issue:
            chosen_issue = f"{now.year}{curr_odd:02d}"

    url = (
        f"https://b.jw-cdn.org/apis/pub-media/GETPUBMEDIALINKS"
        f"?output=json&pub=mwb&issue={chosen_issue}&fileformat=JWPUB&alllangs=0&langwritten={lang}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Erro ao consultar pacote da Apostila mwb ({chosen_issue}): {exc}") from exc

    jwpub_list = data.get("files", {}).get(lang, {}).get("JWPUB", [])
    if not jwpub_list:
        return None

    entry = jwpub_list[0]
    file_info = entry.get("file") or {}
    raw_url = file_info.get("url", "")
    if not raw_url:
        return None

    url_file = Path(urllib.parse.urlsplit(raw_url).path).name
    filename = url_file if url_file else f"mwb_{lang}_{chosen_issue}.jwpub"
    title = entry.get("title") or f"Apostila mwb {chosen_issue} (Pacote de Mídias e Imagens)"
    filesize = int(entry.get("filesize", 0) or 0)

    issue_num = 0
    try:
        issue_num = int(chosen_issue)
    except ValueError:
        pass

    return MediaDownloadItem(
        title=title,
        url=raw_url,
        filesize=filesize,
        media_type="bundle",
        category="midweek",
        suggested_filename=filename,
        checksum=str(file_info.get("checksum") or ""),
        pub_symbol="mwb",
        issue_tag=issue_num,
        meps_language_index=resolve_meps_language_index(lang),
    )


def fetch_weekend_meeting_media(
    language: str = "T",
    issue: str | None = None,
    timeout: float = 10.0,
) -> list[MediaDownloadItem]:
    """Fetches weekend meeting media (Watchtower Study magazine, images, audio) from pub-media API."""
    lang = normalize_meps_language(language)

    chosen_issue = issue.strip() if issue else ""
    if not chosen_issue:
        # Generate candidates around current date (study articles are usually issue M-2, M-1, M, M-3)
        now = datetime.date.today()
        candidates = []
        for delta in (-2, -1, 0, -3, 1, -4):
            m = now.month + delta
            y = now.year
            while m <= 0:
                m += 12
                y -= 1
            while m > 12:
                m -= 12
                y += 1
            candidates.append(f"{y}{m:02d}")

        # Probe candidate issues to find an available issue for this language
        for cand in candidates:
            probe_url = (
                f"https://b.jw-cdn.org/apis/pub-media/GETPUBMEDIALINKS"
                f"?output=json&pub=w&issue={cand}&alllangs=0&langwritten={lang}"
            )
            req = urllib.request.Request(probe_url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=min(timeout, 4.0)) as resp:
                    pdata = json.loads(resp.read().decode("utf-8"))
                    if pdata.get("files", {}).get(lang):
                        chosen_issue = cand
                        break
            except Exception:
                continue

        if not chosen_issue:
            m = now.month - 2
            y = now.year
            while m <= 0:
                m += 12
                y -= 1
            chosen_issue = f"{y}{m:02d}"

    url = (
        f"https://b.jw-cdn.org/apis/pub-media/GETPUBMEDIALINKS"
        f"?output=json&pub=w&issue={chosen_issue}&alllangs=0&langwritten={lang}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(
                f"Edição de A Sentinela {chosen_issue} não encontrada para o idioma {lang} (HTTP 404)."
            ) from exc
        raise RuntimeError(f"Erro ao consultar mídias de A Sentinela ({chosen_issue}): {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Erro ao consultar mídias de A Sentinela: {exc}") from exc

    results: list[MediaDownloadItem] = []
    files_by_lang = data.get("files", {}).get(lang, {})

    # 1. JWPUB (Bundle containing study illustrations and images)
    jwpub_list = files_by_lang.get("JWPUB", [])
    if jwpub_list:
        entry = jwpub_list[0]
        file_info = entry.get("file") or {}
        raw_url = file_info.get("url", "")
        if raw_url:
            title = entry.get("title") or f"A Sentinela {chosen_issue} (Pacote de Mídias e Imagens)"
            filesize = int(entry.get("filesize", 0) or 0)
            url_file = Path(urllib.parse.urlsplit(raw_url).path).name
            filename = url_file if url_file else f"w_{lang}_{chosen_issue}.jwpub"
            results.append(
                MediaDownloadItem(
                    title=title,
                    url=raw_url,
                    filesize=filesize,
                    media_type="bundle",
                    category="weekend",
                    suggested_filename=filename,
                    checksum=str(file_info.get("checksum") or ""),
                    pub_symbol="w",
                    issue_tag=int(chosen_issue) if chosen_issue.isdigit() else 0,
                    meps_language_index=resolve_meps_language_index(lang),
                )
            )

    # 2. MP3 (Audio of study articles)
    mp3_list = files_by_lang.get("MP3", [])
    for idx, entry in enumerate(mp3_list, start=1):
        file_info = entry.get("file") or {}
        raw_url = file_info.get("url", "")
        if not raw_url:
            continue
        title = entry.get("title") or f"A Sentinela {chosen_issue} - Artigo {idx}"
        duration = float(entry.get("duration", 0.0) or 0.0)
        filesize = int(entry.get("filesize", 0) or 0)
        url_file = Path(urllib.parse.urlsplit(raw_url).path).name
        fallback_name = f"w_{lang}_{chosen_issue}_{idx:02d}_{sanitize_filename(title)}.mp3"
        filename = url_file if url_file else fallback_name
        results.append(
            MediaDownloadItem(
                title=title,
                url=raw_url,
                filesize=filesize,
                duration_seconds=duration,
                media_type="audio",
                category="weekend",
                suggested_filename=filename,
                checksum=str(file_info.get("checksum") or ""),
                pub_symbol="w",
                track_num=idx,
                issue_tag=int(chosen_issue) if chosen_issue.isdigit() else 0,
                meps_language_index=resolve_meps_language_index(lang),
            )
        )

    # 3. MP4 (Study videos if available)
    mp4_list = files_by_lang.get("MP4", [])
    for idx, entry in enumerate(mp4_list, start=1):
        file_info = entry.get("file") or {}
        raw_url = file_info.get("url", "")
        if not raw_url:
            continue
        title = entry.get("title") or f"A Sentinela {chosen_issue} - Vídeo {idx}"
        duration = float(entry.get("duration", 0.0) or 0.0)
        filesize = int(entry.get("filesize", 0) or 0)
        url_file = Path(urllib.parse.urlsplit(raw_url).path).name
        fallback_vid = f"w_{lang}_{chosen_issue}_{idx:02d}_{sanitize_filename(title)}.mp4"
        filename = url_file if url_file else fallback_vid
        results.append(
            MediaDownloadItem(
                title=title,
                url=raw_url,
                filesize=filesize,
                duration_seconds=duration,
                media_type="video",
                category="weekend",
                suggested_filename=filename,
                checksum=str(file_info.get("checksum") or ""),
                pub_symbol="w",
                track_num=idx,
                issue_tag=int(chosen_issue) if chosen_issue.isdigit() else 0,
                meps_language_index=resolve_meps_language_index(lang),
            )
        )
    return results


def fetch_publication_bundle(
    pub: str,
    issue: str,
    language: str = "T",
    timeout: float = 6.0,
) -> MediaDownloadItem | None:
    """Checks and returns a MediaDownloadItem for a .jwpub publication bundle on JW.org."""
    lang = normalize_meps_language(language)
    chosen_issue = issue.strip()
    if not chosen_issue:
        return None

    url = (
        f"https://b.jw-cdn.org/apis/pub-media/GETPUBMEDIALINKS"
        f"?output=json&pub={pub}&issue={chosen_issue}&fileformat=JWPUB&alllangs=0&langwritten={lang}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    jwpub_list = data.get("files", {}).get(lang, {}).get("JWPUB", [])
    if not jwpub_list:
        return None

    entry = jwpub_list[0]
    file_info = entry.get("file") or {}
    raw_url = file_info.get("url", "")
    if not raw_url:
        return None

    url_file = Path(urllib.parse.urlsplit(raw_url).path).name
    filename = url_file if url_file else f"{pub}_{lang}_{chosen_issue}.jwpub"
    title = entry.get("title") or f"Publicação {pub.upper()} {chosen_issue}"
    filesize = int(entry.get("filesize", 0) or 0)
    issue_num = int(chosen_issue) if chosen_issue.isdigit() else 0

    return MediaDownloadItem(
        title=title,
        url=raw_url,
        filesize=filesize,
        media_type="bundle",
        category="midweek" if pub.lower() == "mwb" else "weekend",
        suggested_filename=filename,
        checksum=str(file_info.get("checksum") or ""),
        pub_symbol=pub.lower(),
        issue_tag=issue_num,
        meps_language_index=resolve_meps_language_index(lang),
    )


def get_meeting_weeks(
    base_date: datetime.date | None = None,
    past_weeks: int = 2,
    future_weeks: int = 8,
    jwpub_sources: list[Path] | None = None,
) -> list[MeetingWeekInfo]:
    """Computes meeting weeks with Portuguese labels, current week detection, and issue mapping.

    Discovers available future weeks up to the latest date found in provided jwpub packages,
    falling back to at least `future_weeks` weeks ahead.
    """
    today = base_date or datetime.date.today()
    cur_monday = today - datetime.timedelta(days=today.weekday())

    mondays_set: set[datetime.date] = set()

    # 1. Add requested past weeks
    for w in range(past_weeks, 0, -1):
        mondays_set.add(cur_monday - datetime.timedelta(weeks=w))

    # 2. Add current week
    mondays_set.add(cur_monday)

    # 3. Add default future weeks
    for w in range(1, future_weeks + 1):
        mondays_set.add(cur_monday + datetime.timedelta(weeks=w))

    # 4. If jwpub_sources provided, parse DatedText to find all publication weeks
    if jwpub_sources:
        for src in jwpub_sources:
            if not src or not src.exists():
                continue
            db_path, td = _extract_sqlite_db_from_jwpub(src)
            if db_path and db_path.exists():
                try:
                    conn = sqlite3.connect(db_path)
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT FirstDateOffset FROM DatedText "
                        "WHERE FirstDateOffset IS NOT NULL ORDER BY FirstDateOffset"
                    )
                    rows = cur.fetchall()
                    for (offset_val,) in rows:
                        try:
                            offset_int = int(offset_val)
                        except (ValueError, TypeError):
                            continue
                        if offset_int > 20000000:
                            y = offset_int // 10000
                            m = (offset_int % 10000) // 100
                            d = offset_int % 100
                            try:
                                dt = datetime.date(y, m, d)
                                # Align to Monday of that week
                                mon = dt - datetime.timedelta(days=dt.weekday())
                                mondays_set.add(mon)
                            except ValueError:
                                pass
                    conn.close()
                except Exception:
                    pass
                finally:
                    if td:
                        td.cleanup()

    sorted_mondays = sorted(mondays_set)
    weeks: list[MeetingWeekInfo] = []
    for mon in sorted_mondays:
        sun = mon + datetime.timedelta(days=6)
        delta = (mon - cur_monday).days // 7
        is_curr = delta == 0

        # mwb is bimonthly (odd months 1, 3, 5, 7, 9, 11)
        odd_m = mon.month if mon.month % 2 == 1 else mon.month - 1
        mwb_issue = f"{mon.year}{odd_m:02d}"

        # w study magazine
        w_issue = f"{mon.year}{mon.month:02d}"

        date_range_str = f"{mon.strftime('%d/%m')} a {sun.strftime('%d/%m/%Y')}"
        if is_curr:
            label = f"{date_range_str} (Semana Atual)"
        elif delta < 0:
            abs_d = abs(delta)
            plural = "s" if abs_d > 1 else ""
            label = f"{date_range_str} ({abs_d} semana{plural} atrás)"
        else:
            plural = "s" if delta > 1 else ""
            label = f"{date_range_str} (+{delta} semana{plural})"

        weeks.append(
            MeetingWeekInfo(
                monday=mon,
                sunday=sun,
                label=label,
                is_current=is_curr,
                delta_weeks=delta,
                mwb_issue=mwb_issue,
                w_issue=w_issue,
            )
        )

    return weeks


def extract_images_from_jwpub(jwpub_path: Path, output_dir: Path) -> list[Path]:
    """Extracts high-resolution study illustration images from a .jwpub package or publication directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    if not jwpub_path.exists():
        return extracted
    if jwpub_path.is_file() and jwpub_path.stat().st_size == 0:
        return extracted

    try:
        def _is_image(name: str) -> bool:
            return name.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))

        def _filter_names(names: list[str]) -> list[str]:
            img_names = [n for n in names if _is_image(n)]
            low_res_patterns = ("-120x120.", "-240x120.", "-360x120.")
            has_high_res = any(
                not any(pat in n.lower() for pat in low_res_patterns)
                for n in img_names
            )
            if has_high_res:
                filtered = [
                    n for n in img_names
                    if not any(pat in n.lower() for pat in low_res_patterns)
                ]
                return filtered if filtered else img_names
            return img_names

        if jwpub_path.is_dir():
            file_names = [p.name for p in jwpub_path.iterdir() if p.is_file()]
            candidate_names = _filter_names(file_names)
            for name in candidate_names:
                src_file = jwpub_path / name
                clean_name = sanitize_filename(name)
                dest_file = output_dir / clean_name
                dest_file.write_bytes(src_file.read_bytes())
                extracted.append(dest_file)
            return extracted

        with zipfile.ZipFile(jwpub_path, "r") as outer_zip:
            if "contents" in outer_zip.namelist():
                contents_bytes = outer_zip.read("contents")
                with zipfile.ZipFile(io.BytesIO(contents_bytes), "r") as inner_zip:
                    candidate_names = _filter_names(inner_zip.namelist())
                    for name in candidate_names:
                        data = inner_zip.read(name)
                        clean_name = sanitize_filename(Path(name).name)
                        dest_file = output_dir / clean_name
                        dest_file.write_bytes(data)
                        extracted.append(dest_file)
            else:
                candidate_names = _filter_names(outer_zip.namelist())
                for name in candidate_names:
                    data = outer_zip.read(name)
                    clean_name = sanitize_filename(Path(name).name)
                    dest_file = output_dir / clean_name
                    dest_file.write_bytes(data)
                    extracted.append(dest_file)
    except Exception:
        pass
    return extracted


def _extract_sqlite_db_from_jwpub(
    jwpub_path: Path,
) -> tuple[Path | None, tempfile.TemporaryDirectory | None]:
    """Helper to locate or extract the SQLite database file from a .jwpub or directory."""
    if not jwpub_path.exists():
        return None, None
    if jwpub_path.is_file() and jwpub_path.suffix.lower() == ".db":
        return jwpub_path, None
    if jwpub_path.is_dir():
        dbs = list(jwpub_path.glob("*.db"))
        if dbs:
            return dbs[0], None
        return None, None
    if jwpub_path.is_file() and zipfile.is_zipfile(jwpub_path):
        td = tempfile.TemporaryDirectory()
        temp_dir = Path(td.name)
        try:
            with zipfile.ZipFile(jwpub_path, "r") as outer_zip:
                db_names = [n for n in outer_zip.namelist() if n.lower().endswith(".db")]
                if db_names:
                    outer_zip.extract(db_names[0], temp_dir)
                    return temp_dir / db_names[0], td
                if "contents" in outer_zip.namelist():
                    c_bytes = outer_zip.read("contents")
                    with zipfile.ZipFile(io.BytesIO(c_bytes), "r") as inner_zip:
                        inner_dbs = [n for n in inner_zip.namelist() if n.lower().endswith(".db")]
                        if inner_dbs:
                            inner_zip.extract(inner_dbs[0], temp_dir)
                            return temp_dir / inner_dbs[0], td
        except Exception:
            td.cleanup()
            return None, None
    return None, None


def extract_meeting_songs_from_jwpub(
    jwpub_path: Path,
    meeting_date: datetime.date | None = None,
    current_week_only: bool = True,
) -> list[int]:
    """Extracts meeting song numbers (sjjm tracks) from a .jwpub package or publication database.

    If current_week_only is True, extracts only the songs for the week matching meeting_date
    (defaults to today). Otherwise, extracts all distinct songs in the publication in order.
    """
    db_path, td = _extract_sqlite_db_from_jwpub(jwpub_path)
    if not db_path or not db_path.exists():
        return []
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='DatedText'")
        if not cur.fetchone():
            return []

        cur.execute(
            "SELECT DatedTextId, DocumentId, FirstDateOffset, LastDateOffset "
            "FROM DatedText ORDER BY FirstDateOffset"
        )
        dated_texts = cur.fetchall()
        if not dated_texts:
            return []

        cur.execute("SELECT DocumentId, Class, Title FROM Document WHERE Class='40' ORDER BY DocumentId")
        study_docs = cur.fetchall()

        if current_week_only:
            target_date = meeting_date or datetime.date.today()
            target_num = target_date.year * 10000 + target_date.month * 100 + target_date.day

            matching_dt = None
            for dt in dated_texts:
                _dt_id, _doc_id, start_off, end_off = dt
                if start_off <= target_num <= end_off:
                    matching_dt = dt
                    break

            if not matching_dt:
                matching_dt = min(dated_texts, key=lambda dt: abs(dt[2] - target_num))

            target_doc_id = matching_dt[1]
            cur.execute(
                "SELECT m.Track FROM DocumentMultimedia dm "
                "JOIN Multimedia m ON dm.MultimediaId = m.MultimediaId "
                "WHERE dm.DocumentId = ? AND m.KeySymbol IN ('sjjm', 'sjj') AND m.Track IS NOT NULL "
                "ORDER BY dm.DocumentMultimediaId",
                (target_doc_id,),
            )
            songs = [int(r[0]) for r in cur.fetchall()]

            if not songs and study_docs:
                week_idx = dated_texts.index(matching_dt)
                if week_idx < len(study_docs):
                    study_doc_id = study_docs[week_idx][0]
                    cur.execute(
                        "SELECT m.Track FROM DocumentMultimedia dm "
                        "JOIN Multimedia m ON dm.MultimediaId = m.MultimediaId "
                        "WHERE dm.DocumentId = ? AND m.KeySymbol IN ('sjjm', 'sjj') AND m.Track IS NOT NULL "
                        "ORDER BY dm.DocumentMultimediaId",
                        (study_doc_id,),
                    )
                    songs = [int(r[0]) for r in cur.fetchall()]
            return songs
        else:
            cur.execute(
                "SELECT DISTINCT m.Track FROM DocumentMultimedia dm "
                "JOIN Multimedia m ON dm.MultimediaId = m.MultimediaId "
                "WHERE m.KeySymbol IN ('sjjm', 'sjj') AND m.Track IS NOT NULL "
                "ORDER BY dm.DocumentMultimediaId"
            )
            return [int(r[0]) for r in cur.fetchall()]
    except Exception:
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        if td:
            td.cleanup()


class CBSMediaEntry(tuple):
    """Represents an extracted Congregation Bible Study (CBS) or auxiliary video item.

    Inherits from tuple as (pub_symbol, track_number, title_or_label) to preserve
    100% backwards compatibility with existing unpacking code and tests, while
    providing issue_tag and document_id metadata via attributes and tuple indexing.
    """

    pub_symbol: str
    track_number: int
    title_or_label: str
    issue_tag: int
    document_id: int

    def __new__(
        cls,
        pub_symbol: str,
        track_number: int,
        title_or_label: str = "",
        issue_tag: int = 0,
        document_id: int = 0,
    ) -> CBSMediaEntry:
        obj = super().__new__(cls, (pub_symbol, track_number, title_or_label))
        obj.pub_symbol = pub_symbol
        obj.track_number = track_number
        obj.title_or_label = title_or_label
        obj.issue_tag = issue_tag
        obj.document_id = document_id
        return obj


def find_publication_db(
    pub_symbol: str,
    language: str = "T",
    search_dirs: list[Path] | None = None,
) -> Path | None:
    """Locates the local SQLite database for a publication (e.g. 'wcg', 'lff', 'bt')."""
    pub_clean = pub_symbol.strip().lower()
    lang_clean = normalize_meps_language(language).lower()

    candidates_dirs: list[Path] = []
    if search_dirs:
        for sd in search_dirs:
            if sd and sd.is_dir() and sd not in candidates_dirs:
                candidates_dirs.append(sd)

    jwl_pubs = detect_jwl_publications_dir()
    if jwl_pubs and jwl_pubs.is_dir() and jwl_pubs not in candidates_dirs:
        candidates_dirs.append(jwl_pubs)

    scored_candidates: list[tuple[int, Path]] = []
    for base_dir in candidates_dirs:
        try:
            for child in base_dir.iterdir():
                if not child.is_dir():
                    if child.is_file() and child.suffix.lower() == ".db":
                        stem = child.stem.lower()
                        if pub_clean in stem:
                            score = 100 if f"{pub_clean}_{lang_clean}" in stem else (
                                50 if stem == pub_clean else 10
                            )
                            scored_candidates.append((score, child))
                    continue
                c_name = child.name.lower()
                if (
                    c_name == f"{pub_clean}_{lang_clean}"
                    or c_name.startswith(f"{pub_clean}_{lang_clean}")
                    or c_name == pub_clean
                    or c_name.startswith(f"{pub_clean}_")
                ):
                    score = 100 if c_name.startswith(f"{pub_clean}_{lang_clean}") else (
                        50 if c_name == pub_clean else 10
                    )
                    scored_candidates.append((score, child))
        except OSError:
            continue

    scored_candidates.sort(key=lambda x: x[0], reverse=True)

    for _score, target in scored_candidates:
        if target.is_file() and target.suffix.lower() == ".db":
            return target
        if target.is_dir():
            contents_file = target / "contents"
            if contents_file.is_file():
                try:
                    import zipfile

                    with zipfile.ZipFile(contents_file, "r") as czf:
                        czf.extractall(target)
                    try:
                        contents_file.unlink()
                    except OSError:
                        pass
                except Exception:
                    pass
            dbs = list(target.glob("*.db"))
            if dbs:
                return dbs[0]

    return None


def extract_cbs_videos_from_mwb(
    jwpub_path: Path,
    meeting_date: datetime.date | None = None,
    current_week_only: bool = True,
    language: str = "T",
    search_dirs: list[Path] | None = None,
) -> list[CBSMediaEntry]:
    """Extracts Congregation Bible Study (CBS) and auxiliary videos from mwb publication.

    Returns list of CBSMediaEntry, fully compatible with (key_symbol, track_number, title_or_label).
    """
    db_path, td = _extract_sqlite_db_from_jwpub(jwpub_path)
    if not db_path or not db_path.exists():
        return []
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='DatedText'")
        if not cur.fetchone():
            return []

        cur.execute(
            "SELECT DatedTextId, DocumentId, FirstDateOffset, LastDateOffset "
            "FROM DatedText ORDER BY FirstDateOffset"
        )
        dated_texts = cur.fetchall()
        if not dated_texts:
            return []

        if current_week_only:
            target_date = meeting_date or datetime.date.today()
            target_num = target_date.year * 10000 + target_date.month * 100 + target_date.day
            matching_dt = None
            for dt in dated_texts:
                if dt[2] <= target_num <= dt[3]:
                    matching_dt = dt
                    break
            if not matching_dt:
                matching_dt = min(dated_texts, key=lambda dt: abs(dt[2] - target_num))
            target_doc_ids = [matching_dt[1]]
        else:
            target_doc_ids = [dt[1] for dt in dated_texts]

        vids: list[CBSMediaEntry] = []
        seen_keys: set[tuple[str, int, int]] = set()

        for doc_id in target_doc_ids:
            # 1. Auxiliary videos directly in mwb DocumentMultimedia (where KeySymbol is not sjjm/mwbv)
            cur.execute("PRAGMA table_info(Multimedia)")
            mm_cols = {c[1] for c in cur.fetchall()}
            has_major = "MajorType" in mm_cols
            has_mime = "MimeType" in mm_cols
            has_issue = "IssueTagNumber" in mm_cols
            has_meps_doc = "MepsDocumentId" in mm_cols

            issue_col = "coalesce(m.IssueTagNumber, 0)" if has_issue else "0"
            meps_doc_col = "coalesce(m.MepsDocumentId, 0)" if has_meps_doc else "0"

            type_clauses = ["(m.KeySymbol IS NOT NULL AND m.KeySymbol NOT IN ('sjjm', 'sjj', 'mwbv', 'mwb'))"]
            if has_major:
                type_clauses.append("m.MajorType = 2")
            if has_mime:
                type_clauses.append("(m.MimeType IS NOT NULL AND m.MimeType LIKE 'video/%')")
            type_filter = " OR ".join(type_clauses)

            cur.execute(
                f"""
                SELECT m.KeySymbol, coalesce(m.Track, 0), coalesce(m.Label, ''), {issue_col}, {meps_doc_col}
                FROM DocumentMultimedia dm
                JOIN Multimedia m ON dm.MultimediaId = m.MultimediaId
                WHERE dm.DocumentId = ?
                  AND ({type_filter})
                  AND (m.KeySymbol IS NULL OR m.KeySymbol NOT IN ('sjjm', 'sjj', 'mwbv', 'mwb'))
                ORDER BY dm.DocumentMultimediaId
                """,
                (doc_id,),
            )
            for raw_sym, track, label, issue_tag, meps_doc_id in cur.fetchall():
                key_sym = str(raw_sym) if raw_sym else (f"docid-{meps_doc_id}" if meps_doc_id else "")
                if not key_sym and not meps_doc_id:
                    continue
                key_tuple = (key_sym, int(track), int(issue_tag))
                if key_tuple not in seen_keys:
                    seen_keys.add(key_tuple)
                    vids.append(
                        CBSMediaEntry(
                            key_sym,
                            int(track),
                            str(label),
                            issue_tag=int(issue_tag),
                            document_id=int(meps_doc_id),
                        )
                    )

            # 2. CBS Study Book extract(s) referenced in DocumentExtract
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='DocumentExtract'")
            if cur.fetchone():
                cur.execute(
                    """
                    SELECT de.SortPosition, e.ExtractId, e.Link, coalesce(e.Caption, ''),
                           coalesce(rp.Symbol, ''), e.RefMepsDocumentId,
                           e.RefBeginParagraphOrdinal, e.RefEndParagraphOrdinal,
                           coalesce(rp.PublicationCategorySymbol, ''), coalesce(rp.PublicationType, '')
                    FROM DocumentExtract de
                    JOIN Extract e ON de.ExtractId = e.ExtractId
                    LEFT JOIN RefPublication rp ON e.RefPublicationId = rp.RefPublicationId
                    WHERE de.DocumentId = ?
                    ORDER BY de.SortPosition
                    """,
                    (doc_id,),
                )
                extracts = cur.fetchall()

                # Identify song positions to locate the CBS portion (between Song 2 and Song 3)
                song_pos = [
                    x[0] for x in extracts
                    if x[4] in ("sjj", "sjjm")
                    or "sjj" in str(x[3]).lower()
                    or "1102016" in str(x[2])
                ]
                candidates = []
                if len(song_pos) >= 2:
                    s_mid = song_pos[-2]
                    s_end = song_pos[-1]
                    candidates = [x for x in extracts if s_mid < x[0] < s_end]
                if not candidates:
                    candidates = extracts

                # Filter candidate study book extracts (e.g. wcg, bt, lff, cl, etc.)
                cbs_extracts = [
                    x for x in candidates
                    if x[4] and x[4] not in ("sjj", "sjjm", "nwtsty", "bi")
                    and (
                        x[8] in ("bk", "brch")
                        or str(x[9]).lower() in ("book", "brochure")
                        or any(
                            w in str(x[3]).lower()
                            for w in [
                                "pág", "págs", "lição", "cap", "capítulo", "seção",
                                "pag", "pags", "lección", "sección", "page", "pages",
                                "lesson", "chapter", "section",
                            ]
                        )
                        or x[4] in ("wcg", "bt", "lff", "cl", "rr", "jy", "ia", "cf", "lmd", "th")
                    )
                ]

                extra_search_dirs: list[Path] = []
                if jwpub_path.is_file() and jwpub_path.parent.is_dir():
                    extra_search_dirs.append(jwpub_path.parent)
                elif jwpub_path.is_dir():
                    extra_search_dirs.append(jwpub_path)
                if search_dirs:
                    extra_search_dirs.extend(search_dirs)

                for cbs_ext in cbs_extracts:
                    pub_sym = str(cbs_ext[4])
                    ref_doc_id = cbs_ext[5]
                    p_start = cbs_ext[6]
                    p_end = cbs_ext[7]
                    caption = str(cbs_ext[3])

                    pub_db = find_publication_db(pub_sym, language=language, search_dirs=extra_search_dirs)
                    if not pub_db or not pub_db.is_file():
                        continue

                    p_conn = None
                    try:
                        p_conn = sqlite3.connect(pub_db)
                        p_cur = p_conn.cursor()
                        p_cur.execute(
                            "SELECT DocumentId, Title FROM Document "
                            "WHERE MepsDocumentId = ? OR DocumentId = ?",
                            (ref_doc_id, ref_doc_id),
                        )
                        target_doc = p_cur.fetchone()
                        if not target_doc:
                            continue

                        t_doc_id = target_doc[0]
                        t_title = str(target_doc[1] or "")

                        p_cur.execute("PRAGMA table_info(Multimedia)")
                        p_cols = {c[1] for c in p_cur.fetchall()}
                        p_has_issue = "IssueTagNumber" in p_cols
                        p_has_meps_doc = "MepsDocumentId" in p_cols

                        p_issue_col = "coalesce(m.IssueTagNumber, 0)" if p_has_issue else "0"
                        p_meps_doc_col = "coalesce(m.MepsDocumentId, 0)" if p_has_meps_doc else "0"

                        p_cur.execute(
                            f"""
                            SELECT dm.DocumentMultimediaId, dm.BeginParagraphOrdinal, dm.EndParagraphOrdinal,
                                   m.MultimediaId, m.MajorType, m.MimeType, m.KeySymbol, m.Track,
                                   {p_issue_col}, coalesce(m.Label, ''), {p_meps_doc_col}
                            FROM DocumentMultimedia dm
                            JOIN Multimedia m ON dm.MultimediaId = m.MultimediaId
                            WHERE dm.DocumentId = ?
                            ORDER BY dm.DocumentMultimediaId
                            """,
                            (t_doc_id,),
                        )
                        for row in p_cur.fetchall():
                            mm_beg, mm_end = row[1], row[2]
                            if (
                                p_start is not None
                                and p_end is not None
                                and mm_beg is not None
                                and mm_end is not None
                            ):
                                if mm_end < p_start or mm_beg > p_end:
                                    continue
                            major, mime, k_sym, trk = row[4], row[5], row[6], row[7]
                            if major == 2 or str(mime).startswith("video/") or (k_sym and k_sym != "sjjm"):
                                v_sym = str(k_sym or pub_sym)
                                v_track = int(trk) if trk is not None else 0
                                v_issue = int(row[8] or 0)
                                v_label = str(row[9] or t_title or caption)
                                v_meps_doc = int(row[10] or 0)
                                key_tuple = (v_sym, v_track, v_issue)
                                if key_tuple not in seen_keys:
                                    seen_keys.add(key_tuple)
                                    vids.append(
                                        CBSMediaEntry(
                                            v_sym,
                                            v_track,
                                            v_label,
                                            issue_tag=v_issue,
                                            document_id=v_meps_doc,
                                        )
                                    )
                    except Exception:
                        pass
                    finally:
                        if p_conn:
                            try:
                                p_conn.close()
                            except Exception:
                                pass

        return vids
    except Exception:
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        if td:
            td.cleanup()


def fetch_media_item_by_pub_track(
    pub: str,
    track: int,
    issue_tag: int = 0,
    docid: int = 0,
    language: str = "T",
    preferred_quality: str = "720p",
    timeout: float = 10.0,
) -> MediaDownloadItem | None:
    """Fetches a specific video/media item by publication symbol, track, issue, or docid."""
    lang = normalize_meps_language(language)
    pub_code = pub.strip()

    def build_url(with_issue: bool, with_track: bool, with_docid: bool, with_pub: bool = True) -> str:
        params = [
            "output=json",
            "fileformat=mp4",
            "alllangs=0",
            f"langwritten={lang}",
        ]
        if with_pub and pub_code and not pub_code.lower().startswith("docid-"):
            params.append(f"pub={pub_code}")
        if with_track and track is not None and track > 0:
            params.append(f"track={track}")
        if with_issue and issue_tag and issue_tag > 0:
            tag_val = issue_tag // 100 if issue_tag >= 1_000_000 else issue_tag
            params.append(f"issue={tag_val}")
        if with_docid and docid and docid > 0:
            params.append(f"docid={docid}")
        return f"https://b.jw-cdn.org/apis/pub-media/GETPUBMEDIALINKS?{'&'.join(params)}"

    urls_to_try: list[str] = []
    if track is not None and track > 0:
        if issue_tag and issue_tag > 0:
            urls_to_try.append(build_url(with_issue=True, with_track=True, with_docid=False))
        urls_to_try.append(build_url(with_issue=False, with_track=True, with_docid=False))

    if docid and docid > 0:
        if issue_tag and issue_tag > 0:
            urls_to_try.append(build_url(with_issue=True, with_track=False, with_docid=True, with_pub=True))
            urls_to_try.append(build_url(with_issue=True, with_track=False, with_docid=True, with_pub=False))
        urls_to_try.append(build_url(with_issue=False, with_track=False, with_docid=True, with_pub=True))
        urls_to_try.append(build_url(with_issue=False, with_track=False, with_docid=True, with_pub=False))

    if not urls_to_try:
        urls_to_try.append(
            build_url(with_issue=bool(issue_tag), with_track=bool(track), with_docid=bool(docid))
        )
        if docid:
            urls_to_try.append(
                build_url(
                    with_issue=bool(issue_tag),
                    with_track=bool(track),
                    with_docid=bool(docid),
                    with_pub=False,
                )
            )

    data = None
    for target_url in urls_to_try:
        req = urllib.request.Request(target_url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                cand = json.loads(resp.read().decode("utf-8"))
                files_by_lang = cand.get("files", {}).get(lang, {})
                if files_by_lang.get("MP4"):
                    data = cand
                    break
        except Exception:
            continue

    if not data:
        return None

    files_by_lang = data.get("files", {}).get(lang, {})
    mp4_list = files_by_lang.get("MP4", [])
    if not mp4_list:
        return None

    quality_target = preferred_quality.lower()
    selected = None
    for entry in mp4_list:
        label = str(entry.get("label", "")).lower()
        file_info = entry.get("file") or {}
        file_url = file_info.get("url", "")
        if quality_target in label or quality_target in file_url.lower():
            selected = entry
            break
    if not selected and mp4_list:
        selected = mp4_list[-1]

    if not selected:
        return None

    file_info = selected.get("file") or {}
    raw_url = file_info.get("url", "")
    if not raw_url:
        return None

    title = selected.get("title") or f"{pub_code} Track {track}"
    duration = float(selected.get("duration", 0.0) or 0.0)
    filesize = int(selected.get("filesize", 0) or 0)
    url_file = Path(urllib.parse.urlsplit(raw_url).path).name
    filename = url_file if url_file else f"{pub_code}_{lang}_{track:02d}_{sanitize_filename(title)}.mp4"

    return MediaDownloadItem(
        title=title,
        url=raw_url,
        filesize=filesize,
        duration_seconds=duration,
        media_type="video",
        category="midweek",
        track_num=track,
        suggested_filename=filename,
        checksum=str(file_info.get("checksum") or ""),
        pub_symbol=str(selected.get("pub") or pub_code),
        docid=int(selected.get("docid") or docid or 0),
        issue_tag=int(selected.get("issue") or issue_tag or 0),
        book_num=int(selected.get("booknum") or 0),
        meps_language_index=resolve_meps_language_index(lang),
        frame_width=int(selected.get("frameWidth") or 0),
        frame_height=int(selected.get("frameHeight") or 0),
        bit_rate=float(selected.get("bitRate") or 0.0),
        frame_rate=float(selected.get("frameRate") or 0.0),
        label=str(selected.get("label") or ""),
    )



def download_file(
    url: str,
    destination: Path,
    progress_cb=None,
    cancel_token: CancelToken | None = None,
    timeout: float = 20.0,
) -> Path:
    """Downloads a file in streaming chunks with cancellation and atomic commit."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_dest = destination.with_suffix(destination.suffix + ".part")

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            try:
                total_size = int(resp.headers.get("Content-Length") or 0)
            except (ValueError, TypeError):
                total_size = 0
            downloaded = 0
            with open(temp_dest, "wb") as f:
                while True:
                    if cancel_token and cancel_token.is_cancelled:
                        raise InterruptedError("Download cancelado pelo operador.")

                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        try:
                            progress_cb(downloaded, total_size)
                        except TypeError:
                            pct = int(downloaded / total_size * 100) if total_size > 0 else 0
                            progress_cb(pct)

        if cancel_token and cancel_token.is_cancelled:
            if temp_dest.exists():
                temp_dest.unlink()
            raise InterruptedError("Download cancelado pelo operador.")

        os.replace(temp_dest, destination)
        return destination
    except Exception:
        if temp_dest.exists():
            try:
                temp_dest.unlink()
            except OSError:
                pass
        raise
