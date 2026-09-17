from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from json import dumps, loads
from os import environ
from pathlib import Path

DISPLAY_SETTINGS_VERSION = 1


@dataclass(slots=True)
class AppSettings:
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


class SettingsService:
    def __init__(self, path: Path | None = None) -> None:
        appdata = environ.get("APPDATA")
        if appdata:
            default_path = Path(appdata) / "MeetingAssistant" / "settings.json"
        else:
            default_path = Path.home() / ".meeting-assistant" / "settings.json"
        self.path = path or default_path

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            data = loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return AppSettings()

            # Antes de existir uma escolha de saída na interface, simulação=True era
            # apenas o default histórico. A primeira migração muda instalações antigas
            # para o novo padrão: segunda tela física quando disponível.
            legacy_display_settings = "display_settings_version" not in data

            known_fields = {field.name for field in fields(AppSettings)}
            filtered = {key: value for key, value in data.items() if key in known_fields}
            settings = AppSettings(**filtered)
            if legacy_display_settings:
                settings.display_settings_version = DISPLAY_SETTINGS_VERSION
                settings.simulation_enabled = False
                settings.hall_display_key = ""
            return settings
        except (OSError, TypeError, ValueError):
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        settings.display_settings_version = DISPLAY_SETTINGS_VERSION
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
