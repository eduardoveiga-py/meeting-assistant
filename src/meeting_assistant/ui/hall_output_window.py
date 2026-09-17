from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QImage, QPixmap, QResizeEvent, QScreen, QShowEvent
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

WDA_EXCLUDEFROMCAPTURE = 0x00000011


def exclude_window_from_capture(hwnd: int) -> bool:
    """Hide one of our own top-level windows from Windows screen capture."""

    if sys.platform != "win32" or hwnd <= 0:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.SetWindowDisplayAffinity.restype = ctypes.c_bool
        return bool(
            user32.SetWindowDisplayAffinity(
                ctypes.c_void_p(hwnd),
                WDA_EXCLUDEFROMCAPTURE,
            )
        )
    except (AttributeError, OSError):
        return False


class HallOutputWindow(QWidget):
    """Borderless Hall renderer that stays invisible to the capture pipeline.

    The idle layer is a clean reference frame (normally the Text of the Year).
    The media layer receives the live Hall-monitor capture. Fading the media
    layer in/out gives us a smooth transition without changing what JW Library
    itself is doing underneath this window.
    """

    capture_exclusion_changed = Signal(bool)

    def __init__(self, *, fade_duration_ms: int = 300) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setObjectName("HallOutputWindow")
        self.setWindowTitle("Meeting Assistant — Saída do Salão")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet("background: #000;")
        self.setCursor(Qt.CursorShape.BlankCursor)

        self._idle_image = QImage()
        self._media_image = QImage()
        self._capture_excluded = False

        self._idle_label = QLabel(self)
        self._media_label = QLabel(self)
        for label in (self._idle_label, self._media_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("background: #000;")

        self._media_opacity = QGraphicsOpacityEffect(self._media_label)
        self._media_opacity.setOpacity(1.0)
        self._media_label.setGraphicsEffect(self._media_opacity)

        self._fade = QPropertyAnimation(self._media_opacity, b"opacity", self)
        self._fade.setDuration(max(0, fade_duration_ms))
        self._fade.setEasingCurve(QEasingCurve.Type.InOutQuad)

    @property
    def capture_excluded(self) -> bool:
        return self._capture_excluded

    @property
    def media_opacity(self) -> float:
        return float(self._media_opacity.opacity())

    def show_on_screen(self, screen: QScreen) -> None:
        """Show fullscreen on the requested physical screen without taking focus."""

        # Materialize the native handle before assigning its screen.
        self.winId()
        handle = self.windowHandle()
        if handle is not None:
            handle.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.raise_()

    def set_idle_image(self, image: QImage) -> None:
        self._idle_image = image.copy()
        self._render_idle()

    def update_media_frame(self, image: QImage) -> None:
        self._media_image = image.copy()
        self._render_media()

    def show_media(self, *, animated: bool = True) -> None:
        self._animate_media_opacity(1.0, animated=animated)

    def show_idle(self, *, animated: bool = True) -> None:
        self._animate_media_opacity(0.0, animated=animated)

    def _animate_media_opacity(self, target: float, *, animated: bool) -> None:
        target = max(0.0, min(1.0, target))
        self._fade.stop()
        if not animated or self._fade.duration() <= 0:
            self._media_opacity.setOpacity(target)
            return
        self._fade.setStartValue(self._media_opacity.opacity())
        self._fade.setEndValue(target)
        self._fade.start()

    def _scaled_pixmap(self, image: QImage) -> QPixmap | None:
        if image.isNull() or self.width() <= 0 or self.height() <= 0:
            return None
        return QPixmap.fromImage(image).scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _render_idle(self) -> None:
        pixmap = self._scaled_pixmap(self._idle_image)
        if pixmap is None:
            self._idle_label.clear()
        else:
            self._idle_label.setPixmap(pixmap)

    def _render_media(self) -> None:
        pixmap = self._scaled_pixmap(self._media_image)
        if pixmap is None:
            self._media_label.clear()
        else:
            self._media_label.setPixmap(pixmap)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        rect = self.rect()
        self._idle_label.setGeometry(rect)
        self._media_label.setGeometry(rect)
        self._render_idle()
        self._render_media()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        excluded = exclude_window_from_capture(int(self.winId()))
        if excluded != self._capture_excluded:
            self._capture_excluded = excluded
            self.capture_exclusion_changed.emit(excluded)
