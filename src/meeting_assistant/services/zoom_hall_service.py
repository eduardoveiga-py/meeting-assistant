from __future__ import annotations

import sys
import time
from dataclasses import dataclass

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

from meeting_assistant.services.display_service import DisplayInfo
from meeting_assistant.services.jwl_fast_window_guard import JwlFastWindowGuard
from meeting_assistant.services.jwl_secondary_window import JwlSecondaryWindowInfo, WindowRect
from meeting_assistant.services.jwl_uia_secondary_window import choose_native_monitor_rect
from meeting_assistant.services.native_window import activate_window, show_window_async

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

    # EnumChildWindows already enumerates descendants recursively.
    return False


def hall_runtime_flags(
    enabled: bool, zoom_active: bool, returning: bool, switching_to_zoom: bool = False,
) -> tuple[bool, bool]:
    protect_jwl = returning or not (zoom_active or switching_to_zoom)
    media_enabled = enabled and protect_jwl and not returning
    return protect_jwl, media_enabled


class ZoomHallService(QObject):
    """Switch only the local Hall display between JWL and Zoom dual-monitor output."""

    discovery_changed = Signal(object)
    about_to_show = Signal()
    returning_changed = Signal(bool)
    transition_diagnostic = Signal(object)
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
        self._show_started = 0.0
        self._show_rect = None
        self._show_confirmed = False
        self._activation_attempted = False
        self._show_timer = QTimer(self)
        self._show_timer.setInterval(100)
        self._show_timer.timeout.connect(self._poll_show)
        self._returning = False
        self._return_activation_attempted = False
        self._return_activation_allowed = False
        self._return_started = 0.0
        self._return_rect = None
        self._return_timer = QTimer(self)
        self._return_timer.setInterval(100)
        self._return_timer.timeout.connect(self._poll_return)

    @property
    def returning(self) -> bool:
        return self._returning


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
                "Não foi possível identificar com segurança a janela secundária do Zoom. "
                "Mantenha as duas janelas abertas; o diagnóstico foi registrado.",
            )
            return False

        jwl = self._jwl_window_provider()
        if not isinstance(jwl, JwlSecondaryWindowInfo) or not self._is_window(jwl.hwnd):
            self.status_changed.emit(False, "Saída do JW Library não encontrada para o retorno.")
            return False
        self._jwl_hwnd = jwl.hwnd
        # Keep JWL rendering underneath Zoom and save its handle before suspending guards.
        self.about_to_show.emit()

        self._zoom_hwnd = zoom.hwnd
        self._show_rect = self._native_target_rect(target)
        self._show_started = time.monotonic()
        self._show_confirmed = False
        self._activation_attempted = False
        self._active = True
        self.transition_diagnostic.emit({
            "phase": "show_requested", "hwnd": zoom.hwnd, "jwl_hwnd": self._jwl_hwnd,
        })
        self.status_changed.emit(True, "Preparando Zoom na Tela do Salão…")
        self._request_show()
        self._show_timer.start()
        return True

    def _request_show(self) -> None:
        rect = self._show_rect
        try:
            if self._is_window(self._jwl_hwnd):
                win32gui.SetWindowPos(
                    self._jwl_hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                    win32con.SWP_NOACTIVATE | win32con.SWP_NOMOVE
                    | win32con.SWP_NOSIZE | win32con.SWP_ASYNCWINDOWPOS,
                )
            show_window_async(self._zoom_hwnd, win32con.SW_SHOWNOACTIVATE)
            win32gui.SetWindowPos(
                self._zoom_hwnd, win32con.HWND_TOPMOST,
                rect.left, rect.top, rect.width, rect.height,
                win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW | win32con.SWP_ASYNCWINDOWPOS,
            )
        except (OSError, RuntimeError) as exc:
            self.transition_diagnostic.emit({"phase": "show_command_error", "error": type(exc).__name__})

    def _poll_show(self) -> None:
        if not self._active or self._returning:
            self._show_timer.stop()
            return
        elapsed = round((time.monotonic() - self._show_started) * 1000)
        try:
            snapshot = self._window_snapshot(self._zoom_hwnd, self._show_rect)
            if snapshot["ready"]:
                self._show_started = time.monotonic()
                if not self._show_confirmed:
                    self._show_confirmed = True
                    self.transition_diagnostic.emit({
                        "phase": "show_confirmed", "elapsed_ms": elapsed, **snapshot,
                    })
                    message = "Zoom confirmado visível no Salão; Zoom remoto continua recebendo OBS."
                    self.active_changed.emit(True, message)
                    self.status_changed.emit(True, message)
                return
            if (
                not snapshot.get("exposed", False)
                and not self._activation_attempted
                and not self._show_confirmed
            ):
                # TOPMOST/NOACTIVATE can leave a UWP full-screen view above Zoom.
                # Use the foreground permission from the operator's explicit click
                # once; never repeatedly steal focus during an active Zoom part.
                self._activation_attempted = True
                accepted = activate_window(self._zoom_hwnd)
                self.transition_diagnostic.emit({
                    "phase": "show_activation", "accepted": accepted, **snapshot,
                })
            self._request_show()
        except (OSError, RuntimeError) as exc:
            snapshot = {"ready": False, "error": type(exc).__name__}
        if elapsed >= 5000:
            self._show_timer.stop()
            self.transition_diagnostic.emit({"phase": "show_timeout", "elapsed_ms": elapsed, **snapshot})
            self.restore_jwl(activate=False)
            self.status_changed.emit(False, "Zoom não confirmou exibição; restaurando o JW Library.")

    def restore_jwl(self, *, activate: bool = True) -> bool:
        """Accept a return request; only a verified later tick completes it."""
        if self._returning:
            return True
        if sys.platform != "win32" or win32gui is None or win32con is None:
            return False
        target = self._display_provider()
        if not self._is_window(self._jwl_hwnd):
            jwl = self._jwl_window_provider()
            self._jwl_hwnd = jwl.hwnd if isinstance(jwl, JwlSecondaryWindowInfo) else 0
        if target is None or not self._is_window(self._jwl_hwnd):
            self.status_changed.emit(False, "Saída do JW Library não encontrada; Zoom mantido no Salão.")
            return False

        self._show_timer.stop()
        self._return_rect = self._native_target_rect(target)
        self._return_started = time.monotonic()
        self._returning = True
        self._return_activation_attempted = False
        self._return_activation_allowed = activate
        self.transition_diagnostic.emit({"phase": "return_requested", "hwnd": self._jwl_hwnd})
        self.status_changed.emit(True, "Restaurando JW Library na Tela do Salão…")
        self._request_return()
        # Activate on the operator's click before background shell recovery.
        # The inactive UWP view may be shell-cloaked, not merely behind Zoom.
        self._activate_return_if_needed()
        self.returning_changed.emit(True)
        self._return_timer.start()
        return True

    def _activate_return_if_needed(self, snapshot: dict | None = None) -> None:
        if not self._return_activation_allowed or self._return_activation_attempted:
            return
        try:
            snapshot = self._return_snapshot() if snapshot is None else snapshot
            if snapshot["ready"]:
                return
            self._return_activation_attempted = True
            accepted = activate_window(self._jwl_hwnd)
            self.transition_diagnostic.emit({
                "phase": "return_activation", "hwnd": self._jwl_hwnd,
                "accepted": accepted, **snapshot,
            })
        except (OSError, RuntimeError) as exc:
            self.transition_diagnostic.emit({
                "phase": "return_activation_error", "error": type(exc).__name__,
            })

    def _request_return(self) -> None:
        rect = self._return_rect
        try:
            if self._is_window(self._zoom_hwnd):
                # Keep Zoom alive and discoverable underneath JWL. SW_HIDE
                # outlives this app's HWND cache and strands it after a restart.
                win32gui.SetWindowPos(
                    self._zoom_hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                    win32con.SWP_NOACTIVATE | win32con.SWP_NOMOVE
                    | win32con.SWP_NOSIZE | win32con.SWP_ASYNCWINDOWPOS,
                )
            show_window_async(self._jwl_hwnd, win32con.SW_SHOWNOACTIVATE)
            win32gui.SetWindowPos(
                self._jwl_hwnd, win32con.HWND_TOPMOST,
                rect.left, rect.top, rect.width, rect.height,
                win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW | win32con.SWP_ASYNCWINDOWPOS,
            )
        except (OSError, RuntimeError) as exc:
            self.transition_diagnostic.emit({"phase": "return_command_error", "error": type(exc).__name__})

    def _return_snapshot(self) -> dict:
        return self._window_snapshot(self._jwl_hwnd, self._return_rect)

    def _window_snapshot(self, hwnd: int, rect: WindowRect) -> dict:
        valid = self._is_window(hwnd)
        if not valid:
            return {"ready": False, "valid": False}
        actual = self._window_rect(hwnd)
        visible = bool(win32gui.IsWindowVisible(hwnd))
        minimized = bool(win32gui.IsIconic(hwnd))
        cloaked = JwlFastWindowGuard._cloak_state(hwnd)
        exposed = JwlFastWindowGuard._is_exposed_at_center(hwnd, rect)
        geometry_ok = all(abs(a - b) <= 8 for a, b in zip(
            (actual.left, actual.top, actual.width, actual.height),
            (rect.left, rect.top, rect.width, rect.height), strict=True,
        ))
        cover = self._covering_window(rect)
        return {
            "rect": [actual.left, actual.top, actual.right, actual.bottom],
            "target_rect": [rect.left, rect.top, rect.right, rect.bottom],
            **cover,
            "ready": visible and not minimized and not cloaked and exposed and geometry_ok,
            "valid": valid, "visible": visible, "minimized": minimized,
            "cloaked": cloaked, "exposed": exposed, "geometry_ok": geometry_ok,
        }

    @staticmethod
    def _covering_window(rect: WindowRect) -> dict:
        # No window titles or participant names enter telemetry.
        try:
            point = int(win32gui.WindowFromPoint(rect.center) or 0)
            root = int(win32gui.GetAncestor(point, win32con.GA_ROOT) or point)
            return {
                "cover_hwnd": root, "cover_class": win32gui.GetClassName(root),
                "foreground_hwnd": int(win32gui.GetForegroundWindow() or 0),
            }
        except (AttributeError, OSError, RuntimeError):
            return {"cover_hwnd": 0, "cover_class": "unavailable"}

    def _poll_return(self) -> None:
        if not self._returning:
            return
        elapsed = round((time.monotonic() - self._return_started) * 1000)
        try:
            snapshot = self._return_snapshot()
            if snapshot["ready"]:
                # Exposure confirms JWL is above Zoom; Zoom stays open below it.
                self._finish_return(True, elapsed, snapshot)
                return
            else:
                self._activate_return_if_needed(snapshot)
                self._request_return()
        except (OSError, RuntimeError) as exc:
            snapshot = {"ready": False, "error": type(exc).__name__}
        if elapsed >= 5000:
            self._finish_return(False, elapsed, snapshot)

    def _finish_return(self, ok: bool, elapsed: int, snapshot: dict) -> None:
        self._return_timer.stop()
        self._returning = False
        self.transition_diagnostic.emit({
            "phase": "return_confirmed" if ok else "return_timeout",
            "elapsed_ms": elapsed, "hwnd": self._jwl_hwnd, **snapshot,
        })
        if ok:
            self._active = False
        self.returning_changed.emit(False)
        if not ok:
            if self._show_rect is not None:
                self._show_started = time.monotonic()
                self._show_timer.start()
            # Keep the Zoom state and allow a new explicit attempt. Never resume
            # media classification on an unverified desktop/Zoom image.
            try:
                if self._is_window(self._zoom_hwnd):
                    show_window_async(self._zoom_hwnd, win32con.SW_SHOWNOACTIVATE)
                    win32gui.SetWindowPos(
                        self._zoom_hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                        win32con.SWP_NOACTIVATE | win32con.SWP_NOMOVE
                        | win32con.SWP_NOSIZE | win32con.SWP_ASYNCWINDOWPOS,
                    )
            except (OSError, RuntimeError):
                pass
            self.status_changed.emit(
                False, "JWL não confirmou retorno em 5 s; tente novamente. Diagnóstico salvo."
            )
            return
        message = "Zoom removido da Tela do Salão; JW Library confirmado visível."
        self.active_changed.emit(False, message)
        self.status_changed.emit(True, message)

    def toggle(self) -> bool:
        return self.restore_jwl() if self._active else self.show_on_hall()

    def _find_secondary_zoom_window(self) -> ZoomHallWindow | None:
        if win32gui is None or win32process is None:
            return None

        candidates: list[ZoomHallWindow] = []
        inventory: list[dict] = []

        def callback(hwnd: int, _: object) -> bool:
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    process_name = psutil.Process(pid).name().casefold()
                except (psutil.Error, OSError):
                    return True
                if process_name != "zoom.exe":
                    return True

                class_name = win32gui.GetClassName(hwnd)
                visible = bool(win32gui.IsWindowVisible(hwnd))
                rect = self._window_rect(hwnd)
                controls = has_descendant_class(hwnd, _ZOOM_CONTROL_PANEL_CLASS)
                # Do not log window titles: they can contain meeting/participant names.
                inventory.append({
                    "hwnd": int(hwnd), "pid": int(pid), "class_name": class_name,
                    "visible": visible, "width": rect.width, "height": rect.height,
                    "has_controls": controls,
                })
                if class_name != _ZOOM_WINDOW_CLASS or controls:
                    return True
                # A previous app instance may have hidden this window. Its
                # process/class/controls identify it even without our HWND cache.
                if rect.width < 300 or rect.height < 180:
                    return True
                candidates.append(ZoomHallWindow(int(hwnd), int(pid), rect))
            except (OSError, RuntimeError):
                pass
            return True

        try:
            win32gui.EnumWindows(callback, None)
        except (OSError, RuntimeError):
            self.discovery_changed.emit({"windows": inventory, "result": "enumeration_failed"})
            return None

        # Ambiguous candidates must never be resolved by moving the largest window.
        selected = candidates[0] if len(candidates) == 1 else None
        self.discovery_changed.emit({
            "windows": inventory,
            "result": "selected" if selected else "ambiguous" if candidates else "not_found",
            "selected_hwnd": selected.hwnd if selected else 0,
        })
        return selected

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

