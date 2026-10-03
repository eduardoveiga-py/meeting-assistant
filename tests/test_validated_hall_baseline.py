"""Historical signatures remain immutable; explicit policy candidate is separate."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_CHANGE = {"src/meeting_assistant/services/zoom_hall_service.py", "tests/test_zoom_hall_discovery.py"}


def test_validated_hall_engine_and_authorized_policy_candidate():
    baseline = json.loads((ROOT / "docs/validated-hall-baseline.json").read_text(encoding="utf-8"))
    candidate = json.loads((ROOT / "docs/hall-policy-candidate.json").read_text(encoding="utf-8"))
    assert candidate["validation"] == "physical_pending"
    assert candidate["authorization"] == "guardian_only_when_automation_enabled"
    assert set(candidate["sha256"]) == POLICY_CHANGE
    assert baseline["validated_commit"] == "02094d80aa45ab0088d271691122839da759b1ee"
    changed = []
    for path, historical in baseline["sha256"].items():
        source = ROOT / path
        normalized = source.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n") + "\n"
        actual = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        expected = candidate["sha256"].get(path, historical)
        if actual != expected:
            changed.append(path)
    assert not changed, (
        "Protected Hall engine changed: "
        + ", ".join(changed)
        + ". Do not refresh historical hashes merely to pass CI."
    )
