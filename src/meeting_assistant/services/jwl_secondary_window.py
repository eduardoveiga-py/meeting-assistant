from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

from meeting_assistant.services.display_service import DisplayInfo

try:
    import win32api
    import win32con
    import win32gui
    import win32process
except ImportError:  # pragma: no cover - Windows-only implementation
    win32api = None
    win32con = None
    win32gui = None
    win32process = None

_BIDI_MARKS = "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
_BIDI_TRANSLATION = str.maketrans("", "", _BIDI_MARKS)
_TITLEBAR_CLASS = "ApplicationFrameTitleBarWindow"
_CORE_WINDOW_CLASS = "Windows.UI.Core.CoreWindow"
_FRAME_WINDOW_CLASS = "ApplicationFrameWindow"
_JWL_DESCENDANT_CLASSES = {
    "Microsoft.UI.Xaml.Controls.WebView2",
    "ProgressRing",
    "WebView",
}
_FULLSCREEN_TOLERANCE = 60


@dataclass(frozen=True, slots=True)
class WindowRect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def center(self) -> tuple[int, int]:
        return self.left + self.width // 2, self.top + self.height // 2


@dataclass(frozen=True, slots=True)
class JwlSecondaryWindowInfo:
    hwnd: int
    pid: int
    process_name: str
    title: str
    class_name: str
    rect: WindowRect
    visible: bool
    minimized: bool
    topmost: bool
    title_bar_visible: bool
    has_jwl_core_window: bool
    monitor_primary: bool | None
    score: int

    @property
    def size(self) -> str:
        return f"{self.rect.width}x{self.rect.height}"


def normalize_window_title(title: str) -> str:
    cleaned = title.translate(_BIDI_TRANSLATION)
    cleaned = cleaned.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", cleaned).strip().casefold()


def title_has_jw_library(title: str) -> bool:
    normalized = normalize_window_title(title)
    return "jw library" in normalized and "sign language" not in normalized


def looks_like_jw_library_process(process_name: str) -> bool:
    normalized = process_name.casefold().replace(" ", "").replace("_", "").replace("-", "")
    return "jwlibrary" in normalized and "signlanguage" not in normalized


def is_explicit_jwl_secondary_title(title: str) -> bool:
    normalized = normalize_window_title(title)
    prefixes = (
        "second display",
        "second screen",
        "segunda tela",
        "segundo monitor",
        "segunda pantalla",
    )
    return title_has_jw_library(title) and any(prefix in normalized for prefix in prefixes)


def rect_overlap_ratio(rect: WindowRect, display: DisplayInfo) -> float:
    left = max(rect.left, display.x)
    top = max(rect.top, display.y)
    right = min(rect.right, display.x + display.width)
    bottom = min(rect.bottom, display.y + display.height)
    if right <= left or bottom <= top or rect.area <= 0:
        return 0.0
    return ((right - left) * (bottom - top)) / rect.area


def is_fullscreen_on_display(
    rect: WindowRect,
    display: DisplayInfo,
    *,
    tolerance: int = _FULLSCREEN_TOLERANCE,
) -> bool:
    return (
        abs(rect.left - display.x) <= tolerance
        and abs(rect.top - display.y) <= tolerance
        and abs(rect.width - display.width) <= tolerance
        and abs(rect.height - display.height) <= tolerance
    )


