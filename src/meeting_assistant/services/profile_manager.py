"""Typed profile management with atomic persistence and safe recovery."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from meeting_assistant.services.settings import AppSettings
from meeting_assistant.utils.paths import get_appdata_dir


@dataclass
class MeetingProfile:
    obs_host: str = "localhost"
    obs_port: int = 4455
    obs_password: str = ""
    scene_camera: str = "Palco"
    scene_media: str = "Mídias"
    scene_screenshare: str = "Compartilhamento"
    scene_safe: str = "Texto do Ano"
    mic_input_name: str = "Meeting Assistant - Mesa"
    media_input_name: str = "Meeting Assistant - Mídia"
    virtual_cable_name: str = "CABLE"
    media_player_executables: list[str] = field(
        default_factory=lambda: ["JWLibrary.exe", "vlc.exe", "MediaPlayer.exe"]
    )
    zoom_executable: str = "Zoom.exe"
    audio_trigger_threshold: float = 0.015
    audio_silence_hold_seconds: float = 4.5
    secondary_monitor_index: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MeetingProfile:
        valid_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


class ProfileManager:
    """Manages profile loading and atomic saving to disk."""

    def __init__(self, path: Path | None = None) -> None:
        if path is not None:
            self.path = Path(path)
        else:
            self.path = get_appdata_dir() / "profiles" / "default_profile.json"
        self.recovery_message: str = ""

    def load(self) -> MeetingProfile:
        self.recovery_message = ""
        if not self.path.exists():
            return MeetingProfile()
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Profile payload must be a JSON object")
            return MeetingProfile.from_dict(data)
        except Exception as exc:
            self.recovery_message = f"Perfil corrompido restaurado aos padrões: {exc}"
            try:
                backup = self.path.with_suffix(".corrupt.bak")
                if self.path.exists() and not backup.exists():
                    backup.write_bytes(self.path.read_bytes())
            except Exception:
                pass
            return MeetingProfile()

    def save(self, profile: MeetingProfile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        data = profile.to_dict()
        temp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(self.path)

    @staticmethod
    def sync_from_app_settings(settings: AppSettings) -> MeetingProfile:
        return MeetingProfile(
            obs_host=settings.obs_host,
            obs_port=settings.obs_port,
            obs_password=settings.obs_password,
            scene_camera=settings.scene_speaker,
            scene_media=settings.scene_media,
            scene_safe=settings.scene_background,
            scene_screenshare=getattr(settings, "scene_zoom", "Compartilhamento"),
            zoom_executable=settings.zoom_executable,
        )

    @staticmethod
    def apply_to_app_settings(profile: MeetingProfile, settings: AppSettings) -> AppSettings:
        settings.obs_host = profile.obs_host
        settings.obs_port = profile.obs_port
        settings.obs_password = profile.obs_password
        settings.scene_speaker = profile.scene_camera
        settings.scene_media = profile.scene_media
        settings.scene_background = profile.scene_safe
        settings.zoom_executable = profile.zoom_executable
        return settings
