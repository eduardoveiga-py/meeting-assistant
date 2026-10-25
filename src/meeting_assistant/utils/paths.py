"""Path resolution and application data directory utilities."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def get_resource_path(relative_path: str = "") -> Path:
    """Resolve resource path for both development and PyInstaller bundled mode.

    When bundled, sys._MEIPASS holds the temporary extraction directory.
    In development, the path is resolved relative to the package/repository.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
    else:
        # repo root
        base = Path(__file__).resolve().parents[3]

    if not relative_path:
        return base

    candidate = (base / relative_path).resolve()
    if candidate.exists():
        return candidate

    # Try under src/meeting_assistant/
    pkg_candidate = (base / "src" / "meeting_assistant" / relative_path).resolve()
    if pkg_candidate.exists():
        return pkg_candidate

    # Try under meeting_assistant/
    direct_candidate = (base / "meeting_assistant" / relative_path).resolve()
    if direct_candidate.exists():
        return direct_candidate

    return candidate


def get_appdata_dir() -> Path:
    """Return the application data directory (%LOCALAPPDATA%/MeetingAssistant or %APPDATA%)."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        directory = Path(base) / "MeetingAssistant"
    else:
        directory = Path.home() / ".meeting-assistant"
    directory.mkdir(parents=True, exist_ok=True)
    return directory
