"""Window manager with UWP application resolution and multi-monitor projection protection."""

from __future__ import annotations

import logging
from typing import Any

import psutil

try:
    import win32api
    import win32con
    import win32gui
    import win32process
except ImportError:
    win32api = None
    win32con = None
    win32gui = None
    win32process = None

logger = logging.getLogger(__name__)


class WindowManager:
    """Manages window discovery, UWP wrapper resolution, and multi-monitor projection constraints."""

    @staticmethod
    def get_real_window_process(hwnd: int) -> tuple[int, str]:
        """Obtain the real process ID and executable name, unwrapping UWP ApplicationFrameHost."""
        if not win32gui or not win32process or not hwnd:
            return 0, ""

        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if not pid:
                return 0, ""

            try:
                proc = psutil.Process(pid)
                exe_name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return pid, ""

            # If it's an ApplicationFrameHost wrapper (UWP app like JW Library)
            if exe_name.casefold() == "applicationframehost.exe":
                child_hwnds: list[int] = []

                def enum_child(child_hwnd: int, _lparam: Any) -> bool:
                    child_hwnds.append(child_hwnd)
                    return True

                try:
                    win32gui.EnumChildWindows(hwnd, enum_child, None)
                except Exception:
                    pass

                for child in child_hwnds:
                    try:
                        cls_name = win32gui.GetClassName(child)
                        _, c_pid = win32process.GetWindowThreadProcessId(child)
                        if c_pid and c_pid != pid:
                            try:
                                c_proc = psutil.Process(c_pid)
                                c_exe = c_proc.name()
                                if c_exe.casefold() != "applicationframehost.exe":
                                    return c_pid, c_exe
                            except Exception:
                                pass
                        elif cls_name == "Windows.UI.Core.CoreWindow":
                            if c_pid:
                                try:
                                    c_proc = psutil.Process(c_pid)
                                    c_exe = c_proc.name()
                                    if c_exe.casefold() != "applicationframehost.exe":
                                        return c_pid, c_exe
                                except Exception:
                                    pass
                    except Exception:
                        continue

            return pid, exe_name
        except Exception as exc:
            logger.debug("Error obtaining process for hwnd %s: %s", hwnd, exc)
            return 0, ""

    @classmethod
    def find_windows_by_executable(cls, executable_name: str, visible_only: bool = True) -> list[int]:
        """Find window handles corresponding to an executable (Win32 or UWP)."""
        if not win32gui:
            return []

        target = executable_name.casefold()
        matched: list[int] = []

        def enum_top_window(hwnd: int, _lparam: Any) -> bool:
            if visible_only and not win32gui.IsWindowVisible(hwnd):
                return True

            pid, exe = cls.get_real_window_process(hwnd)
            if exe.casefold() == target:
                matched.append(hwnd)
            return True

        try:
            win32gui.EnumWindows(enum_top_window, None)
        except Exception:
            pass

        return matched

    @staticmethod
    def get_monitors_info() -> list[dict[str, Any]]:
        """Identify connected monitors via win32api.EnumDisplayMonitors."""
        monitors: list[dict[str, Any]] = []
        if not win32api:
            return monitors

        try:
            enum_mons = win32api.EnumDisplayMonitors()
            for h_mon, _h_dc, rect in enum_mons:
                info = win32api.GetMonitorInfo(h_mon)
                is_primary = bool(info.get("Flags", 0) & 1)  # MONITORINFOF_PRIMARY = 1
                monitors.append({
                    "handle": h_mon,
                    "rect": tuple(rect),  # (left, top, right, bottom)
                    "work_rect": tuple(info.get("Work", rect)),
                    "primary": is_primary,
                })
        except Exception as exc:
            logger.debug("Error enumerating display monitors: %s", exc)

        return monitors

    @classmethod
    def enforce_secondary_screen_protection(
        cls,
        media_hwnd: int,
        secondary_monitor_rect: tuple[int, int, int, int] | None = None,
        control_hwnds: list[int] | None = None,
    ) -> bool:
        """Positions media window on secondary screen without stealing focus (SWP_NOACTIVATE).

        Also verifies that control windows do not overlap into the secondary screen.
        """
        if not win32gui or not win32con:
            return False

        if not secondary_monitor_rect:
            monitors = cls.get_monitors_info()
            secondary = next((m for m in monitors if not m["primary"]), None)
            if secondary:
                secondary_monitor_rect = secondary["rect"]
            elif monitors:
                secondary_monitor_rect = monitors[0]["rect"]

        if not secondary_monitor_rect:
            return False

        left, top, right, bottom = secondary_monitor_rect
        width = right - left
        height = bottom - top

        # Protect and position media projection window
        if media_hwnd and win32gui.IsWindow(media_hwnd):
            try:
                flags = win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW
                win32gui.SetWindowPos(
                    media_hwnd,
                    win32con.HWND_TOP,
                    left,
                    top,
                    width,
                    height,
                    flags,
                )
            except Exception as exc:
                logger.warning("Failed positioning secondary media window: %s", exc)
                return False

        # Protect secondary screen from invasion by control dialogs/windows
        if control_hwnds:
            for c_hwnd in control_hwnds:
                if c_hwnd and win32gui.IsWindow(c_hwnd):
                    try:
                        c_rect = win32gui.GetWindowRect(c_hwnd)
                        c_left, c_top, c_right, c_bottom = c_rect
                        if not (c_right <= left or c_left >= right or c_bottom <= top or c_top >= bottom):
                            primary = next((m for m in cls.get_monitors_info() if m["primary"]), None)
                            if primary:
                                p_left, p_top, _, _ = primary["rect"]
                                win32gui.SetWindowPos(
                                    c_hwnd,
                                    win32con.HWND_NOTOPMOST,
                                    p_left + 50,
                                    p_top + 50,
                                    c_right - c_left,
                                    c_bottom - c_top,
                                    win32con.SWP_NOACTIVATE,
                                )
                    except Exception:
                        pass

        return True
