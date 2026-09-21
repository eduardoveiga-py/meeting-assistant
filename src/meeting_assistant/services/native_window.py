"""Native window commands with explicit activation separate from asynchronous showing."""
import ctypes
from ctypes import wintypes


def show_window_async(hwnd: int, command: int) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    show = user32.ShowWindowAsync
    show.argtypes = [wintypes.HWND, ctypes.c_int]
    show.restype = wintypes.BOOL
    if not show(hwnd, command):
        raise ctypes.WinError(ctypes.get_last_error())


def activate_window(hwnd: int) -> bool:
    """Ask Windows to activate a window following an explicit operator action."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    activate = user32.SetForegroundWindow
    activate.argtypes = [wintypes.HWND]
    activate.restype = wintypes.BOOL
    return bool(activate(hwnd))
