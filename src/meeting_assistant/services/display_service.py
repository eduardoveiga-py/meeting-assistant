from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication, QScreen


@dataclass(frozen=True, slots=True)
class DisplayInfo:
    key: str
    name: str
    manufacturer: str
    model: str
    serial: str
    x: int
    y: int
    width: int
    height: int
    primary: bool
    device_pixel_ratio: float

    @property
    def resolution(self) -> str:
        return f"{self.width}×{self.height}"


def build_display_key(
    *,
    name: str,
    manufacturer: str,
    model: str,
    serial: str,
    x: int,
    y: int,
    width: int,
    height: int,
) -> str:
    identity = "|".join(part.strip() for part in (manufacturer, model, serial) if part.strip())
    if identity:
        return identity
    return f"{name.strip()}|{x},{y}|{width}x{height}"


def display_info_from_screen(screen: QScreen, *, primary: bool) -> DisplayInfo:
    geometry = screen.geometry()
    name = screen.name() or "Monitor"
    manufacturer = screen.manufacturer() or ""
    model = screen.model() or ""
    serial = screen.serialNumber() or ""
    key = build_display_key(
        name=name,
        manufacturer=manufacturer,
        model=model,
        serial=serial,
        x=geometry.x(),
        y=geometry.y(),
        width=geometry.width(),
        height=geometry.height(),
    )
    return DisplayInfo(
        key=key,
        name=name,
        manufacturer=manufacturer,
        model=model,
        serial=serial,
        x=geometry.x(),
        y=geometry.y(),
        width=geometry.width(),
        height=geometry.height(),
        primary=primary,
        device_pixel_ratio=float(screen.devicePixelRatio()),
    )


class DisplayService(QObject):
    displays_changed = Signal(list)

    def __init__(self, app: QGuiApplication) -> None:
        super().__init__()
        self._app = app
        self._app.screenAdded.connect(self._emit_snapshot)
        self._app.screenRemoved.connect(self._emit_snapshot)
        self._app.primaryScreenChanged.connect(self._emit_snapshot)

    def start(self) -> None:
        self._emit_snapshot()

    def snapshot(self) -> list[DisplayInfo]:
        primary = self._app.primaryScreen()
        return [
            display_info_from_screen(screen, primary=screen is primary)
            for screen in self._app.screens()
        ]

    def _emit_snapshot(self, *_args: object) -> None:
        self.displays_changed.emit(self.snapshot())
