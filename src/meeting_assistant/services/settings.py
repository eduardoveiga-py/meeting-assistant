from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
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
    camera_source_name: str = "Meeting Assistant - Câmera IP"
    congregation_language: str = "T"
    auto_mute_mic_for_jwl_media: bool = True
    congregation_name: str = ""
    whatsapp_enabled: bool = False
    global_shortcuts: bool = False
    camera_ip: str = "10.0.0.40"
    camera_rtsp_port: int = 554
    camera_username: str = ""
    camera_password: str = ""
    camera_ip_user: str = ""
    camera_ip_pass: str = ""
    obs_start_at_logon: bool = False
    obs_standard_scenes: bool = False
    obs_executable: str = ""
    zoom_executable: str = ""
    telemetry_enabled: bool = True
    telemetry_sync_enabled: bool = False
    telemetry_screenshots: bool = False
    telemetry_repo_url: str = "https://github.com/eduardoveiga-py/meeting-assistant-diagnostics.git"
    window_layouts: dict = field(default_factory=dict)
    audio_profile: str = "shared"
    whatsapp_audio_device: str = ""
    audio_gains_db: dict = field(default_factory=dict)
    audio_sync_offsets_ms: dict = field(default_factory=dict)
    meeting_media_folder: str = ""
    jwl_userdata_db_path: str = ""
    meeting_media_quality: str = "720p"
    meeting_media_auto_sync: bool = False
    meeting_media_cleanup_after_import: bool = True

    def __post_init__(self) -> None:
        if self.camera_ip_user and not self.camera_username:
            self.camera_username = self.camera_ip_user
        elif self.camera_username and not self.camera_ip_user:
            self.camera_ip_user = self.camera_username
        if self.camera_ip_pass and not self.camera_password:
            self.camera_password = self.camera_ip_pass
        elif self.camera_password and not self.camera_ip_pass:
            self.camera_ip_pass = self.camera_password


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
            return AppSettings(obs_password=detect_obs_websocket_password())
        try:
            raw = self.path.read_bytes()
        except OSError:
            self.recovery_message = "Não foi possível ler os ajustes; usando valores padrão nesta sessão."
            return AppSettings(obs_password=detect_obs_websocket_password())
        try:
            data = loads(raw.decode("utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("Settings must be an object")

            # Support configuration aliases
            aliases = {
                "camera_username": ("camera_ip_user", "camera_user", "camera_ip_username"),
                "camera_password": ("camera_ip_pass", "camera_pass", "camera_ip_password"),
                "obs_password": ("obs_pass", "websocket_password", "obs_websocket_password"),
                "whatsapp_enabled": ("whatsapp", "use_whatsapp"),
            }
            for canonical, alias_keys in aliases.items():
                if canonical not in data or data[canonical] in ("", None):
                    for ak in alias_keys:
                        if ak in data and data[ak] not in ("", None):
                            data[canonical] = data[ak]
                            break

            if ("obs_password" not in data or data["obs_password"] in ("", None)) and isinstance(
                data.get("obs_password", ""), str
            ):
                detected = detect_obs_websocket_password()
                if detected:
                    data["obs_password"] = detected

            # Mirror camera aliases in data dictionary
            if data.get("camera_username") and not data.get("camera_ip_user"):
                data["camera_ip_user"] = data["camera_username"]
            elif data.get("camera_ip_user") and not data.get("camera_username"):
                data["camera_username"] = data["camera_ip_user"]

            if data.get("camera_password") and not data.get("camera_ip_pass"):
                data["camera_ip_pass"] = data["camera_password"]
            elif data.get("camera_ip_pass") and not data.get("camera_password"):
                data["camera_password"] = data["camera_ip_pass"]

            # Reset stale temporary jwl_userdata_db_path if missing on disk
            raw_db = data.get("jwl_userdata_db_path")
            if raw_db and not Path(raw_db).is_file():
                data["jwl_userdata_db_path"] = ""

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
                if valid and field.name == "window_layouts":
                    from meeting_assistant.services.window_layout import valid_layout

                    valid = valid_layout(value)
                if valid and field.name == "audio_profile":
                    valid = value in {"shared", "whatsapp_zoom"}
                if valid and field.name == "audio_gains_db":
                    import math

                    valid = all(
                        isinstance(k, str) and type(v) in (int, float) and math.isfinite(v) and -30 <= v <= 18
                        for k, v in value.items()
                    )
                if valid and field.name == "audio_sync_offsets_ms":
                    valid = all(
                        isinstance(k, str) and type(v) is int and -950 <= v <= 20000
                        for k, v in value.items()
                    )
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
            if not settings.obs_password:
                settings.obs_password = detect_obs_websocket_password()
            return settings
        except (UnicodeError, TypeError, ValueError):
            self._preserve_invalid(raw)
            return AppSettings(obs_password=detect_obs_websocket_password())

    def save(self, settings: AppSettings) -> None:
        if self._pending_backup is not None:
            backup, raw = self._pending_backup
            if not backup.exists():
                backup.write_bytes(raw)
            self._pending_backup = None
        settings.display_settings_version = DISPLAY_SETTINGS_VERSION
        if settings.camera_username and not settings.camera_ip_user:
            settings.camera_ip_user = settings.camera_username
        elif settings.camera_ip_user and not settings.camera_username:
            settings.camera_username = settings.camera_ip_user
        if settings.camera_password and not settings.camera_ip_pass:
            settings.camera_ip_pass = settings.camera_password
        elif settings.camera_ip_pass and not settings.camera_password:
            settings.camera_password = settings.camera_ip_pass
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)


def detect_obs_websocket_password() -> str:
    """Discovers OBS WebSocket password from local config if present."""
    appdata_env = environ.get("APPDATA")
    if appdata_env:
        obs_ws_cfg = (
            Path(appdata_env) / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"
        )
        if obs_ws_cfg.is_file():
            try:
                ws_raw = loads(obs_ws_cfg.read_text(encoding="utf-8"))
                ws_pwd = ws_raw.get("server_password")
                if isinstance(ws_pwd, str) and ws_pwd:
                    return ws_pwd
            except Exception:
                pass
    return ""

