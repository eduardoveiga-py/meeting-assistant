from __future__ import annotations

import ctypes
import sys
import time
from collections.abc import Callable

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

from meeting_assistant.services.display_service import DisplayInfo
from meeting_assistant.services.jwl_secondary_window import (
    JwlSecondaryWindowInfo,
    WindowRect,
    looks_like_jw_library_process,
    title_has_jw_library,
)
from meeting_assistant.services.jwl_uia_secondary_window import choose_native_monitor_rect
from meeting_assistant.services.native_window import show_window_async

try:
    import win32api
    import win32con
    import win32gui
    import win32process
except ImportError:  # pragma: no cover - Windows-only implementation
    win32api = None
    win32con = None
    win32gui = None
    win32process = None


CandidateProvider = Callable[[], JwlSecondaryWindowInfo | None]
DisplayProvider = Callable[[], DisplayInfo | None]


def window_needs_recovery(
    *,
    minimized: bool,
    visible: bool,
    current_rect: WindowRect,
    target_rect: WindowRect,
    cloaked: bool = False,
    covered: bool = False,
    tolerance: int = 8,
) -> bool:
    """Return whether a known Hall-output HWND needs immediate repair."""

    if minimized or not visible or cloaked or covered:
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
    recovery_detail = Signal(object)
    candidate_changed = Signal(int, str)
    shell_recovery_requested = Signal(int, int)

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
        self._last_fallback_probe_at = 0.0
        self._recovery_started_at = 0.0
        self._recovery_attempts = 0
        self._last_recovery_detail_at = 0.0
        self._last_shell_recovery_request_at = 0.0
        self._last_foreground_hwnd = 0
        self._normalized_hwnd = 0
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
    def cached_candidate(self) -> JwlSecondaryWindowInfo | None:
        return self._cached

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
                self._cache(observed, "uia")

        item = self._cached
        if item is None or not self._is_valid_hwnd(item.hwnd):
            if item is not None:
                self._clear_cache("invalid")
            now = time.monotonic()
            if now - self._last_fallback_probe_at >= 0.8:
                self._last_fallback_probe_at = now
                fallback = self._fallback_candidate_at_hall_center(target)
                if fallback is not None:
                    self._cache(fallback, "hall_center_win32")
            item = self._cached

        if item is None or not self._is_valid_hwnd(item.hwnd):
            self._set_recovering(False)
            return

        self._remember_foreground(item.hwnd)

        target_rect = self._native_target_rect(target)
        if self._normalized_hwnd != item.hwnd:
            if self._normalize_maximized_without_activation(item.hwnd, target_rect):
                self._normalized_hwnd = item.hwnd
                self.recovery_detail.emit(
                    {
                        "hwnd": item.hwnd,
                        "reason": "normalized_maximized",
                    }
                )

        current_rect = self._window_rect(item.hwnd)
        if current_rect is None:
            return
        minimized = self._is_minimized(item.hwnd)
        visible = self._is_visible(item.hwnd)
        cloak_state = self._cloak_state(item.hwnd)
        cloaked = cloak_state != 0
        covered = not self._is_exposed_at_center(item.hwnd, target_rect)

        needs_recovery = window_needs_recovery(
            minimized=minimized,
            visible=visible,
            cloaked=cloaked,
            covered=covered,
            current_rect=current_rect,
            target_rect=target_rect,
        )
        if not needs_recovery:
            self._set_recovering(False)
            return

        if cloak_state & 0x2:
            self._last_recovery_reason = "dwm_cloaked_shell"
        elif cloaked:
            self._last_recovery_reason = "dwm_cloaked"
        elif covered:
            self._last_recovery_reason = "covered_or_show_desktop"
        elif minimized:
            self._last_recovery_reason = "minimized"
        elif not visible:
            self._last_recovery_reason = "hidden"
        else:
            self._last_recovery_reason = "geometry"

        was_recovering = self._recovering
        self._set_recovering(True)
        if not was_recovering:
            self._recovery_started_at = time.monotonic()
            self._recovery_attempts = 0
        self._recovery_attempts += 1

        shell_cloaked = bool(cloak_state & 0x2)
        if shell_cloaked:
            now = time.monotonic()
            if now - self._last_shell_recovery_request_at >= 0.75:
                self._last_shell_recovery_request_at = now
                self.shell_recovery_requested.emit(
                    item.hwnd,
                    self._last_foreground_hwnd,
                )
            self._wait_for_shell_uncloak(item.hwnd, target_rect, cloak_state)
        else:
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
                show_window_async(hwnd, win32con.SW_SHOWNOACTIVATE)

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
        except Exception:  # noqa: BLE001 - best-effort Win32 recovery
            # The slower UIA service remains responsible for rediscovery if the
            # cached HWND became invalid between checks.
            return

    def _cache(self, candidate: JwlSecondaryWindowInfo, source: str) -> None:
        previous = self._cached.hwnd if self._cached is not None else 0
        self._cached = candidate
        if candidate.hwnd != previous:
            self.candidate_changed.emit(candidate.hwnd, source)

    def _clear_cache(self, source: str) -> None:
        if self._cached is None:
            return
        self._cached = None
        self._normalized_hwnd = 0
        self.candidate_changed.emit(0, source)

    def _fallback_candidate_at_hall_center(
        self,
        target: DisplayInfo,
    ) -> JwlSecondaryWindowInfo | None:
        if (
            win32gui is None
            or win32con is None
            or win32process is None
        ):
            return None
        if not self._jwl_process_running():
            return None

        target_rect = self._native_target_rect(target)
        center_x, center_y = target_rect.center
        try:
            point_hwnd = int(win32gui.WindowFromPoint((center_x, center_y)) or 0)
        except (OSError, RuntimeError):
            return None
        root = self._root_hwnd(point_hwnd)
        if root <= 0 or not self._is_valid_hwnd(root):
            return None

        try:
            class_name = win32gui.GetClassName(root)
            title = win32gui.GetWindowText(root).strip()
            _, pid = win32process.GetWindowThreadProcessId(root)
        except (OSError, RuntimeError):
            return None

        if class_name not in {"ApplicationFrameWindow", "Windows.UI.Core.CoreWindow"}:
            return None

        rect = self._window_rect(root)
        if rect is None or rect.width < 300 or rect.height < 180:
            return None

        # The Hall surface must substantially cover the native target monitor.
        overlap_left = max(rect.left, target_rect.left)
        overlap_top = max(rect.top, target_rect.top)
        overlap_right = min(rect.right, target_rect.right)
        overlap_bottom = min(rect.bottom, target_rect.bottom)
        if overlap_right <= overlap_left or overlap_bottom <= overlap_top:
            return None
        overlap_area = (overlap_right - overlap_left) * (overlap_bottom - overlap_top)
        target_area = max(1, target_rect.area)
        if overlap_area / target_area < 0.70:
            return None

        descendant_identity = self._has_jwl_descendant_identity(root)
        if not title_has_jw_library(title) and not descendant_identity:
            # On this Windows/JWL build the secondary ApplicationFrameWindow
            # can be shell-hosted and completely untitled. In that case the
            # combination of an active JWL process + a full-screen UWP surface
            # at the Hall monitor is the stable fallback identity.
            if class_name != "ApplicationFrameWindow":
                return None

        try:
            process_name = psutil.Process(int(pid)).name()
        except (psutil.Error, OSError):
            process_name = ""

        try:
            ex_style = int(win32gui.GetWindowLong(root, win32con.GWL_EXSTYLE))
            topmost = bool(ex_style & win32con.WS_EX_TOPMOST)
        except (OSError, RuntimeError):
            topmost = False

        return JwlSecondaryWindowInfo(
            hwnd=root,
            pid=int(pid),
            process_name=process_name,
            title=title,
            class_name=class_name,
            rect=rect,
            visible=self._is_visible(root),
            minimized=self._is_minimized(root),
            topmost=topmost,
            title_bar_visible=False,
            has_jwl_core_window=descendant_identity,
            monitor_primary=target.primary,
            score=900,
        )

    @staticmethod
    def _jwl_process_running() -> bool:
        try:
            for process in psutil.process_iter(["name"]):
                name = str(process.info.get("name") or "")
                if looks_like_jw_library_process(name):
                    return True
        except (psutil.Error, OSError):
            return False
        return False

    @staticmethod
    def _has_jwl_descendant_identity(hwnd: int) -> bool:
        if win32gui is None:
            return False
        found = False

        def callback(child: int, _extra: object) -> bool:
            nonlocal found
            try:
                child_title = win32gui.GetWindowText(child)
                child_class = win32gui.GetClassName(child)
                if title_has_jw_library(child_title):
                    found = True
                    return False
                if child_class == "Windows.UI.Core.CoreWindow":
                    # Some JWL builds leave the CoreWindow title blank; the
                    # surrounding full-screen ApplicationFrameWindow remains
                    # sufficient when a JW Library process is alive.
                    found = True
                    return False
            except (OSError, RuntimeError):
                pass
            return not found

        try:
            win32gui.EnumChildWindows(hwnd, callback, None)
        except (OSError, RuntimeError):
            return False
        return found

    def _wait_for_shell_uncloak(
        self,
        hwnd: int,
        target_rect: WindowRect,
        cloak_state: int,
    ) -> None:
        """Keep geometry ready while the virtual-desktop pin worker repairs cloak.

        DWMWA_CLOAKED_SHELL is owned by the Windows shell. Forcing foreground
        from another process is intentionally avoided: Windows may reject it,
        and repeated attempts can flood the Qt timer with pywintypes errors.
        The dedicated pin service makes the Hall view visible on every virtual
        desktop; once the shell removes its cloak, the normal fast guard takes
        over again.
        """

        self._restore_without_activation(hwnd, target_rect, cloaked=False)

        now = time.monotonic()
        if now - self._last_recovery_detail_at < 1.0:
            return
        self._last_recovery_detail_at = now
        self.recovery_detail.emit(
            {
                "hwnd": hwnd,
                "reason": "dwm_cloaked_shell_waiting_pin",
                "cloak_state": cloak_state,
                "attempt": self._recovery_attempts,
                "elapsed_ms": round(
                    max(0.0, now - self._recovery_started_at) * 1000
                ),
            }
        )

    def _remember_foreground(self, hall_hwnd: int) -> None:
        if win32gui is None:
            return
        try:
            hwnd = int(win32gui.GetForegroundWindow() or 0)
            if hwnd <= 0 or not win32gui.IsWindow(hwnd):
                return
            root = self._root_hwnd(hwnd)
            if root <= 0 or root == self._root_hwnd(hall_hwnd):
                return
            class_name = win32gui.GetClassName(root)
            if class_name in {"Progman", "WorkerW", "Shell_TrayWnd"}:
                return
            self._last_foreground_hwnd = root
        except (OSError, RuntimeError):
            return

    @staticmethod
    def _normalize_maximized_without_activation(
        hwnd: int,
        target_rect: WindowRect,
    ) -> bool:
        if win32gui is None or win32con is None:
            return False
        try:
            placement = win32gui.GetWindowPlacement(hwnd)
            if not placement or len(placement) < 5:
                return False
            flags, _show_cmd, min_pos, max_pos, normal_rect = placement
            win32gui.SetWindowPlacement(
                hwnd,
                (
                    flags,
                    win32con.SW_SHOWMAXIMIZED,
                    min_pos,
                    max_pos,
                    normal_rect,
                ),
            )
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_TOPMOST,
                target_rect.left,
                target_rect.top,
                target_rect.width,
                target_rect.height,
                win32con.SWP_NOACTIVATE
                | win32con.SWP_SHOWWINDOW
                | win32con.SWP_ASYNCWINDOWPOS,
            )
            return True
        except Exception:  # noqa: BLE001 - best-effort shell normalization
            return False

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
    def _root_hwnd(hwnd: int) -> int:
        if hwnd <= 0 or win32gui is None or win32con is None:
            return hwnd
        try:
            root = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
            return int(root or hwnd)
        except (AttributeError, OSError, RuntimeError):
            return hwnd

    @classmethod
    def _is_exposed_at_center(cls, hwnd: int, target_rect: WindowRect) -> bool:
        if win32gui is None:
            return True
        center_x = target_rect.left + max(1, target_rect.width // 2)
        center_y = target_rect.top + max(1, target_rect.height // 2)
        try:
            visible_hwnd = int(win32gui.WindowFromPoint((center_x, center_y)) or 0)
        except (OSError, RuntimeError):
            return True
        if visible_hwnd <= 0:
            return False
        return cls._root_hwnd(visible_hwnd) == cls._root_hwnd(hwnd)

    @staticmethod
    def _cloak_state(hwnd: int) -> int:
        if hwnd <= 0 or sys.platform != "win32":
            return 0
        try:
            cloaked = ctypes.c_int(0)
            result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                ctypes.c_void_p(hwnd),
                ctypes.c_uint(14),  # DWMWA_CLOAKED
                ctypes.byref(cloaked),
                ctypes.sizeof(cloaked),
            )
            return int(cloaked.value) if result == 0 else 0
        except (AttributeError, OSError):
            return 0

    @staticmethod
    def _is_cloaked(hwnd: int) -> bool:
        return JwlFastWindowGuard._cloak_state(hwnd) != 0

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
        if not recovering:
            self._recovery_started_at = 0.0
            self._recovery_attempts = 0
        self.recovery_changed.emit(recovering)

