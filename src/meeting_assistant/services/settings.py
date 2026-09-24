from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from hashlib import sha256
from json import dumps, loads
from os import environ
from pathlib import Path

DISPLAY_SETTINGS_VERSION = 1


@dataclass(slots=True)
class AppSettings:
    setup_review_version: str = ""
    always_on_top: bool = True
    display_settings_version: int = DISPLAY_SETTINGS_VERSION
    simulation_enabled: bool = False
    hall_display_key: str = ""
    obs_host: str = "127.0.0.1"
    obs_port: int = 4455
    obs_password: str = ""
    scene_background: str = "Texto do Ano"
    scene_speaker: str = "Palco"
    scene_media: str = "Mídias"
    scene_zoom: str = "Zoom"
    zoom_join_url: str = ""
    camera_ip: str = "10.0.0.40"
    camera_rtsp_port: int = 554
    camera_username: str = ""
    camera_password: str = ""
    obs_start_at_logon: bool = False
    obs_standard_scenes: bool = False
    obs_executable: str = ""
    zoom_executable: str = ""
    telemetry_enabled: bool = True
    telemetry_sync_enabled: bool = False
    telemetry_screenshots: bool = False
    telemetry_repo_url: str = ""


class SettingsService:
    def __init__(self, path: Path | None = None) -> None:
        appdata = environ.get("APPDATA")
        if appdata:
            default_path = Path(appdata) / "MeetingAssistant" / "settings.json"
        else:
            default_path = Path.home() / ".meeting-assistant" / "settings.json"
        self.path = path or default_path
        self.recovery_message = ""
        self._pending_backup: tuple[Path, bytes] | None = None

    def _preserve_invalid(self, raw: bytes) -> None:
        backup = self.path.with_name(f"{self.path.name}.invalid-{sha256(raw).hexdigest()[:12]}.bak")
        self._pending_backup = (backup, raw)
        try:
            if not backup.exists():
                backup.write_bytes(raw)
            self._pending_backup = None
            self.recovery_message = (
                "Ajustes inválidos recuperados; o arquivo original foi preservado em backup."
            )
        except OSError:
            self.recovery_message = (
                "Ajustes inválidos recuperados em memória; não foi possível criar o backup."
            )

    def load(self) -> AppSettings:
        self.recovery_message = ""
        if not self.path.exists():
            return AppSettings()
        try:
            raw = self.path.read_bytes()
        except OSError:
            self.recovery_message = "Não foi possível ler os ajustes; usando valores padrão nesta sessão."
            return AppSettings()
        try:
            data = loads(raw.decode("utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("Settings must be an object")

            legacy_display_settings = "display_settings_version" not in data
            defaults = AppSettings()
            filtered = {}
            invalid = False
            for field in fields(AppSettings):
                if field.name not in data:
                    continue
                value = data[field.name]
                default = getattr(defaults, field.name)
                valid = type(value) is type(default)
                if valid and field.name in {"obs_port", "camera_rtsp_port"}:
                    valid = 1 <= value <= 65535
                if valid and field.name == "display_settings_version":
                    valid = value >= 1
                if valid and field.name in {"obs_host", "scene_background", "scene_speaker", "scene_media"}:
                    valid = bool(value.strip())
                if valid:
                    filtered[field.name] = value
                else:
                    invalid = True
            settings = AppSettings(**filtered)
            scene_fields = ("scene_background", "scene_speaker", "scene_media")
            if len({getattr(settings, name) for name in scene_fields}) != 3:
                invalid = True
                for name in scene_fields:
                    setattr(settings, name, getattr(defaults, name))
            if invalid:
                self._preserve_invalid(raw)
            if legacy_display_settings:
                # simulation=True used to be a historical default, not an explicit
                # operator choice. Migrate once to the new physical-output default.
                settings.display_settings_version = DISPLAY_SETTINGS_VERSION
                settings.simulation_enabled = False
                settings.hall_display_key = ""
            return settings
        except (UnicodeError, TypeError, ValueError):
            self._preserve_invalid(raw)
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        if self._pending_backup is not None:
            backup, raw = self._pending_backup
            if not backup.exists():
                backup.write_bytes(raw)
            self._pending_backup = None
        settings.display_settings_version = DISPLAY_SETTINGS_VERSION
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
