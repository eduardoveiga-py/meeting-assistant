from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtGui import QImage


class HallIdleReferenceStore:
    """Persist the clean Hall idle frame used under the live media layer."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self.default_path()

    @staticmethod
    def default_path() -> Path:
        root = os.getenv("LOCALAPPDATA")
        filename = "hall-output-idle-reference-v1.png"
        if root:
            return Path(root) / "MeetingAssistant" / "state" / filename
        return Path.home() / ".meeting-assistant" / "state" / filename

    def load(self) -> QImage | None:
        if not self.path.exists():
            return None
        image = QImage(str(self.path))
        if image.isNull():
            return None
        return image

    def save(self, image: QImage) -> bool:
        if image.isNull():
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp.png")
        if not image.save(str(temp_path), "PNG"):
            return False
        os.replace(temp_path, self.path)
        return True

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
