from __future__ import annotations

import sys
from dataclasses import dataclass

import psutil
from PySide6.QtCore import QObject, Signal

from meeting_assistant.services.display_service import DisplayInfo
from meeting_assistant.services.jwl_secondary_window import JwlSecondaryWindowInfo, WindowRect
from meeting_assistant.services.jwl_uia_secondary_window import choose_native_monitor_rect

try:
    import win32api
    import win32con
    import win32gui
    import win32process
except ImportError:  # pragma: no cover - Windows-only
    win32api = None
    win32con = None
    win32gui = None
    win32process = None


_ZOOM_WINDOW_CLASS = "ConfMultiTabContentWndClass"
_ZOOM_MEETING_TITLE = "Zoom Meeting"
_ZOOM_CONTROL_PANEL_CLASS = "ZPControlPanelClass"


@dataclass(frozen=True, slots=True)
class ZoomHallWindow:
    hwnd: int
    pid: int
    rect: WindowRect


def has_descendant_class(hwnd: int, class_name: str, max_depth: int = 3) -> bool:
    if win32gui is None or hwnd <= 0 or max_depth < 0:
        return False

    direct_children: list[int] = []

    def callback(child: int, _: object) -> bool:
        direct_children.append(child)
        return True

    try:
        win32gui.EnumChildWindows(hwnd, callback, None)
    except (OSError, RuntimeError):
        return False

    for child in direct_children:
        try:
            if win32gui.GetClassName(child) == class_name:
                return True
        except (OSError, RuntimeError):
            continue

    if max_depth == 0:
        return False

    return any(
        has_descendant_class(child, class_name, max_depth - 1)
        for child in direct_children
    )


