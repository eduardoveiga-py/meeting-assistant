"""Read-only verification/capture of the already identified JWL output window."""

from __future__ import annotations

import sys

from meeting_assistant.services.jwl_secondary_window import WindowRect
from meeting_assistant.services.jwl_uia_secondary_window import choose_native_monitor_rect


def obs_window_key(title: str, class_name: str, executable: str) -> str:
    return ":".join(s.replace("#", "#22").replace(":", "#3A") for s in (title, class_name, executable))


def verified_hall_target(candidate, display, blocked: bool) -> dict:
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
    if any(
        abs(a - b) > 16
        for a, b in zip(
            (actual.left, actual.top, actual.right, actual.bottom),
            (target.left, target.top, target.right, target.bottom),
            strict=True,
        )
    ):
        raise ValueError("O JWL ainda não ocupa a Tela do Salão selecionada.")
    for fx in (0.1, 0.5, 0.9):
        for fy in (0.1, 0.5, 0.9):
            covering = win32gui.WindowFromPoint(
                (target.left + int(target.width * fx), target.top + int(target.height * fy))
            )
            if win32gui.GetAncestor(covering, 2) != hwnd:
                raise ValueError("Outra janela está sobre o JWL. Libere a Tela do Salão antes de capturar.")
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
