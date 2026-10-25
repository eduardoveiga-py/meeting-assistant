from __future__ import annotations

import base64
import hashlib
import io
import mimetypes
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_THUMBNAIL_BYTES: bytes = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAYAAADDPmHLAAAAAXNSR0IArs4c6QAAAdhJREFUeAHt1"
    "AEJACAAxEC1f0Eto2CN2zfYGD/P2Xc01sBiyQP/BgoAD6EACgA3gOP3AAWAG8Dxe4ACwA3g+D1AA"
    "eAGcPweoABwAzh+D1AAuAEcvwcoANwAjt8DFABuAMfvAQoAN4Dj9wAFgBvA8XuAAsAN4Pg9QAHgB"
    "nD8HqAAcAM4fg9QALgBHL8HKADcAI7fAxQAbgDH7wEKADeA4/cABYAbwPF7gALADeD4PUAB4AZw/"
    "B6gAHADOH4PUAC4ARy/BygA3ACO3wMUAG4Ax+8BCgA3gOP3AAWAG8Dxe4ACwA3g+D1AAeAGcPweo"
    "ABwAzh+D1AAuAEcvwcoANwAjt8DFABuAMfvAQoAN4Dj9wAFgBvA8XuAAsAN4Pg9QAHgBnD8HqAAc"
    "AM4fg9QALgBHL8HKADcAI7fAxQAbgDH7wEKADeA4/cABYAbwPF7gALADeD4PUAB4AZw/B6gAHADO"
    "H4PUAC4ARy/BygA3ACO3wMUAG4Ax+8BCgA3gOP3AAWAG8Dxe4ACwA3g+D1AAeAGcPweoABwAzh+D"
    "1AAuAEcvwcoANwAjt8DFABuAMfvAQoAN4Dj9wAFgBvA8XuAAsAN4Pg9QAHgBnD8HqAAcAM4fg9QA"
    "LgBHL8HwAN4OkwEjMfaVl8AAAAASUVORK5CYII="
)



@dataclass(slots=True)
class MediaImportItem:
    source_path: Path
    label: str
    mime_type: str = ""
    duration_seconds: float = 0.0
    end_action: int = 2  # 0=Continue, 1=Next, 2=Pause/Stop
    key_symbol: str = ""
    track: int | None = None
    meps_language_index: int = 5
    issue_tag_number: int = 0
    document_id: int | None = None
    book_number: int | None = None
    thumbnail_path: Path | None = None


@dataclass(slots=True)
class MediaImportResult:
    success: bool
    imported_count: int = 0
    synchronized_count: int = 0
    playlist_name: str = ""
    backup_path: Path | None = None
    error_message: str = ""
    imported_items: list[str] = field(default_factory=list)
    package_path: Path | None = None
    activated_jwl: bool = False


def detect_jwl_userdata_dir() -> Path | None:
    """Detects the default JW Library Userdata folder on Windows 11 / 10."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    packages_dir = Path(local_app_data) / "Packages"
    if not packages_dir.exists():
        return None

    # JW Library package name starts with WatchtowerBibleandTractSo.
    for pkg in packages_dir.glob("WatchtowerBibleandTractSo.*"):
        userdata = pkg / "LocalState" / "Userdata"
        if userdata.is_dir():
            return userdata
    return None


def detect_jwl_userdata_db(custom_path: Path | str | None = None) -> Path | None:
    """Locates the userData.db file, checking custom path first, then default package."""
    if custom_path:
        p = Path(custom_path)
        if p.is_file():
            return p

    userdata_dir = detect_jwl_userdata_dir()
    if userdata_dir:
        db_file = userdata_dir / "userData.db"
        if db_file.is_file():
            return db_file
    return None


def detect_jwl_package_dir() -> Path | None:
    """Detects the root folder of the installed JW Library UWP package."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    packages_dir = Path(local_app_data) / "Packages"
    if not packages_dir.exists():
        return None
    for pkg in packages_dir.glob("WatchtowerBibleandTractSo.*"):
        if (pkg / "LocalState").is_dir():
            return pkg
    return None


def detect_jwl_publications_dir() -> Path | None:
    """Returns the LocalState/Publications directory for JW Library if found."""
    pkg = detect_jwl_package_dir()
    if pkg:
        pub_dir = pkg / "LocalState" / "Publications"
        if pub_dir.is_dir():
            return pub_dir
    return None


def detect_jwl_media_collection_db() -> Path | None:
    """Locates the mediaCollection.db file where JW Library stores official downloaded media."""
    pkg = detect_jwl_package_dir()
    if pkg:
        db = pkg / "LocalState" / "Data" / "mediaCollection.db"
        if db.is_file():
            return db
    return None


def detect_jwl_videos_dir() -> Path:
    """Returns the default Windows Videos folder for JW Library media."""
    videos_dir = Path.home() / "Videos" / "JWLibrary"
    try:
        videos_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return videos_dir


def detect_jwl_music_dir() -> Path:
    """Returns the default Windows Music folder for JW Library audio media."""
    music_dir = Path.home() / "Music" / "JWLibrary"
    try:
        music_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return music_dir


MEPS_LANGUAGE_INDEX_MAP: dict[str, int] = {
    "E": 0,    # English
    "S": 1,    # Spanish
    "F": 2,    # French
    "X": 3,    # German
    "I": 4,    # Italian
    "T": 5,    # Portuguese (Brazil)
    "TCN": 733, # Ticuna
}


def resolve_meps_language_index(lang_code: str) -> int:
    """Resolves a MEPS language code (e.g. 'T', 'TCN', 'S') to its integer index."""
    code = lang_code.strip().upper()
    if code in MEPS_LANGUAGE_INDEX_MAP:
        return MEPS_LANGUAGE_INDEX_MAP[code]

    pkg = detect_jwl_package_dir()
    if pkg:
        pub_db = pkg / "LocalState" / "Data" / "pub_collections.db"
        if pub_db.is_file():
            try:
                con = sqlite3.connect(f"file:{pub_db.as_posix()}?mode=ro", uri=True, timeout=10.0)
                try:
                    con.execute("PRAGMA busy_timeout = 10000;")
                    cur = con.cursor()
                    cur.execute("SELECT DISTINCT LanguageIndex FROM Publication")
                    rows = [r[0] for r in cur.fetchall()]
                    if len(rows) == 1:
                        return rows[0]
                finally:
                    con.close()
            except Exception:
                pass
    return 5


