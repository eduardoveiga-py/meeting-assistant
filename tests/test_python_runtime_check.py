"""Startup must reject unsupported runtimes before installing dependencies."""

import runpy
from pathlib import Path

import pytest

runtime_info = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/python-runtime-check.py")
)["runtime_info"]


@pytest.mark.parametrize(
    ("version", "bits", "expected"),
    [
        ((3, 12, 10, "final", 0), 64, True),
        ((3, 14, 7, "final", 0), 64, False),
        ((3, 11, 9, "final", 0), 64, False),
        ((3, 12, 10, "final", 0), 32, False),
        ((3, 12, 0, "candidate", 1), 64, False),
    ],
)
def test_startup_runtime_compatibility(version, bits, expected):
    assert runtime_info(version, bits)["compatible"] is expected
