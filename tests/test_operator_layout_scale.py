"""Render the real operator window in separate Qt processes at each DPI scale."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtGui import QFontMetrics, QIcon
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

import meeting_assistant.ui.program_preview as preview_module
from meeting_assistant.core.state import AppState
from meeting_assistant.services.settings import AppSettings, SettingsService
from meeting_assistant.ui.main_window import MainWindow
from meeting_assistant.ui.window_geometry import fit_window


class Monitor(QObject):
    frame_ready = Signal(object)
    status_changed = Signal(str)
    last_status = "Ponte de vídeo indisponível."
    last_frame = None

    def start(self):
        pass


app = QApplication([])
monitor = Monitor()
preview_module.program_video = lambda: monitor
services = [MagicMock() for _ in range(6)]
services[1].snapshot.return_value = []
services[2].snapshot.return_value = []
services[4].busy = False
services[5].active = False
services[5].returning = False
root = Path(sys.argv[1])
scale = float(sys.argv[2])
icon = QIcon(str(Path.cwd() / "src/meeting_assistant/resources/app_icon.svg"))
window = MainWindow(
    AppState(), AppSettings(), SettingsService(root / "settings.json"), *services, app_icon=icon
)
work_area = QRect(0, 0, round(1920 / scale), round(1040 / scale))
# Isolate the synthetic Full HD desktop before native show() can process real
# runner screen events. Screen fitting itself has separate event tests.
window.removeEventFilter(window._screen_fit)
window._screen_fit._timer.stop()
window._screen_fit._timer.timeout.disconnect()
window.resize(520, min(780, work_area.height() - 40))
window.show()
# Native window creation can clamp the initial size to the runner's smaller
# desktop. Once it exists, apply the explicit test size and work area again.
app.processEvents()
window.resize(520, min(780, work_area.height() - 40))
fit_window(window, work_area)
app.processEvents()
title = window.findChild(QLabel, "Title")
subtitle = window.findChild(QLabel, "Subtitle")
badge = window.automation_badge
scroll = window.centralWidget()
result = {
    "scale": window.devicePixelRatioF(),
    "window_height": window.height(),
    "viewport_height": scroll.viewport().height(),
    "work_area_height": work_area.height(),
    "title_width": title.width(),
    "subtitle_width": subtitle.width(),
    "badge_height": badge.height(),
    "badge_natural_height": badge.sizeHint().height(),
    "preview_height": window.preview.height(),
    "horizontal_scroll": scroll.horizontalScrollBar().maximum(),
    "vertical_scroll": scroll.verticalScrollBar().maximum(),
}
try:
    rendered = window.grab()
    assert not rendered.isNull(), result
    result["rendered_width"] = rendered.width()
    result["logical_width"] = window.width()
    if len(sys.argv) > 3:
        assert rendered.save(sys.argv[3]), "Could not save layout image"
    assert QFontMetrics(title.font()).inFontUcs4(ord("M")), "Header font has no Latin glyphs"
    assert work_area.contains(window.frameGeometry()), result
    for label in (title, subtitle, badge):
        assert label.isVisible() and label.width() > 0, result
        assert scroll.viewport().rect().contains(
            label.mapTo(scroll.viewport(), label.rect().topLeft())
        ), result
        assert scroll.viewport().rect().contains(
            label.mapTo(scroll.viewport(), label.rect().bottomRight())
        ), result
    for label in (title, subtitle):
        assert label.height() >= label.heightForWidth(label.width()), result
    assert badge.height() == badge.sizeHint().height(), result
    assert window.preview.height() >= (100 if work_area.height() >= 600 else 40), result
    assert result["horizontal_scroll"] == result["vertical_scroll"] == 0, result
    for button in window.findChildren(QPushButton):
        if button.isVisible():
            assert button.sizeHint().width() <= button.width(), (button.text(), result)
            assert scroll.viewport().rect().contains(
                button.mapTo(scroll.viewport(), button.rect().bottomRight())
            ), (button.text(), result)
    print(json.dumps(result))
finally:
    window.close()
'''


@pytest.mark.parametrize("scale", ["1", "1.25", "1.5", "2"])
def test_operator_header_and_controls_render_at_desktop_scale(tmp_path, scale):
    env = dict(os.environ)
    # The Windows offscreen plugin renders missing-glyph boxes instead of
    # system fonts. Use the native Qt platform for representative Windows
    # text metrics and images; services remain isolated from real devices.
    env["QT_QPA_PLATFORM"] = "windows" if sys.platform == "win32" else "offscreen"
    env["QT_SCALE_FACTOR"] = scale
    env["PYTHONPATH"] = str(ROOT / "src")
    command = [sys.executable, "-c", PROBE, str(tmp_path), scale]
    capture_directory = env.get("MEETING_ASSISTANT_LAYOUT_CAPTURE_DIRECTORY")
    if capture_directory:
        directory = Path(capture_directory)
        directory.mkdir(parents=True, exist_ok=True)
        command.append(str(directory / f"layout-{scale.replace('.', '_')}.png"))
    process = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    result = json.loads(process.stdout.strip().splitlines()[-1])
    assert result["scale"] == pytest.approx(float(scale))
    assert result["rendered_width"] == pytest.approx(result["logical_width"] * float(scale), abs=1)