def is_publication_installed(
    key_symbol: str,
    issue_tag: int = 0,
    meps_language_index: int = -1,
    db_path: Path | str | None = None,
) -> bool:
    """Checks if a publication (e.g. 'mwb', 'w', 'nwt') is installed in JW Library."""
    pkg = detect_jwl_package_dir()
    resolved_db = Path(db_path) if db_path else None
    if not resolved_db and pkg:
        resolved_db = pkg / "LocalState" / "Data" / "pub_collections.db"

    if not resolved_db or not resolved_db.is_file():
        return False

    tag_8 = issue_tag * 100 if (0 < issue_tag < 1_000_000) else issue_tag
    tag_6 = issue_tag if (0 < issue_tag < 1_000_000) else (issue_tag // 100 if issue_tag > 0 else 0)

    try:
        con = sqlite3.connect(f"file:{resolved_db.as_posix()}?mode=ro", uri=True, timeout=10.0)
        try:
            con.execute("PRAGMA busy_timeout = 10000;")
            cur = con.cursor()
            cur.execute("PRAGMA table_info(Publication)")
            col_names = {row[1].lower() for row in cur.fetchall()}
            symbol_clause = " OR LOWER(Symbol) = LOWER(?)" if "symbol" in col_names else ""
            query = f"""
                SELECT DatabasePath, JwPub FROM Publication
                WHERE (LOWER(KeySymbol) = LOWER(?){symbol_clause})
            """
            params: list[object] = [key_symbol]
            if "symbol" in col_names:
                params.append(key_symbol)
            if issue_tag > 0:
                query += " AND (IssueTagNumber IN (?, ?) OR IssueTagNumber = 0)"
                params.extend([tag_8, tag_6])
            if meps_language_index >= 0:
                query += " AND (LanguageIndex = ? OR LanguageIndex IS NULL)"
                params.append(meps_language_index)

            cur.execute(query, params)
            rows = cur.fetchall()
            if not rows:
                return False

            for db_file, jwpub_name in rows:
                if db_file and Path(db_file).is_file():
                    return True
                if jwpub_name and pkg:
                    cand = pkg / "LocalState" / "Publications" / jwpub_name
                    if cand.is_file() and cand.stat().st_size > 0:
                        return True
                    stem = Path(jwpub_name).stem
                    cand_folder = pkg / "LocalState" / "Publications" / stem
                    if cand_folder.is_dir() and list(cand_folder.glob("*.db")):
                        return True
            return False
        finally:
            con.close()
    except Exception:
        return False


def is_jwlibrary_running() -> bool:
    """Checks if the JW Library process is currently running on the system."""
    try:
        import subprocess

        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        out = subprocess.check_output(
            ["tasklist.exe", "/FI", "IMAGENAME eq JWLibrary.exe", "/NH"],
            text=True,
            timeout=2.0,
            creationflags=flags,
        )
        return "jwlibrary.exe" in out.lower()
    except Exception:
        return False


def install_jwpub_to_jwl(jwpub_path: Path | str) -> bool:
    """Triggers JW Library to install a .jwpub publication package on Windows."""
    path = Path(jwpub_path)
    if not path.is_file():
        return False

    success = False
    pkg = detect_jwl_package_dir()
    if pkg:
        try:
            import json
            import zipfile

            if zipfile.is_zipfile(path):
                stem = path.stem
                pub_dir = pkg / "LocalState" / "Publications" / stem
                pub_dir.mkdir(parents=True, exist_ok=True)
                manifest_data = None
                with zipfile.ZipFile(path, "r") as zf:
                    # Extract nested contents zip containing the sqlite publication db and assets
                    if "contents" in zf.namelist():
                        contents_bytes = zf.read("contents")
                        try:
                            with zipfile.ZipFile(io.BytesIO(contents_bytes), "r") as inner_zf:
                                inner_zf.extractall(pub_dir)
                        except Exception:
                            pass
                    # Extract other files from outer zip (e.g. manifest.json, cover images)
                    for member in zf.namelist():
                        if member != "contents":
                            try:
                                zf.extract(member, pub_dir)
                            except Exception:
                                pass

                    manifest_file = pub_dir / "manifest.json"
                    if manifest_file.is_file():
                        try:
                            manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                        except Exception:
                            pass

                # Locate the publication database within pub_dir.
                # If contents archive exists as a file in pub_dir, extract its members directly.
                contents_file = pub_dir / "contents"
                if contents_file.is_file():
                    try:
                        with zipfile.ZipFile(contents_file, "r") as czf:
                            czf.extractall(pub_dir)
                        try:
                            contents_file.unlink()
                        except OSError:
                            pass
                    except Exception:
                        pass

                db_files = list(pub_dir.glob("*.db"))
                pub_db_path = db_files[0] if db_files else None
                pub_row_dict = {}
                dated_texts = []
                documents = []
                issue_props = {}

                if pub_db_path and pub_db_path.is_file():
                    try:
                        db_uri = f"file:{pub_db_path.as_posix()}?mode=ro"
                        p_con = sqlite3.connect(db_uri, uri=True, timeout=5.0)
                        try:
                            p_cur = p_con.cursor()
                            # 1. Read Publication metadata from inner database
                            try:
                                p_cur.execute("SELECT * FROM Publication LIMIT 1")
                                if p_cur.description:
                                    p_cols = [d[0] for d in p_cur.description]
                                    p_row = p_cur.fetchone()
                                    if p_row:
                                        pub_row_dict = dict(zip(p_cols, p_row, strict=False))
                            except Exception:
                                pass

                            # 2. Read DatedText rows from inner database
                            try:
                                p_cur.execute("PRAGMA table_info(DatedText)")
                                dt_cols = {r[1].lower() for r in p_cur.fetchall()}
                                start_col = None
                                if "firstdateoffset" in dt_cols:
                                    start_col = "firstdateoffset"
                                elif "start" in dt_cols:
                                    start_col = "start"

                                end_col = None
                                if "lastdateoffset" in dt_cols:
                                    end_col = "lastdateoffset"
                                elif "end" in dt_cols:
                                    end_col = "end"

                                class_col = "class" if "class" in dt_cols else None
                                doc_col = "documentid" if "documentid" in dt_cols else None

                                if start_col and end_col:
                                    query = f"SELECT {start_col}, {end_col}"
                                    if class_col:
                                        query += f", {class_col}"
                                    elif doc_col:
                                        subq = (
                                            f"(SELECT Class FROM Document WHERE "
                                            f"Document.DocumentId = DatedText.{doc_col})"
                                        )
                                        query += f", {subq}"
                                    else:
                                        query += ", 106"
                                    query += " FROM DatedText"
                                    p_cur.execute(query)
                                    dated_texts = p_cur.fetchall()
                            except Exception:
                                pass

                            # 3. Read Document mappings from inner database
                            try:
                                p_cur.execute("PRAGMA table_info(Document)")
                                d_cols = {r[1].lower() for r in p_cur.fetchall()}
                                if "mepsdocumentid" in d_cols:
                                    lang_col = None
                                    if "mepslanguageindex" in d_cols:
                                        lang_col = "mepslanguageindex"
                                    elif "languageindex" in d_cols:
                                        lang_col = "languageindex"
                                    if lang_col:
                                        p_cur.execute(f"SELECT {lang_col}, MepsDocumentId FROM Document")
                                    else:
                                        p_cur.execute("SELECT 5, MepsDocumentId FROM Document")
                                    documents = p_cur.fetchall()
                            except Exception:
                                pass

                            # 4. Read PublicationIssueProperty from inner database
                            try:
                                p_cur.execute("SELECT * FROM PublicationIssueProperty LIMIT 1")
                                if p_cur.description:
                                    pip_cols = [d[0] for d in p_cur.description]
                                    pip_row = p_cur.fetchone()
                                    if pip_row:
                                        issue_props = dict(zip(pip_cols, pip_row, strict=False))
                            except Exception:
                                pass
                        finally:
                            p_con.close()
                    except Exception:
                        pass

                first_date = min((int(r[0]) for r in dated_texts if r[0]), default=0)
                last_date = max((int(r[1]) for r in dated_texts if r[1]), default=0)

                pub_meta = (manifest_data.get("publication") if manifest_data else {}) or {}
                lang_idx = pub_row_dict.get("LanguageIndex", pub_meta.get("language", 5))
                pub_type = pub_row_dict.get("PublicationType", pub_meta.get("publicationType", ""))
                cats = pub_meta.get("categories", [])
                cat_sym = pub_row_dict.get(
                    "PublicationCategorySymbol",
                    cats[0] if cats else pub_meta.get("undatedSymbol", ""),
                )
                key_symbol = pub_row_dict.get("KeySymbol", pub_meta.get("undatedSymbol") or cat_sym)
                title = pub_row_dict.get("Title", pub_meta.get("title", ""))
                short_title = pub_row_dict.get("ShortTitle", pub_meta.get("shortTitle", ""))
                display_title = pub_row_dict.get("DisplayTitle", pub_meta.get("displayTitle", ""))
                symbol = pub_row_dict.get("Symbol", pub_meta.get("symbol", ""))
                unique_eng_symbol = pub_row_dict.get(
                    "UniqueEnglishSymbol", pub_meta.get("uniqueEnglishSymbol", symbol)
                )
                year = pub_row_dict.get("Year", pub_meta.get("year", 0))
                issue_tag = pub_row_dict.get("IssueTagNumber", pub_meta.get("issueId", 0))
                if 0 < issue_tag < 1_000_000:
                    issue_tag *= 100
                root_symbol = pub_row_dict.get("RootSymbol", pub_meta.get("rootSymbol", symbol))
                root_year = pub_row_dict.get("RootYear", pub_meta.get("rootYear", year))
                root_lang = pub_row_dict.get("RootMepsLanguageIndex", pub_meta.get("rootLanguage", 0))
                version_num = pub_row_dict.get("VersionNumber", pub_meta.get("schemaVersion", 1))
                schema_ver = pub_row_dict.get("SchemaVersionNumber", pub_meta.get("schemaVersion", 1))
                pub_hash = pub_row_dict.get("Hash", pub_meta.get("hash", ""))
                timestamp = pub_row_dict.get("Timestamp", pub_meta.get("timestamp", ""))
                undated_ref_title = pub_row_dict.get(
                    "UndatedReferenceTitle", pub_meta.get("undatedReferenceTitle", "")
                )
                expanded_size = (
                    manifest_data.get("expandedSize", pub_row_dict.get("ExpandedSize", 0))
                    if manifest_data
                    else pub_row_dict.get("ExpandedSize", 0)
                )
                min_plat_ver = pub_row_dict.get(
                    "MinPlatformVersion", pub_meta.get("minPlatformVersion", 1)
                )
                meps_build = pub_row_dict.get(
                    "MepsBuildNumber",
                    manifest_data.get("mepsBuildNumber", 0) if manifest_data else 0,
                )

                db_name = pub_meta.get("fileName") or (pub_db_path.name if pub_db_path else f"{stem}.db")
                db_full_path = str(pub_db_path) if pub_db_path else str(pub_dir / db_name)

                pub_col_db = pkg / "LocalState" / "Data" / "pub_collections.db"
                if pub_col_db.is_file():
                    con = sqlite3.connect(pub_col_db.as_posix(), timeout=10.0)
                    try:
                        con.execute("PRAGMA busy_timeout = 10000;")
                        cur = con.cursor()
                        cur.execute("BEGIN IMMEDIATE")
                        jwpub_file_name = (manifest_data.get("name") if manifest_data else None) or path.name
                        cur.execute(
                            "SELECT PublicationId FROM Publication "
                            "WHERE JwPub = ? OR (KeySymbol = ? AND IssueTagNumber = ? AND LanguageIndex = ?)",
                            (jwpub_file_name, key_symbol, issue_tag, lang_idx),
                        )
                        existing = cur.fetchone()

                        cur.execute("PRAGMA table_info(Publication)")
                        pub_cols_in_db = {row[1].lower(): row[1] for row in cur.fetchall()}

                        pub_data_dict = {
                            "LanguageIndex": lang_idx,
                            "PublicationType": pub_type,
                            "PublicationCategorySymbol": cat_sym,
                            "Title": title,
                            "ShortTitle": short_title,
                            "DisplayTitle": display_title,
                            "Symbol": symbol,
                            "UniqueEnglishSymbol": unique_eng_symbol,
                            "Year": year,
                            "VolumeNumber": 0,
                            "IssueTagNumber": issue_tag,
                            "RootSymbol": root_symbol,
                            "RootYear": root_year,
                            "RootMepsLanguageIndex": root_lang,
                            "VersionNumber": version_num,
                            "SchemaVersionNumber": schema_ver,
                            "Hash": pub_hash,
                            "Timestamp": timestamp,
                            "JwPub": jwpub_file_name,
                            "DatabasePath": db_full_path,
                            "OnExternalStorage": 0,
                            "UndatedReferenceTitle": undated_ref_title,
                            "ExpandedSize": expanded_size,
                            "MinPlatformVersion": min_plat_ver,
                            "KeySymbol": key_symbol,
                            "MepsBuildNumber": meps_build,
                            "FirstDatedTextDateOffset": first_date,
                            "LastDatedTextDateOffset": last_date,
                        }

                        # Filter fields to only columns that exist in the target database
                        matched_fields = {
                            k: v for k, v in pub_data_dict.items() if k.lower() in pub_cols_in_db
                        }

                        if existing:
                            pub_id = existing[0]
                            set_clause = ", ".join(f"{col} = ?" for col in matched_fields.keys())
                            cur.execute(
                                f"UPDATE Publication SET {set_clause} WHERE PublicationId = ?",
                                list(matched_fields.values()) + [pub_id],
                            )
                        else:
                            col_clause = ", ".join(matched_fields.keys())
                            q_marks = ", ".join("?" for _ in matched_fields)
                            cur.execute(
                                f"INSERT INTO Publication ({col_clause}) VALUES ({q_marks})",
                                list(matched_fields.values()),
                            )
                            pub_id = cur.lastrowid

                        # Populate DatedText in pub_collections.db
                        cur.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name='DatedText'"
                        )
                        if cur.fetchone() and dated_texts:
                            cur.execute("DELETE FROM DatedText WHERE PublicationId = ?", (pub_id,))
                            for dt in dated_texts:
                                dt_start = int(dt[0]) if dt[0] else 0
                                dt_end = int(dt[1]) if dt[1] else 0
                                dt_cls = int(dt[2]) if len(dt) > 2 and str(dt[2]).isdigit() else 106
                                cur.execute(
                                    "INSERT INTO DatedText (PublicationId, Start, End, Class) "
                                    "VALUES (?, ?, ?, ?)",
                                    (pub_id, dt_start, dt_end, dt_cls),
                                )

                        # Populate Document mappings in pub_collections.db
                        cur.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name='Document'"
                        )
                        if cur.fetchone() and documents:
                            cur.execute("DELETE FROM Document WHERE PublicationId = ?", (pub_id,))
                            for doc in documents:
                                doc_lang = int(doc[0]) if doc[0] else lang_idx
                                doc_meps_id = int(doc[1]) if doc[1] else 0
                                cur.execute(
                                    "INSERT OR IGNORE INTO Document "
                                    "(LanguageIndex, MepsDocumentId, PublicationId) VALUES (?, ?, ?)",
                                    (doc_lang, doc_meps_id, pub_id),
                                )

                        # Populate PublicationIssueProperty in pub_collections.db
                        cur.execute(
                            "SELECT name FROM sqlite_master "
                            "WHERE type='table' AND name='PublicationIssueProperty'"
                        )
                        if cur.fetchone() and (issue_props or title):
                            cur.execute(
                                "DELETE FROM PublicationIssueProperty WHERE PublicationId = ?",
                                (pub_id,),
                            )
                            cur.execute(
                                """
                                INSERT INTO PublicationIssueProperty
                                (PublicationId, Title, UndatedTitle, CoverTitle, Symbol, KeySymbol)
                                VALUES (?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    pub_id,
                                    issue_props.get("Title") or title,
                                    issue_props.get("UndatedTitle") or undated_ref_title,
                                    issue_props.get("CoverTitle") or title,
                                    issue_props.get("Symbol") or symbol,
                                    issue_props.get("KeySymbol") or key_symbol,
                                ),
                            )

                        con.commit()
                        success = True
                    finally:
                        con.close()
                elif pub_dir.exists():
                    success = True
        except Exception:
            pass

    if success:
        return True

    # Fallback to system shell activation if direct install was not available
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(path))
            return True
        import subprocess

        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        subprocess.Popen(["cmd.exe", "/c", "start", "", str(path)], shell=True, creationflags=flags)
        return True
    except Exception:
        pass

    return False


def register_media_in_jwl_collection(
    db_path: Path | str | None,
    file_path: Path,
    key_symbol: str,
    media_type: int = 1,
    meps_language_index: int = 5,
    track: int = -1,
    issue_tag_number: int = 0,
    document_id: int = 0,
    book_number: int = 0,
    title: str = "",
    duration: float = 0.0,
    filesize: int = 0,
    checksum: str = "",
    label: str = "720p",
    frame_width: int = 1280,
    frame_height: int = 720,
    bit_rate: float = 0.0,
    frame_rate: float = 0.0,
    mime_type: str = "video/mp4",
) -> bool:
    """Registers downloaded media into JW Library's official mediaCollection.db.

    This ensures JW Library recognizes the video/audio as locally downloaded
    across official publication interfaces (Cancioneiro, Apostila, etc.),
    removing the cloud download icon and enabling instant local playback.
    """
    resolved_db = Path(db_path) if db_path else detect_jwl_media_collection_db()
    if not resolved_db or not resolved_db.is_file():
        return False

    if filesize <= 0 and file_path.is_file():
        try:
            filesize = file_path.stat().st_size
        except OSError:
            pass

    symbols_to_register = [key_symbol]
    if key_symbol in ("sjjm", "sjj"):
        symbols_to_register = ["sjjm", "sjj"]
    elif key_symbol in ("mwbv", "mwb"):
        symbols_to_register = ["mwbv", "mwb"]

    tag_8 = issue_tag_number * 100 if (0 < issue_tag_number < 1_000_000) else issue_tag_number
    tag_6 = (
        issue_tag_number
        if (0 < issue_tag_number < 1_000_000)
        else (issue_tag_number // 100 if issue_tag_number > 0 else 0)
    )

    try:
        con = sqlite3.connect(resolved_db.as_posix(), timeout=10.0)
        try:
            con.execute("PRAGMA busy_timeout = 10000;")
            cur = con.cursor()
            cur.execute("BEGIN IMMEDIATE")

            cur.execute("PRAGMA table_info(Video)")
            video_cols = {r[1] for r in cur.fetchall()}
            has_specialty = "SpecialtyDescription" in video_cols

            for sym in symbols_to_register:
                if issue_tag_number > 0 and track >= 0:
                    cur.execute(
                        """
                        SELECT MediaKeyId FROM MediaKey
                        WHERE KeySymbol = ? AND MediaType = ? AND MepsLanguageIndex = ?
                          AND Track = ? AND (IssueTagNumber IN (?, ?) OR IssueTagNumber = 0)
                        """,
                        (sym, media_type, meps_language_index, track, tag_8, tag_6),
                    )
                elif issue_tag_number > 0:
                    cur.execute(
                        """
                        SELECT MediaKeyId FROM MediaKey
                        WHERE KeySymbol = ? AND MediaType = ? AND MepsLanguageIndex = ?
                          AND (IssueTagNumber IN (?, ?) OR IssueTagNumber = 0)
                          AND (DocumentId = ? OR ? = 0)
                        """,
                        (sym, media_type, meps_language_index, tag_8, tag_6, document_id, document_id),
                    )
                elif track >= 0:
                    cur.execute(
                        """
                        SELECT MediaKeyId FROM MediaKey
                        WHERE KeySymbol = ? AND MediaType = ? AND MepsLanguageIndex = ? AND Track = ?
                        """,
                        (sym, media_type, meps_language_index, track),
                    )
                else:
                    cur.execute(
                        """
                        SELECT MediaKeyId FROM MediaKey
                        WHERE KeySymbol = ? AND MediaType = ? AND MepsLanguageIndex = ?
                          AND (DocumentId = ? OR ? = 0)
                        """,
                        (sym, media_type, meps_language_index, document_id, document_id),
                    )
                row = cur.fetchone()
                if row:
                    media_key_id = row[0]
                else:
                    insert_tag = issue_tag_number
                    if insert_tag >= 1_000_000 and insert_tag % 100 == 0:
                        if sym.startswith("jwb") or sym in ("jwbai", "jwbcov"):
                            insert_tag = insert_tag // 100
                    cur.execute(
                        """
                        INSERT INTO MediaKey (
                            KeySymbol, MediaType, DocumentId, MepsLanguageIndex,
                            IssueTagNumber, Track, BookNumber
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            sym,
                            media_type,
                            document_id,
                            meps_language_index,
                            insert_tag,
                            track,
                            book_number,
                        ),
                    )
                    media_key_id = cur.lastrowid

                if media_type == 1:
                    cur.execute("SELECT VideoId FROM Video WHERE MediaKeyId = ?", (media_key_id,))
                    vrow = cur.fetchone()
                    if vrow:
                        if has_specialty:
                            cur.execute(
                                """
                                UPDATE Video SET
                                    FilePath = ?,
                                    FileSize = COALESCE(NULLIF(?, 0), FileSize),
                                    Duration = COALESCE(NULLIF(?, 0.0), Duration),
                                    Checksum = COALESCE(NULLIF(?, ''), Checksum),
                                    Label = COALESCE(NULLIF(?, ''), Label),
                                    SpecialtyDescription = COALESCE(SpecialtyDescription, ''),
                                    Specialty = COALESCE(Specialty, ''),
                                    Edition = COALESCE(Edition, '')
                                WHERE MediaKeyId = ?
                                """,
                                (str(file_path), filesize, duration, checksum, label, media_key_id),
                            )
                        else:
                            cur.execute(
                                """
                                UPDATE Video SET
                                    FilePath = ?,
                                    FileSize = COALESCE(NULLIF(?, 0), FileSize),
                                    Duration = COALESCE(NULLIF(?, 0.0), Duration),
                                    Checksum = COALESCE(NULLIF(?, ''), Checksum),
                                    Label = COALESCE(NULLIF(?, ''), Label)
                                WHERE MediaKeyId = ?
                                """,
                                (str(file_path), filesize, duration, checksum, label, media_key_id),
                            )
                    else:
                        if has_specialty:
                            cur.execute(
                                """
                                INSERT INTO Video (
                                    MediaKeyId, Title, Version, MimeType, BitRate, FrameRate,
                                    Duration, Checksum, FileSize, FrameHeight, FrameWidth,
                                    Label, SpecialtyDescription, Specialty, Edition, FilePath, Source
                                )
                                VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', '', ?, 0)
                                """,
                                (
                                    media_key_id, title, mime_type, bit_rate, frame_rate,
                                    duration, checksum, filesize, frame_height, frame_width,
                                    label, str(file_path),
                                ),
                            )
                        else:
                            cur.execute(
                                """
                                INSERT INTO Video (
                                    MediaKeyId, Title, Version, MimeType, BitRate, FrameRate,
                                    Duration, Checksum, FileSize, FrameHeight, FrameWidth,
                                    Label, FilePath, Source
                                )
                                VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                                """,
                                (
                                    media_key_id, title, mime_type, bit_rate, frame_rate,
                                    duration, checksum, filesize, frame_height, frame_width,
                                    label, str(file_path),
                                ),
                            )
                elif media_type == 2:
                    cur.execute("SELECT AudioId FROM Audio WHERE MediaKeyId = ?", (media_key_id,))
                    arow = cur.fetchone()
                    if arow:
                        cur.execute(
                            """
                            UPDATE Audio SET
                                FilePath = ?,
                                FileSize = COALESCE(NULLIF(?, 0), FileSize),
                                Duration = COALESCE(NULLIF(?, 0.0), Duration),
                                Checksum = COALESCE(NULLIF(?, ''), Checksum)
                            WHERE MediaKeyId = ?
                            """,
                            (str(file_path), filesize, duration, checksum, media_key_id),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO Audio (
                                MediaKeyId, Title, Version, MimeType, BitRate,
                                Duration, Checksum, FileSize, FilePath, Source
                            )
                            VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, 0)
                            """,
                            (
                                media_key_id, title, mime_type, bit_rate,
                                duration, checksum, filesize, str(file_path),
                            ),
                        )

            con.commit()
            try:
                con.execute("PRAGMA wal_checkpoint(PASSIVE);")
            except sqlite3.Error:
                pass
            return True
        finally:
            con.close()
    except Exception:
        return False


def calculate_jwl_hash(data: bytes) -> str:
    """Calculates the standard SHA-256 hash formatted exactly as JW Library (64-character lowercase hex)."""
    return hashlib.sha256(data).hexdigest().lower()


def detect_mime_type(file_path: Path) -> str:
    """Detects the MIME type for common media files used in meetings."""
    ext = file_path.suffix.lower()
    mapping = {
        ".mp4": "video/mp4",
        ".m4v": "video/mp4",
        ".mp3": "audio/mp3",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    if ext in mapping:
        return mapping[ext]
    guessed, _ = mimetypes.guess_type(str(file_path))
    return guessed or "application/octet-stream"


def backup_userdata_db(
    db_path: Path,
    backup_dir: Path | None = None,
    max_backups: int = 10,
) -> Path:
    """Creates a safe, consistent backup of userData.db using SQLite backup API and rotates older backups."""
    if not db_path.exists():
        raise FileNotFoundError(f"Arquivo de banco de dados não encontrado: {db_path}")

    if backup_dir is None:
        backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    backup_file = backup_dir / f"userData_backup_{timestamp}.db"

    # Use SQLite online backup API to ensure ACID consistency even if WAL is active
    source_con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=10.0)
    try:
        source_con.execute("PRAGMA busy_timeout = 10000;")
        dest_con = sqlite3.connect(backup_file.as_posix(), timeout=10.0)
        try:
            dest_con.execute("PRAGMA busy_timeout = 10000;")
            with dest_con:
                source_con.backup(dest_con)
        finally:
            dest_con.close()
    finally:
        source_con.close()

    # Rotation: keep at most max_backups
    backups = sorted(
        backup_dir.glob("userData_backup_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old_backup in backups[max_backups:]:
        try:
            old_backup.unlink()
        except OSError:
            pass

    return backup_file


def list_userdata_backups(
    backup_dir: Path | None = None,
    db_path: Path | None = None,
) -> list[dict]:
    """Lists existing backups with timestamp, file path, and size."""
    if backup_dir is None:
        if db_path is not None:
            backup_dir = db_path.parent / "backups"
        else:
            detected = detect_jwl_userdata_dir()
            backup_dir = (detected / "backups") if detected else None

    if not backup_dir or not backup_dir.is_dir():
        return []

    results = []
    for f in sorted(backup_dir.glob("userData_backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = f.stat()
        mtime = datetime.fromtimestamp(st.st_mtime, tz=UTC).strftime("%d/%m/%Y %H:%M:%S UTC")
        results.append({
            "path": f,
            "filename": f.name,
            "timestamp": mtime,
            "size_bytes": st.st_size,
        })
    return results


def restore_userdata_backup(backup_file: Path, target_db_path: Path) -> None:
    """Restores a backup into target userData.db, cleaning up any stale WAL/SHM files."""
    if not backup_file.is_file():
        raise FileNotFoundError(f"Arquivo de backup não encontrado: {backup_file}")

    target_db_path.parent.mkdir(parents=True, exist_ok=True)

    # Clean up wal and shm files of the target if present
    wal_file = target_db_path.parent / f"{target_db_path.name}-wal"
    shm_file = target_db_path.parent / f"{target_db_path.name}-shm"
    if wal_file.exists():
        try:
            wal_file.unlink()
        except OSError:
            pass
    if shm_file.exists():
        try:
            shm_file.unlink()
        except OSError:
            pass

    try:
        shutil.copy2(backup_file, target_db_path)
    except PermissionError as exc:
        raise PermissionError(
            f"O arquivo {target_db_path.name} está em uso. "
            "Feche o aplicativo JW Library antes de restaurar o backup."
        ) from exc


def init_jwl_schema(db_path: Path) -> None:
    """Initializes the full, official JW Library SQLite schema (version 16)

    including all 17 tables, triggers, and indexes. This ensures 100% compatibility
    when importing .jwlplaylist files into JW Library.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path.as_posix(), timeout=10.0)
    try:
        con.execute("PRAGMA busy_timeout = 10000;")
        cur = con.cursor()
        cur.executescript("""
            PRAGMA user_version = 16;

            CREATE TABLE IF NOT EXISTS BlockRange(
                BlockRangeId INTEGER NOT NULL PRIMARY KEY,
                BlockType INTEGER NOT NULL,
                Identifier INTEGER NOT NULL,
                StartToken INTEGER,
                EndToken INTEGER,
                UserMarkId INTEGER NOT NULL,
                CHECK (BlockType BETWEEN 1 AND 2),
                FOREIGN KEY(UserMarkId) REFERENCES UserMark(UserMarkId)
            );

            CREATE TABLE IF NOT EXISTS Bookmark(
                BookmarkId INTEGER NOT NULL PRIMARY KEY,
                LocationId INTEGER NOT NULL,
                PublicationLocationId INTEGER NOT NULL,
                Slot INTEGER NOT NULL,
                Title TEXT NOT NULL,
                Snippet TEXT,
                BlockType INTEGER NOT NULL DEFAULT 0,
                BlockIdentifier INTEGER,
                FOREIGN KEY(LocationId) REFERENCES Location(LocationId),
                FOREIGN KEY(PublicationLocationId) REFERENCES Location(LocationId),
                CONSTRAINT PublicationLocationId_Slot UNIQUE (PublicationLocationId, Slot),
                CHECK(
                    (BlockType = 0 AND BlockIdentifier IS NULL)
                    OR ((BlockType BETWEEN 1 AND 2) AND BlockIdentifier IS NOT NULL)
                )
            );

            CREATE TABLE IF NOT EXISTS IndependentMedia(
                IndependentMediaId INTEGER NOT NULL PRIMARY KEY,
                OriginalFilename TEXT NOT NULL,
                FilePath TEXT NOT NULL UNIQUE,
                MimeType TEXT NOT NULL,
                Hash TEXT NOT NULL,
                CHECK(length(OriginalFilename) > 0),
                CHECK(length(FilePath) > 0),
                CHECK(length(MimeType) > 0),
                CHECK(length(Hash) > 0)
            );

            CREATE TABLE IF NOT EXISTS InputField(
                LocationId INTEGER NOT NULL,
                TextTag TEXT NOT NULL,
                Value TEXT NOT NULL,
                FOREIGN KEY (LocationId) REFERENCES Location (LocationId),
                CONSTRAINT LocationId_TextTag PRIMARY KEY (LocationId, TextTag)
            );

            CREATE TABLE IF NOT EXISTS LastModified(
                LastModified TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS Location (
                LocationId INTEGER NOT NULL PRIMARY KEY,
                BookNumber INTEGER,
                ChapterNumber INTEGER,
                DocumentId INTEGER,
                Track INTEGER,
                IssueTagNumber INTEGER NOT NULL DEFAULT 0,
                KeySymbol TEXT,
                MepsLanguage INTEGER,
                Type INTEGER NOT NULL,
                Title TEXT,
                Specialty TEXT,
                Edition TEXT,
                UNIQUE(BookNumber, ChapterNumber, KeySymbol, MepsLanguage, Type),
                CHECK ((
                    Type = 0 AND (
                        (DocumentId IS NOT NULL AND DocumentId != 0)
                        OR (
                            Track IS NOT NULL AND (
                                (KeySymbol IS NOT NULL AND (length(KeySymbol) > 0))
                                OR (DocumentId IS NOT NULL AND DocumentId != 0)
                            )
                        )
                        OR (
                            BookNumber IS NOT NULL AND BookNumber != 0
                            AND KeySymbol IS NOT NULL AND (length(KeySymbol) > 0)
                            AND (ChapterNumber IS NULL OR ChapterNumber = 0)
                        )
                        OR (
                            ChapterNumber IS NOT NULL AND ChapterNumber != 0
                            AND BookNumber IS NOT NULL AND BookNumber != 0
                            AND KeySymbol IS NOT NULL AND (length(KeySymbol) > 0)
                        )
                    )
                ) OR Type != 0),
                CHECK((
                    Type = 1
                    AND (BookNumber IS NULL OR BookNumber = 0)
                    AND (ChapterNumber IS NULL OR ChapterNumber = 0)
                    AND (DocumentId IS NULL OR DocumentId = 0)
                    AND KeySymbol IS NOT NULL AND (length(KeySymbol) > 0)
                    AND Track IS NULL
                ) OR Type != 1),
                CHECK((
                    Type IN (2, 3)
                    AND (BookNumber IS NULL OR BookNumber = 0)
                    AND (ChapterNumber IS NULL OR ChapterNumber = 0)
                ) OR Type NOT IN (2, 3))
            );

            CREATE TABLE IF NOT EXISTS Note(
                NoteId INTEGER NOT NULL PRIMARY KEY,
                Guid TEXT NOT NULL UNIQUE,
                UserMarkId INTEGER,
                LocationId INTEGER,
                Title TEXT,
                Content TEXT,
                LastModified TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                Created TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                BlockType INTEGER NOT NULL DEFAULT 0,
                BlockIdentifier INTEGER,
                CHECK(
                    (BlockType = 0 AND BlockIdentifier IS NULL)
                    OR ((BlockType BETWEEN 1 AND 2) AND BlockIdentifier IS NOT NULL)
                ),
                FOREIGN KEY(UserMarkId) REFERENCES UserMark(UserMarkId),
                FOREIGN KEY(LocationId) REFERENCES Location(LocationId)
            );

            CREATE TABLE IF NOT EXISTS PlaylistItemAccuracy(
                PlaylistItemAccuracyId INTEGER NOT NULL PRIMARY KEY,
                Description TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS PlaylistItem(
                PlaylistItemId INTEGER NOT NULL PRIMARY KEY,
                Label TEXT NOT NULL,
                StartTrimOffsetTicks INTEGER,
                EndTrimOffsetTicks INTEGER,
                Accuracy INTEGER NOT NULL,
                EndAction INTEGER NOT NULL,
                ThumbnailFilePath TEXT,
                FOREIGN KEY(Accuracy) REFERENCES PlaylistItemAccuracy(PlaylistItemAccuracyId),
                FOREIGN KEY(ThumbnailFilePath) REFERENCES IndependentMedia(FilePath),
                CHECK(length(Label) > 0),
                CHECK(EndAction IN(0, 1, 2, 3))
            );

            CREATE TABLE IF NOT EXISTS PlaylistItemIndependentMediaMap(
                PlaylistItemId INTEGER NOT NULL,
                IndependentMediaId INTEGER NOT NULL,
                DurationTicks INTEGER NOT NULL,
                PRIMARY KEY(PlaylistItemId, IndependentMediaId),
                FOREIGN KEY(PlaylistItemId) REFERENCES PlaylistItem(PlaylistItemId),
                FOREIGN KEY(IndependentMediaId) REFERENCES IndependentMedia(IndependentMediaId)
            ) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS PlaylistItemLocationMap(
                PlaylistItemId INTEGER NOT NULL,
                LocationId INTEGER NOT NULL,
                MajorMultimediaType INTEGER NOT NULL,
                BaseDurationTicks INTEGER,
                PRIMARY KEY(PlaylistItemId, LocationId),
                FOREIGN KEY(PlaylistItemId) REFERENCES PlaylistItem(PlaylistItemId),
                FOREIGN KEY(LocationId) REFERENCES Location(LocationId)
            ) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS PlaylistItemMarker(
                PlaylistItemMarkerId INTEGER NOT NULL PRIMARY KEY,
                PlaylistItemId INTEGER NOT NULL,
                Label TEXT NOT NULL,
                StartTimeTicks INTEGER NOT NULL,
                DurationTicks INTEGER NOT NULL,
                EndTransitionDurationTicks INTEGER NOT NULL,
                UNIQUE(PlaylistItemId, StartTimeTicks),
                FOREIGN KEY(PlaylistItemId) REFERENCES PlaylistItem(PlaylistItemId)
            );

            CREATE TABLE IF NOT EXISTS PlaylistItemMarkerBibleVerseMap(
                PlaylistItemMarkerId INTEGER NOT NULL,
                VerseId INTEGER NOT NULL,
                PRIMARY KEY(PlaylistItemMarkerId, VerseId),
                FOREIGN KEY(PlaylistItemMarkerId) REFERENCES PlaylistItemMarker(PlaylistItemMarkerId)
            ) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS PlaylistItemMarkerParagraphMap(
                PlaylistItemMarkerId INTEGER NOT NULL,
                MepsDocumentId INTEGER NOT NULL,
                ParagraphIndex INTEGER NOT NULL,
                MarkerIndexWithinParagraph INTEGER NOT NULL,
                PRIMARY KEY(PlaylistItemMarkerId, MepsDocumentId, ParagraphIndex, MarkerIndexWithinParagraph),
                FOREIGN KEY(PlaylistItemMarkerId) REFERENCES PlaylistItemMarker(PlaylistItemMarkerId)
            ) WITHOUT ROWID;

            CREATE TABLE IF NOT EXISTS Tag(
                TagId INTEGER NOT NULL PRIMARY KEY,
                Type INTEGER NOT NULL,
                Name TEXT NOT NULL,
                UNIQUE(Type, Name),
                CHECK(length(Name) > 0),
                CHECK(Type IN (0, 1, 2))
            );

            CREATE TABLE IF NOT EXISTS TagMap(
                TagMapId INTEGER NOT NULL PRIMARY KEY,
                PlaylistItemId INTEGER,
                LocationId INTEGER,
                NoteId INTEGER,
                TagId INTEGER NOT NULL,
                Position INTEGER NOT NULL,
                FOREIGN KEY(TagId) REFERENCES Tag(TagId),
                FOREIGN KEY(PlaylistItemId) REFERENCES PlaylistItem(PlaylistItemId),
                FOREIGN KEY(LocationId) REFERENCES Location(LocationId),
                FOREIGN KEY(NoteId) REFERENCES Note(NoteId),
                CONSTRAINT TagId_Position UNIQUE(TagId, Position),
                CONSTRAINT TagId_NoteId UNIQUE(TagId, NoteId),
                CONSTRAINT TagId_LocationId UNIQUE(TagId, LocationId),
                CONSTRAINT TagId_PlaylistItemId UNIQUE(TagId, PlaylistItemId),
                CHECK(
                    (NoteId IS NULL AND LocationId IS NULL AND PlaylistItemId IS NOT NULL) OR
                    (LocationId IS NULL AND PlaylistItemId IS NULL AND NoteId IS NOT NULL) OR
                    (PlaylistItemId IS NULL AND NoteId IS NULL AND LocationId IS NOT NULL)
                )
            );

            CREATE TABLE IF NOT EXISTS UserMark(
                UserMarkId INTEGER NOT NULL PRIMARY KEY,
                ColorIndex INTEGER NOT NULL,
                LocationId INTEGER NOT NULL,
                StyleIndex INTEGER NOT NULL,
                UserMarkGuid TEXT NOT NULL UNIQUE,
                Version INTEGER NOT NULL,
                FOREIGN KEY(LocationId) REFERENCES Location(LocationId)
            );

            INSERT OR IGNORE INTO PlaylistItemAccuracy VALUES (1, 'Accurate'), (2, 'NeedsUserVerification');
        """)

        # Seed initial LastModified row BEFORE insert triggers are created
        cur.execute("SELECT count(*) FROM LastModified")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO LastModified VALUES (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))")

        # Create Indexes and Triggers
        cur.executescript("""
            CREATE INDEX IF NOT EXISTS IX_BlockRange_UserMarkId
                ON BlockRange(UserMarkId);
            CREATE INDEX IF NOT EXISTS IX_Location_KeySymbol_MepsLanguage_BookNumber_ChapterNumber
                ON Location(KeySymbol, MepsLanguage, BookNumber, ChapterNumber);
            CREATE INDEX IF NOT EXISTS IX_Location_MepsLanguage_DocumentId
                ON Location(MepsLanguage, DocumentId);
            CREATE INDEX IF NOT EXISTS IX_Note_LastModified_LocationId
                ON Note(LastModified, LocationId);
            CREATE INDEX IF NOT EXISTS IX_Note_LocationId_BlockIdentifier
                ON Note(LocationId, BlockIdentifier);
            CREATE INDEX IF NOT EXISTS IX_PlaylistItemIndependentMediaMap_IndependentMediaId
                ON PlaylistItemIndependentMediaMap(IndependentMediaId);
            CREATE INDEX IF NOT EXISTS IX_PlaylistItemLocationMap_LocationId
                ON PlaylistItemLocationMap(LocationId);
            CREATE INDEX IF NOT EXISTS IX_PlaylistItem_ThumbnailFilePath
                ON PlaylistItem(ThumbnailFilePath);
            CREATE INDEX IF NOT EXISTS IX_TagMap_LocationId_TagId_Position
                ON TagMap(LocationId, TagId, Position);
            CREATE INDEX IF NOT EXISTS IX_TagMap_NoteId_TagId_Position
                ON TagMap(NoteId, TagId, Position);
            CREATE INDEX IF NOT EXISTS IX_TagMap_PlaylistItemId_TagId_Position
                ON TagMap(PlaylistItemId, TagId, Position);
            CREATE INDEX IF NOT EXISTS IX_TagMap_TagId
                ON TagMap(TagId);
            CREATE INDEX IF NOT EXISTS IX_Tag_Name_Type_TagId
                ON Tag(Name, Type, TagId);
            CREATE INDEX IF NOT EXISTS IX_UserMark_LocationId
                ON UserMark(LocationId);

            CREATE TRIGGER IF NOT EXISTS TR_Raise_Error_Before_Delete_LastModified
            BEFORE DELETE ON LastModified BEGIN
                SELECT RAISE (FAIL, 'DELETE FROM LastModified not allowed');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Raise_Error_Before_Insert_LastModified
            BEFORE INSERT ON LastModified BEGIN
                SELECT RAISE (FAIL, 'INSERT INTO LastModified not allowed');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Delete_BlockRange
            DELETE ON BlockRange BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Delete_Bookmark
            DELETE ON Bookmark BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Delete_IndependentMedia
            DELETE ON IndependentMedia BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Delete_InputField
            DELETE ON InputField BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Delete_Note
            DELETE ON Note BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Delete_PlaylistItem
            DELETE ON PlaylistItem BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Delete_Tag
            DELETE ON Tag BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Delete_TagMap
            DELETE ON TagMap BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Delete_UserMark
            DELETE ON UserMark BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Insert_BlockRange
            INSERT ON BlockRange BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Insert_Bookmark
            INSERT ON Bookmark BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Insert_IndependentMedia
            INSERT ON IndependentMedia BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Insert_InputField
            INSERT ON InputField BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Insert_Note
            INSERT ON Note BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Insert_PlaylistItem
            INSERT ON PlaylistItem BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Insert_Tag
            INSERT ON Tag BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Insert_TagMap
            INSERT ON TagMap BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Insert_UserMark
            INSERT ON UserMark BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Update_BlockRange
            UPDATE ON BlockRange BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Update_Bookmark
            UPDATE ON Bookmark BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Update_IndependentMedia
            UPDATE ON IndependentMedia BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Update_InputField
            UPDATE ON InputField BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Update_Note
            UPDATE ON Note BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Update_PlaylistItem
            UPDATE ON PlaylistItem BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Update_Tag
            UPDATE ON Tag BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Update_TagMap
            UPDATE ON TagMap BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;

            CREATE TRIGGER IF NOT EXISTS TR_Update_LastModified_Update_UserMark
            UPDATE ON UserMark BEGIN
                UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');
            END;
        """)
        con.commit()
    finally:
        con.close()



