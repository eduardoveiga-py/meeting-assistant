"""Role-specific, monitor-relative layouts; secondary Hall windows are excluded."""

import math
import threading
from copy import deepcopy

from PySide6.QtCore import QObject, QTimer, Signal

from meeting_assistant.services.window_inventory import WindowBackend, main_jwl


def encode_rect(rect, monitor):
    left, top, right, bottom = monitor["work"]
    width, height = right - left, bottom - top
    return {
        "monitor": monitor["name"],
        "relative": [
            (rect[0] - left) / width,
            (rect[1] - top) / height,
            (rect[2] - rect[0]) / width,
            (rect[3] - rect[1]) / height,
        ],
    }


def decode_rect(record, monitors, *, minimum=(320, 240)):
    values = record.get("relative", []) if isinstance(record, dict) else []
    if len(values) != 4 or not all(type(v) in (int, float) and math.isfinite(v) for v in values):
        return None
    monitor = next((m for m in monitors if m["name"] == record.get("monitor")), None)
    monitor = monitor or next((m for m in monitors if m["primary"]), None)
    if not monitor:
        return None
    left, top, right, bottom = monitor["work"]
    width, height = right - left, bottom - top
    w = min(width, max(minimum[0], round(values[2] * width)))
    h = min(height, max(minimum[1], round(values[3] * height)))
    x = min(right - w, max(left, left + round(values[0] * width)))
    y = min(bottom - h, max(top, top + round(values[1] * height)))
    return x, y, x + w, y + h


def valid_layout(data):
    if not isinstance(data, dict):
        return False
    if not data:
        return True
    if data.get("version") == 2:
        roles = data.get("roles")
        if not isinstance(roles, dict) or not set(roles).issubset({"app", "jwl_main"}):
            return False
        for record in roles.values():
            if not isinstance(record, dict) or not isinstance(record.get("monitor"), str):
                return False
            relative = record.get("relative")
            if (
                not isinstance(relative, list)
                or len(relative) != 4
                or not all(type(v) in (int, float) and math.isfinite(v) for v in relative)
                or relative[2] <= 0
                or relative[3] <= 0
            ):
                return False
        return True
    # Old records are loaded only for the app geometry migration. JWL/Zoom
    # records remain untouched until replaced with an unambiguous role snapshot.
    return all(
        isinstance(value, list) and len(value) == 4 and all(type(v) is int for v in value)
        for value in data.values()
    )


class WindowLayoutService(QObject):
    captured = Signal(object)
    status_changed = Signal(str)

    def __init__(self, settings_provider, secondary_provider, *, backend=None):
        super().__init__()
        self._settings_provider = settings_provider
        self._secondary_provider = secondary_provider
        self.backend = backend or WindowBackend()
        self._thread = None
        self._cancel = threading.Event()
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.capture)
        self.latest = {}
        self.captured.connect(self._cache)

    def _cache(self, layout):
        self.latest.setdefault("version", 2)
        self.latest.setdefault("roles", {}).update(layout.get("roles", {}))

    def start(self):
        self._timer.start()
        self.capture()

    def stop(self):
        self._timer.stop()
        self._cancel.set()

    def _request(self, restore=False, app_fraction=0.4):
        if self._thread and self._thread.is_alive():
            return False
        # Providers are read on the GUI thread. Workers receive immutable copies.
        secondary = self._secondary_provider()
        secondary_hwnd = getattr(secondary, "hwnd", 0)
        settings = deepcopy(self._settings_provider().window_layouts)
        self._cancel.clear()

        def work():
            try:
                monitors = self.backend.monitors()
                primary = next((m for m in monitors if m["primary"]), None)
                if not primary or self._cancel.is_set():
                    return
                windows = self.backend.windows()
                jwl = main_jwl(windows, primary["work"], secondary_hwnd)
                if not jwl or (jwl.minimized and not restore):
                    self.status_changed.emit(
                        "Disposição: janela principal JWL ausente ou ambígua; secundária preservada."
                    )
                    return
                if restore:
                    record = (
                        settings.get("roles", {}).get("jwl_main") if settings.get("version") == 2 else None
                    )
                    rect = decode_rect(record, monitors) if record else None
                    if not rect:
                        left, top, right, bottom = primary["work"]
                        split = left + round((right - left) * min(0.65, max(0.15, app_fraction)))
                        rect = (split, top, right, bottom)
                    self.backend.restore(jwl, rect)
                    for window in windows:
                        if window.process in {"obs64.exe", "obs32.exe"} and window.title.startswith("OBS"):
                            self.backend.minimize(window)
                        elif window.process == "zoom.exe" and (
                            window.meeting_controls
                            or window.class_name
                            in {
                                "ZPPTopWndClass",
                                "ConfMultiTabContentWndClass",
                            }
                        ):
                            self.backend.minimize(window)
                    self.status_changed.emit(
                        "Disposição aplicada à janela principal JWL; telas secundárias preservadas."
                    )
                if restore:
                    jwl = main_jwl(self.backend.windows(), primary["work"], secondary_hwnd) or jwl
                if not self._cancel.is_set():
                    self.captured.emit({"version": 2, "roles": {"jwl_main": encode_rect(jwl.rect, primary)}})
            except Exception:
                self.status_changed.emit(
                    "Disposição não confirmada. Abra o JWL na tela principal e tente novamente."
                )

        self._thread = threading.Thread(target=work, daemon=True, name="Window layout")
        self._thread.start()
        return True

    def capture(self):
        return self._request()

    def restore(self, app_fraction=0.4):
        return self._request(True, app_fraction)
