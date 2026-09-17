from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from meeting_assistant.services.display_service import DisplayInfo
from meeting_assistant.services.jwl_service import JwlWindowInfo

try:
    import numpy as np
    from windows_capture import Frame, InternalCaptureControl, WindowsCapture
except ImportError:  # pragma: no cover - exercised only when optional Windows deps are unavailable
    np = None
    Frame = Any  # type: ignore[misc,assignment]
    InternalCaptureControl = Any  # type: ignore[misc,assignment]
    WindowsCapture = None


@dataclass(frozen=True, slots=True)
class CaptureTarget:
    window: JwlWindowInfo
    overlap_area: int


def _intersection_area(window: JwlWindowInfo, display: DisplayInfo) -> int:
    left = max(window.left, display.x)
    top = max(window.top, display.y)
    right = min(window.right, display.x + display.width)
    bottom = min(window.bottom, display.y + display.height)
    return max(0, right - left) * max(0, bottom - top)


def _window_area(window: JwlWindowInfo) -> int:
    return max(0, window.right - window.left) * max(0, window.bottom - window.top)


def select_jwl_capture_target(
    windows: list[JwlWindowInfo],
    hall_display: DisplayInfo | None,
) -> CaptureTarget | None:
    """Select the visible JW Library window that belongs to the Hall display.

    Coordinate overlap is preferred. Windows can expose monitor geometry through
    a DPI coordinate space that differs from Qt's QScreen geometry, so when the
    overlap is zero we may safely fall back to a JW Library window that Win32
    explicitly reports on a non-primary monitor. We never fall back to a window
    known to be on the primary/operator monitor.
    """

    candidates = [
        window
        for window in windows
        if window.visible
        and not window.minimized
        and window.right - window.left >= 320
        and window.bottom - window.top >= 180
    ]
    if not candidates:
        return None

    if hall_display is None:
        window = max(candidates, key=_window_area)
        return CaptureTarget(window=window, overlap_area=0)

    ranked = [
        CaptureTarget(window=window, overlap_area=_intersection_area(window, hall_display))
        for window in candidates
    ]
    overlapping = [target for target in ranked if target.overlap_area > 0]
    if overlapping:
        return max(
            overlapping,
            key=lambda target: (target.overlap_area, _window_area(target.window)),
        )

    if not hall_display.primary:
        secondary_candidates = [
            window for window in candidates if window.monitor_primary is False
        ]
        if secondary_candidates:
            window = max(secondary_candidates, key=_window_area)
            return CaptureTarget(window=window, overlap_area=0)

    return None


class JwlWindowCapture(QObject):
    """Live Windows Graphics Capture stream for one JW Library HWND.

    The native capture callback never touches Qt widgets. It copies the newest
    frame into a single-slot buffer; a Qt timer then publishes at most one
    current frame per UI tick. This naturally drops stale frames instead of
    building a signal backlog during video playback.
    """

    frame_ready = Signal(object, float, int, int)
    status_changed = Signal(bool, str)

    def __init__(self, ui_interval_ms: int = 33) -> None:
        super().__init__()
        self._timer = QTimer(self)
        self._timer.setInterval(max(16, ui_interval_ms))
        self._timer.timeout.connect(self._publish_latest_frame)

        self._lock = threading.Lock()
        self._latest_bgr: Any | None = None
        self._latest_sequence = 0
        self._published_sequence = 0
        self._frame_times: list[float] = []

        self._capture: Any | None = None
        self._capture_control: Any | None = None
        self._hwnd: int | None = None
        self._closed_by_us = False

    @property
    def hwnd(self) -> int | None:
        return self._hwnd

    def start(self, hwnd: int) -> bool:
        self.stop()

        if sys.platform != "win32":
            self.status_changed.emit(False, "Captura direta disponível somente no Windows.")
            return False
        if WindowsCapture is None or np is None:
            self.status_changed.emit(
                False,
                "Dependência windows-capture não instalada. Execute scripts/setup-dev.ps1.",
            )
            return False
        if hwnd <= 0:
            self.status_changed.emit(False, "HWND inválido para captura.")
            return False

        self._hwnd = hwnd
        self._closed_by_us = False
        self._frame_times.clear()
        self._latest_sequence = 0
        self._published_sequence = 0

        try:
            capture = WindowsCapture(
                cursor_capture=False,
                draw_border=False,
                secondary_window=False,
                minimum_update_interval=33,
                window_hwnd=hwnd,
            )

            @capture.event
            def on_frame_arrived(
                frame: Frame,
                _capture_control: InternalCaptureControl,
            ) -> None:
                # windows-capture exposes a zero-copy native-backed ndarray.
                # Retained pixels must be copied before this callback returns.
                bgr = np.ascontiguousarray(frame.frame_buffer[:, :, :3]).copy()
                now = time.perf_counter()
                with self._lock:
                    self._latest_bgr = bgr
                    self._latest_sequence += 1
                    self._frame_times.append(now)
                    cutoff = now - 1.5
                    while self._frame_times and self._frame_times[0] < cutoff:
                        self._frame_times.pop(0)

            @capture.event
            def on_closed() -> None:
                if not self._closed_by_us:
                    self.status_changed.emit(
                        False,
                        "A janela capturada foi fechada ou a sessão de captura terminou.",
                    )

            self._capture = capture
            self._capture_control = capture.start_free_threaded()
            self._timer.start()
            self.status_changed.emit(True, f"Captura direta ativa • HWND {hwnd}")
            return True
        except Exception as exc:  # noqa: BLE001 - native capture failures must be surfaced safely
            self._capture = None
            self._capture_control = None
            self._hwnd = None
            self.status_changed.emit(False, f"Falha ao iniciar captura direta: {exc}")
            return False

    def stop(self) -> None:
        self._timer.stop()
        self._closed_by_us = True

        control = self._capture_control
        self._capture_control = None
        self._capture = None
        self._hwnd = None

        with self._lock:
            self._latest_bgr = None
            self._latest_sequence = 0
            self._published_sequence = 0
            self._frame_times.clear()

        if control is not None:
            try:
                control.stop()
            except (OSError, RuntimeError):
                pass

    def _publish_latest_frame(self) -> None:
        with self._lock:
            if (
                self._latest_bgr is None
                or self._latest_sequence == self._published_sequence
            ):
                return
            bgr = self._latest_bgr
            sequence = self._latest_sequence
            frame_times = tuple(self._frame_times)

        height, width, _channels = bgr.shape
        stride = int(bgr.strides[0])
        image = QImage(
            bgr.data,
            width,
            height,
            stride,
            QImage.Format.Format_BGR888,
        ).copy()

        fps = 0.0
        if len(frame_times) >= 2:
            elapsed = frame_times[-1] - frame_times[0]
            if elapsed > 0:
                fps = (len(frame_times) - 1) / elapsed

        self._published_sequence = sequence
        self.frame_ready.emit(image, fps, width, height)
