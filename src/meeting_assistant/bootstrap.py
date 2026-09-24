"""Packaged entry point with a smoke test that never starts operational services."""
from __future__ import annotations

import json
import sys
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path


def smoke_test(report: Path) -> int:
    try:
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication

        # Verify imports packaged through the normal dependency graph, without
        # starting telemetry, window guards, OBS connections or installation.
        from meeting_assistant.main import _load_app_icon
        from meeting_assistant.services.setup_assistant import review_key

        app = QApplication.instance() or QApplication([])
        icon = _load_app_icon()
        if icon.isNull() or icon.pixmap(32, 32).isNull():
            raise RuntimeError("Missing Qt SVG support")
        if QImage(2, 2, QImage.Format.Format_RGB32).isNull():
            raise RuntimeError("Qt image support unavailable")
        if not files("meeting_assistant.resources").joinpath("app_icon.svg").is_file():
            raise RuntimeError("Missing application resource")
        app.processEvents()
        result = {"ok": True, "version": version("meeting-assistant"), "review_key": review_key()}
        code = 0
    except Exception as exc:
        result = {"ok": False, "error_type": type(exc).__name__}
        code = 1
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return code


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        return smoke_test(Path(sys.argv[2]))
    from meeting_assistant.main import main as run_application

    return run_application()


if __name__ == "__main__":
    raise SystemExit(main())
