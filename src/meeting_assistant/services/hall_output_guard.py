from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from meeting_assistant.services.jwl_service import JwlWindowInfo

try:
    import win32con
    import win32gui
except ImportError:  # pragma: no cover - exercised only outside Windows
    win32con = None
    win32gui = None

DisplayBounds = tuple[int, int, int, int]


def window_center_inside_display(window: JwlWindowInfo, bounds: DisplayBounds) -> bool:
    x, y, width, height = bounds
    center_x = window.left + max(0, window.right - window.left) // 2
    center_y = window.top + max(0, window.bottom - window.top) // 2
    return x <= center_x < x + width and y <= center_y < y + height


def select_hall_window(
    windows: list[JwlWindowInfo],
    bounds: DisplayBounds,
    tracked_hwnd: int | None = None,
) -> JwlWindowInfo | None:
    """Resolve a janela do JW Library pertencente à Tela do Salão.

    Depois que uma janela é conhecida, preservamos o HWND mesmo se ela for
    minimizada ou movida por engano. Sem HWND conhecido, escolhemos somente uma
    janela normal cuja região central esteja dentro do monitor configurado.
    """

    if tracked_hwnd is not None:
        tracked = next((item for item in windows if item.hwnd == tracked_hwnd), None)
        if tracked is not None:
            return tracked

    candidates = [
        item
        for item in windows
        if item.visible
        and not item.minimized
        and item.right - item.left >= 400
        and item.bottom - item.top >= 300
        and window_center_inside_display(item, bounds)
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (item.right - item.left) * (item.bottom - item.top),
    )


class HallOutputGuard(QObject):
    """Restaura a saída do JW Library no monitor do Salão sem bloquear o operador."""

    status_changed = Signal(str)
    restored = Signal(int)
    error = Signal(str)

    def __init__(
        self,
        bounds_provider: Callable[[], DisplayBounds | None],
        window_provider: Callable[[], list[JwlWindowInfo]],
        interval_ms: int = 350,
    ) -> None:
        super().__init__()
        self._bounds_provider = bounds_provider
        self._window_provider = window_provider
        self._enabled = False
        self._tracked_hwnd: int | None = None
        self._last_status: str | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(max(250, interval_ms))
        self._timer.timeout.connect(self._tick)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def tracked_hwnd(self) -> int | None:
        return self._tracked_hwnd

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._enabled = False
        self._tracked_hwnd = None

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._tracked_hwnd = None
            self._emit_status("Proteção da saída do Salão pausada.")
            return
        self._emit_status("Proteção da saída do Salão ativa.")
        self._tick()

    def _tick(self) -> None:
        if not self._enabled:
            return

        bounds = self._bounds_provider()
        if bounds is None:
            self._tracked_hwnd = None
            self._emit_status("Proteção da saída: modo de simulação ou Tela do Salão indisponível.")
            return

        try:
            windows = self._window_provider()
            target = select_hall_window(windows, bounds, self._tracked_hwnd)
            if target is None:
                self._tracked_hwnd = None
                self._emit_status("Proteção aguardando a janela do JW Library na Tela do Salão.")
                return

            self._tracked_hwnd = target.hwnd
            if target.minimized or not window_center_inside_display(target, bounds):
                self._restore_without_activation(target.hwnd, bounds)
                self.restored.emit(target.hwnd)
                self._emit_status("Saída do JW Library restaurada automaticamente na Tela do Salão.")
            else:
                self._emit_status("Saída do JW Library protegida na Tela do Salão.")
        except Exception as exc:
            message = f"Falha ao proteger a saída do JW Library: {exc}"
            self.error.emit(message)
            self._emit_status(message)

    @staticmethod
    def _restore_without_activation(hwnd: int, bounds: DisplayBounds) -> None:
        if win32gui is None or win32con is None:
            raise RuntimeError("Win32 indisponível")
        if not win32gui.IsWindow(hwnd):
            raise RuntimeError("janela do JW Library não existe mais")

        x, y, display_width, display_height = bounds
        try:
            placement = win32gui.GetWindowPlacement(hwnd)
            normal_left, normal_top, normal_right, normal_bottom = placement[4]
            width = max(1, normal_right - normal_left)
            height = max(1, normal_bottom - normal_top)
        except (OSError, RuntimeError, IndexError, TypeError):
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = max(1, right - left)
            height = max(1, bottom - top)

        width = min(width, display_width)
        height = min(height, display_height)

        # SW_SHOWNOACTIVATE restaura/exibe sem tomar o foco do operador.
        win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
        win32gui.SetWindowPos(
            hwnd,
            0,
            x,
            y,
            width,
            height,
            win32con.SWP_NOACTIVATE
            | win32con.SWP_NOZORDER
            | win32con.SWP_SHOWWINDOW,
        )

    def _emit_status(self, message: str) -> None:
        if message == self._last_status:
            return
        self._last_status = message
        self.status_changed.emit(message)
