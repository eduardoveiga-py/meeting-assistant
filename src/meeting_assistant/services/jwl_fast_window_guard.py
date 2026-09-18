from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from meeting_assistant.services.display_service import DisplayInfo
from meeting_assistant.services.jwl_secondary_window import JwlSecondaryWindowInfo, WindowRect
from meeting_assistant.services.jwl_uia_secondary_window import choose_native_monitor_rect

try:
    import win32api
    import win32con
    import win32gui
except ImportError:  # pragma: no cover - Windows-only implementation
    win32api = None
    win32con = None
    win32gui = None


CandidateProvider = Callable[[], JwlSecondaryWindowInfo | None]
DisplayProvider = Callable[[], DisplayInfo | None]


def window_needs_recovery(
    *,
    minimized: bool,
    visible: bool,
    current_rect: WindowRect,
    target_rect: WindowRect,
    cloaked: bool = False,
    tolerance: int = 8,
) -> bool:
    """Return whether a known Hall-output HWND needs immediate repair."""

    if minimized or not visible or cloaked:
        return True
    return bool(
        abs(current_rect.left - target_rect.left) > tolerance
        or abs(current_rect.top - target_rect.top) > tolerance
        or abs(current_rect.width - target_rect.width) > tolerance
        or abs(current_rect.height - target_rect.height) > tolerance
    )


