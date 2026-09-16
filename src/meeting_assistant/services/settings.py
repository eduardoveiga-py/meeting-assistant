from __future__ import annotations

import json
from dataclasses import asdict, dataclass
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


class SettingsService:
    def __init__(self, path: Path | None = None) -> None:
        default_path = (
            Path.home()
            / "AppData"
            / "Roaming"
            / "MeetingAssistant"
            / "settings.json"
        )
        self.path = path or default_path

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return AppSettings(**data)
        except (OSError, json.JSONDecodeError, TypeError):
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
