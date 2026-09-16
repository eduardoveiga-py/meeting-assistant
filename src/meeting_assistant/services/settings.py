from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass(slots=True)
class AppSettings:
    always_on_top: bool = True
    simulation_enabled: bool = True
    obs_host: str = "127.0.0.1"
    obs_port: int = 4455
    obs_password: str = ""
    scene_background: str = "Texto do Ano"
    scene_speaker: str = "Palco"
    scene_media: str = "Mídias"
    scene_zoom: str = "Zoom"


class SettingsService:
    def __init__(self, path: Path | None = None) -> None:
        appdata = os.environ.get("APPDATA")
        if appdata:
            default_path = Path(appdata) / "MeetingAssistant" / "settings.json"
        else:
            default_path = Path.home() / ".meeting-assistant" / "settings.json"
        self.path = path or default_path

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            known_fields = {field.name for field in fields(AppSettings)}
            filtered = {key: value for key, value in data.items() if key in known_fields}
            return AppSettings(**filtered)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
