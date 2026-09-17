from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from meeting_assistant.services.jwl_service import JwlWindowInfo

try:
    import win32api
    import win32con
    import win32gui
except ImportError:  # pragma: no cover - exercised only outside Windows
    win32api = None
    win32con = None
    win32gui = None

DisplayBounds = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class HallOutputTarget:
    device_name: str
    bounds: DisplayBounds


def window_center_inside_display(window: JwlWindowInfo, bounds: DisplayBounds) -> bool:
    x, y, width, height = bounds
    center_x = window.left + max(0, window.right - window.left) // 2
    center_y = window.top + max(0, window.bottom - window.top) // 2
    return x <= center_x < x + width and y <= center_y < y + height


def window_overlap_ratio(window: JwlWindowInfo, bounds: DisplayBounds) -> float:
    x, y, width, height = bounds
    left = max(window.left, x)
    top = max(window.top, y)
    right = min(window.right, x + width)
    bottom = min(window.bottom, y + height)
    overlap = max(0, right - left) * max(0, bottom - top)
    window_area = max(1, window.right - window.left) * max(1, window.bottom - window.top)
    return overlap / window_area


def window_monitor_device(hwnd: int) -> str | None:
    """Retorna o nome Win32 do monitor que contém a maior parte da janela."""

    if win32api is None or win32con is None:
        return None
    try:
        monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONULL)
        if not monitor:
            return None
        info = win32api.GetMonitorInfo(monitor)
        device = info.get("Device")
        return str(device) if device else None
    except (OSError, RuntimeError):
        return None


def _normalize_device_name(value: str | None) -> str:
    return (value or "").strip().casefold()


def select_hall_window(
    windows: list[JwlWindowInfo],
    bounds: DisplayBounds,
    tracked_hwnd: int | None = None,
    *,
    device_name: str = "",
    monitor_device_resolver: Callable[[int], str | None] = window_monitor_device,
) -> JwlWindowInfo | None:
    """Resolve de forma persistente a janela de saída do JW Library.

    A identidade Win32 do monitor é preferida à geometria, evitando diferenças de
    escala/DPI entre coordenadas do Qt e do Win32. Depois de conhecido, o HWND é
    mantido mesmo se a janela for minimizada ou movida por engano.
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
    ]
    if not candidates:
        return None

    normalized_target = _normalize_device_name(device_name)
    if normalized_target:
        exact = [
            item
            for item in candidates
            if _normalize_device_name(monitor_device_resolver(item.hwnd))
            == normalized_target
        ]
        if exact:
            candidates = exact
        else:
            candidates = [
                item for item in candidates if window_overlap_ratio(item, bounds) >= 0.35
            ]
    else:
        candidates = [
            item for item in candidates if window_overlap_ratio(item, bounds) >= 0.35
        ]

    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            window_overlap_ratio(item, bounds),
            (item.right - item.left) * (item.bottom - item.top),
        ),
    )


class HallOutputGuard(QObject):
    """Restaura a saída do JW Library no monitor do Salão sem bloquear o operador."""

    status_changed = Signal(str)
    target_changed = Signal(int)
    restored = Signal(int)
    error = Signal(str)

    def __init__(
        self,
        target_provider: Callable[[], HallOutputTarget | None],
        window_provider: Callable[[], list[JwlWindowInfo]],
        interval_ms: int = 350,
    ) -> None:
        super().__init__()
        self._target_provider = target_provider
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
        self._set_tracked_hwnd(None)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._set_tracked_hwnd(None)
            self._emit_status("Proteção da saída do Salão pausada.")
            return
        self._emit_status("Proteção da saída do Salão ativa.")
        self._tick()

    def _tick(self) -> None:
        if not self._enabled:
            return

        target_display = self._target_provider()
        if target_display is None:
            self._set_tracked_hwnd(None)
            self._emit_status(
                "Proteção da saída: modo de simulação ou Tela do Salão indisponível."
            )
            return

        try:
            windows = self._window_provider()
            target = select_hall_window(
                windows,
                target_display.bounds,
                self._tracked_hwnd,
                device_name=target_display.device_name,
            )
            if target is None:
                self._set_tracked_hwnd(None)
                self._emit_status(
                    "Proteção aguardando a janela do JW Library na Tela do Salão."
                )
                return

            self._set_tracked_hwnd(target.hwnd)
            on_target_monitor = (
                _normalize_device_name(window_monitor_device(target.hwnd))
                == _normalize_device_name(target_display.device_name)
                if target_display.device_name
                else window_overlap_ratio(target, target_display.bounds) >= 0.35
            )
            if target.minimized or not on_target_monitor:
                self._restore_without_activation(target.hwnd, target_display.bounds)
                self.restored.emit(target.hwnd)
                self._emit_status(
                    "Saída do JW Library restaurada automaticamente na Tela do Salão."
                )
            else:
                self._emit_status("Saída do JW Library protegida na Tela do Salão.")
        except Exception as exc:
            message = f"Falha ao proteger a saída do JW Library: {exc}"
            self.error.emit(message)
            self._emit_status(message)

    def _set_tracked_hwnd(self, hwnd: int | None) -> None:
        if hwnd == self._tracked_hwnd:
            return
        self._tracked_hwnd = hwnd
        self.target_changed.emit(hwnd or 0)

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
