from __future__ import annotations

from dataclasses import dataclass, replace

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

try:
    import win32api
    import win32gui
    import win32process
except ImportError:  # pragma: no cover - exercised only outside Windows
    win32api = None
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
    monitor_primary: bool | None = None

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


def describe_hosted_process(host_process_name: str, child_process_name: str) -> str:
    if not child_process_name or child_process_name == host_process_name:
        return host_process_name
    if not host_process_name:
        return child_process_name
    return f"{host_process_name} → {child_process_name}"


def is_related_jwl_host_window(
    process_name: str,
    pid: int,
    known_jwl_host_pids: set[int],
) -> bool:
    """Return whether a title-less top-level window belongs to a known JWL host.

    JW Library may create its fullscreen presentation window as a sibling of the
    titled operator window. Both are commonly hosted by the same
    ApplicationFrameHost process, while the presentation sibling has no useful
    title. Once a PID is proven to host JW Library, those sibling windows are
    safe candidates for monitor-based selection.
    """

    if pid not in known_jwl_host_pids:
        return False

    normalized = process_name.casefold().replace(" ", "")
    return normalized == "applicationframehost.exe" or looks_like_jw_library(
        process_name,
        "",
    )


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
                item.monitor_primary,
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
        return any(looks_like_jw_library(name, "") for name in self._process_map().values())

    def _hosted_jwl_process_name(
        self,
        hwnd: int,
        process_map: dict[int, str],
    ) -> str:
        if win32gui is None or win32process is None:
            return ""

        matches: list[str] = []

        def child_callback(child_hwnd: int, _: object) -> bool:
            try:
                _, child_pid = win32process.GetWindowThreadProcessId(child_hwnd)
                child_name = process_map.get(child_pid, "")
                if looks_like_jw_library(child_name, ""):
                    matches.append(child_name)
            except (OSError, RuntimeError):
                pass
            return True

        try:
            win32gui.EnumChildWindows(hwnd, child_callback, None)
        except (OSError, RuntimeError):
            return ""
        return matches[0] if matches else ""

    def _monitor_primary(self, hwnd: int) -> bool | None:
        if win32api is None:
            return None
        try:
            monitor = win32api.MonitorFromWindow(hwnd, 0)
            if not monitor:
                return None
            info = win32api.GetMonitorInfo(monitor)
            return bool(int(info.get("Flags", 0)) & 1)
        except (OSError, RuntimeError):
            return None

    def _discover_windows(self, include_hidden: bool = False) -> list[JwlWindowInfo]:
        if win32gui is None or win32process is None:
            return []

        process_map = self._process_map()
        raw_windows: list[JwlWindowInfo] = []
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
                class_name = win32gui.GetClassName(hwnd)
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                raw_windows.append(
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
                        monitor_primary=self._monitor_primary(hwnd),
                    )
                )
            except (OSError, RuntimeError, psutil.Error):
                pass
            return True

        win32gui.EnumWindows(callback, None)

        classified_by_hwnd: dict[int, JwlWindowInfo] = {}
        known_jwl_host_pids: set[int] = set()

        # Pass 1: establish trusted JW Library host PIDs from titled/direct
        # windows or from a JWLibrary.exe child hosted by ApplicationFrameHost.
        for item in raw_windows:
            if looks_like_jw_library(item.process_name, item.title):
                classified_by_hwnd[item.hwnd] = item
                known_jwl_host_pids.add(item.pid)
                continue

            child_process_name = self._hosted_jwl_process_name(item.hwnd, process_map)
            if not child_process_name:
                continue

            classified_by_hwnd[item.hwnd] = replace(
                item,
                process_name=describe_hosted_process(
                    item.process_name,
                    child_process_name,
                ),
            )
            known_jwl_host_pids.add(item.pid)

        # Pass 2: include title-less sibling windows of a proven JW Library
        # host. The Hall output is then selected by monitor/geometry, so an
        # operator window on the primary display cannot win by accident.
        for item in raw_windows:
            if item.hwnd in classified_by_hwnd:
                continue
            if is_related_jwl_host_window(
                item.process_name,
                item.pid,
                known_jwl_host_pids,
            ):
                classified_by_hwnd[item.hwnd] = item

        windows = list(classified_by_hwnd.values())
        windows.sort(key=lambda item: (not item.visible, item.top, item.left, item.hwnd))
        return windows
