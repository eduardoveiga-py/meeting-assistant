"""Visual overlap checks, independent from mouse hit testing and input state."""

from __future__ import annotations


def overlaps(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


SHELL_TASKBARS = frozenset({"Shell_TrayWnd", "Shell_SecondaryTrayWnd"})


def first_covering_window(target_root, target_rect, windows, *, allow_taskbar_preview=False):
    """Rows are top-to-bottom; never treat a window behind the target as covering it."""
    for row in windows:
        if row["hwnd"] == target_root:
            return None
        # Explorer can report its full taskbar rectangle above a fullscreen UWP
        # output even when DWM does not paint it. Only photo preview may waive
        # this inconclusive shell geometry; other windows still block capture.
        if allow_taskbar_preview and row.get("class_name") in SHELL_TASKBARS:
            continue
        if row["visible"] and not row["cloaked"] and not row["transparent"]:
            if overlaps(row["rect"], target_rect):
                return row
    raise ValueError("A ordem das janelas mudou. Aguarde o JWL e tente capturar novamente.")


def verify_visual_exposure(hwnd, target_rect, diagnostic=None, *, allow_taskbar_preview=False):
    import ctypes
    from ctypes import wintypes

    import win32gui

    root = win32gui.GetAncestor(hwnd, 2) or hwnd
    handles = []
    win32gui.EnumWindows(lambda handle, _: handles.append(handle), None)
    rows = []
    for handle in handles:
        if handle == root:
            rows.append({"hwnd": root})
            break
        if not win32gui.IsWindowVisible(handle) or win32gui.IsIconic(handle):
            continue
        cloak = ctypes.c_int()
        hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            ctypes.c_void_p(handle), 14, ctypes.byref(cloak), ctypes.sizeof(cloak)
        )
        if hr == 0 and cloak.value:
            continue
        frame = wintypes.RECT()
        hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            ctypes.c_void_p(handle), 9, ctypes.byref(frame), ctypes.sizeof(frame)
        )
        rect = (
            (frame.left, frame.top, frame.right, frame.bottom) if hr == 0 else win32gui.GetWindowRect(handle)
        )
        transparent = False
        if win32gui.GetWindowLong(handle, -20) & 0x80000:  # WS_EX_LAYERED
            try:
                _, alpha, flags = win32gui.GetLayeredWindowAttributes(handle)
                transparent = bool(flags & 2) and alpha == 0
            except Exception:
                pass  # Per-pixel layered windows are not assumed transparent.
        rows.append(
            {
                "hwnd": handle,
                "visible": True,
                "cloaked": False,
                "transparent": transparent,
                "rect": rect,
                "class_name": win32gui.GetClassName(handle),
            }
        )
    shell_rows = [
        row for row in rows
        if row.get("class_name") in SHELL_TASKBARS and overlaps(row["rect"], target_rect)
    ]
    blocker = first_covering_window(
        root, target_rect, rows, allow_taskbar_preview=allow_taskbar_preview
    )
    if diagnostic:
        detail = {"hwnd": hwnd, "root_hwnd": root, "visual_blocker": blocker}
        if shell_rows:
            detail["shell_taskbars"] = shell_rows
            detail["taskbar_preview_allowed"] = allow_taskbar_preview
        diagnostic(detail)
    if blocker:
        raise ValueError(
            f"Janela visível sobre o JWL ({blocker['class_name']}). Libere a Tela do Salão antes de capturar."
        )
    return bool(shell_rows and allow_taskbar_preview)
