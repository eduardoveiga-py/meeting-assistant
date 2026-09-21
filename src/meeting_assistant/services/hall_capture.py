"""Read-only verification/capture of the already identified JWL output window."""

from __future__ import annotations

import sys

from meeting_assistant.services.jwl_secondary_window import WindowRect
from meeting_assistant.services.jwl_uia_secondary_window import choose_native_monitor_rect


def obs_window_key(title: str, class_name: str, executable: str) -> str:
    return ":".join(s.replace("#", "#22").replace(":", "#3A") for s in (title, class_name, executable))


def require_full_coverage(rect, target):
    """Refuse even a thin exposed desktop/title-bar strip in a saved photo."""
    if rect[0] > target[0] or rect[1] > target[1] or rect[2] < target[2] or rect[3] < target[3]:
        raise ValueError(
            "O conteúdo do JWL não cobre toda a Tela do Salão (há uma borda exposta). "
            "Restaure a tela cheia no JWL e capture novamente. A foto anterior foi preservada."
        )


def verified_hall_target(candidate, display, blocked: bool, diagnostic=None) -> dict:
    if blocked:
        raise ValueError("Pare Zoom → Salão e aguarde o retorno completo ao JWL.")
    if candidate is None or display is None:
        raise ValueError("A saída JWL na Tela do Salão não está disponível.")
    if sys.platform != "win32":
        raise ValueError("Captura física disponível somente no Windows.")
    import ctypes

    import psutil
    import win32api
    import win32gui
    import win32process

    hwnd = candidate.hwnd
    if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
        raise ValueError("A janela do JWL precisa estar visível na Tela do Salão.")
    if win32process.GetWindowThreadProcessId(hwnd)[1] != candidate.pid:
        raise ValueError("A janela mudou. Aguarde a nova identificação do JWL.")
    cloak = ctypes.c_int(0)
    hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        ctypes.c_void_p(hwnd),
        14,
        ctypes.byref(cloak),
        ctypes.sizeof(cloak),
    )
    if hr != 0 or cloak.value:
        raise ValueError("O Windows ainda não expôs a janela do JWL.")
    monitors = []
    for monitor, _, rect in win32api.EnumDisplayMonitors():
        info = win32api.GetMonitorInfo(monitor)
        monitors.append((bool(info.get("Flags", 0) & 1), WindowRect(*info.get("Monitor", rect))))
    target = choose_native_monitor_rect(display, monitors)
    actual = WindowRect(*win32gui.GetWindowRect(hwnd))
    monitor_rect = (target.left, target.top, target.right, target.bottom)
    client = win32gui.GetClientRect(hwnd)
    client_rect = (*win32gui.ClientToScreen(hwnd, client[:2]),
                   *win32gui.ClientToScreen(hwnd, client[2:]))
    from ctypes import wintypes

    frame = wintypes.RECT()
    frame_hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        ctypes.c_void_p(hwnd), 9, ctypes.byref(frame), ctypes.sizeof(frame)
    )
    frame_rect = (frame.left, frame.top, frame.right, frame.bottom) if frame_hr == 0 else None
    if diagnostic is not None:
        diagnostic({
            "hwnd": hwnd,
            "monitor_rect": monitor_rect,
            "outer_rect": (actual.left, actual.top, actual.right, actual.bottom),
            "client_rect": client_rect,
            "visible_frame_rect": frame_rect,
        })
    require_full_coverage(client_rect, monitor_rect)
    if frame_rect is not None:
        require_full_coverage(frame_rect, monitor_rect)
    if any(
        abs(a - b) > 16
        for a, b in zip(
            (actual.left, actual.top, actual.right, actual.bottom),
            (target.left, target.top, target.right, target.bottom),
            strict=True,
        )
    ):
        raise ValueError("O JWL ainda não ocupa a Tela do Salão selecionada.")
    from meeting_assistant.services.window_exposure import verify_visual_exposure

    taskbar_preview = verify_visual_exposure(
        hwnd, monitor_rect, diagnostic, allow_taskbar_preview=True
    )
    related = [hwnd]
    win32gui.EnumChildWindows(hwnd, lambda child, _: related.append(child), None)
    selectors = []
    for handle in related:
        title = win32gui.GetWindowText(handle)
        class_name = win32gui.GetClassName(handle)
        if not title or class_name not in {candidate.class_name, "Windows.UI.Core.CoreWindow"}:
            continue
        try:
            exe = psutil.Process(win32process.GetWindowThreadProcessId(handle)[1]).name()
        except psutil.Error:
            continue
        selectors.append(obs_window_key(title, class_name, exe))
    return {
        "hwnd": hwnd,
        "taskbar_preview": taskbar_preview,
        "rect": (target.left, target.top, target.right, target.bottom),
        "selectors": list(dict.fromkeys(selectors)),
    }


def capture_png(target: dict) -> bytes:
    import mss
    import mss.tools

    left, top, right, bottom = target["rect"]
    with mss.mss() as capture:
        shot = capture.grab({"left": left, "top": top, "width": right - left, "height": bottom - top})
        return mss.tools.to_png(shot.rgb, shot.size)
