"""Qt logical-pixel layout for the fixed-width operator window."""

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from meeting_assistant.services.window_layout import decode_rect
from meeting_assistant.ui.window_geometry import fit_window


def restore_app(window, saved):
    screen = QApplication.primaryScreen()
    if screen is None:
        return
    area = screen.availableGeometry()
    monitors = [
        {
            "name": screen.name(),
            "primary": True,
            "work": (area.x(), area.y(), area.x() + area.width(), area.y() + area.height()),
        }
    ]
    rect = None
    if isinstance(saved, dict) and saved.get("version") == 2:
        rect = decode_rect(saved.get("roles", {}).get("app"), monitors)
    # Legacy JWL/Zoom rectangles are ambiguous and never migrated. Only the
    # operator app's known x/y/w/h format is safe to recover and clamp.
    elif isinstance(saved, dict):
        legacy = saved.get("meeting_assistant")
        if isinstance(legacy, list) and len(legacy) == 4 and all(type(v) is int for v in legacy):
            rect = (legacy[0], legacy[1], legacy[0] + legacy[2], legacy[1] + legacy[3])
    if rect:
        window.setGeometry(rect[0], rect[1], min(520, rect[2] - rect[0]), rect[3] - rect[1])
    else:
        window.move(area.left() + 8, area.top() + 8)
    fit_window(window, QRect(area))


def operator_fraction(window):
    area = QApplication.primaryScreen().availableGeometry()
    return min(0.65, (window.frameGeometry().right() - area.left() + 1) / max(1, area.width()))
