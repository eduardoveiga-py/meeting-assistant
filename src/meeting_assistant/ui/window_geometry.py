"""Keep operator windows inside Qt's DPI-aware desktop work area."""

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
        self._window = window
        self._handle = None
        self._screen = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fit)
        window.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Show:
            handle = self._window.windowHandle()
            if handle is not None and handle is not self._handle:
                self._handle = handle
                handle.screenChanged.connect(self._screen_changed)
            self._screen_changed(self._window.screen())
        return super().eventFilter(watched, event)

    def _screen_changed(self, screen) -> None:
        if self._screen is not screen:
            if self._screen is not None:
                try:
                    self._screen.availableGeometryChanged.disconnect(self._schedule)
                except RuntimeError:
                    pass
            self._screen = screen
            if screen is not None:
                screen.availableGeometryChanged.connect(self._schedule)
        self._schedule()

    def _schedule(self, *_args) -> None:
        self._timer.start(0)

    def _fit(self) -> None:
        fit_window(self._window)
