from __future__ import annotations

import base64
import json
import os
from pathlib import Path


class IdleReferenceStore:
    """Persiste uma amostra pequena do estado de repouso da saída do JW Library."""

    def __init__(self, path: Path | None = None) -> None:
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            default_path = (
                Path(local_appdata)
                / "MeetingAssistant"
                / "state"
                / "hall-idle-reference.json"
            )
        else:
            default_path = (
                Path.home()
                / ".meeting-assistant"
                / "state"
                / "hall-idle-reference.json"
            )
        self.path = path or default_path

    def load(self, key: str) -> bytes | None:
        if not key or not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("key") != key:
                return None
            encoded = payload.get("frame")
            if not isinstance(encoded, str):
                return None
            frame = base64.b64decode(encoded, validate=True)
            return frame or None
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def save(self, key: str, frame: bytes) -> None:
        if not key or not frame:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(
                {
                    "key": key,
                    "frame": base64.b64encode(frame).decode("ascii"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
