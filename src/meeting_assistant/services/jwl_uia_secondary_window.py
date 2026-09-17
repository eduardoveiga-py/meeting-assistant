from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

from meeting_assistant.services.display_service import DisplayInfo
from meeting_assistant.services.jwl_secondary_window import (
    JwlSecondaryWindowInfo,
    JwlSecondaryWindowService,
    WindowRect,
    is_fullscreen_on_display,
    normalize_window_title,
    rect_overlap_ratio,
    title_has_jw_library,
)

try:
    import win32api
    import win32con
    import win32gui
    import win32process
    from pywinauto import Desktop
except ImportError:  # pragma: no cover - Windows-only implementation
    win32api = None
    win32con = None
    win32gui = None
    win32process = None
    Desktop = None

_CORE_WINDOW_CLASS = "Windows.UI.Core.CoreWindow"
_JWL_MEDIA_CHILD_CLASSES = {
    "Microsoft.UI.Xaml.Controls.WebView2",
    "ProgressRing",
    "WebView",
}


def uia_media_candidate_score(
    *,
    name: str,
    class_name: str,
    topmost: bool,
    core_verified: bool,
    monitor_primary: bool | None,
    target_display: DisplayInfo | None,
    rect: WindowRect,
) -> int:
    """Rank a desktop UIA element as JW Library's media/output window.

    This mirrors the proven strategy used by JwlMediaWin: a top-level desktop
    element named JW Library, top-most, with a JW Library CoreWindow below it.
    Geometry is supporting evidence only because Qt and Win32 can disagree on
    mixed-DPI desktops.
    """

    if not title_has_jw_library(name):
        return -10_000

    score = 500
    if class_name:
        score += 30
    if topmost:
        score += 700
    if core_verified:
        score += 900

    if target_display is not None:
        overlap = rect_overlap_ratio(rect, target_display)
        if overlap >= 0.70:
            score += 350
        elif overlap >= 0.30:
            score += 120

        if monitor_primary is not None:
            if monitor_primary == target_display.primary:
                score += 500
            else:
                score -= 900

        if is_fullscreen_on_display(rect, target_display):
            score += 200

    return score