class JwlFastWindowGuard(QObject):
    """Keep a previously identified JW Library Hall window healthy via Win32.

    UI Automation is intentionally not used here. Once the UIA service has
    identified the correct HWND, this guard caches that identity and checks it
    at a high frequency using only very cheap Win32 calls. This keeps recovery
    latency independent from slower UIA discovery scans.
    """

    recovery_changed = Signal(bool)

    def __init__(
        self,
        candidate_provider: CandidateProvider,
        display_provider: DisplayProvider,
        *,
        interval_ms: int = 180,
    ) -> None:
        super().__init__()
        self._candidate_provider = candidate_provider
        self._display_provider = display_provider
        self._enabled = False
        self._cached: JwlSecondaryWindowInfo | None = None
        self._recovering = False
        self._last_recovery_reason = ""
        self._timer = QTimer(self)
        self._timer.setInterval(max(120, interval_ms))
        self._timer.timeout.connect(self._tick)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def recovering(self) -> bool:
        return self._recovering

    @property
    def cached_hwnd(self) -> int:
        return self._cached.hwnd if self._cached is not None else 0

    @property
    def last_recovery_reason(self) -> str:
        return self._last_recovery_reason

    def start(self) -> None:
        self._timer.start()
        self._tick()

    def stop(self) -> None:
        self._timer.stop()
        self._set_recovering(False)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._set_recovering(False)
            return
        self._tick()

    def _tick(self) -> None:
        if not self._enabled or win32gui is None or win32con is None:
            return

        target = self._display_provider()
        if target is None:
            return

        observed = self._candidate_provider()
        if observed is not None and self._is_valid_hwnd(observed.hwnd):
            # Cache only a candidate that belongs to the same monitor role as
            # the configured Hall display. A stale/main JW Library window must
            # never replace a previously verified Hall HWND.
            if observed.monitor_primary is None or observed.monitor_primary == target.primary:
                self._cached = observed

        item = self._cached
        if item is None or not self._is_valid_hwnd(item.hwnd):
            self._cached = None
            self._set_recovering(False)
            return

        current_rect = self._window_rect(item.hwnd)
        if current_rect is None:
            return
        target_rect = self._native_target_rect(target)
        minimized = self._is_minimized(item.hwnd)
        visible = self._is_visible(item.hwnd)
        cloaked = self._is_cloaked(item.hwnd)

        needs_recovery = window_needs_recovery(
            minimized=minimized,
            visible=visible,
            cloaked=cloaked,
            current_rect=current_rect,
            target_rect=target_rect,
        )
        if not needs_recovery:
            self._set_recovering(False)
            return

        if cloaked:
            self._last_recovery_reason = "dwm_cloaked"
        elif minimized:
            self._last_recovery_reason = "minimized"
        elif not visible:
            self._last_recovery_reason = "hidden"
        else:
            self._last_recovery_reason = "geometry"

        self._set_recovering(True)
        self._restore_without_activation(item.hwnd, target_rect, cloaked=cloaked)

        # A successful ShowWindow/SetWindowPos is normally visible immediately.
        # Confirm on the next 120–180 ms tick instead of blocking the UI thread.

    def _restore_without_activation(
        self,
        hwnd: int,
        target_rect: WindowRect,
        *,
        cloaked: bool = False,
    ) -> None:
        if win32gui is None or win32con is None:
            return
        try:
            if (
                win32gui.IsIconic(hwnd)
                or not win32gui.IsWindowVisible(hwnd)
                or cloaked
            ):
                # Show Desktop can make a top-level window disappear without
                # changing IsIconic/IsWindowVisible. Calling ShowWindow again
                # followed by SetWindowPos makes Explorer/DWM surface it again
                # without activating the operator's main JW Library window.
                win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)

            flags = (
                win32con.SWP_NOACTIVATE
                | win32con.SWP_SHOWWINDOW
                | win32con.SWP_ASYNCWINDOWPOS
            )
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_TOPMOST,
                target_rect.left,
                target_rect.top,
                target_rect.width,
                target_rect.height,
                flags,
            )
        except (OSError, RuntimeError):
            # The slower UIA service remains responsible for rediscovery if the
            # cached HWND became invalid between checks.
            return

    @staticmethod
    def _is_valid_hwnd(hwnd: int) -> bool:
        if hwnd <= 0 or win32gui is None:
            return False
        try:
            return bool(win32gui.IsWindow(hwnd))
        except (OSError, RuntimeError):
            return False

    @staticmethod
    def _is_visible(hwnd: int) -> bool:
        if win32gui is None:
            return True
        try:
            return bool(win32gui.IsWindowVisible(hwnd))
        except (OSError, RuntimeError):
            return True

    @staticmethod
    def _is_cloaked(hwnd: int) -> bool:
        if hwnd <= 0 or sys.platform != "win32":
            return False
        try:
            cloaked = ctypes.c_int(0)
            result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                ctypes.c_void_p(hwnd),
                ctypes.c_uint(14),  # DWMWA_CLOAKED
                ctypes.byref(cloaked),
                ctypes.sizeof(cloaked),
            )
            return result == 0 and bool(cloaked.value)
        except (AttributeError, OSError):
            return False

    @staticmethod
    def _is_minimized(hwnd: int) -> bool:
        if win32gui is None:
            return False
        try:
            return bool(win32gui.IsIconic(hwnd))
        except (OSError, RuntimeError):
            return False

    @staticmethod
    def _window_rect(hwnd: int) -> WindowRect | None:
        if win32gui is None:
            return None
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            return WindowRect(int(left), int(top), int(right), int(bottom))
        except (OSError, RuntimeError):
            return None

    @staticmethod
    def _native_target_rect(target: DisplayInfo) -> WindowRect:
        fallback = WindowRect(
            target.x,
            target.y,
            target.x + target.width,
            target.y + target.height,
        )
        if win32api is None:
            return fallback

        monitors: list[tuple[bool, WindowRect]] = []
        try:
            for monitor, _hdc, rect in win32api.EnumDisplayMonitors():
                info = win32api.GetMonitorInfo(monitor)
                left, top, right, bottom = info.get("Monitor", rect)
                monitors.append(
                    (
                        bool(int(info.get("Flags", 0)) & 1),
                        WindowRect(int(left), int(top), int(right), int(bottom)),
                    )
                )
        except (OSError, RuntimeError, TypeError, ValueError):
            return fallback
        return choose_native_monitor_rect(target, monitors)

    def _set_recovering(self, recovering: bool) -> None:
        if recovering == self._recovering:
            return
        self._recovering = recovering
        self.recovery_changed.emit(recovering)