class ZoomHallService(QObject):
    """Switch only the local Hall display between JWL and Zoom dual-monitor output."""

    about_to_show = Signal()
    active_changed = Signal(bool, str)
    status_changed = Signal(bool, str)

    def __init__(
        self,
        display_provider,
        jwl_window_provider,
    ) -> None:
        super().__init__()
        self._display_provider = display_provider
        self._jwl_window_provider = jwl_window_provider
        self._active = False
        self._zoom_hwnd = 0
        self._jwl_hwnd = 0

    @property
    def active(self) -> bool:
        return self._active

    def show_on_hall(self) -> bool:
        if sys.platform != "win32" or win32gui is None or win32con is None:
            self.status_changed.emit(False, "Zoom → Salão requer Windows.")
            return False

        target = self._display_provider()
        if target is None:
            self.status_changed.emit(False, "Tela do Salão física não está disponível.")
            return False

        zoom = self._find_secondary_zoom_window()
        if zoom is None:
            self.status_changed.emit(
                False,
                "Janela secundária do Zoom não encontrada. "
                "Ative 'Usar dois monitores' no Zoom antes de entrar na reunião.",
            )
            return False

        self.about_to_show.emit()

        jwl = self._jwl_window_provider()
        if isinstance(jwl, JwlSecondaryWindowInfo) and self._is_window(jwl.hwnd):
            self._jwl_hwnd = jwl.hwnd
            try:
                win32gui.ShowWindow(jwl.hwnd, win32con.SW_MINIMIZE)
            except (OSError, RuntimeError):
                pass

        target_rect = self._native_target_rect(target)
        try:
            win32gui.ShowWindow(zoom.hwnd, win32con.SW_RESTORE)
            win32gui.ShowWindow(zoom.hwnd, win32con.SW_SHOW)
            flags = (
                win32con.SWP_NOACTIVATE
                | win32con.SWP_SHOWWINDOW
                | win32con.SWP_FRAMECHANGED
            )
            win32gui.SetWindowPos(
                zoom.hwnd,
                win32con.HWND_TOPMOST,
                target_rect.left,
                target_rect.top,
                target_rect.width,
                target_rect.height,
                flags,
            )
        except (OSError, RuntimeError):
            self.status_changed.emit(False, "Não foi possível posicionar o Zoom na Tela do Salão.")
            return False

        self._zoom_hwnd = zoom.hwnd
        self._active = True
        message = (
            "Zoom exibido somente no Salão. "
            "Os participantes remotos continuam recebendo a câmera virtual do OBS."
        )
        self.status_changed.emit(True, message)
        self.active_changed.emit(True, message)
        return True

    def restore_jwl(self) -> bool:
        if sys.platform != "win32" or win32gui is None or win32con is None:
            return False

        target = self._display_provider()

        if self._is_window(self._zoom_hwnd):
            try:
                # Hiding the secondary Zoom window is more predictable than
                # minimizing it and preserves its full-screen state for next use.
                win32gui.ShowWindow(self._zoom_hwnd, win32con.SW_HIDE)
            except (OSError, RuntimeError):
                pass

        restored = False
        jwl = self._jwl_window_provider()
        jwl_hwnd = (
            jwl.hwnd
            if isinstance(jwl, JwlSecondaryWindowInfo) and self._is_window(jwl.hwnd)
            else self._jwl_hwnd
        )
        if target is not None and self._is_window(jwl_hwnd):
            rect = self._native_target_rect(target)
            try:
                win32gui.ShowWindow(jwl_hwnd, win32con.SW_SHOWNOACTIVATE)
                flags = (
                    win32con.SWP_NOACTIVATE
                    | win32con.SWP_SHOWWINDOW
                    | win32con.SWP_FRAMECHANGED
                )
                win32gui.SetWindowPos(
                    jwl_hwnd,
                    win32con.HWND_TOPMOST,
                    rect.left,
                    rect.top,
                    rect.width,
                    rect.height,
                    flags,
                )
                restored = True
            except (OSError, RuntimeError):
                restored = False

        self._active = False
        message = (
            "Zoom removido da Tela do Salão; saída do JW Library restaurada."
            if restored
            else "Zoom removido da Tela do Salão; aguardando o guardião restaurar o JW Library."
        )
        self.status_changed.emit(True, message)
        self.active_changed.emit(False, message)
        return True

    def toggle(self) -> bool:
        return self.restore_jwl() if self._active else self.show_on_hall()

    def _find_secondary_zoom_window(self) -> ZoomHallWindow | None:
        if win32gui is None or win32process is None:
            return None

        if self._is_window(self._zoom_hwnd):
            try:
                rect = self._window_rect(self._zoom_hwnd)
                _, pid = win32process.GetWindowThreadProcessId(self._zoom_hwnd)
                return ZoomHallWindow(self._zoom_hwnd, int(pid), rect)
            except (OSError, RuntimeError):
                self._zoom_hwnd = 0

        candidates: list[tuple[int, ZoomHallWindow]] = []

        def callback(hwnd: int, _: object) -> bool:
            try:
                if win32gui.GetClassName(hwnd) != _ZOOM_WINDOW_CLASS:
                    return True
                if win32gui.GetWindowText(hwnd).strip() != _ZOOM_MEETING_TITLE:
                    return True

                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    process_name = psutil.Process(pid).name().casefold()
                except (psutil.Error, OSError):
                    process_name = ""
                if process_name and process_name != "zoom.exe":
                    return True

                # Zoom dual-monitor secondary window has no meeting control panel.
                if has_descendant_class(hwnd, _ZOOM_CONTROL_PANEL_CLASS, 3):
                    return True

                rect = self._window_rect(hwnd)
                if rect.width < 300 or rect.height < 180:
                    return True
                score = rect.width * rect.height
                if win32gui.IsWindowVisible(hwnd):
                    score += 10_000_000
                candidates.append((score, ZoomHallWindow(int(hwnd), int(pid), rect)))
            except (OSError, RuntimeError):
                pass
            return True

        try:
            win32gui.EnumWindows(callback, None)
        except (OSError, RuntimeError):
            return None

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _native_target_rect(self, target: DisplayInfo) -> WindowRect:
        if win32api is None:
            return WindowRect(
                target.x,
                target.y,
                target.x + target.width,
                target.y + target.height,
            )

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
            pass
        return choose_native_monitor_rect(target, monitors)

    @staticmethod
    def _window_rect(hwnd: int) -> WindowRect:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        return WindowRect(int(left), int(top), int(right), int(bottom))

    @staticmethod
    def _is_window(hwnd: int) -> bool:
        if hwnd <= 0 or win32gui is None:
            return False
        try:
            return bool(win32gui.IsWindow(hwnd))
        except (OSError, RuntimeError):
            return False
