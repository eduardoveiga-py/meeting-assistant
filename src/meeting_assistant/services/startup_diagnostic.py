"""Offline packaged-runtime check. Does not open OBS, a camera, settings or telemetry."""

import json
import sys
from pathlib import Path

from PySide6.QtMultimediaWidgets import QVideoWidget

from meeting_assistant import __version__
from meeting_assistant.services.program_video import video_frame
from meeting_assistant.services.virtual_camera import HEIGHT, WIDTH


def write_startup_diagnostic(path, icon):
    pixels = bytes([16]) * (WIDTH * HEIGHT) + bytes([128]) * (WIDTH * HEIGHT // 2)
    frame = video_frame(pixels)
    widget = QVideoWidget()
    widget.videoSink().setVideoFrame(frame)
    report = {
        "app_version": __version__,
        "frozen": bool(getattr(sys, "frozen", False)),
        "icon_loaded": not icon.pixmap(32, 32).isNull(),
        "nv12_frame_accepted": widget.videoSink().videoFrame().isValid(),
        "nv12_black_decoded": frame.toImage().pixelColor(WIDTH // 2, HEIGHT // 2).red() < 3,
        "external_apps_started": False,
        "camera_registered": False,
    }
    report["ok"] = all(report[key] for key in ("icon_loaded", "nv12_frame_accepted", "nv12_black_decoded"))
    Path(path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
