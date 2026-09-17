from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path

REFERENCE_VERSION = 1


@dataclass(frozen=True, slots=True)
class JwlIdleReference:
    pixels: bytes
    sample_width: int
    sample_height: int
    crop_version: int = 1


class JwlIdleReferenceStore:
    """Persist the visual signature of the JW Library Hall idle screen."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self.default_path()

    @staticmethod
    def default_path() -> Path:
        root = os.getenv("LOCALAPPDATA")
        if root:
            return Path(root) / "MeetingAssistant" / "state" / "jwl-secondary-idle-v1.json"
        return Path.home() / ".meeting-assistant" / "state" / "jwl-secondary-idle-v1.json"

    def load(self) -> JwlIdleReference | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != REFERENCE_VERSION:
                return None
            pixels = base64.b64decode(str(data["pixels"]), validate=True)
            width = int(data["sample_width"])
            height = int(data["sample_height"])
            crop_version = int(data.get("crop_version", 1))
            if width <= 0 or height <= 0 or len(pixels) != width * height:
                return None
            return JwlIdleReference(
                pixels=pixels,
                sample_width=width,
                sample_height=height,
                crop_version=crop_version,
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def save(self, reference: JwlIdleReference) -> None:
        if (
            reference.sample_width <= 0
            or reference.sample_height <= 0
            or len(reference.pixels)
            != reference.sample_width * reference.sample_height
        ):
            raise ValueError("referência visual inválida")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": REFERENCE_VERSION,
            "sample_width": reference.sample_width,
            "sample_height": reference.sample_height,
            "crop_version": reference.crop_version,
            "pixels": base64.b64encode(reference.pixels).decode("ascii"),
        }
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_path, self.path)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
