from __future__ import annotations

import os
import subprocess
from pathlib import Path

from meeting_assistant.services.jwl_media_importer import (
    MediaImportItem,
    MediaImportResult,
    import_media_to_jwl,
    install_jwpub_to_jwl,
)
from meeting_assistant.services.meeting_media_downloader import extract_images_from_jwpub

SUPPORTED_EXTENSIONS = {
    ".mp4",
    ".m4v",
    ".mp3",
    ".m4a",
    ".wav",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".jwpub",
}


def get_default_meeting_media_folder() -> Path:
    """Returns the default folder used to store meeting media (in Downloads or user home)."""
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        downloads = Path(user_profile) / "Downloads" / "MeetingMedia"
    else:
        downloads = Path.home() / "MeetingMedia"
    downloads.mkdir(parents=True, exist_ok=True)
    return downloads


def scan_watch_folder(folder: Path) -> list[Path]:
    """Scans the watch folder for supported media files, returning sorted file paths."""
    if not folder.is_dir():
        return []

    found: list[Path] = []
    for item in sorted(folder.rglob("*")):
        if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
            found.append(item)
    return found


def convert_files_to_import_items(files: list[Path]) -> list[MediaImportItem]:
    """Converts local files to MediaImportItem objects with clean display labels."""
    items: list[MediaImportItem] = []
    for f in files:
        if f.suffix.lower() == ".jwpub":
            try:
                install_jwpub_to_jwl(f)
                img_dir = f.parent / f"{f.stem}_imagens"
                extracted = extract_images_from_jwpub(f, img_dir)
                for img in sorted(extracted):
                    label = img.stem.replace("_", " ").strip()
                    items.append(
                        MediaImportItem(
                            source_path=img,
                            label=label or img.name,
                            end_action=2,
                        )
                    )
            except Exception:
                pass
            continue
        label = f.stem.replace("_", " ").strip()
        items.append(
            MediaImportItem(
                source_path=f,
                label=label or f.name,
                end_action=2,
            )
        )
    return items


def sync_watch_folder_to_jwl(
    folder: Path,
    playlist_name: str = "Mídias do Salão",
    db_path: Path | None = None,
) -> MediaImportResult:
    """Scans the watch folder and imports all found media into the specified JW Library playlist."""
    files = scan_watch_folder(folder)
    if not files:
        return MediaImportResult(
            success=False,
            error_message=f"Nenhum arquivo de mídia encontrado na pasta: {folder}",
        )

    items = convert_files_to_import_items(files)
    res = import_media_to_jwl(items, playlist_name, db_path=db_path, backup=True)
    try:
        import re

        from meeting_assistant.services.jwlibrary_backup_exporter import export_playlist_to_jwlplaylist

        clean_name = re.sub(r'[\\/*?:"<>|]', "_", playlist_name).strip() or "Playlist"
        pkg_file = folder / f"{clean_name}.jwlplaylist"
        export_playlist_to_jwlplaylist(items, playlist_name, pkg_file)
        res.package_path = pkg_file
    except Exception:
        pass
    return res


def open_folder_in_explorer(folder: Path) -> None:
    """Reveals the folder in Windows File Explorer as a reliable manual drag/drop fallback."""
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(folder))
        else:
            subprocess.Popen(["explorer.exe", str(folder)])
    except Exception:
        try:
            subprocess.Popen(["explorer.exe", str(folder)])
        except Exception:
            pass