def score_secondary_candidate(
    *,
    title: str,
    class_name: str,
    rect: WindowRect,
    minimized: bool,
    topmost: bool,
    title_bar_visible: bool,
    has_jwl_core_window: bool,
    monitor_primary: bool | None,
    target_display: DisplayInfo | None,
    process_name: str = "",
    has_jwl_descendant_hint: bool = False,
) -> int:
    explicit_secondary = is_explicit_jwl_secondary_title(title)
    title_hint = title_has_jw_library(title)
    process_hint = looks_like_jw_library_process(process_name)
    core_top_level = class_name == _CORE_WINDOW_CLASS
    frame_top_level = class_name == _FRAME_WINDOW_CLASS

    structural_identity = bool(
        explicit_secondary
        or title_hint
        or process_hint
        or has_jwl_core_window
        or has_jwl_descendant_hint
    )
    if not structural_identity:
        return -10_000

    score = 0
    if explicit_secondary:
        score += 1400
    if process_hint:
        score += 520
    if title_hint:
        score += 300
    if has_jwl_core_window:
        score += 500
    if has_jwl_descendant_hint:
        score += 260
    if core_top_level:
        score += 220
    elif frame_top_level:
        score += 80

    if topmost:
        score += 110
    if not title_bar_visible:
        score += 150
    if minimized:
        score += 20

    if target_display is not None:
        overlap = rect_overlap_ratio(rect, target_display)
        if overlap >= 0.70:
            score += 430
        elif overlap >= 0.30:
            score += 120
        else:
            # Qt and Win32 can expose different coordinate spaces on mixed-DPI
            # desktops. A geometry mismatch is therefore evidence, not a veto.
            score -= 250

        if monitor_primary is not None:
            if monitor_primary == target_display.primary:
                score += 260
            else:
                score -= 650

        if is_fullscreen_on_display(rect, target_display):
            score += 360

    return score


def choose_secondary_candidate(
    candidates: list[JwlSecondaryWindowInfo],
) -> JwlSecondaryWindowInfo | None:
    if not candidates:
        return None
    best = max(candidates, key=lambda item: item.score)
    return best if best.score >= 650 else None