def import_media_to_jwl(
    items: list[MediaImportItem],
    playlist_name: str,
    db_path: Path | None = None,
    backup: bool = True,
    skip_duplicates: bool = True,
    clear_existing: bool = False,
    auto_thumbnails: bool = False,
) -> MediaImportResult:
    """Imports media files directly into JW Library's Userdata folder and SQLite schema."""
    if not items:
        return MediaImportResult(success=False, error_message="Nenhum arquivo fornecido para importação.")

    resolved_db = db_path or detect_jwl_userdata_db()
    if not resolved_db or not resolved_db.exists():
        return MediaImportResult(
            success=False,
            error_message="Banco de dados do JW Library (userData.db) não encontrado.",
        )

    userdata_dir = resolved_db.parent
    backup_file: Path | None = None
    if backup:
        try:
            backup_file = backup_userdata_db(resolved_db)
        except Exception as exc:
            return MediaImportResult(
                success=False,
                error_message=f"Falha ao realizar backup de segurança antes da importação: {exc}",
            )

    imported_names: list[str] = []
    synced_count = 0
    con = sqlite3.connect(resolved_db.as_posix(), timeout=10.0)
    try:
        con.execute("PRAGMA busy_timeout = 10000;")
        cur = con.cursor()
        cur.execute("BEGIN IMMEDIATE")

        # 1. Resolve or create Tag for playlist (Type 2 = Playlist)
        cur.execute("SELECT TagId FROM Tag WHERE Type = 2 AND Name = ?", (playlist_name,))
        row = cur.fetchone()
        if row:
            tag_id = row[0]
        else:
            cur.execute("INSERT INTO Tag (Type, Name) VALUES (2, ?)", (playlist_name,))
            tag_id = cur.lastrowid

        if clear_existing:
            cur.execute(
                "SELECT PlaylistItemId FROM TagMap WHERE TagId = ? AND PlaylistItemId IS NOT NULL",
                (tag_id,),
            )
            old_item_ids = [r[0] for r in cur.fetchall()]
            cur.execute("DELETE FROM TagMap WHERE TagId = ?", (tag_id,))
            for p_id in old_item_ids:
                cur.execute("SELECT count(*) FROM TagMap WHERE PlaylistItemId = ?", (p_id,))
                if cur.fetchone()[0] == 0:
                    try:
                        cur.execute(
                            "DELETE FROM PlaylistItemMarkerBibleVerseMap WHERE PlaylistItemMarkerId IN "
                            "(SELECT PlaylistItemMarkerId FROM PlaylistItemMarker WHERE PlaylistItemId = ?)",
                            (p_id,),
                        )
                        cur.execute(
                            "DELETE FROM PlaylistItemMarkerParagraphMap WHERE PlaylistItemMarkerId IN "
                            "(SELECT PlaylistItemMarkerId FROM PlaylistItemMarker WHERE PlaylistItemId = ?)",
                            (p_id,),
                        )
                        cur.execute("DELETE FROM PlaylistItemMarker WHERE PlaylistItemId = ?", (p_id,))
                    except sqlite3.OperationalError:
                        pass
                    cur.execute("DELETE FROM PlaylistItemLocationMap WHERE PlaylistItemId = ?", (p_id,))
                    cur.execute(
                        "DELETE FROM PlaylistItemIndependentMediaMap WHERE PlaylistItemId = ?",
                        (p_id,),
                    )
                    cur.execute("DELETE FROM PlaylistItem WHERE PlaylistItemId = ?", (p_id,))
            cur_pos = 0
            skip_duplicates = False
        else:
            # 2. Get current maximum position in playlist
            cur.execute("SELECT COALESCE(MAX(Position), -1) FROM TagMap WHERE TagId = ?", (tag_id,))
            cur_pos = cur.fetchone()[0] + 1

        def _register_thumb_bytes(
            tb_bytes: bytes, orig_name: str, tb_mime: str, ext: str = ""
        ) -> str:
            tb_hash = calculate_jwl_hash(tb_bytes)
            cur.execute(
                "SELECT FilePath FROM IndependentMedia WHERE Hash = ?",
                (tb_hash,),
            )
            tb_existing = cur.fetchone()
            if tb_existing:
                dest_fn = tb_existing[0]
                dest_file = userdata_dir / dest_fn
                if not dest_file.is_file():
                    dest_file.write_bytes(tb_bytes)
                return dest_fn
            # JW Library official packages name thumbnails with pure lowercase UUID without extension
            dest_fn = f"{uuid.uuid4()}{ext}" if ext else str(uuid.uuid4()).lower()
            dest_file = userdata_dir / dest_fn
            dest_file.write_bytes(tb_bytes)
            # In official JW Library, OriginalFilename for thumbnails is also an extensionless UUID
            thumb_orig_name = (
                orig_name
                if orig_name and not orig_name.endswith(".png")
                else str(uuid.uuid4()).lower()
            )
            cur.execute(
                """
                INSERT INTO IndependentMedia (OriginalFilename, FilePath, MimeType, Hash)
                VALUES (?, ?, ?, ?)
                """,
                (thumb_orig_name, dest_fn, tb_mime, tb_hash),
            )
            return dest_fn

        def _get_or_create_thumb(item: MediaImportItem) -> str | None:
            # 1. Explicit thumbnail_path is always honored
            if item.thumbnail_path and item.thumbnail_path.is_file():
                try:
                    tb_bytes = item.thumbnail_path.read_bytes()
                    return _register_thumb_bytes(
                        tb_bytes,
                        str(uuid.uuid4()).lower(),
                        detect_mime_type(item.thumbnail_path) or "image/jpeg",
                        ext="",
                    )
                except Exception:
                    pass

            # 2. Only auto-generate synthetic thumbnails if requested (e.g. for package export)
            if not auto_thumbnails:
                return None

            src = item.source_path
            if src and src.is_file():
                ext = src.suffix.lower()
                if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"):
                    try:
                        from PySide6.QtCore import QBuffer, QIODevice, Qt
                        from PySide6.QtGui import QImage

                        qimg = QImage(str(src))
                        if not qimg.isNull():
                            scaled = qimg.scaled(
                                160,
                                90,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                            buf = QBuffer()
                            buf.open(QIODevice.OpenModeFlag.WriteOnly)
                            scaled.save(buf, "JPEG", 85)
                            tb_bytes = bytes(buf.data())
                            if tb_bytes:
                                return _register_thumb_bytes(
                                    tb_bytes, str(uuid.uuid4()).lower(), "image/jpeg", ext=""
                                )
                    except Exception:
                        pass
                elif ext in (".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".mp3", ".m4a"):
                    try:
                        from PySide6.QtCore import QBuffer, QIODevice

                        from meeting_assistant.ui.media_thumbnail_helper import render_media_thumbnail

                        pix = render_media_thumbnail(item, width=160, height=90)
                        if pix and not pix.isNull():
                            buf = QBuffer()
                            buf.open(QIODevice.OpenModeFlag.WriteOnly)
                            pix.save(buf, "JPEG", 85)
                            tb_bytes = bytes(buf.data())
                            if tb_bytes:
                                return _register_thumb_bytes(
                                    tb_bytes, str(uuid.uuid4()).lower(), "image/jpeg", ext=""
                                )
                    except Exception:
                        pass

            try:
                return _register_thumb_bytes(
                    DEFAULT_THUMBNAIL_BYTES, str(uuid.uuid4()).lower(), "image/png", ext=""
                )
            except Exception:
                return None

        def _register_thumb(thumb_path: Path | None) -> str | None:
            if not thumb_path or not thumb_path.is_file():
                return None
            try:
                tb_bytes = thumb_path.read_bytes()
                return _register_thumb_bytes(
                    tb_bytes, thumb_path.name, detect_mime_type(thumb_path) or "image/jpeg"
                )
            except Exception:
                return None


        for item in items:
            source = item.source_path
            is_location_item = bool(
                item.key_symbol and (
                    (item.track is not None and item.track > 0)
                    or (item.document_id and item.document_id > 0)
                    or item.track == 0
                )
            )
            if not is_location_item and (not source or not source.is_file()):
                continue

            if item.key_symbol and (
                (item.track is not None and item.track > 0)
                or (item.document_id and item.document_id > 0)
                or item.track == 0
            ):
                tag_8 = (
                    item.issue_tag_number * 100
                    if (0 < item.issue_tag_number < 1_000_000)
                    else item.issue_tag_number
                )
                tag_6 = (
                    item.issue_tag_number
                    if (0 < item.issue_tag_number < 1_000_000)
                    else (item.issue_tag_number // 100 if item.issue_tag_number > 0 else 0)
                )
                # Official publication media linked via Location and PlaylistItemLocationMap
                if item.track is not None and item.track > 0:
                    cur.execute(
                        """
                        SELECT LocationId FROM Location
                        WHERE KeySymbol = ? AND Track = ? AND MepsLanguage = ?
                          AND (IssueTagNumber IN (?, ?) OR IssueTagNumber = 0 OR ? = 0)
                          AND Type = 3
                        """,
                        (
                            item.key_symbol,
                            item.track,
                            item.meps_language_index,
                            tag_8,
                            tag_6,
                            item.issue_tag_number,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        SELECT LocationId FROM Location
                        WHERE KeySymbol = ? AND (DocumentId = ? OR ? = 0) AND MepsLanguage = ?
                          AND (IssueTagNumber IN (?, ?) OR IssueTagNumber = 0 OR ? = 0)
                          AND Type = 3
                        """,
                        (
                            item.key_symbol,
                            item.document_id,
                            item.document_id,
                            item.meps_language_index,
                            tag_8,
                            tag_6,
                            item.issue_tag_number,
                        ),
                    )
                loc_row = cur.fetchone()
                if loc_row:
                    location_id = loc_row[0]
                else:
                    insert_tag = item.issue_tag_number
                    if insert_tag >= 1_000_000 and insert_tag % 100 == 0:
                        if item.key_symbol.startswith("jwb") or item.key_symbol in ("jwbai", "jwbcov"):
                            insert_tag = insert_tag // 100
                    loc_track = item.track if (item.track is not None and item.track > 0) else None
                    loc_doc = item.document_id if (item.document_id and item.document_id > 0) else None
                    cur.execute(
                        """
                        INSERT INTO Location (
                            BookNumber, ChapterNumber, DocumentId, Track,
                            IssueTagNumber, KeySymbol, MepsLanguage, Type, Title
                        )
                        VALUES (?, NULL, ?, ?, ?, ?, ?, 3, ?)
                        """,
                        (
                            item.book_number,
                            loc_doc,
                            loc_track,
                            insert_tag,
                            item.key_symbol,
                            item.meps_language_index,
                            item.label,
                        ),
                    )
                    location_id = cur.lastrowid

                # Deduplication: check if already in this playlist
                if skip_duplicates:
                    cur.execute(
                        """
                        SELECT tm.TagMapId, plm.PlaylistItemId FROM TagMap tm
                        JOIN PlaylistItemLocationMap plm ON tm.PlaylistItemId = plm.PlaylistItemId
                        WHERE tm.TagId = ? AND plm.LocationId = ?
                        """,
                        (tag_id, location_id),
                    )
                    exist_row = cur.fetchone()
                    if exist_row is not None:
                        t_fn = _get_or_create_thumb(item)
                        cur.execute(
                            """
                            UPDATE PlaylistItem
                            SET EndAction = ?, Label = ?,
                                ThumbnailFilePath = COALESCE(?, ThumbnailFilePath)
                            WHERE PlaylistItemId = ?
                            """,
                            (item.end_action, item.label, t_fn, exist_row[1]),
                        )
                        synced_count += 1
                        continue

                # Create PlaylistItem
                t_fn = _get_or_create_thumb(item)
                cur.execute(
                    """
                    INSERT INTO PlaylistItem (
                        Label, StartTrimOffsetTicks, EndTrimOffsetTicks,
                        Accuracy, EndAction, ThumbnailFilePath
                    )
                    VALUES (?, NULL, NULL, 1, ?, ?)
                    """,
                    (item.label, item.end_action, t_fn),
                )
                playlist_item_id = cur.lastrowid

                # MajorMultimediaType: 2 for Video, 1 for Audio
                mime = item.mime_type or detect_mime_type(source)
                major_type = 1 if mime.startswith("audio/") else 2
                duration_ticks = (
                    int(item.duration_seconds * 10_000_000) if item.duration_seconds > 0 else 0
                )

                cur.execute(
                    """
                    INSERT INTO PlaylistItemLocationMap (
                        PlaylistItemId, LocationId, MajorMultimediaType, BaseDurationTicks
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (playlist_item_id, location_id, major_type, duration_ticks),
                )

                # Map to TagMap
                cur.execute(
                    """
                    INSERT INTO TagMap (PlaylistItemId, LocationId, NoteId, TagId, Position)
                    VALUES (?, NULL, NULL, ?, ?)
                    """,
                    (playlist_item_id, tag_id, cur_pos),
                )
                cur_pos += 1
                imported_names.append(item.label)
                continue

            file_bytes = source.read_bytes()
            media_hash = calculate_jwl_hash(file_bytes)
            mime = item.mime_type or detect_mime_type(source)

            # Check if this exact file hash already exists in IndependentMedia
            cur.execute(
                "SELECT IndependentMediaId, FilePath FROM IndependentMedia WHERE Hash = ?",
                (media_hash,),
            )
            existing = cur.fetchone()
            if existing:
                ind_id = existing[0]
                dest_filename = existing[1]
                dest_path = userdata_dir / dest_filename
                # Restore physical file if it was removed or missing on disk
                if not dest_path.is_file():
                    dest_path.write_bytes(file_bytes)
            else:
                # Generate unique storage filename in Userdata (lowercase UUID per JW Library format)
                ext = source.suffix.lower()
                dest_filename = f"{uuid.uuid4()}{ext}"
                dest_path = userdata_dir / dest_filename
                dest_path.write_bytes(file_bytes)

                cur.execute(
                    """
                    INSERT INTO IndependentMedia (OriginalFilename, FilePath, MimeType, Hash)
                    VALUES (?, ?, ?, ?)
                    """,
                    (source.name, dest_filename, mime, media_hash),
                )
                ind_id = cur.lastrowid

            # Deduplication: check if this media is already in this playlist
            if skip_duplicates:
                cur.execute(
                    """
                    SELECT tm.TagMapId, pim.PlaylistItemId FROM TagMap tm
                    JOIN PlaylistItemIndependentMediaMap pim ON tm.PlaylistItemId = pim.PlaylistItemId
                    WHERE tm.TagId = ? AND pim.IndependentMediaId = ?
                    """,
                    (tag_id, ind_id),
                )
                exist_row = cur.fetchone()
                if exist_row is not None:
                    # Item already in this playlist, update EndAction, label, and thumbnail
                    t_fn = _get_or_create_thumb(item)
                    cur.execute(
                        """
                        UPDATE PlaylistItem
                        SET EndAction = ?, Label = ?,
                            ThumbnailFilePath = COALESCE(?, ThumbnailFilePath)
                        WHERE PlaylistItemId = ?
                        """,
                        (item.end_action, item.label, t_fn, exist_row[1]),
                    )
                    synced_count += 1
                    continue

            # 3. Create PlaylistItem
            t_fn = _get_or_create_thumb(item)
            cur.execute(
                """
                INSERT INTO PlaylistItem (
                    Label, StartTrimOffsetTicks, EndTrimOffsetTicks, Accuracy, EndAction, ThumbnailFilePath
                )
                VALUES (?, NULL, NULL, 1, ?, ?)
                """,
                (item.label, item.end_action, t_fn),
            )
            playlist_item_id = cur.lastrowid

            # 4. Map media to playlist item
            # 1 second = 10,000,000 ticks. Default for image is 40,000,000 (4 seconds).
            if item.duration_seconds > 0:
                duration_ticks = int(item.duration_seconds * 10_000_000)
            elif mime.startswith("image/"):
                duration_ticks = 40_000_000
            else:
                duration_ticks = 0

            cur.execute(
                """
                INSERT INTO PlaylistItemIndependentMediaMap (
                    PlaylistItemId, IndependentMediaId, DurationTicks
                )
                VALUES (?, ?, ?)
                """,
                (playlist_item_id, ind_id, duration_ticks),
            )

            # 5. Map to TagMap
            cur.execute(
                """
                INSERT INTO TagMap (PlaylistItemId, LocationId, NoteId, TagId, Position)
                VALUES (?, NULL, NULL, ?, ?)
                """,
                (playlist_item_id, tag_id, cur_pos),
            )
            cur_pos += 1
            imported_names.append(item.label)

        # 6. Update LastModified
        cur.execute("UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')")
        if cur.rowcount == 0:
            try:
                cur.execute("INSERT INTO LastModified VALUES (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))")
            except sqlite3.Error:
                pass
        con.commit()

        # TRUNCATE WAL checkpoint to flush all committed data directly to userData.db file
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except sqlite3.Error:
            try:
                con.execute("PRAGMA wal_checkpoint(PASSIVE);")
            except sqlite3.Error:
                pass

        return MediaImportResult(
            success=True,
            imported_count=len(imported_names),
            synchronized_count=synced_count,
            playlist_name=playlist_name,
            backup_path=backup_file,
            imported_items=imported_names,
        )
    except Exception as exc:
        try:
            con.rollback()
        except Exception:
            pass
        return MediaImportResult(
            success=False,
            error_message=f"Erro ao importar mídias para o JW Library: {exc}",
            backup_path=backup_file,
        )
    finally:
        con.close()


def cleanup_jwl_storage(
    keep_weeks: int = 2,
    db_path: Path | None = None,
    remove_old_videos: bool = True,
    remove_orphan_userdata: bool = True,
) -> tuple[list[str], int, list[str]]:
    """Cleans up expired meeting videos and orphaned IndependentMedia files in JW Library.

    Args:
        keep_weeks: Number of weeks of meeting media to retain. Media older than
            this threshold will be purged.
        db_path: Optional path to userData.db.
        remove_old_videos: If True, purges weekly meeting videos (mwbv_..., w_...)
            older than keep_weeks from Videos\\JWLibrary.
        remove_orphan_userdata: If True, purges unreferenced IndependentMedia files
            and their records from userData.db.

    Returns:
        (deleted_files_list, total_bytes_freed, error_list)
    """
    import datetime

    deleted_files: list[str] = []
    total_bytes_freed = 0
    errors: list[str] = []

    resolved_db = db_path or detect_jwl_userdata_db()
    userdata_dir = resolved_db.parent if (resolved_db and resolved_db.exists()) else None

    # 1. Clean orphaned IndependentMedia in Userdata
    if remove_orphan_userdata and resolved_db and resolved_db.is_file() and userdata_dir:
        try:
            con = sqlite3.connect(resolved_db.as_posix(), timeout=10.0)
            try:
                con.execute("PRAGMA busy_timeout = 10000;")
                cur = con.cursor()
                cur.execute("BEGIN IMMEDIATE")

                # Find IndependentMediaId not referenced by any playlist item or thumbnail
                query = """
                    SELECT IndependentMediaId, FilePath FROM IndependentMedia
                    WHERE IndependentMediaId NOT IN (
                        SELECT DISTINCT IndependentMediaId FROM PlaylistItemIndependentMediaMap
                        WHERE IndependentMediaId IS NOT NULL
                    )
                    AND FilePath NOT IN (
                        SELECT DISTINCT ThumbnailFilePath FROM PlaylistItem
                        WHERE ThumbnailFilePath IS NOT NULL
                    )
                """
                cur.execute(query)
                orphan_rows = cur.fetchall()

                for ind_id, file_path_str in orphan_rows:
                    if file_path_str:
                        disk_file = userdata_dir / file_path_str
                        if disk_file.is_file():
                            try:
                                sz = disk_file.stat().st_size
                                disk_file.unlink()
                                total_bytes_freed += sz
                                deleted_files.append(f"Userdata/{file_path_str}")
                            except OSError as exc:
                                errors.append(f"Falha ao apagar arquivo {file_path_str}: {exc}")

                        cur.execute("DELETE FROM IndependentMedia WHERE IndependentMediaId = ?", (ind_id,))

                if orphan_rows:
                    cur.execute(
                        "UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
                    )
                    con.commit()
                    try:
                        con.execute("PRAGMA wal_checkpoint(PASSIVE);")
                    except sqlite3.Error:
                        pass
                else:
                    con.rollback()
            finally:
                con.close()
        except Exception as exc:
            errors.append(f"Erro ao limpar IndependentMedia no userData.db: {exc}")

    # 2. Clean old meeting videos from Videos\\JWLibrary
    if remove_old_videos:
        import re

        jwl_videos_dir = detect_jwl_videos_dir()
        if jwl_videos_dir and jwl_videos_dir.is_dir():
            cutoff_date = datetime.date.today() - datetime.timedelta(days=max(0, keep_weeks) * 7)
            cutoff_ts = datetime.datetime.combine(cutoff_date, datetime.time.min).timestamp()

            # Find active custom playlist video tags to protect them
            protected_media_identifiers: set[str] = set()
            if resolved_db and resolved_db.is_file():
                try:
                    pcon = sqlite3.connect(resolved_db.as_posix(), timeout=5.0)
                    try:
                        pcur = pcon.cursor()
                        # Any media linked to custom tags (not standard meetings)
                        pcur.execute("""
                            SELECT l.KeySymbol, l.Track, l.IssueTagNumber
                            FROM Location l
                            JOIN PlaylistItemLocationMap plm ON l.LocationId = plm.LocationId
                            JOIN TagMap tm ON plm.PlaylistItemId = tm.PlaylistItemId
                            JOIN Tag t ON tm.TagId = t.TagId
                            WHERE t.Name NOT IN (
                                'Reunião de Meio de Semana',
                                'Estudo de A Sentinela',
                                'Cânticos da Reunião'
                            )
                        """)
                        for sym, trk, iss in pcur.fetchall():
                            if sym:
                                protected_media_identifiers.add(f"{sym.lower()}_{trk}_{iss}")
                    finally:
                        pcon.close()
                except Exception:
                    pass

            # Inspect files in Videos\\JWLibrary
            try:
                for video_path in list(jwl_videos_dir.iterdir()):
                    if not video_path.is_file():
                        continue
                    v_name = video_path.name.lower()
                    # Only target weekly meeting workbook videos or watchtower study videos
                    is_meeting_video = v_name.startswith("mwbv_") or (
                        v_name.startswith("w_") and not v_name.endswith(".jwpub")
                    )
                    # NEVER delete songs (sjjm/sjj)
                    if not is_meeting_video or "sjj" in v_name:
                        continue

                    # Check modification date
                    try:
                        mtime = video_path.stat().st_mtime
                    except OSError:
                        continue

                    # Extract issue tag if present in name (e.g. mwbv_t_202611_01 or w_t_202610)
                    issue_tag_match = re.search(r"(\d{6,8})", v_name)
                    issue_tag_int = int(issue_tag_match.group(1)) if issue_tag_match else 0

                    # Check if protected by active custom playlist
                    is_protected = False
                    for prot in protected_media_identifiers:
                        if prot in v_name:
                            is_protected = True
                            break

                    if is_protected:
                        continue

                    # Calculate publication issue expiration date
                    is_expired = False
                    if issue_tag_int > 0:
                        tag6 = issue_tag_int // 100 if issue_tag_int >= 1_000_000 else issue_tag_int
                        if 200000 <= tag6 <= 210012:
                            y = tag6 // 100
                            m = tag6 % 100
                            if 1 <= m <= 12:
                                # mwb is bimonthly (covers m and m+1)
                                if v_name.startswith("mwb"):
                                    exp_m = m + 1
                                    exp_y = y
                                    if exp_m > 12:
                                        exp_m = 1
                                        exp_y += 1
                                else:
                                    exp_m = m
                                    exp_y = y
                                if exp_m in (1, 3, 5, 7, 8, 10, 12):
                                    last_d = 31
                                elif exp_m in (4, 6, 9, 11):
                                    last_d = 30
                                else:
                                    is_leap = exp_y % 4 == 0 and (exp_y % 100 != 0 or exp_y % 400 == 0)
                                    last_d = 29 if is_leap else 28
                                exp_date = datetime.date(exp_y, exp_m, last_d)
                                # Issue is strictly expired if its validity period ended before cutoff_date
                                is_expired = exp_date < cutoff_date
                    else:
                        is_expired = mtime < cutoff_ts

                    if is_expired:
                        try:
                            sz = video_path.stat().st_size
                            video_path.unlink()
                            total_bytes_freed += sz
                            deleted_files.append(f"Videos/{video_path.name}")

                            # Clean up from mediaCollection.db if present
                            col_db = detect_jwl_media_collection_db()
                            if col_db and col_db.is_file():
                                try:
                                    mcon = sqlite3.connect(col_db.as_posix(), timeout=5.0)
                                    try:
                                        mcon.execute("PRAGMA busy_timeout = 5000;")
                                        mcon.execute(
                                            "DELETE FROM Video WHERE FilePath = ? OR FilePath = ?",
                                            (str(video_path), video_path.as_posix()),
                                        )
                                        mcon.execute(
                                            "DELETE FROM MediaKey WHERE MediaKeyId NOT IN "
                                            "(SELECT MediaKeyId FROM Video UNION "
                                            "SELECT MediaKeyId FROM Audio)"
                                        )
                                        mcon.commit()
                                    finally:
                                        mcon.close()
                                except Exception:
                                    pass
                        except OSError as exc:
                            errors.append(f"Falha ao apagar vídeo {video_path.name}: {exc}")
            except Exception as exc:
                errors.append(f"Erro ao listar pasta de vídeos do JW Library: {exc}")

    return deleted_files, total_bytes_freed, errors


def discover_jwl_progid() -> str:
    """Discovers the dynamic Windows AppX ProgID for JW Library, with fallback to official ID."""
    if os.name != "nt":
        return "AppXf9xsn2hpxwq9w3jf8tg0qmszyzky91z7"
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "") as root:
            idx = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, idx)
                    idx += 1
                    if sub.startswith("AppX"):
                        try:
                            with winreg.OpenKey(root, rf"{sub}\Application") as app_k:
                                app_name, _ = winreg.QueryValueEx(app_k, "ApplicationName")
                                if "JW Library" in app_name:
                                    return sub
                        except OSError:
                            pass
                except OSError:
                    break
    except Exception:
        pass
    return "AppXf9xsn2hpxwq9w3jf8tg0qmszyzky91z7"


def ensure_jwlplaylist_association() -> bool:
    """Ensures .jwlplaylist file extension is registered to open with JW Library in current user registry."""
    if os.name != "nt":
        return False
    try:
        import winreg

        prog_id = discover_jwl_progid()
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.jwlplaylist")
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, prog_id)
        winreg.CloseKey(key)

        open_with = winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.jwlplaylist\OpenWithProgids",
        )
        winreg.SetValueEx(open_with, prog_id, 0, winreg.REG_NONE, b"")
        winreg.CloseKey(open_with)
        return True
    except Exception:
        return False


def launch_jwl_with_playlist(playlist_path: Path) -> bool:
    """Launches or activates JW Library to import the given .jwlplaylist package."""
    if not playlist_path.is_file():
        return False
    ensure_jwlplaylist_association()
    success = False
    try:
        os.startfile(str(playlist_path.resolve()))
        success = True
    except Exception:
        pass

    if not success:
        try:
            import subprocess

            subprocess.Popen(
                ["explorer.exe", str(playlist_path.resolve())],
                shell=False,
            )
            success = True
        except Exception:
            pass

    # If JW Library is running, bring its main window to the foreground
    if success and os.name == "nt":
        try:
            from meeting_assistant.services.window_inventory import WindowBackend, is_jwl

            wb = WindowBackend()
            for win in wb.windows():
                if is_jwl(win) and win.hwnd:
                    import ctypes

                    user32 = ctypes.windll.user32
                    user32.ShowWindow(win.hwnd, 9)  # SW_RESTORE
                    user32.SetForegroundWindow(win.hwnd)
                    break
        except Exception:
            pass

    return success


def delete_playlist_from_jwl(playlist_name: str, db_path: Path | None = None) -> bool:
    """Deletes a playlist tag and unreferenced items from JW Library userData.db."""
    resolved_db = db_path or detect_jwl_userdata_db()
    if not resolved_db or not resolved_db.is_file():
        return False
    try:
        con = sqlite3.connect(resolved_db.as_posix(), timeout=5.0)
        try:
            con.execute("PRAGMA busy_timeout = 5000;")
            cur = con.cursor()
            cur.execute("SELECT TagId FROM Tag WHERE Type = 2 AND Name = ?", (playlist_name,))
            row = cur.fetchone()
            if not row:
                return False
            tag_id = row[0]
            cur.execute(
                "SELECT PlaylistItemId FROM TagMap WHERE TagId = ? AND PlaylistItemId IS NOT NULL",
                (tag_id,),
            )
            item_ids = [r[0] for r in cur.fetchall()]
            cur.execute("DELETE FROM TagMap WHERE TagId = ?", (tag_id,))
            cur.execute("DELETE FROM Tag WHERE TagId = ?", (tag_id,))
            for p_id in item_ids:
                cur.execute("SELECT count(*) FROM TagMap WHERE PlaylistItemId = ?", (p_id,))
                if cur.fetchone()[0] == 0:
                    try:
                        cur.execute(
                            "DELETE FROM PlaylistItemMarkerBibleVerseMap WHERE PlaylistItemMarkerId IN "
                            "(SELECT PlaylistItemMarkerId FROM PlaylistItemMarker WHERE PlaylistItemId = ?)",
                            (p_id,),
                        )
                        cur.execute(
                            "DELETE FROM PlaylistItemMarkerParagraphMap WHERE PlaylistItemMarkerId IN "
                            "(SELECT PlaylistItemMarkerId FROM PlaylistItemMarker WHERE PlaylistItemId = ?)",
                            (p_id,),
                        )
                        cur.execute("DELETE FROM PlaylistItemMarker WHERE PlaylistItemId = ?", (p_id,))
                    except sqlite3.OperationalError:
                        pass
                    cur.execute("DELETE FROM PlaylistItemLocationMap WHERE PlaylistItemId = ?", (p_id,))
                    cur.execute(
                        "DELETE FROM PlaylistItemIndependentMediaMap WHERE PlaylistItemId = ?",
                        (p_id,),
                    )
                    cur.execute("DELETE FROM PlaylistItem WHERE PlaylistItemId = ?", (p_id,))
            cur.execute("UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')")
            con.commit()
            try:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except sqlite3.Error:
                pass
            return True
        finally:
            con.close()
    except Exception:
        return False


def list_jwl_playlists(db_path: Path | None = None) -> list[dict]:
    """Returns a list of all playlists (Tag Type=2) in JW Library userData.db."""
    resolved_db = db_path or detect_jwl_userdata_db()
    if not resolved_db or not resolved_db.is_file():
        return []
    try:
        con = sqlite3.connect(f"file:{resolved_db.as_posix()}?mode=ro", uri=True, timeout=5.0)
        try:
            con.execute("PRAGMA busy_timeout = 5000;")
            cur = con.cursor()
            cur.execute("""
                SELECT t.TagId, t.Name, COUNT(tm.TagMapId) as item_count
                FROM Tag t
                LEFT JOIN TagMap tm ON t.TagId = tm.TagId AND tm.PlaylistItemId IS NOT NULL
                WHERE t.Type = 2
                GROUP BY t.TagId, t.Name
                ORDER BY t.Name COLLATE NOCASE ASC
            """)
            rows = cur.fetchall()
            return [{"tag_id": r[0], "name": r[1], "item_count": r[2]} for r in rows]
        finally:
            con.close()
    except Exception:
        return []


def load_playlist_items_from_db(
    tag_id: int | None = None,
    playlist_name: str | None = None,
    db_path: Path | None = None,
) -> tuple[str, list[MediaImportItem]]:
    """Loads all items of a playlist from JW Library userData.db."""
    resolved_db = db_path or detect_jwl_userdata_db()
    if not resolved_db or not resolved_db.is_file():
        raise FileNotFoundError("Banco de dados userData.db do JW Library não encontrado.")

    userdata_dir = resolved_db.parent
    con = sqlite3.connect(f"file:{resolved_db.as_posix()}?mode=ro", uri=True, timeout=5.0)
    try:
        con.execute("PRAGMA busy_timeout = 5000;")
        cur = con.cursor()

        if tag_id is None:
            if not playlist_name:
                raise ValueError("tag_id ou playlist_name deve ser fornecido.")
            cur.execute("SELECT TagId, Name FROM Tag WHERE Type = 2 AND Name = ?", (playlist_name,))
            t_row = cur.fetchone()
            if not t_row:
                raise ValueError(f"Playlist '{playlist_name}' não encontrada.")
            resolved_tag_id, resolved_name = t_row
        else:
            cur.execute("SELECT Name FROM Tag WHERE TagId = ?", (tag_id,))
            t_row = cur.fetchone()
            resolved_name = t_row[0] if t_row else f"Playlist {tag_id}"
            resolved_tag_id = tag_id

        cur.execute("""
            SELECT tm.Position, pi.PlaylistItemId, pi.Label, pi.EndAction, pi.ThumbnailFilePath,
                   im.IndependentMediaId, im.OriginalFilename, im.FilePath, im.MimeType,
                   pimm.DurationTicks,
                   loc.LocationId, loc.KeySymbol, loc.Track, loc.MepsLanguage, loc.IssueTagNumber,
                   loc.DocumentId, loc.BookNumber, plm.MajorMultimediaType, plm.BaseDurationTicks
            FROM TagMap tm
            JOIN PlaylistItem pi ON tm.PlaylistItemId = pi.PlaylistItemId
            LEFT JOIN PlaylistItemIndependentMediaMap pimm ON pi.PlaylistItemId = pimm.PlaylistItemId
            LEFT JOIN IndependentMedia im ON pimm.IndependentMediaId = im.IndependentMediaId
            LEFT JOIN PlaylistItemLocationMap plm ON pi.PlaylistItemId = plm.PlaylistItemId
            LEFT JOIN Location loc ON plm.LocationId = loc.LocationId
            WHERE tm.TagId = ?
            ORDER BY tm.Position ASC
        """, (resolved_tag_id,))

        items: list[MediaImportItem] = []
        for r in cur.fetchall():
            (
                pos, pid, label, end_act, thumb_fn,
                imid, orig_fn, file_fn, mime, dur_ticks,
                locid, keysym, trk, lang, issue,
                docid, book, major_type, base_dur_ticks
            ) = r

            thumb_path = (
                (userdata_dir / thumb_fn)
                if thumb_fn and (userdata_dir / thumb_fn).is_file()
                else None
            )

            if imid:
                target_file = userdata_dir / file_fn
                src_path = target_file if target_file.is_file() else Path(orig_fn or file_fn)
                duration_sec = (dur_ticks / 10_000_000.0) if dur_ticks and dur_ticks > 0 else 0.0
                item = MediaImportItem(
                    source_path=src_path,
                    label=label or orig_fn or "Mídia",
                    mime_type=mime or "",
                    duration_seconds=duration_sec,
                    end_action=end_act if end_act is not None else 2,
                    thumbnail_path=thumb_path,
                )
                items.append(item)
            elif locid:
                dur_sec = (base_dur_ticks / 10_000_000.0) if base_dur_ticks and base_dur_ticks > 0 else 0.0
                loc_name = f"{keysym}_{trk}" if (keysym and trk) else (label or "Publicação")
                src_path = Path(label or loc_name)
                item = MediaImportItem(
                    source_path=src_path,
                    label=label or loc_name,
                    mime_type="video/mp4" if major_type == 2 else ("audio/mpeg" if major_type == 1 else ""),
                    duration_seconds=dur_sec,
                    end_action=end_act if end_act is not None else 2,
                    key_symbol=keysym or "",
                    track=trk,
                    meps_language_index=lang if lang is not None else 5,
                    issue_tag_number=issue or 0,
                    document_id=docid,
                    book_number=book,
                    thumbnail_path=thumb_path,
                )
                items.append(item)
            else:
                item = MediaImportItem(
                    source_path=Path(label),
                    label=label,
                    end_action=end_act if end_act is not None else 2,
                    thumbnail_path=thumb_path,
                )
                items.append(item)

        return resolved_name, items
    finally:
        con.close()


def load_playlist_items_from_package(
    package_path: Path,
    extract_dir: Path | None = None,
) -> tuple[str, list[MediaImportItem]]:
    """Loads a playlist and its extracted media items from a .jwlplaylist package."""
    import json
    import zipfile

    if not package_path.is_file():
        raise FileNotFoundError(f"Arquivo de playlist não encontrado: {package_path}")

    if extract_dir is None:
        target_dir = package_path.parent / f"{package_path.stem}_extracted"
    else:
        target_dir = extract_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(package_path, "r") as zf:
        zf.extractall(target_dir)

    manifest_p = target_dir / "manifest.json"
    manifest_name = ""
    if manifest_p.is_file():
        try:
            m_data = json.loads(manifest_p.read_text(encoding="utf-8"))
            raw_name = m_data.get("name", "")
            manifest_name = raw_name.removesuffix(".jwlplaylist").removesuffix(".jwlibrary")
        except Exception:
            pass

    db_p = target_dir / "userData.db"
    if not db_p.is_file():
        raise RuntimeError("Arquivo userData.db não encontrado no pacote .jwlplaylist.")

    con = sqlite3.connect(db_p.as_posix())
    try:
        cur = con.cursor()
        cur.execute("SELECT TagId, Name FROM Tag WHERE Type = 2 LIMIT 1")
        row = cur.fetchone()
        tag_id = row[0] if row else None
        tag_name = row[1] if row else manifest_name or package_path.stem
    finally:
        con.close()

    if tag_id is not None:
        p_name, items = load_playlist_items_from_db(tag_id=tag_id, db_path=db_p)
    else:
        p_name, items = tag_name, []

    final_name = p_name or tag_name or manifest_name or package_path.stem
    return final_name, items
