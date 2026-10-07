"""Read-only identity of the discovered hall window, on the OBS worker.

Unlike the photo path, WGC does not require foreground/exposure and can capture
JWL while Zoom covers it. This module never activates, resizes or restores it.
"""

from __future__ import annotations

import sys

from meeting_assistant.services.jwl_secondary_window import WindowRect
from meeting_assistant.services.jwl_uia_secondary_window import choose_native_monitor_rect


def _process_created(pid: int) -> str:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise ValueError("Não foi possível verificar a identidade do processo JWL.")
    try:
        birth, end, system, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in (birth, end, system, user))):
            raise ValueError("O processo JWL mudou durante a identificação.")
        return str((birth.dwHighDateTime << 32) | birth.dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


def _observe(candidate, display) -> dict:
    if sys.platform != "win32":
        raise ValueError("Captura JWL por HWND requer Windows 11.")
    import ctypes
    from ctypes import wintypes

    import psutil
    import win32api
    import win32gui
    import win32process

    user = ctypes.WinDLL("user32", use_last_error=True)
    user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    try:
        hwnd = int(candidate.hwnd)
        if not win32gui.IsWindow(hwnd):
            raise ValueError("A janela JWL identificada já não existe.")
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        process = psutil.Process(pid).name()
        class_name = win32gui.GetClassName(hwnd)
        related = [hwnd]
        win32gui.EnumChildWindows(hwnd, lambda child, _: related.append(child), None)
        jwl = None
        for child in related:
            try:
                child_pid = win32process.GetWindowThreadProcessId(child)[1]
                if psutil.Process(child_pid).name().casefold() == "jwlibrary.exe":
                    jwl = (child, child_pid, _process_created(child_pid))
                    break
            except (psutil.Error, OSError):
                continue
        if jwl is None:
            raise ValueError("A janela de saída não confirmou vínculo com JWLibrary.exe.")
        monitors = []
        for monitor, _, rect in win32api.EnumDisplayMonitors():
            info = win32api.GetMonitorInfo(monitor)
            monitors.append((bool(info.get("Flags", 0) & 1), WindowRect(*info.get("Monitor", rect))))
        target = choose_native_monitor_rect(display, monitors)
        target_rect = (target.left, target.top, target.right, target.bottom)
        info = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, 0))
        cloak = wintypes.DWORD(1)
        dwm = ctypes.WinDLL("dwmapi")
        dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwm.DwmGetWindowAttribute.restype = ctypes.c_long
        result = dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloak), ctypes.sizeof(cloak))
        return {
            "hwnd": hwnd, "pid": pid, "created": _process_created(pid),
            "process": process, "class": class_name, "jwl": jwl,
            "visible": bool(win32gui.IsWindowVisible(hwnd)), "minimized": bool(win32gui.IsIconic(hwnd)),
            "cloaked": result != 0 or bool(cloak.value),
            "monitor": tuple(info["Monitor"]), "primary": bool(info.get("Flags", 0) & 1),
            "target": target_rect, "rect": tuple(win32gui.GetWindowRect(hwnd)),
        }
    except (psutil.Error, OSError) as exc:
        raise ValueError("JWL ou monitor mudou durante a identificação; aguardando redescoberta.") from exc
    finally:
        if previous:
            user.SetThreadDpiAwarenessContext(previous)


def capture_binding(candidate, display, session: str) -> dict:
    if candidate is None or display is None:
        raise ValueError("Abra a segunda janela do JWL e configure a Tela do Salão.")
    observed = _observe(candidate, display)
    if observed["hwnd"] != candidate.hwnd or observed["pid"] != candidate.pid:
        raise ValueError("A janela JWL mudou; aguardando redescoberta.")
    if observed["class"] != candidate.class_name:
        raise ValueError("A classe da janela JWL mudou; aguardando redescoberta.")
    if observed["process"].casefold() not in {"jwlibrary.exe", "applicationframehost.exe"}:
        raise ValueError("A janela identificada não pertence ao JWL.")
    if not observed["visible"] or observed["minimized"] or observed["cloaked"]:
        raise ValueError("Restaure a segunda janela JWL antes de preparar a captura.")
    if observed["primary"] or observed["monitor"] != observed["target"]:
        raise ValueError("A janela JWL não está no monitor secundário configurado para o Salão.")
    left, top, right, bottom = observed["target"]
    x1, y1, x2, y2 = observed["rect"]
    area = (right - left) * (bottom - top)
    overlap = max(0, min(right, x2) - max(left, x1)) * max(0, min(bottom, y2) - max(top, y1))
    if area <= 0 or overlap / area < 0.85:
        raise ValueError("A segunda janela JWL precisa ocupar a Tela do Salão.")
    child, child_pid, child_created = observed["jwl"]
    return {
        "hwnd": str(observed["hwnd"]), "pid": observed["pid"], "created": observed["created"],
        "jwl_hwnd": str(child), "jwl_pid": child_pid, "jwl_created": child_created,
        "window_class": observed["class"], "hall_left": left, "hall_top": top,
        "hall_right": right, "hall_bottom": bottom, "session": session,
    }
