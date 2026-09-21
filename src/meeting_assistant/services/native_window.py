"""Nonblocking commands for windows owned by other processes."""
import ctypes
from ctypes import wintypes


def show_window_async(hwnd: int, command: int) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    show = user32.ShowWindowAsync
    show.argtypes = [wintypes.HWND, ctypes.c_int]
    show.restype = wintypes.BOOL
    if not show(hwnd, command):
        raise ctypes.WinError(ctypes.get_last_error())
