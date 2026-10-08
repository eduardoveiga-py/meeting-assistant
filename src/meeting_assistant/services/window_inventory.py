"""Win32 inventory with UWP child-process identity and process reuse checks.

All enumeration is performed by service workers, never by widget callbacks.
"""

import os
import sys
from dataclasses import dataclass

import psutil

from meeting_assistant.services.jwl_secondary_window import is_explicit_jwl_secondary_title


@dataclass(frozen=True)
class NativeWindow:
    hwnd: int
    pid: int
    created: float
    process: str
    title: str
    class_name: str
    rect: tuple
    placement: tuple
    visible: bool
    minimized: bool
    topmost: bool = False
    style: int = 0
    extended_style: int = 0
    meeting_controls: bool = False


def is_jwl(window):
    return window.process.casefold() == "jwlibrary.exe"


def main_jwl(windows, primary_work, secondary_hwnd=0):
    left, top, right, bottom = primary_work
    candidates = []
    for window in windows:
        if (
            not is_jwl(window)
            or window.hwnd == secondary_hwnd
            or is_explicit_jwl_secondary_title(window.title)
        ):
            continue
        x1, y1, x2, y2 = window.rect
        overlap = max(0, min(right, x2) - max(left, x1)) * max(0, min(bottom, y2) - max(top, y1))
        if overlap > 0:
            candidates.append(window)
    return candidates[0] if len(candidates) == 1 else None


