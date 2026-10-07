"""Render every category and inner page with native Windows metrics at each DPI."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = r"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QCheckBox, QScrollArea, QLayout

import meeting_assistant.ui.program_preview as preview_module
import meeting_assistant.ui.virtual_camera_dialog as camera_module
from meeting_assistant.ui.setup_assistant_dialog import SetupAssistantDialog
from meeting_assistant.ui.window_geometry import fit_window
from test_settings_workspace import make_owner, run_queued
from test_yeartext_store import png

class Monitor(QObject):
    frame_ready = Signal(object)
    status_changed = Signal(str)
    last_status = "Aguardando Program do OBS."
    last_frame = None
    diagnostic = {}
    def start(self):
        pass

root, scale = Path(sys.argv[1]), float(sys.argv[2])
profile = root / "appdata/obs-studio/basic/profiles/unit"
profile.mkdir(parents=True)
(profile / "basic.ini").write_text(
    "[General]\nName=Unit audio\n[Audio]\nMonitoringDeviceId=cable\nMonitoringDeviceName=CABLE Input\n"
)
os.environ["APPDATA"] = str(root / "appdata")
app = QApplication([])
monitor = Monitor()
preview_module.program_video = lambda: monitor
camera_module.program_video = lambda: monitor
owner, fake = make_owner(root)
owner.yeartext_store.save(png(), datetime.now().year)
dialog = SetupAssistantDialog(owner, page="meeting")
dialog.removeEventFilter(dialog._fit)
dialog._fit._timer.stop()
dialog._fit._timer.timeout.disconnect()
area = QRect(0, 0, round(1920 / scale), round(1040 / scale))
# Like the operator-window probe, request the synthetic desktop size before
# native creation; otherwise Windows retains the constructor's 700 px height.
dialog.resize(620, min(700, area.height() - 40))
dialog.show()
app.processEvents()
views = [("meeting", None), ("video", 0), ("video", 1), ("video", 2), ("video", 3),
         ("audio", 0), ("audio", 1), ("audio", 2), ("installation", None), ("diagnostics", None)]
for page, tab in views:
    dialog.select_page(page)
    if page == "video":
        dialog.video_tabs.setCurrentIndex(tab)
    elif page == "audio":
        dialog.audio.tabs.setCurrentIndex(tab)
    app.processEvents()
    if dialog.audio.busy:
        run_queued(owner, "audio_task")
        app.processEvents()
    if page == "video" and tab == 1:
        dialog.maintenance.request("inspect")
        run_queued(owner, "maintenance_task")
        app.processEvents()
    before_fit = (dialog.frameGeometry(), dialog.isMaximized(), dialog.isMinimized())
    dialog.resize(620, min(700, area.height() - 40))
    after_resize = (dialog.frameGeometry(), dialog.isMaximized(), dialog.isMinimized())
    fit_window(dialog, area)
    after_fit = (dialog.frameGeometry(), dialog.isMaximized(), dialog.isMinimized())
    app.processEvents()
    before_grab = (dialog.frameGeometry(), dialog.isMaximized(), dialog.isMinimized())
    image = dialog.grab()
    directory = os.environ.get("MEETING_ASSISTANT_LAYOUT_CAPTURE_DIRECTORY")
    if directory:
        folder = Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        assert image.save(str(folder / f"settings-{scale}-{page}-{tab}.png"))
    assert area.contains(dialog.frameGeometry()), (
        page, tab, dialog.frameGeometry(), area, dialog.minimumSize(), dialog.minimumSizeHint(),
        dialog.maintenance.minimumSizeHint(), dialog.pages.minimumSizeHint(),
        before_fit, after_resize, after_fit, before_grab, dialog.isMaximized(), dialog.isMinimized(),
        dialog.screen().availableGeometry()
    )
    assert QLayout.closestAcceptableSize(dialog, dialog.size()) == dialog.size(), (
        page, tab, dialog.size(), dialog.layout().minimumHeightForWidth(dialog.width())
    )
    for scroll in dialog.findChildren(QScrollArea):
        if scroll.isVisible():
            assert scroll.horizontalScrollBar().maximum() == 0, (page, tab, scroll.objectName())
    for widget in dialog.findChildren(QPushButton) + dialog.findChildren(QCheckBox):
        if widget.isVisible():
            assert widget.width() >= widget.minimumSizeHint().width(), (
                page, tab, widget.text(), widget.width(), widget.minimumSizeHint().width()
            )
    for label in dialog.findChildren(QLabel):
        if label.isVisible() and label.wordWrap():
            assert label.height() >= label.heightForWidth(label.width()), (
                page, tab, label.text(), label.height(), label.heightForWidth(label.width())
            )
    for widget in (dialog.navigation, dialog.hint, dialog.status, dialog.save_button):
        if widget.isVisible():
            assert dialog.rect().contains(widget.geometry()), (page, tab, widget.geometry())
assert not any(r in {"SetCurrentProgramScene", "RemoveInput"} for r, _ in fake.calls)
print(json.dumps({"scale": dialog.devicePixelRatioF(), "views": len(views),
                  "rendered_width": image.width(), "width": dialog.width()}))
dialog.close()
owner.close()
app.processEvents()
"""


@pytest.mark.parametrize("scale", ["1", "1.25", "1.5", "2"])
def test_all_settings_pages_fit_fhd_work_area_at_desktop_scale(tmp_path, scale):
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "windows" if sys.platform == "win32" else "offscreen"
    env["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    env["QT_SCALE_FACTOR"] = scale
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT / "tests")])
    result = subprocess.run(
        [sys.executable, "-c", PROBE, str(tmp_path), scale],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "QWindowsWindow::setGeometry" not in result.stderr, result.stderr
    details = json.loads(result.stdout.strip().splitlines()[-1])
    assert details["scale"] == pytest.approx(float(scale))
    assert details["views"] == 10
    assert details["rendered_width"] == pytest.approx(details["width"] * float(scale), abs=1)