class JwlSecondaryWindowService(QObject):
    """Find and protect the real JW Library second-display window."""

    window_changed = Signal(object)
    status_changed = Signal(bool, str)

    def __init__(
        self,
        display_provider: Callable[[], DisplayInfo | None],
        *,
        interval_ms: int = 450,
    ) -> None:
        super().__init__()
        self._display_provider = display_provider
        self._timer = QTimer(self)
        self._timer.setInterval(max(250, interval_ms))
        self._timer.timeout.connect(self.refresh)
        self._current: JwlSecondaryWindowInfo | None = None
        self._guard_enabled = False
        self._last_status: tuple[bool, str] | None = None

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
        changed = (candidate.hwnd if candidate else 0) != (
            self._current.hwnd if self._current else 0
        )
        self._current = candidate

        if candidate is None:
            if target is None:
                self._emit_status(False, "Tela do Salão física não está disponível.")
            else:
                self._emit_status(
                    False,
                    "Saída secundária do JW Library ainda não foi encontrada na Tela do Salão.",
                )
            if changed:
                self.window_changed.emit(None)
            return

        if self._guard_enabled and target is not None:
            candidate = self._ensure_window(candidate, target)
            self._current = candidate

        state = "minimizada" if candidate.minimized else "ativa"
        self._emit_status(
            True,
            f"Saída JWL identificada • HWND {candidate.hwnd} • {candidate.size} • {state}",
        )
        if changed:
            self.window_changed.emit(candidate)

    def discover(self, target_display: DisplayInfo | None) -> JwlSecondaryWindowInfo | None:
        return choose_secondary_candidate(self.scan_candidates(target_display))

    def scan_candidates(
        self,
        target_display: DisplayInfo | None,
    ) -> list[JwlSecondaryWindowInfo]:
        if sys.platform != "win32" or win32gui is None or win32process is None:
            return []

        process_map = self._process_map()
        candidates: list[JwlSecondaryWindowInfo] = []

        def callback(hwnd: int, _: object) -> bool:
            try:
                if not win32gui.IsWindow(hwnd):
                    return True

                title = win32gui.GetWindowText(hwnd).strip()
                class_name = win32gui.GetClassName(hwnd)
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process_name = process_map.get(pid, "")

                quick_hint = bool(
                    title_has_jw_library(title)
                    or looks_like_jw_library_process(process_name)
                    or class_name in {_FRAME_WINDOW_CLASS, _CORE_WINDOW_CLASS}
                )
                if not quick_hint:
                    return True

                has_core = self._has_jwl_core_window(hwnd)
                has_descendant_hint = self._has_jwl_descendant_hint(hwnd)
                rect = self._window_rect(hwnd)
                minimized = bool(win32gui.IsIconic(hwnd))
                visible = bool(win32gui.IsWindowVisible(hwnd))
                title_bar_visible = self._has_visible_title_bar(hwnd)
                ex_style = int(win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE))
                topmost = bool(ex_style & win32con.WS_EX_TOPMOST)
                monitor_primary = self._monitor_primary_for_rect(rect)
                score = score_secondary_candidate(
                    title=title,
                    class_name=class_name,
                    rect=rect,
                    minimized=minimized,
                    topmost=topmost,
                    title_bar_visible=title_bar_visible,
                    has_jwl_core_window=has_core,
                    monitor_primary=monitor_primary,
                    target_display=target_display,
                    process_name=process_name,
                    has_jwl_descendant_hint=has_descendant_hint,
                )
                if score <= -10_000:
                    return True

                candidates.append(
                    JwlSecondaryWindowInfo(
                        hwnd=hwnd,
                        pid=pid,
                        process_name=process_name,
                        title=title,
                        class_name=class_name,
                        rect=rect,
                        visible=visible,
                        minimized=minimized,
                        topmost=topmost,
                        title_bar_visible=title_bar_visible,
                        has_jwl_core_window=has_core,
                        monitor_primary=monitor_primary,
                        score=score,
                    )
                )
            except (OSError, RuntimeError, psutil.Error):
                pass
            return True

        try:
            win32gui.EnumWindows(callback, None)
        except (OSError, RuntimeError):
            return []
        return sorted(candidates, key=lambda item: item.score, reverse=True)

    def diagnostic_snapshot(
        self,
        target_display: DisplayInfo | None,
    ) -> dict[str, Any]:
        """Return a JSON-safe Win32 inventory for troubleshooting real machines."""

        if sys.platform != "win32" or win32gui is None or win32process is None:
            return {
                "platform": sys.platform,
                "target_display": asdict(target_display) if target_display else None,
                "selected_candidate": None,
                "windows": [],
                "native_monitors": [],
            }

        process_map = self._process_map()
        selected = self.discover(target_display)
        windows: list[dict[str, Any]] = []

        def callback(hwnd: int, _: object) -> bool:
            try:
                if not win32gui.IsWindow(hwnd):
                    return True
                title = win32gui.GetWindowText(hwnd).strip()
                class_name = win32gui.GetClassName(hwnd)
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process_name = process_map.get(pid, "")
                rect = self._window_rect(hwnd)
                monitor_primary, monitor_device = self._monitor_details_for_rect(rect)
                visible = bool(win32gui.IsWindowVisible(hwnd))
                minimized = bool(win32gui.IsIconic(hwnd))

                on_target_role = bool(
                    target_display is not None
                    and monitor_primary is not None
                    and monitor_primary == target_display.primary
                )
                relevant = bool(
                    title_has_jw_library(title)
                    or looks_like_jw_library_process(process_name)
                    or class_name in {_FRAME_WINDOW_CLASS, _CORE_WINDOW_CLASS}
                    or (visible and on_target_role and rect.width >= 300 and rect.height >= 180)
                )
                if not relevant:
                    return True

                has_core = self._has_jwl_core_window(hwnd)
                has_descendant_hint = self._has_jwl_descendant_hint(hwnd)
                title_bar_visible = self._has_visible_title_bar(hwnd)
                style = int(win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE))
                ex_style = int(win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE))
                topmost = bool(ex_style & win32con.WS_EX_TOPMOST)
                score = score_secondary_candidate(
                    title=title,
                    class_name=class_name,
                    rect=rect,
                    minimized=minimized,
                    topmost=topmost,
                    title_bar_visible=title_bar_visible,
                    has_jwl_core_window=has_core,
                    monitor_primary=monitor_primary,
                    target_display=target_display,
                    process_name=process_name,
                    has_jwl_descendant_hint=has_descendant_hint,
                )
                owner = int(win32gui.GetWindow(hwnd, win32con.GW_OWNER) or 0)
                windows.append(
                    {
                        "hwnd": int(hwnd),
                        "pid": int(pid),
                        "process_name": process_name,
                        "title": title,
                        "normalized_title": normalize_window_title(title),
                        "class_name": class_name,
                        "rect": asdict(rect),
                        "visible": visible,
                        "enabled": bool(win32gui.IsWindowEnabled(hwnd)),
                        "minimized": minimized,
                        "topmost": topmost,
                        "title_bar_visible": title_bar_visible,
                        "has_jwl_core_window": has_core,
                        "has_jwl_descendant_hint": has_descendant_hint,
                        "monitor_primary": monitor_primary,
                        "monitor_device": monitor_device,
                        "style_hex": f"0x{style & 0xFFFFFFFF:08X}",
                        "ex_style_hex": f"0x{ex_style & 0xFFFFFFFF:08X}",
                        "owner_hwnd": owner,
                        "target_overlap": (
                            round(rect_overlap_ratio(rect, target_display), 4)
                            if target_display is not None
                            else None
                        ),
                        "fullscreen_on_target": (
                            is_fullscreen_on_display(rect, target_display)
                            if target_display is not None
                            else False
                        ),
                        "score": score,
                        "selected": bool(selected and selected.hwnd == hwnd),
                        "descendants": self._descendant_inventory(hwnd),
                    }
                )
            except (OSError, RuntimeError, psutil.Error):
                pass
            return True

        try:
            win32gui.EnumWindows(callback, None)
        except (OSError, RuntimeError):
            pass

        windows.sort(key=lambda item: (not item["selected"], -int(item["score"])))
        return {
            "platform": sys.platform,
            "target_display": asdict(target_display) if target_display else None,
            "selected_candidate": self._candidate_to_dict(selected),
            "windows": windows,
            "native_monitors": self._native_monitor_inventory(),
        }

    @staticmethod
    def _candidate_to_dict(item: JwlSecondaryWindowInfo | None) -> dict[str, Any] | None:
        if item is None:
            return None
        data = asdict(item)
        data["size"] = item.size
        return data

    @staticmethod
    def _process_map() -> dict[int, str]:
        processes: dict[int, str] = {}
        try:
            for process in psutil.process_iter(["pid", "name"]):
                pid = process.info.get("pid")
                if isinstance(pid, int):
                    processes[pid] = process.info.get("name") or ""
        except (psutil.Error, OSError):
            pass
        return processes

    @staticmethod
    def _window_rect(hwnd: int) -> WindowRect:
        try:
            if win32gui.IsIconic(hwnd):
                placement = win32gui.GetWindowPlacement(hwnd)
                if placement and len(placement) >= 5:
                    left, top, right, bottom = placement[4]
                    rect = WindowRect(left, top, right, bottom)
                    if rect.width >= 100 and rect.height >= 100:
                        return rect
        except (OSError, RuntimeError, TypeError, ValueError):
            pass

        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        return WindowRect(left, top, right, bottom)

    @staticmethod
    def _monitor_details_for_rect(rect: WindowRect) -> tuple[bool | None, str]:
        if win32api is None or win32con is None:
            return None, ""
        try:
            monitor = win32api.MonitorFromPoint(
                rect.center,
                win32con.MONITOR_DEFAULTTONEAREST,
            )
            info = win32api.GetMonitorInfo(monitor)
            return bool(int(info.get("Flags", 0)) & 1), str(info.get("Device", ""))
        except (OSError, RuntimeError, TypeError, ValueError):
            return None, ""

    @classmethod
    def _monitor_primary_for_rect(cls, rect: WindowRect) -> bool | None:
        primary, _device = cls._monitor_details_for_rect(rect)
        return primary

    @staticmethod
    def _native_monitor_inventory() -> list[dict[str, Any]]:
        if win32api is None:
            return []
        result: list[dict[str, Any]] = []
        try:
            for monitor, _hdc, rect in win32api.EnumDisplayMonitors():
                info = win32api.GetMonitorInfo(monitor)
                result.append(
                    {
                        "device": str(info.get("Device", "")),
                        "primary": bool(int(info.get("Flags", 0)) & 1),
                        "monitor_rect": list(info.get("Monitor", rect)),
                        "work_rect": list(info.get("Work", rect)),
                    }
                )
        except (OSError, RuntimeError, TypeError, ValueError):
            return result
        return result

    @staticmethod
    def _descendant_inventory(hwnd: int, limit: int = 80) -> list[dict[str, Any]]:
        if win32gui is None:
            return []
        result: list[dict[str, Any]] = []

        def callback(child: int, _: object) -> bool:
            if len(result) >= limit:
                return False
            try:
                result.append(
                    {
                        "hwnd": int(child),
                        "parent_hwnd": int(win32gui.GetParent(child) or 0),
                        "title": win32gui.GetWindowText(child).strip(),
                        "class_name": win32gui.GetClassName(child),
                        "visible": bool(win32gui.IsWindowVisible(child)),
                        "enabled": bool(win32gui.IsWindowEnabled(child)),
                    }
                )
            except (OSError, RuntimeError):
                pass
            return len(result) < limit

        try:
            win32gui.EnumChildWindows(hwnd, callback, None)
        except (OSError, RuntimeError):
            pass
        return result

    @staticmethod
    def _has_visible_title_bar(hwnd: int) -> bool:
        found = False

        def callback(child: int, _: object) -> bool:
            nonlocal found
            try:
                if (
                    win32gui.GetClassName(child) == _TITLEBAR_CLASS
                    and win32gui.IsWindowVisible(child)
                ):
                    found = True
                    return False
            except (OSError, RuntimeError):
                pass
            return not found

        try:
            win32gui.EnumChildWindows(hwnd, callback, None)
        except (OSError, RuntimeError):
            return False
        return found

    @staticmethod
    def _has_jwl_core_window(hwnd: int) -> bool:
        found = False

        def callback(child: int, _: object) -> bool:
            nonlocal found
            try:
                if win32gui.GetClassName(child) != _CORE_WINDOW_CLASS:
                    return True
                title = win32gui.GetWindowText(child)
                if title_has_jw_library(title):
                    found = True
                    return False
            except (OSError, RuntimeError):
                pass
            return not found

        try:
            win32gui.EnumChildWindows(hwnd, callback, None)
        except (OSError, RuntimeError):
            return False
        return found

    @staticmethod
    def _has_jwl_descendant_hint(hwnd: int) -> bool:
        found = False

        def callback(child: int, _: object) -> bool:
            nonlocal found
            try:
                class_name = win32gui.GetClassName(child)
                title = win32gui.GetWindowText(child)
                if class_name in _JWL_DESCENDANT_CLASSES or title_has_jw_library(title):
                    found = True
                    return False
            except (OSError, RuntimeError):
                pass
            return not found

        try:
            win32gui.EnumChildWindows(hwnd, callback, None)
        except (OSError, RuntimeError):
            return False
        return found

    def _ensure_window(
        self,
        item: JwlSecondaryWindowInfo,
        target: DisplayInfo,
    ) -> JwlSecondaryWindowInfo:
        if win32gui is None or win32con is None:
            return item
        try:
            if item.minimized:
                win32gui.ShowWindow(item.hwnd, win32con.SW_SHOWNOACTIVATE)

            overlap = rect_overlap_ratio(item.rect, target)
            geometry_matches = overlap >= 0.90 and is_fullscreen_on_display(item.rect, target)
            same_monitor_role = (
                item.monitor_primary is not None
                and item.monitor_primary == target.primary
            )
            if not geometry_matches and not same_monitor_role:
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

            refreshed = self.discover(target)
            return refreshed or item
        except (OSError, RuntimeError):
            return item

    def _emit_status(self, ok: bool, message: str) -> None:
        current = (ok, message)
        if current == self._last_status:
            return
        self._last_status = current
        self.status_changed.emit(ok, message)
