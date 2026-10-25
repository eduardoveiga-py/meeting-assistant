from __future__ import annotations

import datetime
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from meeting_assistant.services.jwl_media_importer import (
    MediaImportItem,
    MediaImportResult,
    backup_userdata_db,
    cleanup_jwl_storage,
    delete_playlist_from_jwl,
    detect_jwl_music_dir,
    detect_jwl_publications_dir,
    detect_jwl_userdata_db,
    detect_jwl_videos_dir,
    import_media_to_jwl,
    install_jwpub_to_jwl,
    is_publication_installed,
    launch_jwl_with_playlist,
    list_jwl_playlists,
    list_userdata_backups,
    load_playlist_items_from_db,
    load_playlist_items_from_package,
    register_media_in_jwl_collection,
    resolve_meps_language_index,
    restore_userdata_backup,
)
from meeting_assistant.services.jwlibrary_backup_exporter import (
    export_playlist_to_jwlplaylist,
)
from meeting_assistant.services.meeting_media_downloader import (
    CancelToken,
    MediaDownloadItem,
    MeetingWeekInfo,
    download_file,
    extract_cbs_videos_from_mwb,
    extract_images_from_jwpub,
    extract_meeting_songs_from_jwpub,
    fetch_category_videos,
    fetch_media_item_by_pub_track,
    fetch_midweek_meeting_bundle,
    fetch_midweek_meeting_media,
    fetch_publication_bundle,
    fetch_songs_catalog,
    fetch_weekend_meeting_media,
    get_meeting_weeks,
    normalize_meps_language,
)
from meeting_assistant.services.meeting_media_watch_folder import (
    convert_files_to_import_items,
    get_default_meeting_media_folder,
    open_folder_in_explorer,
    sync_watch_folder_to_jwl,
)
from meeting_assistant.services.settings import AppSettings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PublicationCheckStatus:
    pub_symbol: str
    issue: str
    title: str
    is_installed: bool
    is_available_online: bool
    download_item: MediaDownloadItem | None = None
    installed_now: bool = False
    error: str = ""


@dataclass(slots=True)
class NewPublicationsResult:
    success: bool
    checked_items: list[PublicationCheckStatus] = field(default_factory=list)
    newly_installed: list[PublicationCheckStatus] = field(default_factory=list)
    already_installed: list[PublicationCheckStatus] = field(default_factory=list)
    error_message: str = ""


@dataclass(slots=True)
class StorageCleanupResult:
    success: bool
    app_files_deleted: list[str] = field(default_factory=list)
    app_bytes_freed: int = 0
    jwl_files_deleted: list[str] = field(default_factory=list)
    jwl_bytes_freed: int = 0
    total_bytes_freed: int = 0
    errors: list[str] = field(default_factory=list)


