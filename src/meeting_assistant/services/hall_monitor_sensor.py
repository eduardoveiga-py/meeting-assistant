from __future__ import annotations

import sys
from dataclasses import dataclass

from meeting_assistant.services.display_service import DisplayInfo
from meeting_assistant.services.jwl_screen_sensor import CaptureRegion

try:
    import win32api
except ImportError:  # pragma: no cover - Windows-only implementation
    win32api = None


@dataclass(frozen=True, slots=True)
class NativeMonitorInfo:
    device: str
    primary: bool
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def native_monitor_score(native: NativeMonitorInfo, target: DisplayInfo) -> float:
    score = 0.0
    if native.primary == target.primary:
        score += 10_000.0
    else:
        score -= 10_000.0

    expected_width = max(1.0, target.width * target.device_pixel_ratio)
    expected_height = max(1.0, target.height * target.device_pixel_ratio)
    size_error = abs(native.width - expected_width) + abs(native.height - expected_height)
    score -= size_error

    # On mixed-DPI desktops Qt can report logical size while preserving the
    # native monitor origin. Matching the origin is therefore useful evidence.
    score -= abs(native.left - target.x) * 0.25
    score -= abs(native.top - target.y) * 0.25
    return score


def choose_native_monitor(
    monitors: list[NativeMonitorInfo],
    target: DisplayInfo,
) -> NativeMonitorInfo | None:
    if not monitors:
        return None
    matching_role = [item for item in monitors if item.primary == target.primary]
    pool = matching_role or monitors
    return max(pool, key=lambda item: native_monitor_score(item, target))


def central_capture_region(monitor: NativeMonitorInfo) -> CaptureRegion:
    # Ignore the outer 6% so taskbars, borders and transient edge overlays do
    # not dominate the media classifier. The audience content remains central.
    margin_x = max(0, int(monitor.width * 0.06))
    margin_y = max(0, int(monitor.height * 0.06))
    return CaptureRegion(
        hwnd=0,
        left=monitor.left + margin_x,
        top=monitor.top + margin_y,
        width=max(320, monitor.width - (2 * margin_x)),
        height=max(180, monitor.height - (2 * margin_y)),
    )


class HallMonitorSensorRegionProvider:
    """Resolve the configured Hall display to native Win32 capture pixels."""

    def __init__(self, display_provider) -> None:
        self._display_provider = display_provider

    def __call__(self) -> CaptureRegion | None:
        target = self._display_provider()
        if target is None:
            return None
        native = choose_native_monitor(self._native_monitors(), target)
        return central_capture_region(native) if native else None

    @staticmethod
    def _native_monitors() -> list[NativeMonitorInfo]:
        if sys.platform != "win32" or win32api is None:
            return []
        result: list[NativeMonitorInfo] = []
        try:
            monitors = win32api.EnumDisplayMonitors()
        except (OSError, RuntimeError):
            return result

        for handle, _hdc, _rect in monitors:
            try:
                info = win32api.GetMonitorInfo(handle)
                left, top, right, bottom = info["Monitor"]
                result.append(
                    NativeMonitorInfo(
                        device=str(info.get("Device", "")),
                        primary=bool(int(info.get("Flags", 0)) & 1),
                        left=int(left),
                        top=int(top),
                        right=int(right),
                        bottom=int(bottom),
                    )
                )
            except (OSError, RuntimeError, TypeError, ValueError, KeyError):
                continue
        return result
