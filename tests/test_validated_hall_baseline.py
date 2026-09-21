"""Protect the operator-validated Hall engine from accidental changes."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_validated_hall_engine_is_unchanged():
    baseline = json.loads((ROOT / "docs/validated-hall-baseline.json").read_text(encoding="utf-8"))
    changed = []
    for path, expected in baseline["sha256"].items():
        source = ROOT / path
        if not source.is_file():
            changed.append(path)
            continue
        normalized = source.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n") + "\n"
        actual = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if actual != expected:
            changed.append(path)
    assert not changed, (
        "Operator-validated Hall engine changed: " + ", ".join(changed)
        + ". Follow AGENTS.md; do not refresh fingerprints merely to pass CI."
    )