class MeetingMediaService:
    """Coordinating service for meeting media downloading, JW Library importing,

    watch folder monitoring, and database backup management.
    """

    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or AppSettings()

    @property
    def media_folder(self) -> Path:
        folder_setting = getattr(self.settings, "meeting_media_folder", "")
        if folder_setting:
            p = Path(folder_setting)
            p.mkdir(parents=True, exist_ok=True)
            return p
        return get_default_meeting_media_folder()

    @property
    def jwl_db_path(self) -> Path | None:
        custom_db = getattr(self.settings, "jwl_userdata_db_path", "")
        return detect_jwl_userdata_db(custom_db if custom_db else None)

    @property
    def language(self) -> str:
        raw_lang = getattr(self.settings, "congregation_language", "") or "T"
        return normalize_meps_language(raw_lang)

    @property
    def preferred_quality(self) -> str:
        return getattr(self.settings, "meeting_media_quality", "720p") or "720p"

    def list_backups(self) -> list[dict]:
        return list_userdata_backups(db_path=self.jwl_db_path)

    def create_manual_backup(self) -> Path:
        db = self.jwl_db_path
        if not db or not db.is_file():
            raise FileNotFoundError("Banco de dados userData.db do JW Library não encontrado.")
        return backup_userdata_db(db)

    def restore_backup(self, backup_file: Path) -> None:
        db = self.jwl_db_path
        if not db:
            raise FileNotFoundError("Caminho do banco de dados do JW Library não configurado.")
        restore_userdata_backup(backup_file, db)

    def _find_installed_publication_db(self, key_symbol: str) -> Path | None:
        """Finds the local SQLite db of an installed publication in JW Library LocalState/Publications."""
        try:
            pub_dir = detect_jwl_publications_dir()
            if not pub_dir or not pub_dir.exists():
                return None
            prefix = key_symbol.lower()
            lang_prefix = f"{prefix}_{self.language.lower()}"
            candidates: list[tuple[int, Path]] = []
            for sub in pub_dir.iterdir():
                if not sub.is_dir():
                    continue
                sub_name = sub.name.lower()
                if sub_name.startswith(lang_prefix) or sub_name.startswith(prefix):
                    contents_file = sub / "contents"
                    if contents_file.is_file():
                        try:
                            import zipfile

                            with zipfile.ZipFile(contents_file, "r") as czf:
                                czf.extractall(sub)
                            try:
                                contents_file.unlink()
                            except OSError:
                                pass
                        except Exception:
                            pass
                    dbs = list(sub.glob("*.db"))
                    if dbs:
                        digits = "".join(ch for ch in sub_name if ch.isdigit())
                        issue_num = int(digits[:8]) if digits else 0
                        score = (20000000 if sub_name.startswith(lang_prefix) else 10000000) + issue_num
                        candidates.append((score, dbs[0]))
            if candidates:
                candidates.sort(key=lambda c: c[0], reverse=True)
                return candidates[0][1]
        except Exception:
            pass
        return None

    def _download_and_register_song_items(
        self,
        song_numbers: list[int],
        dest_dir: Path,
        format_type: str = "mp4",
        progress_cb=None,
        status_cb=None,
        cancel_token: CancelToken | None = None,
    ) -> list[MediaImportItem]:
        """Downloads selected song numbers, registers in mediaCollection.db and copies to JW Library."""
        if not song_numbers:
            return []

        try:
            catalog = fetch_songs_catalog(
                language=self.language,
                format_type=format_type,
                preferred_quality=self.preferred_quality,
            )
        except Exception as exc:
            logger.debug("Falha ao obter catálogo de cânticos: %s", exc)
            return []

        dest_dir.mkdir(parents=True, exist_ok=True)
        downloaded_items: list[MediaImportItem] = []
        total = len(song_numbers)

        for idx, num in enumerate(song_numbers, start=1):
            if cancel_token and cancel_token.is_cancelled:
                break

            item = catalog.get(num)
            if not item:
                if status_cb:
                    status_cb(f"Cântico {num} não encontrado no catálogo do idioma {self.language}.")
                continue

            target_path = dest_dir / item.suggested_filename
            jwl_media_dir = (
                detect_jwl_videos_dir() if item.media_type == "video" else detect_jwl_music_dir()
            )
            jwl_target = jwl_media_dir / item.suggested_filename

            need_download = (
                not target_path.exists()
                or target_path.stat().st_size == 0
                or not jwl_target.exists()
                or jwl_target.stat().st_size == 0
            )

            if need_download:
                if status_cb:
                    status_cb(f"Baixando ({idx}/{total}): {item.title}…")

                def item_progress(curr, tot, i=idx):
                    if progress_cb and tot > 0:
                        overall = int(((i - 1) / total + (curr / tot) / total) * 90)
                        progress_cb(overall)

                if target_path.exists() and target_path.stat().st_size > 0:
                    shutil.copy2(target_path, jwl_target)
                else:
                    try:
                        download_file(
                            item.url,
                            target_path,
                            progress_cb=item_progress,
                            cancel_token=cancel_token,
                        )
                    except Exception as exc:
                        logger.debug("Falha ao baixar cântico %s: %s", num, exc)
                        continue
            else:
                if status_cb:
                    status_cb(f"Cântico {num} já existente em cache local.")

            # Register in JW Library official media collection and copy to JWLibrary folder
            try:
                if not jwl_target.exists() or jwl_target.stat().st_size != target_path.stat().st_size:
                    shutil.copy2(target_path, jwl_target)
                register_media_in_jwl_collection(
                    db_path=None,
                    file_path=jwl_target,
                    key_symbol=item.pub_symbol or "sjjm",
                    media_type=1 if item.media_type == "video" else 2,
                    meps_language_index=item.meps_language_index,
                    track=item.track_num if item.track_num is not None else -1,
                    issue_tag_number=item.issue_tag,
                    document_id=item.docid,
                    book_number=item.book_num,
                    title=item.title,
                    duration=item.duration_seconds,
                    filesize=item.filesize,
                    checksum=item.checksum,
                    label=item.label,
                    frame_width=item.frame_width,
                    frame_height=item.frame_height,
                    bit_rate=item.bit_rate,
                    frame_rate=item.frame_rate,
                )
            except Exception as exc:
                logger.debug("Falha ao registrar cântico no mediaCollection.db: %s", exc)

            downloaded_items.append(
                MediaImportItem(
                    source_path=target_path,
                    label=item.title,
                    duration_seconds=item.duration_seconds,
                    end_action=2,
                    key_symbol=item.pub_symbol or "sjjm",
                    track=item.track_num,
                    meps_language_index=item.meps_language_index,
                    issue_tag_number=item.issue_tag,
                    document_id=item.docid,
                    book_number=item.book_num,
                )
            )
        return downloaded_items

    def _download_and_register_cbs_items(
        self,
        cbs_entries: list[tuple[str, int, str]],
        dest_dir: Path,
        progress_cb=None,
        status_cb=None,
        cancel_token: CancelToken | None = None,
    ) -> list[MediaImportItem]:
        """Downloads Congregation Bible Study and auxiliary videos, registers in JW Library."""
        if not cbs_entries:
            return []

        downloaded: list[MediaImportItem] = []
        jwl_media_dir = detect_jwl_videos_dir()

        for cbs_entry in cbs_entries:
            if cancel_token and cancel_token.is_cancelled:
                break
            pub_code = cbs_entry[0]
            track_num = cbs_entry[1]
            label = cbs_entry[2]
            issue_tag = getattr(cbs_entry, "issue_tag", 0)
            doc_id = getattr(cbs_entry, "document_id", 0)

            try:
                item = fetch_media_item_by_pub_track(
                    pub=pub_code,
                    track=track_num,
                    issue_tag=issue_tag,
                    docid=doc_id,
                    language=self.language,
                    preferred_quality=self.preferred_quality,
                )
            except Exception as exc:
                logger.debug("Falha ao consultar mídia auxiliar %s track %s: %s", pub_code, track_num, exc)
                continue

            if not item:
                continue

            target_path = dest_dir / item.suggested_filename
            jwl_target = jwl_media_dir / item.suggested_filename

            need_download = (
                not target_path.exists()
                or target_path.stat().st_size == 0
                or not jwl_target.exists()
                or jwl_target.stat().st_size == 0
            )

            if need_download:
                if status_cb:
                    status_cb(f"Baixando vídeo auxiliar: {item.title}…")
                if target_path.exists() and target_path.stat().st_size > 0:
                    shutil.copy2(target_path, jwl_target)
                else:
                    try:
                        download_file(
                            item.url,
                            target_path,
                            progress_cb=progress_cb,
                            cancel_token=cancel_token,
                        )
                    except Exception as exc:
                        logger.debug("Falha ao baixar vídeo auxiliar %s: %s", item.title, exc)
                        continue
            else:
                if status_cb:
                    status_cb(f"Vídeo auxiliar já em cache: {item.title}")

            try:
                if not jwl_target.exists() or jwl_target.stat().st_size != target_path.stat().st_size:
                    shutil.copy2(target_path, jwl_target)
                register_media_in_jwl_collection(
                    db_path=None,
                    file_path=jwl_target,
                    key_symbol=item.pub_symbol or pub_code,
                    media_type=1,
                    meps_language_index=item.meps_language_index,
                    track=item.track_num if item.track_num is not None else -1,
                    issue_tag_number=item.issue_tag or issue_tag,
                    document_id=item.docid or doc_id,
                    book_number=item.book_num,
                    title=item.title,
                    duration=item.duration_seconds,
                    filesize=item.filesize,
                    checksum=item.checksum,
                    label=item.label or label,
                    frame_width=item.frame_width,
                    frame_height=item.frame_height,
                    bit_rate=item.bit_rate,
                    frame_rate=item.frame_rate,
                )
            except Exception as exc:
                logger.debug("Falha ao registrar vídeo auxiliar no mediaCollection.db: %s", exc)

            downloaded.append(
                MediaImportItem(
                    source_path=target_path,
                    label=item.title,
                    duration_seconds=item.duration_seconds,
                    end_action=2,
                    key_symbol=item.pub_symbol or pub_code,
                    track=item.track_num,
                    meps_language_index=item.meps_language_index,
                    issue_tag_number=item.issue_tag or issue_tag,
                    document_id=item.docid or doc_id,
                    book_number=item.book_num,
                )
            )
        return downloaded

    def download_songs_items(
        self,
        song_numbers: list[int],
        format_type: str = "mp4",
        progress_cb=None,
        status_cb=None,
        cancel_token: CancelToken | None = None,
    ) -> list[MediaImportItem]:
        """Downloads selected song numbers and returns them as MediaImportItems."""
        if not song_numbers:
            return []
        if status_cb:
            status_cb("Consultando catálogo de cânticos no JW.org…")
        dest_dir = self.media_folder / "Canticos"
        return self._download_and_register_song_items(
            song_numbers=song_numbers,
            dest_dir=dest_dir,
            format_type=format_type,
            progress_cb=progress_cb,
            status_cb=status_cb,
            cancel_token=cancel_token,
        )

    def download_songs_and_import(
        self,
        song_numbers: list[int],
        playlist_name: str = "Cânticos da Reunião",
        format_type: str = "mp4",
        progress_cb=None,
        status_cb=None,
        cancel_token: CancelToken | None = None,
    ) -> MediaImportResult:
        """Downloads selected songs and imports them directly into JW Library."""
        if not song_numbers:
            return MediaImportResult(success=False, error_message="Nenhum número de cântico especificado.")

        downloaded_items = self.download_songs_items(
            song_numbers=song_numbers,
            format_type=format_type,
            progress_cb=progress_cb,
            status_cb=status_cb,
            cancel_token=cancel_token,
        )

        if not downloaded_items:
            if cancel_token and cancel_token.is_cancelled:
                return MediaImportResult(success=False, error_message="Operação cancelada pelo operador.")
            return MediaImportResult(
                success=False,
                error_message="Nenhum arquivo de cântico pôde ser baixado.",
            )

        if status_cb:
            status_cb(
                f"Importando {len(downloaded_items)} cântico(s) na playlist '{playlist_name}' do JW Library…"
            )

        result = import_media_to_jwl(
            downloaded_items,
            playlist_name=playlist_name,
            db_path=self.jwl_db_path,
            backup=True,
        )
        try:
            import re

            clean_name = re.sub(r'[\\/*?:"<>|]', '_', playlist_name).strip() or "Canticos"
            pkg_file = self.media_folder / f"{clean_name}.jwlplaylist"
            export_playlist_to_jwlplaylist(downloaded_items, playlist_name, pkg_file)
            result.package_path = pkg_file
        except Exception as exc:
            logger.warning("Falha ao gerar pacote .jwlplaylist para cânticos: %s", exc)

        if progress_cb:
            progress_cb(100)
        return result

    def download_midweek_items(
        self,
        issue: str | None = None,
        include_images: bool = True,
        include_videos: bool = True,
        include_songs: bool = True,
        include_cbs_videos: bool = True,
        meeting_date: datetime.date | None = None,
        progress_cb=None,
        status_cb=None,
        cancel_token: CancelToken | None = None,
    ) -> list[MediaImportItem]:
        """Downloads videos and/or workbook images, songs, and CBS media from the Midweek Meeting."""
        dest_dir = self.media_folder / "MeioDeSemana"
        dest_dir.mkdir(parents=True, exist_ok=True)

        downloaded_items: list[MediaImportItem] = []
        target_pkg = None

        # 1. Handle JWPUB bundle and extract study illustrations, songs, and CBS videos
        if include_images or include_songs or include_cbs_videos:
            if status_cb:
                status_cb("Consultando pacote da Apostila mwb no JW.org…")
            try:
                bundle = fetch_midweek_meeting_bundle(language=self.language, issue=issue)
            except Exception as exc:
                bundle = None
                logger.debug("Falha ao consultar pacote da Apostila mwb: %s", exc)

            if bundle:
                target_pkg = dest_dir / bundle.suggested_filename
                if not target_pkg.exists() or target_pkg.stat().st_size == 0:
                    if status_cb:
                        status_cb(f"Baixando pacote da Apostila: {bundle.title}…")

                    def bundle_prog(curr, tot):
                        if progress_cb and tot > 0:
                            span = 45 if include_videos else 90
                            progress_cb(int((curr / tot) * span))

                    download_file(
                        bundle.url,
                        target_pkg,
                        progress_cb=bundle_prog,
                        cancel_token=cancel_token,
                    )

                if cancel_token and cancel_token.is_cancelled:
                    return []

                if target_pkg.is_file():
                    try:
                        if not is_publication_installed(
                            key_symbol="mwb",
                            issue_tag=bundle.issue_tag,
                            meps_language_index=bundle.meps_language_index,
                        ):
                            if status_cb:
                                status_cb(
                                    f"Instalando publicação da Apostila ({target_pkg.name}) no JW Library…"
                                )
                            install_jwpub_to_jwl(target_pkg)
                    except Exception as exc:
                        logger.debug("Falha ao verificar/instalar apostila mwb no JWL: %s", exc)

                if include_images:
                    images_dir = dest_dir / f"{target_pkg.stem}_imagens"
                    if status_cb:
                        status_cb("Extraindo gravuras e imagens da Apostila mwb…")
                    extracted_imgs = extract_images_from_jwpub(target_pkg, images_dir)
                    for img_path in sorted(extracted_imgs):
                        downloaded_items.append(
                            MediaImportItem(
                                source_path=img_path,
                                label=img_path.stem.replace("_", " "),
                                duration_seconds=0.0,
                                end_action=2,
                            )
                        )

            # Determine extraction source: downloaded pkg or installed publication database
            source_for_extraction = None
            if target_pkg and target_pkg.is_file():
                source_for_extraction = target_pkg
            else:
                source_for_extraction = self._find_installed_publication_db("mwb")

            # Extract and download weekly songs
            if include_songs and source_for_extraction:
                if status_cb:
                    status_cb("Detectando cânticos da semana na Apostila mwb…")
                weekly_songs = extract_meeting_songs_from_jwpub(
                    source_for_extraction,
                    meeting_date=meeting_date,
                    current_week_only=True,
                )
                if weekly_songs:
                    if status_cb:
                        status_cb(f"Cânticos da semana detectados: {weekly_songs}. Baixando e importando…")
                    song_items = self._download_and_register_song_items(
                        weekly_songs,
                        dest_dir=self.media_folder / "Canticos",
                        format_type="mp4",
                        status_cb=status_cb,
                        cancel_token=cancel_token,
                    )
                    downloaded_items.extend(song_items)

            # Extract and download Congregation Bible Study and auxiliary videos
            if include_cbs_videos and source_for_extraction:
                if status_cb:
                    status_cb("Detectando vídeos do Estudo Bíblico de Congregação (EBC)…")
                cbs_entries = extract_cbs_videos_from_mwb(
                    source_for_extraction,
                    meeting_date=meeting_date,
                    current_week_only=True,
                    language=self.language,
                )
                if cbs_entries:
                    cbs_items = self._download_and_register_cbs_items(
                        cbs_entries,
                        dest_dir=dest_dir,
                        status_cb=status_cb,
                        cancel_token=cancel_token,
                    )
                    downloaded_items.extend(cbs_items)

        # 2. Handle midweek videos if requested
        if include_videos:
            if status_cb:
                status_cb("Consultando vídeos da Reunião de Meio de Semana no JW.org…")

            items = fetch_midweek_meeting_media(language=self.language)
            total = len(items)
            seen_source_paths = {str(it.source_path) for it in downloaded_items}

            for idx, item in enumerate(items, start=1):
                if cancel_token and cancel_token.is_cancelled:
                    return []

                target_path = dest_dir / item.suggested_filename
                if str(target_path) in seen_source_paths:
                    continue
                seen_source_paths.add(str(target_path))

                jwl_media_dir = detect_jwl_videos_dir()
                jwl_target = jwl_media_dir / item.suggested_filename

                need_download = (
                    not target_path.exists()
                    or target_path.stat().st_size == 0
                    or not jwl_target.exists()
                    or jwl_target.stat().st_size == 0
                )

                if need_download:
                    if status_cb:
                        status_cb(f"Baixando ({idx}/{total}): {item.title}…")

                    def item_progress(curr, tot, i=idx, n=total):
                        if progress_cb and tot > 0:
                            base = 45 if include_images else 0
                            span = 45 if include_images else 90
                            overall = base + int(((i - 1) / n + (curr / tot) / n) * span)
                            progress_cb(overall)

                    if target_path.exists() and target_path.stat().st_size > 0:
                        shutil.copy2(target_path, jwl_target)
                    else:
                        download_file(
                            item.url,
                            target_path,
                            progress_cb=item_progress,
                            cancel_token=cancel_token,
                        )
                else:
                    if status_cb:
                        status_cb(f"Vídeo já em cache: {item.title}")

                # Register in JW Library official media collection and copy to Videos folder
                try:
                    if not jwl_target.exists() or jwl_target.stat().st_size != target_path.stat().st_size:
                        shutil.copy2(target_path, jwl_target)
                    register_media_in_jwl_collection(
                        db_path=None,
                        file_path=jwl_target,
                        key_symbol=item.pub_symbol or "mwbv",
                        media_type=1,
                        meps_language_index=item.meps_language_index,
                        track=item.track_num if item.track_num is not None else -1,
                        issue_tag_number=item.issue_tag,
                        document_id=item.docid,
                        book_number=item.book_num,
                        title=item.title,
                        duration=item.duration_seconds,
                        filesize=item.filesize,
                        checksum=item.checksum,
                        label=item.label,
                        frame_width=item.frame_width,
                        frame_height=item.frame_height,
                        bit_rate=item.bit_rate,
                        frame_rate=item.frame_rate,
                    )
                except Exception as exc:
                    logger.debug("Falha ao registrar vídeo de meio de semana no mediaCollection.db: %s", exc)

                downloaded_items.append(
                    MediaImportItem(
                        source_path=target_path,
                        label=item.title,
                        duration_seconds=item.duration_seconds,
                        end_action=2,
                        key_symbol=item.pub_symbol or "mwbv",
                        track=item.track_num,
                        meps_language_index=item.meps_language_index,
                        issue_tag_number=item.issue_tag,
                        document_id=item.docid,
                        book_number=item.book_num,
                    )
                )

        return downloaded_items

    def download_midweek_and_import(
        self,
        playlist_name: str = "Reunião de Meio de Semana",
        issue: str | None = None,
        include_images: bool = True,
        include_videos: bool = True,
        include_songs: bool = True,
        include_cbs_videos: bool = True,
        meeting_date: datetime.date | None = None,
        progress_cb=None,
        status_cb=None,
        cancel_token: CancelToken | None = None,
        cleanup_cache_after_import: bool | None = None,
    ) -> MediaImportResult:
        """Downloads Midweek Meeting media and imports them into JW Library."""
        downloaded_items = self.download_midweek_items(
            issue=issue,
            include_images=include_images,
            include_videos=include_videos,
            include_songs=include_songs,
            include_cbs_videos=include_cbs_videos,
            meeting_date=meeting_date,
            progress_cb=progress_cb,
            status_cb=status_cb,
            cancel_token=cancel_token,
        )

        if cancel_token and cancel_token.is_cancelled:
            return MediaImportResult(success=False, error_message="Operação cancelada.")

        if not downloaded_items:
            return MediaImportResult(
                success=False,
                error_message=(
                    f"Nenhuma mídia encontrada ou baixada para a Reunião de Meio de Semana ({self.language})."
                ),
            )

        if status_cb:
            status_cb(f"Importando {len(downloaded_items)} item(s) no JW Library…")

        result = import_media_to_jwl(
            downloaded_items,
            playlist_name=playlist_name,
            db_path=self.jwl_db_path,
            backup=True,
        )
        try:
            import re

            clean_name = re.sub(r'[\\/*?:"<>|]', '_', playlist_name).strip() or "MeioDeSemana"
            pkg_file = self.media_folder / f"{clean_name}.jwlplaylist"
            export_playlist_to_jwlplaylist(downloaded_items, playlist_name, pkg_file)
            result.package_path = pkg_file
        except Exception as exc:
            logger.warning("Falha ao gerar pacote .jwlplaylist para reunião de meio de semana: %s", exc)

        if progress_cb:
            progress_cb(100)

        is_standard_playlist = playlist_name == "Reunião de Meio de Semana"
        should_cleanup = (
            cleanup_cache_after_import
            if cleanup_cache_after_import is not None
            else getattr(self.settings, "meeting_media_cleanup_after_import", True)
        )
        if result.success and should_cleanup and is_standard_playlist:
            try:
                dest_dir = self.media_folder / "MeioDeSemana"
                if dest_dir.is_dir():
                    shutil.rmtree(dest_dir)
                    dest_dir.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                logger.debug("Falha na limpeza pós-importação da pasta MeioDeSemana: %s", exc)

        return result

    def download_weekend_items(
        self,
        issue: str | None = None,
        include_images: bool = True,
        include_audio: bool = False,
        include_videos: bool = True,
        include_songs: bool = True,
        meeting_date: datetime.date | None = None,
        progress_cb=None,
        status_cb=None,
        cancel_token: CancelToken | None = None,
    ) -> list[MediaImportItem]:
        """Downloads Watchtower Study media/images, songs, and audio, returning them as MediaImportItems."""
        if status_cb:
            status_cb("Consultando mídias da Reunião de Final de Semana (A Sentinela) no JW.org…")

        try:
            items = fetch_weekend_meeting_media(language=self.language, issue=issue)
        except Exception as exc:
            logger.debug("Falha ao consultar mídias da Sentinela: %s", exc)
            return []

        if not items:
            return []

        dest_dir = self.media_folder / "FinalDeSemana"
        dest_dir.mkdir(parents=True, exist_ok=True)

        downloaded_items: list[MediaImportItem] = []

        # 1. Handle JWPUB bundle and extract study images and songs
        bundle_items = [it for it in items if it.media_type == "bundle"]
        other_items = [it for it in items if it.media_type != "bundle"]
        target_pkg = None

        if (include_images or include_songs) and bundle_items:
            bundle = bundle_items[0]
            target_pkg = dest_dir / bundle.suggested_filename
            if not target_pkg.exists() or target_pkg.stat().st_size == 0:
                if status_cb:
                    status_cb(f"Baixando pacote da Sentinela: {bundle.title}…")

                def bundle_progress(curr, tot):
                    if progress_cb and tot > 0:
                        span = 50 if ((include_audio or include_videos) and other_items) else 90
                        progress_cb(int((curr / tot) * span))

                download_file(
                    bundle.url,
                    target_pkg,
                    progress_cb=bundle_progress,
                    cancel_token=cancel_token,
                )

            if cancel_token and cancel_token.is_cancelled:
                return []

            if target_pkg.is_file():
                try:
                    if not is_publication_installed(
                        key_symbol="w",
                        issue_tag=bundle.issue_tag,
                        meps_language_index=bundle.meps_language_index,
                    ):
                        if status_cb:
                            status_cb(
                                f"Instalando publicação de A Sentinela ({target_pkg.name}) no JW Library…"
                            )
                        install_jwpub_to_jwl(target_pkg)
                except Exception as exc:
                    logger.debug("Falha ao verificar/instalar Sentinela w no JWL: %s", exc)

                if include_images:
                    images_dir = dest_dir / f"{target_pkg.stem}_imagens"
                    if status_cb:
                        status_cb("Extraindo gravuras e imagens do estudo da Sentinela…")
                    extracted_imgs = extract_images_from_jwpub(target_pkg, images_dir)

                    for img_path in sorted(extracted_imgs):
                        downloaded_items.append(
                            MediaImportItem(
                                source_path=img_path,
                                label=img_path.stem.replace("_", " "),
                                duration_seconds=0.0,
                                end_action=2,
                            )
                        )

        # Extract and download study songs
        source_for_extraction = None
        if target_pkg and target_pkg.is_file():
            source_for_extraction = target_pkg
        else:
            source_for_extraction = self._find_installed_publication_db("w")

        if include_songs and source_for_extraction:
            if status_cb:
                status_cb("Detectando cânticos do Estudo de A Sentinela…")
            study_songs = extract_meeting_songs_from_jwpub(
                source_for_extraction,
                meeting_date=meeting_date,
                current_week_only=True,
            )
            if study_songs:
                if status_cb:
                    status_cb(f"Cânticos de estudo detectados: {study_songs}. Baixando e importando…")
                song_items = self._download_and_register_song_items(
                    study_songs,
                    dest_dir=self.media_folder / "Canticos",
                    format_type="mp4",
                    status_cb=status_cb,
                    cancel_token=cancel_token,
                )
                downloaded_items.extend(song_items)

        # 2. Handle audio and/or videos if requested
        media_items_to_download: list[MediaDownloadItem] = []
        if include_audio:
            media_items_to_download.extend([it for it in other_items if it.media_type == "audio"])
        if include_videos:
            media_items_to_download.extend([it for it in other_items if it.media_type == "video"])

        total_media = len(media_items_to_download)
        for idx, item in enumerate(media_items_to_download, start=1):
            if cancel_token and cancel_token.is_cancelled:
                return []
            target_path = dest_dir / item.suggested_filename
            jwl_media_dir = (
                detect_jwl_videos_dir() if item.media_type == "video" else detect_jwl_music_dir()
            )
            jwl_target = jwl_media_dir / item.suggested_filename

            need_download = (
                not target_path.exists()
                or target_path.stat().st_size == 0
                or not jwl_target.exists()
                or jwl_target.stat().st_size == 0
            )

            if need_download:
                if status_cb:
                    status_cb(f"Baixando ({idx}/{total_media}): {item.title}…")

                def media_progress(curr, tot, i=idx, n=total_media):
                    if progress_cb and tot > 0:
                        base = 50 if (include_images and bundle_items) else 0
                        span = 40 if (include_images and bundle_items) else 90
                        overall = base + int(((i - 1) / n + (curr / tot) / n) * span)
                        progress_cb(overall)

                if target_path.exists() and target_path.stat().st_size > 0:
                    shutil.copy2(target_path, jwl_target)
                else:
                    download_file(
                        item.url,
                        target_path,
                        progress_cb=media_progress,
                        cancel_token=cancel_token,
                    )
            else:
                if status_cb:
                    status_cb(f"Mídia já em cache: {item.title}")

            # Register in JW Library official media collection and copy to JWLibrary folder
            try:
                if not jwl_target.exists() or jwl_target.stat().st_size != target_path.stat().st_size:
                    shutil.copy2(target_path, jwl_target)
                register_media_in_jwl_collection(
                    db_path=None,
                    file_path=jwl_target,
                    key_symbol=item.pub_symbol or "w",
                    media_type=1 if item.media_type == "video" else 2,
                    meps_language_index=item.meps_language_index,
                    track=item.track_num if item.track_num is not None else -1,
                    issue_tag_number=item.issue_tag,
                    document_id=item.docid,
                    book_number=item.book_num,
                    title=item.title,
                    duration=item.duration_seconds,
                    filesize=item.filesize,
                    checksum=item.checksum,
                    label=item.label,
                    frame_width=item.frame_width,
                    frame_height=item.frame_height,
                    bit_rate=item.bit_rate,
                    frame_rate=item.frame_rate,
                )
            except Exception as exc:
                logger.debug("Falha ao registrar mídia da Sentinela no mediaCollection.db: %s", exc)

            downloaded_items.append(
                MediaImportItem(
                    source_path=target_path,
                    label=item.title,
                    duration_seconds=item.duration_seconds,
                    end_action=2,
                    key_symbol=item.pub_symbol or "w",
                    track=item.track_num,
                    meps_language_index=item.meps_language_index,
                    issue_tag_number=item.issue_tag,
                    document_id=item.docid,
                    book_number=item.book_num,
                )
            )

        return downloaded_items

    def download_weekend_and_import(
        self,
        issue: str | None = None,
        playlist_name: str = "Estudo de A Sentinela",
        include_images: bool = True,
        include_audio: bool = False,
        include_videos: bool = True,
        include_songs: bool = True,
        meeting_date: datetime.date | None = None,
        progress_cb=None,
        status_cb=None,
        cancel_token: CancelToken | None = None,
        cleanup_cache_after_import: bool | None = None,
    ) -> MediaImportResult:
        """Downloads Watchtower Study media/images, songs, and audio and imports into JW Library."""
        downloaded_items = self.download_weekend_items(
            issue=issue,
            include_images=include_images,
            include_audio=include_audio,
            include_videos=include_videos,
            include_songs=include_songs,
            meeting_date=meeting_date,
            progress_cb=progress_cb,
            status_cb=status_cb,
            cancel_token=cancel_token,
        )

        if cancel_token and cancel_token.is_cancelled:
            return MediaImportResult(success=False, error_message="Operação cancelada.")

        if not downloaded_items:
            return MediaImportResult(
                success=False,
                error_message="Nenhum arquivo de imagem ou mídia pôde ser extraído da Sentinela.",
            )

        if status_cb:
            status_cb(
                f"Importando {len(downloaded_items)} item(ns) na playlist '{playlist_name}' do JW Library…"
            )

        result = import_media_to_jwl(
            downloaded_items,
            playlist_name=playlist_name,
            db_path=self.jwl_db_path,
            backup=True,
        )
        try:
            import re

            clean_name = re.sub(r'[\\/*?:"<>|]', '_', playlist_name).strip() or "EstudoSentinela"
            pkg_file = self.media_folder / f"{clean_name}.jwlplaylist"
            export_playlist_to_jwlplaylist(downloaded_items, playlist_name, pkg_file)
            result.package_path = pkg_file
        except Exception as exc:
            logger.warning("Falha ao gerar pacote .jwlplaylist para Sentinela: %s", exc)

        if progress_cb:
            progress_cb(100)

        is_standard_playlist = playlist_name == "Estudo de A Sentinela"
        should_cleanup = (
            cleanup_cache_after_import
            if cleanup_cache_after_import is not None
            else getattr(self.settings, "meeting_media_cleanup_after_import", True)
        )
        if result.success and should_cleanup and is_standard_playlist:
            try:
                dest_dir = self.media_folder / "Sentinela"
                if dest_dir.is_dir():
                    shutil.rmtree(dest_dir)
                    dest_dir.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                logger.debug("Falha na limpeza pós-importação da pasta Sentinela: %s", exc)

        return result

    def download_media_item_by_pub_track(
        self,
        pub: str,
        track: int,
        issue_tag: int = 0,
        docid: int = 0,
        progress_cb=None,
        status_cb=None,
        cancel_token: CancelToken | None = None,
    ) -> MediaImportItem | None:
        """Downloads a specific video/media item from JW.org and registers in media collection."""
        dest_dir = self.media_folder / "Videos"
        dest_dir.mkdir(parents=True, exist_ok=True)
        item = fetch_media_item_by_pub_track(
            pub=pub,
            track=track,
            issue_tag=issue_tag,
            docid=docid,
            language=self.language,
            preferred_quality=self.preferred_quality,
        )
        if not item:
            return None
        target_path = dest_dir / (item.suggested_filename or f"{pub}_{track}.mp4")
        if not target_path.exists() or target_path.stat().st_size == 0:
            if status_cb:
                status_cb(f"Baixando mídia: {item.title}…")
            download_file(item.url, target_path, progress_cb=progress_cb, cancel_token=cancel_token)
        jwl_videos_dir = detect_jwl_videos_dir()
        target_to_register = target_path
        if jwl_videos_dir and jwl_videos_dir.exists():
            jwl_target = jwl_videos_dir / target_path.name
            try:
                if not jwl_target.exists() or jwl_target.stat().st_size != target_path.stat().st_size:
                    shutil.copy2(target_path, jwl_target)
                target_to_register = jwl_target
            except Exception:
                pass
        thumb_file = None
        if getattr(item, "thumbnail_url", ""):
            thumb_path = target_path.with_suffix(".thumb.jpg")
            if not thumb_path.exists() or thumb_path.stat().st_size == 0:
                try:
                    download_file(item.thumbnail_url, thumb_path, cancel_token=cancel_token)
                except Exception:
                    pass
            if thumb_path.is_file() and thumb_path.stat().st_size > 0:
                thumb_file = thumb_path

        try:
            register_media_in_jwl_collection(
                db_path=None,
                file_path=target_to_register,
                key_symbol=item.pub_symbol or pub,
                media_type=(
                    1
                    if (item.media_type == "video" or target_path.suffix.lower() in (".mp4", ".m4v"))
                    else 2
                ),
                meps_language_index=item.meps_language_index,
                track=item.track_num if item.track_num is not None else track,
                issue_tag_number=item.issue_tag or issue_tag,
                document_id=item.docid or docid,
                title=item.title,
                duration=item.duration_seconds,
                filesize=item.filesize,
                checksum=item.checksum,
                label=item.label or "720p",
            )
        except Exception as exc:
            logger.debug("Falha ao registrar mídia no mediaCollection.db: %s", exc)
        return MediaImportItem(
            source_path=target_path,
            label=item.title,
            duration_seconds=item.duration_seconds,
            end_action=2,
            key_symbol=item.pub_symbol or pub,
            track=item.track_num or track,
            meps_language_index=item.meps_language_index,
            issue_tag_number=item.issue_tag or issue_tag,
            document_id=item.docid or docid,
            thumbnail_path=thumb_file,
        )

    def get_category_videos(self, category_key: str) -> list[MediaDownloadItem]:
        """Fetches videos for a given JW.org category."""
        return fetch_category_videos(
            category_key=category_key,
            language=self.language,
            preferred_quality=self.preferred_quality,
        )

    def download_media_item(
        self,
        item: MediaDownloadItem,
        dest_dir: Path | None = None,
        progress_cb=None,
        status_cb=None,
        cancel_token: CancelToken | None = None,
    ) -> MediaImportItem | None:
        """Downloads an individual MediaDownloadItem (e.g. from category videos or pub/track search),
        copies to JW Library and registers in mediaCollection.db."""
        if not item or not item.url:
            return None
        target_dir = dest_dir or (self.media_folder / "JW_Videos")
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / item.suggested_filename

        jwl_media_dir = (
            detect_jwl_videos_dir() if item.media_type == "video" else detect_jwl_music_dir()
        )
        jwl_target = jwl_media_dir / item.suggested_filename

        need_download = (
            not target_path.exists()
            or target_path.stat().st_size == 0
            or not jwl_target.exists()
            or jwl_target.stat().st_size == 0
        )

        if need_download:
            if status_cb:
                status_cb(f"Baixando: {item.title}…")
            if target_path.exists() and target_path.stat().st_size > 0:
                shutil.copy2(target_path, jwl_target)
            else:
                try:
                    download_file(
                        item.url,
                        target_path,
                        progress_cb=progress_cb,
                        cancel_token=cancel_token,
                    )
                except Exception as exc:
                    logger.debug("Falha ao baixar item %s: %s", item.title, exc)
                    return None
        else:
            if status_cb:
                status_cb(f"Item já existente em cache local: {item.title}")

        # Download thumbnail if available and not existing
        thumb_file = None
        if getattr(item, "thumbnail_url", ""):
            thumb_path = target_path.with_suffix(".thumb.jpg")
            if not thumb_path.exists() or thumb_path.stat().st_size == 0:
                try:
                    download_file(item.thumbnail_url, thumb_path, cancel_token=cancel_token)
                except Exception:
                    pass
            if thumb_path.is_file() and thumb_path.stat().st_size > 0:
                thumb_file = thumb_path

        try:
            if not jwl_target.exists() or jwl_target.stat().st_size != target_path.stat().st_size:
                shutil.copy2(target_path, jwl_target)
            register_media_in_jwl_collection(
                db_path=None,
                file_path=jwl_target,
                key_symbol=item.pub_symbol or "mwbv",
                media_type=1 if item.media_type == "video" else 2,
                meps_language_index=item.meps_language_index,
                track=item.track_num if item.track_num is not None else -1,
                issue_tag_number=item.issue_tag,
                document_id=item.docid,
                book_number=item.book_num,
                title=item.title,
                duration=item.duration_seconds,
                filesize=item.filesize,
                checksum=item.checksum,
                label=item.label,
                frame_width=item.frame_width,
                frame_height=item.frame_height,
                bit_rate=item.bit_rate,
                frame_rate=item.frame_rate,
            )
        except Exception as exc:
            logger.debug("Falha ao registrar item no mediaCollection.db: %s", exc)

        return MediaImportItem(
            source_path=target_path,
            label=item.title,
            duration_seconds=item.duration_seconds,
            end_action=2,
            key_symbol=item.pub_symbol or "mwbv",
            track=item.track_num,
            meps_language_index=item.meps_language_index,
            issue_tag_number=item.issue_tag,
            document_id=item.docid,
            book_number=item.book_num,
            thumbnail_path=thumb_file,
        )

    def import_playlist_items(
        self,
        items: list[MediaImportItem],
        playlist_name: str = "Discurso Público",
        clear_existing: bool = True,
        launch_jwl: bool = False,
    ) -> MediaImportResult:
        """Imports a custom ordered list of MediaImportItems into JW Library
        with their specific EndActions.

        Writes to userData.db and exports an official .jwlplaylist package to the media folder.
        If launch_jwl is True, triggers JW Library file activation for immediate native import.
        """
        if clear_existing:
            delete_playlist_from_jwl(playlist_name, db_path=self.jwl_db_path)

        result = import_media_to_jwl(
            items,
            playlist_name=playlist_name,
            db_path=self.jwl_db_path,
            backup=True,
            clear_existing=clear_existing,
            auto_thumbnails=True,
        )

        # Always generate the official .jwlplaylist package
        try:
            import re

            clean_name = re.sub(r'[\\/*?:"<>|]', '_', playlist_name).strip() or "Playlist"
            pkg_file = self.media_folder / f"{clean_name}.jwlplaylist"
            export_playlist_to_jwlplaylist(items, playlist_name, pkg_file)
            result.package_path = pkg_file

            if launch_jwl and result.success:
                result.activated_jwl = launch_jwl_with_playlist(pkg_file)
        except Exception as exc:
            logger.warning("Erro ao gerar/ativar pacote .jwlplaylist: %s", exc)

        return result

    def delete_playlist(self, playlist_name: str) -> bool:
        """Deletes an existing playlist from JW Library userData.db."""
        return delete_playlist_from_jwl(playlist_name, db_path=self.jwl_db_path)

    def list_existing_playlists(self) -> list[dict]:
        """Lists all existing playlists found in JW Library userData.db."""
        return list_jwl_playlists(db_path=self.jwl_db_path)

    def load_playlist_from_db(
        self,
        tag_id: int | None = None,
        playlist_name: str | None = None,
    ) -> tuple[str, list[MediaImportItem]]:
        """Loads items of an existing playlist from JW Library userData.db."""
        return load_playlist_items_from_db(
            tag_id=tag_id,
            playlist_name=playlist_name,
            db_path=self.jwl_db_path,
        )

    def load_playlist_from_file(
        self,
        file_path: Path,
    ) -> tuple[str, list[MediaImportItem]]:
        """Loads items from an existing .jwlplaylist file."""
        extract_dir = self.media_folder / f"{file_path.stem}_extracted"
        return load_playlist_items_from_package(file_path, extract_dir=extract_dir)

    def export_playlist_items(
        self,
        items: list[MediaImportItem],
        playlist_name: str,
        target_file: Path,
    ) -> Path:
        """Exports a custom list of MediaImportItems as an official .jwlplaylist package."""
        return export_playlist_to_jwlplaylist(items, playlist_name, target_file)

    def import_local_files(
        self,
        files: list[Path],
        playlist_name: str = "Discurso Público",
        launch_jwl: bool = False,
    ) -> MediaImportResult:
        """Imports local media files into JW Library."""
        items = convert_files_to_import_items(files)
        return self.import_playlist_items(
            items, playlist_name=playlist_name, launch_jwl=launch_jwl
        )

    def export_backup_package(
        self,
        files: list[Path],
        playlist_name: str,
        target_file: Path,
    ) -> Path:
        """Exports a list of local files as an official .jwlplaylist package."""
        items = convert_files_to_import_items(files)
        return export_playlist_to_jwlplaylist(items, playlist_name, target_file)

    def sync_watch_folder(self, playlist_name: str = "Mídias do Salão") -> MediaImportResult:
        """Synchronizes the watch folder into JW Library."""
        return sync_watch_folder_to_jwl(
            self.media_folder,
            playlist_name=playlist_name,
            db_path=self.jwl_db_path,
        )

    def open_media_folder(self) -> None:
        """Opens the meeting media folder in Windows Explorer."""
        open_folder_in_explorer(self.media_folder)

    def get_available_weeks(
        self,
        base_date: datetime.date | None = None,
        past_weeks: int = 2,
        future_weeks: int = 8,
    ) -> list[MeetingWeekInfo]:
        """Returns the list of available meeting weeks based on current date and installed publications."""
        jwpub_sources: list[Path] = []
        mwb_source = self._find_installed_publication_db("mwb")
        if mwb_source:
            jwpub_sources.append(mwb_source)

        pub_dir = detect_jwl_publications_dir()
        if pub_dir and pub_dir.exists():
            for sub in pub_dir.iterdir():
                if sub.is_dir() and "mwb" in sub.name.lower():
                    jwpub_sources.append(sub)

        # Also check downloaded publications in media folder
        download_pub_dir = self.media_folder / "Publicacoes"
        if download_pub_dir.is_dir():
            for p in download_pub_dir.glob("*.jwpub"):
                jwpub_sources.append(p)

        mwb_cache = self.media_folder / "MeioDeSemana"
        if mwb_cache.is_dir():
            for p in mwb_cache.glob("*.jwpub"):
                jwpub_sources.append(p)

        return get_meeting_weeks(
            base_date=base_date,
            past_weeks=past_weeks,
            future_weeks=future_weeks,
            jwpub_sources=jwpub_sources,
        )

    def check_for_newer_publications(
        self,
        language: str | None = None,
        timeout: float = 6.0,
    ) -> list[PublicationCheckStatus]:
        """Probes JW.org for upcoming issues of mwb and w, checking if they are already installed in JWL."""
        lang = normalize_meps_language(language or self.language)
        lang_idx = resolve_meps_language_index(lang)

        now = datetime.date.today()
        # Candidate issues:
        # mwb (bimonthly odd months: 0, +2, +4 months)
        curr_odd = now.month if now.month % 2 == 1 else now.month - 1
        mwb_candidates: list[str] = []
        for delta_m in (0, 2, 4):
            m = curr_odd + delta_m
            y = now.year
            while m > 12:
                m -= 12
                y += 1
            mwb_candidates.append(f"{y}{m:02d}")

        # w (monthly: 0, +1, +2 months)
        w_candidates: list[str] = []
        for delta_m in (0, 1, 2):
            m = now.month + delta_m
            y = now.year
            while m > 12:
                m -= 12
                y += 1
            w_candidates.append(f"{y}{m:02d}")

        results: list[PublicationCheckStatus] = []

        # Check mwb candidates
        for cand in mwb_candidates:
            issue_tag = int(cand) if cand.isdigit() else 0
            is_inst = is_publication_installed(
                key_symbol="mwb",
                issue_tag=issue_tag,
                meps_language_index=lang_idx,
            )
            bundle_item = None
            is_online = False
            try:
                bundle_item = fetch_publication_bundle("mwb", cand, language=lang, timeout=timeout)
                is_online = bundle_item is not None
            except Exception:
                pass

            title = bundle_item.title if bundle_item else f"Apostila mwb {cand}"
            results.append(
                PublicationCheckStatus(
                    pub_symbol="mwb",
                    issue=cand,
                    title=title,
                    is_installed=is_inst,
                    is_available_online=is_online,
                    download_item=bundle_item,
                )
            )

        # Check w candidates
        for cand in w_candidates:
            issue_tag = int(cand) if cand.isdigit() else 0
            is_inst = is_publication_installed(
                key_symbol="w",
                issue_tag=issue_tag,
                meps_language_index=lang_idx,
            )
            bundle_item = None
            is_online = False
            try:
                bundle_item = fetch_publication_bundle("w", cand, language=lang, timeout=timeout)
                is_online = bundle_item is not None
            except Exception:
                pass

            title = bundle_item.title if bundle_item else f"A Sentinela {cand}"
            results.append(
                PublicationCheckStatus(
                    pub_symbol="w",
                    issue=cand,
                    title=title,
                    is_installed=is_inst,
                    is_available_online=is_online,
                    download_item=bundle_item,
                )
            )

        return results

    def check_and_install_new_publications(
        self,
        language: str | None = None,
        auto_install: bool = True,
        progress_cb=None,
        status_cb=None,
        cancel_token: CancelToken | None = None,
    ) -> NewPublicationsResult:
        """Verifies if newer publication editions exist on JW.org and installs uninstalled ones into JWL."""
        lang = normalize_meps_language(language or self.language)
        if status_cb:
            status_cb("Verificando edições disponíveis de Apostilas e Sentinelas no JW.org…")
        if progress_cb:
            progress_cb(10)

        checked = self.check_for_newer_publications(language=lang)
        if cancel_token and cancel_token.is_cancelled:
            return NewPublicationsResult(success=False, error_message="Operação cancelada.")

        if progress_cb:
            progress_cb(40)

        newly_installed: list[PublicationCheckStatus] = []
        already_installed: list[PublicationCheckStatus] = []
        pub_folder = self.media_folder / "Publicacoes"
        pub_folder.mkdir(parents=True, exist_ok=True)

        for idx, item in enumerate(checked, start=1):
            if cancel_token and cancel_token.is_cancelled:
                return NewPublicationsResult(success=False, error_message="Operação cancelada.")

            if item.is_installed:
                already_installed.append(item)
                continue

            if not item.is_available_online or not item.download_item:
                continue

            if auto_install:
                target_file = pub_folder / item.download_item.suggested_filename
                need_dl = not target_file.is_file() or target_file.stat().st_size == 0
                if need_dl:
                    if status_cb:
                        status_cb(f"Baixando nova publicação ({item.title})…")
                    try:
                        download_file(
                            item.download_item.url,
                            target_file,
                            cancel_token=cancel_token,
                        )
                    except Exception as exc:
                        item.error = f"Falha no download: {exc}"
                        continue

                if target_file.is_file():
                    if status_cb:
                        status_cb(f"Instalando {item.title} no JW Library…")
                    try:
                        installed = install_jwpub_to_jwl(target_file)
                        if installed:
                            item.installed_now = True
                            item.is_installed = True
                            newly_installed.append(item)
                        else:
                            item.error = "Falha ao registrar publicação no JW Library."
                    except Exception as exc:
                        item.error = f"Erro na instalação: {exc}"

            if progress_cb:
                progress_cb(40 + int((idx / len(checked)) * 55))

        if progress_cb:
            progress_cb(100)

        return NewPublicationsResult(
            success=True,
            checked_items=checked,
            newly_installed=newly_installed,
            already_installed=already_installed,
        )

    def cleanup_app_cache(
        self,
        keep_weeks: int = 0,
        meeting_type: str = "all",
    ) -> tuple[list[str], int, list[str]]:
        """Cleans temporary downloaded files in the app's media folder.

        Custom playlists, watch folders, and operator-defined files are NEVER touched.
        """
        deleted_files: list[str] = []
        total_freed = 0
        errors: list[str] = []

        folders_to_clean: list[Path] = []
        if meeting_type in ("all", "midweek"):
            folders_to_clean.append(self.media_folder / "MeioDeSemana")
        if meeting_type in ("all", "weekend"):
            folders_to_clean.append(self.media_folder / "Sentinela")
        if meeting_type in ("all", "publications"):
            folders_to_clean.append(self.media_folder / "Publicacoes")

        today = datetime.date.today()
        cutoff_date = today - datetime.timedelta(days=max(0, keep_weeks) * 7)
        cutoff_ts = None
        if keep_weeks > 0:
            cutoff_ts = datetime.datetime.combine(cutoff_date, datetime.time.min).timestamp()

        def _is_item_expired(name: str, mtime: float) -> bool:
            import re
            m = re.search(r"(\d{6,8})", name)
            if m:
                tag = int(m.group(1))
                tag6 = tag // 100 if tag >= 1_000_000 else tag
                if 200000 <= tag6 <= 210012:
                    y = tag6 // 100
                    mo = tag6 % 100
                    if 1 <= mo <= 12:
                        if "mwb" in name.lower():
                            exp_m = mo + 1
                            exp_y = y
                            if exp_m > 12:
                                exp_m = 1
                                exp_y += 1
                        else:
                            exp_m = mo
                            exp_y = y
                        if exp_m in (1, 3, 5, 7, 8, 10, 12):
                            last_d = 31
                        elif exp_m in (4, 6, 9, 11):
                            last_d = 30
                        else:
                            is_leap = exp_y % 4 == 0 and (exp_y % 100 != 0 or exp_y % 400 == 0)
                            last_d = 29 if is_leap else 28
                        exp_date = datetime.date(exp_y, exp_m, last_d)
                        return exp_date < cutoff_date
            return (cutoff_ts is not None) and (mtime < cutoff_ts)

        for folder in folders_to_clean:
            if not folder.exists() or not folder.is_dir():
                continue
            is_pub_folder = folder.name == "Publicacoes"
            for item in list(folder.iterdir()):
                try:
                    mtime = item.stat().st_mtime
                    if is_pub_folder:
                        # Publicações: ONLY purge if the publication issue is truly expired
                        if not _is_item_expired(item.name, mtime):
                            continue
                    elif keep_weeks > 0:
                        if not _is_item_expired(item.name, mtime):
                            continue

                    if item.is_file():
                        sz = item.stat().st_size
                        item.unlink()
                        total_freed += sz
                        deleted_files.append(f"{folder.name}/{item.name}")
                    elif item.is_dir():
                        dir_sz = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                        shutil.rmtree(item)
                        total_freed += dir_sz
                        deleted_files.append(f"{folder.name}/{item.name}/")
                except OSError as exc:
                    errors.append(f"Erro ao remover {item.name}: {exc}")

        return deleted_files, total_freed, errors

    def cleanup_storage(
        self,
        keep_weeks: int = 2,
        clean_app_cache: bool = True,
        clean_jwl_storage: bool = True,
    ) -> StorageCleanupResult:
        """Purges old meeting media across both the app cache and JW Library storage."""
        app_files: list[str] = []
        app_bytes = 0
        jwl_files: list[str] = []
        jwl_bytes = 0
        all_errors: list[str] = []

        if clean_app_cache:
            af, ab, aerr = self.cleanup_app_cache(keep_weeks=keep_weeks)
            app_files.extend(af)
            app_bytes += ab
            all_errors.extend(aerr)

        if clean_jwl_storage:
            jf, jb, jerr = cleanup_jwl_storage(
                keep_weeks=keep_weeks,
                db_path=self.jwl_db_path,
                remove_old_videos=True,
                remove_orphan_userdata=True,
            )
            jwl_files.extend(jf)
            jwl_bytes += jb
            all_errors.extend(jerr)

        total_bytes = app_bytes + jwl_bytes
        return StorageCleanupResult(
            success=True,
            app_files_deleted=app_files,
            app_bytes_freed=app_bytes,
            jwl_files_deleted=jwl_files,
            jwl_bytes_freed=jwl_bytes,
            total_bytes_freed=total_bytes,
            errors=all_errors,
        )

    def is_jwl_running(self) -> bool:
        """Checks if JW Library is currently running."""
        import psutil

        try:
            for proc in psutil.process_iter(["pid", "name"]):
                name = proc.info.get("name") or ""
                compact = name.casefold().replace(" ", "").replace("_", "").replace("-", "")
                if "jwlibrary" in compact and "signlanguage" not in compact:
                    return True
        except Exception:
            pass
        return False

    def restart_jwl(self) -> bool:
        """Terminates running instances of JW Library and relaunches it to refresh SQLite in-memory cache."""
        import subprocess
        import sys
        import time

        import psutil

        if sys.platform != "win32":
            return False

        # 1. Terminate running JWLibrary instances
        try:
            for proc in psutil.process_iter(["pid", "name"]):
                name = proc.info.get("name") or ""
                compact = name.casefold().replace(" ", "").replace("_", "").replace("-", "")
                if "jwlibrary" in compact and "signlanguage" not in compact:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
            time.sleep(0.5)
        except Exception:
            pass

        # 2. Launch JW Library
        from meeting_assistant.services.meeting_launcher import (
            _JWL_FALLBACK_AUMID,
            MeetingLauncherService,
        )

        aumid = MeetingLauncherService._discover_jwl_aumid() or _JWL_FALLBACK_AUMID
        try:
            subprocess.Popen(
                ["explorer.exe", rf"shell:AppsFolder\{aumid}"],
                close_fds=True,
            )
            return True
        except OSError:
            return False