class JwlUiaSecondaryWindowService(QObject):
    """Discover the JW Library media output through Windows UI Automation.

    Win32 EnumWindows is retained as a fallback and as a diagnostic source, but
    UIA is the primary discovery mechanism because UWP/XAML app frames may not
    expose the useful automation name through GetWindowText.
    """

    window_changed = Signal(object)
    status_changed = Signal(bool, str)

    def __init__(
        self,
        display_provider: Callable[[], DisplayInfo | None],
        *,
        interval_ms: int = 650,
    ) -> None:
        super().__init__()
        self._display_provider = display_provider
        self._timer = QTimer(self)
        self._timer.setInterval(max(400, interval_ms))
        self._timer.timeout.connect(self.refresh)
        self._current: JwlSecondaryWindowInfo | None = None
        self._guard_enabled = False
        self._last_status: tuple[bool, str] | None = None
        self._win32_fallback = JwlSecondaryWindowService(display_provider, interval_ms=interval_ms)

    @property
    def current(self) -> JwlSecondaryWindowInfo | None:
        return self._current

    @property
    def guard_enabled(self) -> bool:
        return self._guard_enabled

    def start(self) -> None:
        self.refresh()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def set_guard_enabled(self, enabled: bool) -> None:
        self._guard_enabled = enabled
        if enabled:
            self.refresh()

    def refresh(self) -> None:
        target = self._display_provider()
        candidate = self.discover(target)
        previous_hwnd = self._current.hwnd if self._current else 0

        if candidate is not None and self._guard_enabled and target is not None:
            candidate = self._ensure_window(candidate, target)

        self._current = candidate
        current_hwnd = candidate.hwnd if candidate else 0

        if candidate is None:
            if target is None:
                self._emit_status(False, "Tela do Salão física não está disponível.")
            else:
                self._emit_status(
                    False,
                    "Saída do JW Library ainda não foi encontrada por UI Automation.",
                )
        else:
            state = "minimizada" if candidate.minimized else "ativa"
            self._emit_status(
                True,
                "Saída JWL identificada por UI Automation • "
                f"HWND {candidate.hwnd} • {candidate.size} • {state}",
            )

        if current_hwnd != previous_hwnd:
            self.window_changed.emit(candidate)

    def discover(self, target_display: DisplayInfo | None) -> JwlSecondaryWindowInfo | None:
        uia_candidates = self.scan_uia_candidates(target_display)
        if uia_candidates:
            best = max(uia_candidates, key=lambda item: item.score)
            if best.score >= 1300:
                return best
        return self._win32_fallback.discover(target_display)

    def scan_uia_candidates(
        self,
        target_display: DisplayInfo | None,
    ) -> list[JwlSecondaryWindowInfo]:
        if sys.platform != "win32" or Desktop is None:
            return []

        candidates: list[JwlSecondaryWindowInfo] = []
        try:
            desktop_children = Desktop(backend="uia", allow_magic_lookup=False).children()
        except Exception:  # noqa: BLE001 - COM/UIA failures must not crash live meeting
            return candidates

        for wrapper in desktop_children:
            try:
                info = wrapper.element_info
                name = (getattr(info, "name", "") or "").strip()
                if not title_has_jw_library(name):
                    continue

                handle = int(getattr(info, "handle", 0) or 0)
                if handle <= 0:
                    try:
                        handle = int(wrapper.handle)
                    except Exception:  # noqa: BLE001
                        handle = 0
                if handle <= 0:
                    continue

                class_name = str(getattr(info, "class_name", "") or "")
                rect = self._rect_for_wrapper(handle, wrapper)
                topmost = self._is_topmost(handle)
                monitor_primary = self._monitor_primary_for_rect(rect)
                core_verified = self._verify_jwl_core(wrapper)
                score = uia_media_candidate_score(
                    name=name,
                    class_name=class_name,
                    topmost=topmost,
                    core_verified=core_verified,
                    monitor_primary=monitor_primary,
                    target_display=target_display,
                    rect=rect,
                )

                pid = self._pid_for_handle(handle)
                process_name = self._process_name(pid)
                visible = self._is_visible(handle)
                minimized = self._is_minimized(handle)
                candidates.append(
                    JwlSecondaryWindowInfo(
                        hwnd=handle,
                        pid=pid,
                        process_name=process_name,
                        title=name,
                        class_name=class_name,
                        rect=rect,
                        visible=visible,
                        minimized=minimized,
                        topmost=topmost,
                        title_bar_visible=False,
                        has_jwl_core_window=core_verified,
                        monitor_primary=monitor_primary,
                        score=score,
                    )
                )
            except Exception:  # noqa: BLE001 - one bad UIA element must not abort discovery
                continue

        return sorted(candidates, key=lambda item: item.score, reverse=True)

    def diagnostic_snapshot(
        self,
        target_display: DisplayInfo | None,
    ) -> dict[str, Any]:
        snapshot = self._win32_fallback.diagnostic_snapshot(target_display)
        uia_rows: list[dict[str, Any]] = []

        if sys.platform == "win32" and Desktop is not None:
            try:
                desktop_children = Desktop(backend="uia", allow_magic_lookup=False).children()
            except Exception as exc:  # noqa: BLE001
                snapshot["uia_error"] = repr(exc)
                desktop_children = []

            for wrapper in desktop_children:
                try:
                    info = wrapper.element_info
                    name = str(getattr(info, "name", "") or "")
                    class_name = str(getattr(info, "class_name", "") or "")
                    handle = int(getattr(info, "handle", 0) or 0)
                    if handle <= 0:
                        try:
                            handle = int(wrapper.handle)
                        except Exception:  # noqa: BLE001
                            handle = 0

                    relevant = bool(
                        title_has_jw_library(name)
                        or "jw" in normalize_window_title(name)
                        or class_name in {_CORE_WINDOW_CLASS, "ApplicationFrameWindow"}
                    )
                    if not relevant:
                        continue

                    rect = self._rect_for_wrapper(handle, wrapper)
                    monitor_primary = self._monitor_primary_for_rect(rect)
                    core_verified = self._verify_jwl_core(wrapper)
                    topmost = self._is_topmost(handle)
                    score = uia_media_candidate_score(
                        name=name,
                        class_name=class_name,
                        topmost=topmost,
                        core_verified=core_verified,
                        monitor_primary=monitor_primary,
                        target_display=target_display,
                        rect=rect,
                    )
                    uia_rows.append(
                        {
                            "name": name,
                            "class_name": class_name,
                            "automation_id": str(getattr(info, "automation_id", "") or ""),
                            "control_type": str(getattr(info, "control_type", "") or ""),
                            "handle": handle,
                            "pid": self._pid_for_handle(handle),
                            "process_name": self._process_name(self._pid_for_handle(handle)),
                            "rect": asdict(rect),
                            "topmost": topmost,
                            "visible": self._is_visible(handle),
                            "minimized": self._is_minimized(handle),
                            "monitor_primary": monitor_primary,
                            "core_verified": core_verified,
                            "score": score,
                            "children": self._uia_child_inventory(wrapper),
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    uia_rows.append({"error": repr(exc)})

        uia_rows.sort(key=lambda item: int(item.get("score", -10_000)), reverse=True)
        snapshot["uia_windows"] = uia_rows
        selected = self.discover(target_display)
        snapshot["selected_candidate"] = asdict(selected) if selected else None
        snapshot["discovery_backend"] = "uia" if selected and any(
            int(row.get("handle", 0)) == selected.hwnd for row in uia_rows
        ) else "win32-fallback"
        return snapshot

    @staticmethod
    def _verify_jwl_core(wrapper: Any) -> bool:
        try:
            children = wrapper.children()
        except Exception:  # noqa: BLE001
            return False

        for child in children:
            try:
                info = child.element_info
                if str(getattr(info, "class_name", "") or "") != _CORE_WINDOW_CLASS:
                    continue
                core_name = str(getattr(info, "name", "") or "")
                if core_name and not title_has_jw_library(core_name):
                    continue

                try:
                    descendants = child.descendants()
                except Exception:  # noqa: BLE001
                    descendants = []

                if not descendants:
                    return True
                for descendant in descendants:
                    d_info = descendant.element_info
                    d_class = str(getattr(d_info, "class_name", "") or "")
                    d_type = str(getattr(d_info, "control_type", "") or "")
                    if d_class in _JWL_MEDIA_CHILD_CLASSES or d_type == "ProgressBar":
                        return True
            except Exception:  # noqa: BLE001
                continue
        return False

    @staticmethod
    def _uia_child_inventory(wrapper: Any, limit: int = 80) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            descendants = wrapper.descendants()
        except Exception:  # noqa: BLE001
            return rows
        for child in descendants[:limit]:
            try:
                info = child.element_info
                rows.append(
                    {
                        "name": str(getattr(info, "name", "") or ""),
                        "class_name": str(getattr(info, "class_name", "") or ""),
                        "automation_id": str(getattr(info, "automation_id", "") or ""),
                        "control_type": str(getattr(info, "control_type", "") or ""),
                        "handle": int(getattr(info, "handle", 0) or 0),
                    }
                )
            except Exception:  # noqa: BLE001
                continue
        return rows

    def _ensure_window(
        self,
        item: JwlSecondaryWindowInfo,
        target: DisplayInfo,
    ) -> JwlSecondaryWindowInfo:
        if win32gui is None or win32con is None:
            return item
        try:
            if win32gui.IsIconic(item.hwnd):
                win32gui.ShowWindow(item.hwnd, win32con.SW_SHOWNOACTIVATE)

            refreshed_rect = self._rect_for_handle(item.hwnd) or item.rect
            monitor_primary = self._monitor_primary_for_rect(refreshed_rect)
            overlap = rect_overlap_ratio(refreshed_rect, target)
            same_monitor_role = (
                monitor_primary is not None and monitor_primary == target.primary
            )
            if overlap < 0.65 and not same_monitor_role:
                flags = (
                    win32con.SWP_NOACTIVATE
                    | win32con.SWP_SHOWWINDOW
                    | win32con.SWP_ASYNCWINDOWPOS
                )
                win32gui.SetWindowPos(
                    item.hwnd,
                    win32con.HWND_TOPMOST,
                    target.x,
                    target.y,
                    target.width,
                    target.height,
                    flags,
                )
            return self.discover(target) or item
        except (OSError, RuntimeError):
            return item

    @staticmethod
    def _rect_for_wrapper(handle: int, wrapper: Any) -> WindowRect:
        rect = JwlUiaSecondaryWindowService._rect_for_handle(handle)
        if rect is not None:
            return rect
        ui_rect = wrapper.rectangle()
        return WindowRect(
            int(ui_rect.left),
            int(ui_rect.top),
            int(ui_rect.right),
            int(ui_rect.bottom),
        )

    @staticmethod
    def _rect_for_handle(handle: int) -> WindowRect | None:
        if handle <= 0 or win32gui is None:
            return None
        try:
            left, top, right, bottom = win32gui.GetWindowRect(handle)
            return WindowRect(int(left), int(top), int(right), int(bottom))
        except (OSError, RuntimeError):
            return None

    @staticmethod
    def _is_topmost(handle: int) -> bool:
        if handle <= 0 or win32gui is None or win32con is None:
            return False
        try:
            ex_style = int(win32gui.GetWindowLong(handle, win32con.GWL_EXSTYLE))
            return bool(ex_style & win32con.WS_EX_TOPMOST)
        except (OSError, RuntimeError):
            return False

    @staticmethod
    def _is_visible(handle: int) -> bool:
        if handle <= 0 or win32gui is None:
            return True
        try:
            return bool(win32gui.IsWindowVisible(handle))
        except (OSError, RuntimeError):
            return True

    @staticmethod
    def _is_minimized(handle: int) -> bool:
        if handle <= 0 or win32gui is None:
            return False
        try:
            return bool(win32gui.IsIconic(handle))
        except (OSError, RuntimeError):
            return False

    @staticmethod
    def _pid_for_handle(handle: int) -> int:
        if handle <= 0 or win32process is None:
            return 0
        try:
            _, pid = win32process.GetWindowThreadProcessId(handle)
            return int(pid)
        except (OSError, RuntimeError):
            return 0

    @staticmethod
    def _process_name(pid: int) -> str:
        if pid <= 0:
            return ""
        try:
            return psutil.Process(pid).name()
        except (psutil.Error, OSError):
            return ""

    @staticmethod
    def _monitor_primary_for_rect(rect: WindowRect) -> bool | None:
        if win32api is None or win32con is None:
            return None
        try:
            monitor = win32api.MonitorFromPoint(
                rect.center,
                win32con.MONITOR_DEFAULTTONEAREST,
            )
            info = win32api.GetMonitorInfo(monitor)
            return bool(int(info.get("Flags", 0)) & 1)
        except (OSError, RuntimeError, TypeError, ValueError):
            return None

    def _emit_status(self, ok: bool, message: str) -> None:
        current = (ok, message)
        if current == self._last_status:
            return
        self._last_status = current
        self.status_changed.emit(ok, message)
