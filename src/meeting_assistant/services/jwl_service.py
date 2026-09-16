from __future__ import annotations

from dataclasses import dataclass

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

try:
    import win32gui
    import win32process
except ImportError:  # pragma: no cover - exercised only outside Windows
    win32gui = None
    win32process = None


@dataclass(frozen=True, slots=True)
class JwlWindowInfo:
    hwnd: int
    pid: int
    process_name: str
    title: str
    class_name: str
    left: int
    top: int
    right: int
    bottom: int
    visible: bool
    minimized: bool
    foreground: bool

    @property
    def size(self) -> str:
        return f"{max(0, self.right - self.left)}x{max(0, self.bottom - self.top)}"


def looks_like_jw_library(process_name: str, title: str) -> bool:
    process = process_name.casefold()
    window_title = title.casefold()

    if "sign language" in process or "sign language" in window_title:
        return False

    if "jw library" in window_title:
        return True

    compact_process = process.replace(" ", "").replace("_", "").replace("-", "")
    return "jwlibrary" in compact_process


class JwlService(QObject):
    status_changed = Signal(bool, str)
    snapshot_changed = Signal(list)

    def __init__(self, interval_ms: int = 2000) -> None:
        super().__init__()
        self._timer = QTimer(self)
        self._timer.setInterval(max(1000, interval_ms))
        self._timer.timeout.connect(self.refresh)
        self._last_running: bool | None = None
        self._last_signature: tuple[tuple[object, ...], ...] = ()
        self._snapshot: list[JwlWindowInfo] = []

    def start(self) -> None:
        self.refresh()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def snapshot(self) -> list[JwlWindowInfo]:
        return list(self._snapshot)

    def scan(self, include_hidden: bool = False) -> list[JwlWindowInfo]:
        return self._discover_windows(include_hidden=include_hidden)

    def refresh(self) -> None:
        snapshot = self.scan(include_hidden=False)
        signature = tuple(
            (
                item.hwnd,
                item.pid,
                item.process_name,
                item.title,
                item.class_name,
                item.left,
                item.top,
                item.right,
                item.bottom,
                item.visible,
                item.minimized,
            )
            for item in snapshot
        )
        running = bool(snapshot) or self._has_candidate_process()

        if signature != self._last_signature:
            self._last_signature = signature
            self._snapshot = snapshot
            self.snapshot_changed.emit(snapshot)

        if running != self._last_running:
            self._last_running = running
            if running:
                window_count = len(snapshot)
                message = (
                    f"JW Library detectado • {window_count} janela(s) candidata(s)"
                    if window_count
                    else "Processo do JW Library detectado; aguardando janela visível"
                )
            else:
                message = "JW Library não detectado"
            self.status_changed.emit(running, message)

    def _process_map(self) -> dict[int, str]:
        processes: dict[int, str] = {}
        try:
            for process in psutil.process_iter(["pid", "name"]):
                pid = process.info.get("pid")
                if not isinstance(pid, int):
                    continue
                processes[pid] = process.info.get("name") or ""
        except (psutil.Error, OSError):
            return processes
        return processes

    def _has_candidate_process(self) -> bool:
        return any(
            looks_like_jw_library(name, "")
            for name in self._process_map().values()
        )

    def _discover_windows(self, include_hidden: bool = False) -> list[JwlWindowInfo]:
        if win32gui is None or win32process is None:
            return []

        process_map = self._process_map()
        windows: list[JwlWindowInfo] = []
        try:
            foreground_hwnd = win32gui.GetForegroundWindow()
        except (OSError, RuntimeError):
            foreground_hwnd = 0

        def callback(hwnd: int, _: object) -> bool:
            try:
                if not win32gui.IsWindow(hwnd):
                    return True

                visible = bool(win32gui.IsWindowVisible(hwnd))
                if not include_hidden and not visible:
                    return True

                title = win32gui.GetWindowText(hwnd).strip()
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process_name = process_map.get(pid, "")
                if not looks_like_jw_library(process_name, title):
                    return True

                class_name = win32gui.GetClassName(hwnd)
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                windows.append(
                    JwlWindowInfo(
                        hwnd=hwnd,
                        pid=pid,
                        process_name=process_name,
                        title=title,
                        class_name=class_name,
                        left=left,
                        top=top,
                        right=right,
                        bottom=bottom,
                        visible=visible,
                        minimized=bool(win32gui.IsIconic(hwnd)),
                        foreground=hwnd == foreground_hwnd,
                    )
                )
            except (OSError, RuntimeError, psutil.Error):
                pass
            return True

        win32gui.EnumWindows(callback, None)
        windows.sort(key=lambda item: (not item.visible, item.top, item.left, item.hwnd))
        return windows
