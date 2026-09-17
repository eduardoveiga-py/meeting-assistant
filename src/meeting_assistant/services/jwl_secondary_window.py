from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Callable

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

from meeting_assistant.services.display_service import DisplayInfo

try:
    import win32con
    import win32gui
    import win32process
except ImportError:  # pragma: no cover - Windows-only implementation
    win32con = None
    win32gui = None
    win32process = None

_BIDI_MARKS = "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
_BIDI_TRANSLATION = str.maketrans("", "", _BIDI_MARKS)
_TITLEBAR_CLASS = "ApplicationFrameTitleBarWindow"
_CORE_WINDOW_CLASS = "Windows.UI.Core.CoreWindow"
_FRAME_WINDOW_CLASS = "ApplicationFrameWindow"
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
    score: int

    @property
    def size(self) -> str:
        return f"{self.rect.width}x{self.rect.height}"


def normalize_window_title(title: str) -> str:
    cleaned = title.translate(_BIDI_TRANSLATION)
    cleaned = cleaned.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", cleaned).strip().casefold()


def is_explicit_jwl_secondary_title(title: str) -> bool:
    normalized = normalize_window_title(title)
    return (
        "jw library" in normalized
        and "sign language" not in normalized
        and any(prefix in normalized for prefix in ("second display", "second screen"))
    )


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
    target_display: DisplayInfo | None,
) -> int:
    normalized = normalize_window_title(title)
    score = 0

    if is_explicit_jwl_secondary_title(title):
        score += 1200
    if class_name == _FRAME_WINDOW_CLASS:
        score += 80
    if "jw library" in normalized and "sign language" not in normalized:
        score += 160
    if has_jwl_core_window:
        score += 520
    if topmost:
        score += 90
    if not title_bar_visible:
        score += 170
    if minimized:
        score += 20  # minimized secondary output must remain discoverable

    if target_display is not None:
        overlap = rect_overlap_ratio(rect, target_display)
        if overlap >= 0.70:
            score += 420
        elif overlap >= 0.30:
            score += 120
        else:
            score -= 700
        if is_fullscreen_on_display(rect, target_display):
            score += 300

    # ApplicationFrameHost also hosts unrelated UWP apps. A structural JW signal
    # is mandatory unless the special secondary-window title is present.
    if not is_explicit_jwl_secondary_title(title) and not has_jwl_core_window:
        return -10_000
    return score


def choose_secondary_candidate(
    candidates: list[JwlSecondaryWindowInfo],
) -> JwlSecondaryWindowInfo | None:
    if not candidates:
        return None
    best = max(candidates, key=lambda item: item.score)
    return best if best.score >= 650 else None


class JwlSecondaryWindowService(QObject):
    """Find and protect the real JW Library second-display window.

    Discovery intentionally does not trust ApplicationFrameHost.exe by itself.
    The host process is shared by unrelated UWP applications. Instead, the
    secondary output is recognized by the special JWL title when present or by
    its embedded Windows.UI.Core.CoreWindow plus fullscreen/title-bar traits.
    """

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
                explicit_title = is_explicit_jwl_secondary_title(title)
                if class_name != _FRAME_WINDOW_CLASS and not explicit_title:
                    return True

                has_core = self._has_jwl_core_window(hwnd)
                if not explicit_title and not has_core:
                    return True

                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process_name = process_map.get(pid, "")
                rect = self._window_rect(hwnd)
                minimized = bool(win32gui.IsIconic(hwnd))
                visible = bool(win32gui.IsWindowVisible(hwnd))
                title_bar_visible = self._has_visible_title_bar(hwnd)
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
                    target_display=target_display,
                )
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
            placement = win32gui.GetWindowPlacement(hwnd)
            # rcNormalPosition remains useful while the window is minimized.
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
                title = normalize_window_title(win32gui.GetWindowText(child))
                if "jw library" in title and "sign language" not in title:
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
                # Restore without intentionally taking keyboard focus.
                win32gui.ShowWindow(item.hwnd, win32con.SW_SHOWNOACTIVATE)

            overlap = rect_overlap_ratio(item.rect, target)
            if overlap < 0.90 or not is_fullscreen_on_display(item.rect, target):
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
