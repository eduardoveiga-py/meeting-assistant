import hashlib
import io
from unittest.mock import Mock

import pytest

from meeting_assistant.services.update_service import UpdateService

URL = "https://github.com/eduardoveiga-py/meeting-assistant/releases/download/v0.9.0/"


def release(version="0.9.0"):
    return {
        "tag_name": "v" + version,
        "body": "Release notes",
        "assets": [
            {
                "name": "MeetingAssistant-Setup-0.9.0.exe",
                "browser_download_url": URL + "MeetingAssistant-Setup-0.9.0.exe",
            },
            {"name": "SHA256SUMS.txt", "browser_download_url": URL + "SHA256SUMS.txt"},
        ],
    }


@pytest.mark.parametrize(
    "remote,available", [("0.8.0", False), ("0.8.1", False), ("0.9.0", True), ("0.10.0", True)]
)
def test_update_order_never_offers_downgrade(remote, available):
    import json

    service = UpdateService(
        installed_version="0.8.1", opener=lambda *a, **kw: io.BytesIO(json.dumps(release(remote)).encode())
    )
    notices = []
    service.update_available.connect(lambda *args: notices.append(args))
    service._check_for_updates_worker()
    assert bool(notices) is available


@pytest.mark.parametrize("flag", ["draft", "prerelease"])
def test_prerelease_and_draft_excluded(flag):
    service = UpdateService()
    assert service._offer(release() | {flag: True}) is None


def test_python_run_only_instructs_git_no_download_or_install():
    opener = Mock()
    service = UpdateService(frozen=False, opener=opener)
    messages = []
    service.status_changed.connect(lambda text, busy: messages.append((text, busy)))
    assert service.download_and_install_async("anything", "0.9.0") is False
    opener.assert_not_called()
    assert "git pull --ff-only" in messages[-1][0]
    assert messages[-1][1] is False


def make_service(monkeypatch, tmp_path, checksum_text=None, active=lambda: False):
    binary = b"review-test-installer"
    digest = hashlib.sha256(binary).hexdigest()
    name = "MeetingAssistant-Setup-0.9.0.exe"
    sums = checksum_text if checksum_text is not None else f"{digest}  {name}\n"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(
        "meeting_assistant.services.window_inventory.WindowBackend.processes", lambda self: []
    )

    def opened(request, timeout):
        assert timeout == 10
        return io.BytesIO(sums.encode() if request.full_url.endswith("SHA256SUMS.txt") else binary)

    service = UpdateService(frozen=True, opener=opened, activity_provider=active, installed_version="0.8.0")
    offer = service._offer(release())
    return service, offer, digest


def test_verified_installer_only_emits_handoff_never_executes_in_worker(monkeypatch, tmp_path):
    service, offer, digest = make_service(monkeypatch, tmp_path)
    popen = Mock()
    monkeypatch.setattr("subprocess.Popen", popen)
    ready = []
    service.install_ready.connect(lambda *args: ready.append(args))
    service._install_worker(offer["url"], offer["version"])
    assert len(ready) == 1 and ready[0][2] == digest
    popen.assert_not_called()
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize(
    "sums",
    [
        "",
        "0" * 64 + "  MeetingAssistant-Setup-0.9.0.exe\n",
        ("0" * 64 + "  MeetingAssistant-Setup-0.9.0.exe\n") * 2,
    ],
)
def test_missing_corrupt_or_duplicate_checksum_never_hands_off(monkeypatch, tmp_path, sums):
    service, offer, _ = make_service(monkeypatch, tmp_path, sums)
    ready, status = [], []
    service.install_ready.connect(lambda *args: ready.append(args))
    service.status_changed.connect(lambda *args: status.append(args))
    service._install_worker(offer["url"], offer["version"])
    assert not ready and status[-1][1] is False
    assert not list(tmp_path.rglob("*.part"))


def test_meeting_starting_during_download_defers_install(monkeypatch, tmp_path):
    service, offer, _ = make_service(monkeypatch, tmp_path, active=lambda: True)
    ready = []
    service.install_ready.connect(lambda *args: ready.append(args))
    service._install_worker(offer["url"], offer["version"])
    assert not ready
    assert not list(tmp_path.rglob("*.exe"))


def test_untrusted_asset_or_unlisted_url_rejected(monkeypatch, tmp_path):
    service, offer, _ = make_service(monkeypatch, tmp_path)
    ready = []
    service.install_ready.connect(lambda *args: ready.append(args))
    service._install_worker("https://attacker.example/setup.exe", "0.9.0")
    assert not ready
    external = release()
    external["assets"][0]["browser_download_url"] = "https://attacker.example/setup.exe"
    assert service._offer(external)["url"] == ""
