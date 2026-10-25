"""Keep operator windows inside Qt's DPI-aware desktop work area."""

import shiboken6
from PySide6.QtCore import QEvent, QObject, QRect, QTimer
from PySide6.QtWidgets import QWidget


def fit_window(window: QWidget, available: QRect | None = None) -> None:
    if window.isMaximized() or window.isMinimized():
        return
    screen = window.screen()
    if available is None:
        if screen is None:
            return
        available = screen.availableGeometry()
    area = available.adjusted(8, 8, -8, -8)
    frame = window.frameGeometry()
    border_width = max(0, frame.width() - window.width())
    border_height = max(0, frame.height() - window.height())
    width = max(1, area.width() - border_width)
    height = max(1, area.height() - border_height)
    window.resize(min(window.width(), width), min(window.height(), height))
    frame = window.frameGeometry()
    x = max(area.left(), min(frame.x(), area.right() - frame.width() + 1))
    y = max(area.top(), min(frame.y(), area.bottom() - frame.height() + 1))
    window.move(x, y)


class ScreenFitController(QObject):
    """Fit after native frame creation and when the monitor/work area changes."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window: QWidget | None = window
        self._handle = None
        self._screen = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fit)
        window.installEventFilter(self)

    def cleanup(self, *_args) -> None:
        try:
            if not shiboken6.isValid(self):
                return
        except Exception:
            return
        if self._timer is not None:
            try:
                if shiboken6.isValid(self._timer):
                    self._timer.stop()
            except Exception:
                pass
        if self._screen is not None:
            try:
                if shiboken6.isValid(self._screen):
                    self._screen.availableGeometryChanged.disconnect(self._schedule)
            except (RuntimeError, TypeError, ReferenceError):
                pass
            self._screen = None
        if self._handle is not None:
            try:
                if shiboken6.isValid(self._handle):
                    self._handle.screenChanged.disconnect(self._screen_changed)
            except (RuntimeError, TypeError, ReferenceError):
                pass
            self._handle = None
        if self._window is not None:
            try:
                if shiboken6.isValid(self._window):
                    self._window.removeEventFilter(self)
            except Exception:
                pass
            self._window = None

    def eventFilter(self, watched, event):
        try:
            if not shiboken6.isValid(self):
                return False
        except Exception:
            return False

        event_type = event.type()
        if event_type == QEvent.Type.Show:
            if self._window is not None:
                try:
                    if shiboken6.isValid(self._window):
                        handle = self._window.windowHandle()
                        if (
                            handle is not None
                            and shiboken6.isValid(handle)
                            and hasattr(handle, "screenChanged")
                            and handle is not self._handle
                        ):
                            self._handle = handle
                            handle.screenChanged.connect(self._screen_changed)
                        if hasattr(self._window, "screen"):
                            self._screen_changed(self._window.screen())
                except (RuntimeError, ReferenceError):
                    pass
        elif event_type == QEvent.Type.Close:
            self.cleanup()
        return super().eventFilter(watched, event)

    def _screen_changed(self, screen) -> None:
        if self._screen is not screen:
            if self._screen is not None:
                try:
                    if shiboken6.isValid(self._screen):
                        self._screen.availableGeometryChanged.disconnect(self._schedule)
                except (RuntimeError, TypeError, ReferenceError):
                    pass
            self._screen = screen
            if screen is not None:
                try:
                    if shiboken6.isValid(screen):
                        screen.availableGeometryChanged.connect(self._schedule)
                except (RuntimeError, TypeError, ReferenceError):
                    pass
        self._schedule()

    def _schedule(self, *_args) -> None:
        if self._window is not None and self._timer is not None:
            try:
                if shiboken6.isValid(self._window) and shiboken6.isValid(self._timer):
                    self._timer.start(0)
            except (RuntimeError, ReferenceError):
                pass

    def _fit(self) -> None:
        if self._window is not None:
            try:
                if shiboken6.isValid(self._window):
                    fit_window(self._window)
            except (RuntimeError, Exception):
                pass