class WindowBackend:
    def windows(self):
        if sys.platform != "win32":
            return []
        import pywintypes
        import win32gui
        import win32process

        result = []

        def append(hwnd, _):
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process = psutil.Process(pid)
                name = process.name().casefold()
                if name == "applicationframehost.exe":
                    identities = []

                    def child_identity(child, _):
                        try:
                            _, child_pid = win32process.GetWindowThreadProcessId(child)
                            child_process = psutil.Process(child_pid)
                            if child_process.name().casefold() != "applicationframehost.exe":
                                identities.append(child_process)
                        except (psutil.Error, pywintypes.error):
                            return

                    win32gui.EnumChildWindows(hwnd, child_identity, None)
                    unique = {p.pid: p for p in identities}
                    jwl_procs = [p for p in unique.values() if p.name().casefold() == "jwlibrary.exe"]
                    if jwl_procs:
                        process = jwl_procs[0]
                    elif len(unique) == 1:
                        process = next(iter(unique.values()))
                    else:
                        return
                    pid, name = process.pid, process.name().casefold()
                if pid == os.getpid():
                    return
                meeting_controls = False
                if name == "zoom.exe":

                    def inspect_child(child, _):
                        nonlocal meeting_controls
                        try:
                            if win32gui.GetClassName(child) == "ConfMultiTabContentWndClass":
                                meeting_controls = True
                        except pywintypes.error:
                            return

                    win32gui.EnumChildWindows(hwnd, inspect_child, None)
                placement = win32gui.GetWindowPlacement(hwnd)
                result.append(
                    NativeWindow(
                        hwnd,
                        pid,
                        process.create_time(),
                        name,
                        win32gui.GetWindowText(hwnd),
                        win32gui.GetClassName(hwnd),
                        win32gui.GetWindowRect(hwnd),
                        placement,
                        bool(win32gui.IsWindowVisible(hwnd)),
                        bool(win32gui.IsIconic(hwnd)),
                        bool(win32gui.GetWindowLong(hwnd, -20) & 8),
                        win32gui.GetWindowLong(hwnd, -16),
                        win32gui.GetWindowLong(hwnd, -20),
                        meeting_controls,
                    )
                )
            except (OSError, psutil.Error, pywintypes.error):
                return

        win32gui.EnumWindows(append, None)
        return result

    def monitors(self):
        if sys.platform != "win32":
            return []
        import win32api

        result = []
        for handle, _, _ in win32api.EnumDisplayMonitors():
            info = win32api.GetMonitorInfo(handle)
            result.append(
                {
                    "name": info["Device"],
                    "work": tuple(info["Work"]),
                    "rect": tuple(info["Monitor"]),
                    "primary": bool(info["Flags"] & 1),
                }
            )
        return result

    def same_process(self, window):
        try:
            return psutil.Process(window.pid).create_time() == window.created
        except psutil.Error:
            return False

    def same_window(self, window):
        if not self.same_process(window) or sys.platform != "win32":
            return False
        import pywintypes
        import win32gui
        import win32process

        try:
            if not win32gui.IsWindow(window.hwnd) or win32gui.GetClassName(window.hwnd) != window.class_name:
                return False
            _, pid = win32process.GetWindowThreadProcessId(window.hwnd)
            if pid == window.pid:
                return True
            matches = []

            def child(child, _):
                try:
                    if win32process.GetWindowThreadProcessId(child)[1] == window.pid:
                        matches.append(child)
                except pywintypes.error:
                    return

            win32gui.EnumChildWindows(window.hwnd, child, None)
            return bool(matches)
        except pywintypes.error:
            return False

    def processes(self):
        from meeting_assistant.services.meeting_shutdown import TARGETS

        result = []
        for process in psutil.process_iter(["pid", "name", "create_time"]):
            try:
                name = (process.info["name"] or "").casefold()
                if name in TARGETS:
                    result.append((process.pid, process.info["create_time"], name))
            except psutil.Error:
                continue
        return result

    def restore(self, window, rect):
        import win32con
        import win32gui

        if not self.same_window(window):
            raise ValueError("Janela mudou de processo; disposição não aplicada.")
        # rcNormalPosition uses workspace coordinates. SetWindowPos uses screen
        # pixels and handles taskbars at the top/left without double offsets.
        from meeting_assistant.services.native_window import show_window_async

        show_window_async(window.hwnd, win32con.SW_RESTORE)
        win32gui.SetWindowPos(
            window.hwnd,
            0,
            rect[0],
            rect[1],
            rect[2] - rect[0],
            rect[3] - rect[1],
            win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
        )
        actual = win32gui.GetWindowRect(window.hwnd)
        if any(abs(a - b) > 12 for a, b in zip(actual, rect, strict=True)):
            raise ValueError("Janela ainda não confirmou a disposição solicitada.")

    def close(self, window):
        import win32con
        import win32gui

        if self.same_window(window):
            win32gui.PostMessage(window.hwnd, win32con.WM_CLOSE, 0, 0)

    def minimize(self, window):
        from meeting_assistant.services.native_window import show_window_async

        if self.same_window(window):
            show_window_async(window.hwnd, 6)

    def present(self, window, rect):
        import time

        import win32con
        import win32gui

        from meeting_assistant.services.native_window import show_window_async

        if not self.same_window(window):
            raise ValueError("Player mudou de processo.")
        show_window_async(window.hwnd, win32con.SW_RESTORE)
        win32gui.SetWindowLong(
            window.hwnd, win32con.GWL_STYLE, window.style & ~(win32con.WS_CAPTION | win32con.WS_THICKFRAME)
        )
        win32gui.SetWindowLong(
            window.hwnd,
            win32con.GWL_EXSTYLE,
            window.extended_style & ~(win32con.WS_EX_CLIENTEDGE | win32con.WS_EX_WINDOWEDGE),
        )
        win32gui.SetWindowPos(
            window.hwnd,
            win32con.HWND_TOPMOST,
            rect[0],
            rect[1],
            rect[2] - rect[0],
            rect[3] - rect[1],
            win32con.SWP_SHOWWINDOW | win32con.SWP_FRAMECHANGED,
        )
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            actual = win32gui.GetWindowRect(window.hwnd)
            if all(abs(a - b) <= 12 for a, b in zip(actual, rect, strict=True)):
                return True
            time.sleep(0.05)
        raise ValueError("Posicionamento do player não confirmado.")

    def restore_presentation(self, window):
        import win32con
        import win32gui

        if not self.same_window(window):
            return  # The operator already closed this player.
        win32gui.SetWindowLong(window.hwnd, win32con.GWL_STYLE, window.style)
        win32gui.SetWindowLong(window.hwnd, win32con.GWL_EXSTYLE, window.extended_style)
        win32gui.SetWindowPlacement(window.hwnd, window.placement)
        win32gui.SetWindowPos(
            window.hwnd,
            win32con.HWND_TOPMOST if window.topmost else win32con.HWND_NOTOPMOST,
            0,
            0,
            0,
            0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED,
        )
        if win32gui.GetWindowPlacement(window.hwnd)[4] != window.placement[4]:
            raise ValueError("Player não confirmou a posição anterior.")
