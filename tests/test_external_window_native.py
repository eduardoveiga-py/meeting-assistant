"""API availability and asynchronous GUI-thread behavior must run on Windows CI."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Requires real Windows HWNDs and message queues")
@pytest.mark.parametrize("initial_state", ["normal", "minimized", "maximized"])
def test_real_native_player_restore_present_and_return(initial_state):
    root = Path(__file__).resolve().parents[1]
    try:
        process = subprocess.run(
            [sys.executable, str(root / "tests/windows_external_window_probe.py"), initial_state],
            cwd=root, env={**os.environ, "PYTHONPATH": str(root / "src")},
            capture_output=True, text=True, timeout=20,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"Native HWND probe timed out. stdout={exc.stdout!r}; stderr={exc.stderr!r}")
    assert process.returncode == 0, process.stderr + process.stdout
    result = json.loads(process.stdout)
    assert result["ok"] and result["presented"]["ready"]
    assert result["initial_state"] == initial_state
