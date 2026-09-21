"""Versioned images with an atomic manifest; independent of sensor calibration."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

from PySide6.QtGui import QImage

_LOCK = threading.RLock()


def synchronized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _LOCK:
            return function(*args, **kwargs)
    return wrapped


class YeartextStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.manifest = directory / "current.json"

    @synchronized
    def current(self) -> dict | None:
        try:
            data = json.loads(self.manifest.read_text(encoding="utf-8"))
            name = data["file"]
            if not isinstance(name, str) or Path(name).name != name or not name.endswith(".png"):
                return None
            path = self.directory / name
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != data["sha256"]:
                return None
            image = QImage.fromData(content)
            if image.isNull() or type(data["year"]) is not int:
                return None
            if (image.width(), image.height()) != (data["width"], data["height"]):
                return None
            if not isinstance(data["captured_at"], str) or not isinstance(data["obs_pending"], bool):
                return None
            return {**data, "path": str(path)}
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def status(self, year: int | None = None) -> str:
        current = self.current()
        if current is None:
            return "Foto ausente ou inválida — criar foto do Texto do Ano."
        year = year or datetime.now().year
        if current["year"] != year:
            return f"Foto de {current['year']} — atualizar para o Texto do Ano de {year}."
        return f"Foto do Texto do Ano de {year} salva."

    def _commit(self, data: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.manifest)

    @synchronized
    def save(self, png: bytes, year: int) -> dict:
        image = QImage.fromData(png)
        if image.isNull() or not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("A captura não é uma imagem PNG válida.")
        if not 2000 <= year <= datetime.now().year + 1:
            raise ValueError("Confira o ano do texto exibido na imagem.")
        self.directory.mkdir(parents=True, exist_ok=True)
        name = f"yeartext-{year}-{uuid.uuid4().hex}.png"
        path = self.directory / name
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(png)
        temporary.replace(path)
        data = {
            "file": name,
            "sha256": hashlib.sha256(png).hexdigest(),
            "year": year,
            "captured_at": datetime.now().astimezone().isoformat(),
            "width": image.width(),
            "height": image.height(),
            "obs_pending": True,
        }
        # The old manifest and its immutable image remain valid if this step fails.
        self._commit(data)
        return {**data, "path": str(path)}

    @synchronized
    def mark_applied(self, digest: str, filename: str | None = None) -> None:
        current = self.current()
        if current and current["sha256"] == digest and (filename is None or current["file"] == filename):
            current.pop("path", None)
            current["obs_pending"] = False
            self._commit(current)
