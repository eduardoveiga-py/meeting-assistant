import json
import queue
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from meeting_assistant.services.diagnostics_export import export_latest_session
from meeting_assistant.services.settings import AppSettings, SettingsService
from meeting_assistant.services.telemetry_service import TelemetryService, sanitize_text


@pytest.mark.parametrize("field,value", [
    ("obs_port", "4455"), ("obs_port", True), ("obs_port", 0), ("obs_port", 65536),
    ("camera_rtsp_port", -1), ("telemetry_repo_url", None), ("obs_password", []),
    ("telemetry_enabled", "false"), ("telemetry_sync_enabled", 1), ("obs_host", " "),
    ("scene_media", ""), ("display_settings_version", -1),
])
def test_invalid_field_is_recovered_without_losing_valid_settings(tmp_path, field, value):
    path = tmp_path / "settings.json"
    raw = json.dumps({"display_settings_version": 1, "zoom_executable": "custom.exe", field: value})
    path.write_text(raw, encoding="utf-8")
    service = SettingsService(path)
    settings = service.load()
    assert getattr(settings, field) == getattr(AppSettings(), field)
    assert settings.zoom_executable == "custom.exe"
    assert path.read_text(encoding="utf-8") == raw
    backups = list(tmp_path.glob("*.bak"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == raw
    assert service.recovery_message
    service.load()
    assert len(list(tmp_path.glob("*.bak"))) == 1


@pytest.mark.parametrize("raw", [b"{broken", b"\xff", b"[]"])
def test_invalid_document_is_preserved(tmp_path, raw):
    path = tmp_path / "settings.json"
    path.write_bytes(raw)
    service = SettingsService(path)
    assert service.load() == AppSettings()
    assert next(tmp_path.glob("*.bak")).read_bytes() == raw


def test_duplicate_scenes_are_recovered(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"scene_media":"Palco", "display_settings_version":1}')
    settings = SettingsService(path).load()
    assert settings.scene_media == "Mídias"


def test_failed_backup_prevents_overwriting_invalid_original(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_bytes(b"{broken")
    original_write = Path.write_bytes
    def fail_backup(self, data):
        if self.suffix == ".bak":
            raise PermissionError("backup denied")
        return original_write(self, data)
    monkeypatch.setattr(Path, "write_bytes", fail_backup)
    service = SettingsService(path)
    settings = service.load()
    with pytest.raises(PermissionError):
        service.save(settings)
    assert path.read_bytes() == b"{broken"


def test_old_telemetry_setting_does_not_opt_into_upload(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"telemetry_enabled":true,"telemetry_repo_url":"https://example.invalid/repo"}')
    settings = SettingsService(path).load()
    assert settings.telemetry_enabled and not settings.telemetry_sync_enabled


def test_unwritable_telemetry_does_not_prevent_startup(tmp_path):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("x")
    original_hook = sys.excepthook
    service = TelemetryService(enabled=True, root=blocked)
    service.start()
    assert not service.enabled
    assert "indisponível" in service.status_message
    service.event("ignored")
    service.stop()
    assert sys.excepthook is original_hook


def test_local_diagnostics_never_invokes_git(tmp_path, monkeypatch):
    service = TelemetryService(enabled=True, root=tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("Local diagnostics must not invoke Git")
    monkeypatch.setattr(service, "_ensure_repo", forbidden)
    service.start()
    service.event("test")
    service.request_sync()
    service.stop()
    assert not service._thread.is_alive()
    summary = json.loads(service.summary_path.read_text())
    assert summary["status"] == "completed"
    assert '"event":"test"' in service.events_path.read_text()


def test_worker_disk_failure_is_contained(tmp_path, monkeypatch):
    service = TelemetryService(enabled=True, root=tmp_path)
    def fail():
        raise OSError("disk full")
    monkeypatch.setattr(service, "_worker", fail)
    service._worker_guarded()
    assert not service.enabled


def test_upload_requires_explicit_option_and_destination(tmp_path, monkeypatch):
    service = TelemetryService(enabled=True, sync_enabled=True, root=tmp_path)
    assert not service.sync_enabled
    service = TelemetryService(
        enabled=True, sync_enabled=True, repo_url="https://example.invalid", root=tmp_path
    )
    monkeypatch.setattr("meeting_assistant.services.telemetry_service.find_git", lambda: Path("git"))
    calls = []
    monkeypatch.setattr(service, "_ensure_repo", lambda git: calls.append("ensure"))
    monkeypatch.setattr(service, "_copy_session_to_repo", lambda: calls.append("copy"))
    monkeypatch.setattr(service, "_git_commit_and_push", lambda git: calls.append("push"))
    service._dirty = True
    service._sync_best_effort()
    assert calls == ["ensure", "copy", "push"]
    assert not service._dirty


def test_full_queue_does_not_block_operator(tmp_path):
    service = TelemetryService(enabled=True, root=tmp_path)
    service._queue = queue.Queue(maxsize=1)
    service.event("first")
    service.event("second")
    assert service._queue.qsize() == 1


@pytest.mark.parametrize("text,secret", [
    ("rtsp://operator:camera-secret@10.0.0.2/live", "camera-secret"),
    ("request failed token=abc123", "abc123"),
    ("Authorization: Bearer abc.def.123", "abc.def.123"),
])
def test_free_text_credentials_are_redacted(text, secret):
    assert secret not in sanitize_text(text)


def test_export_excludes_screenshots_settings_and_git(tmp_path):
    session = tmp_path / "sessions" / "MA-20260924-120000-ABCD"
    session.mkdir(parents=True)
    (session / "events.jsonl").write_text(
        '{"message":"rtsp://user:secret@camera/live"}\n{"incomplete":', encoding="utf-8"
    )
    (session / "settings.json").write_text('{"password":"never-export"}')
    (session / "screenshots").mkdir()
    (session / "screenshots" / "private.png").write_bytes(b"private")
    output = export_latest_session(tmp_path / "export.zip", tmp_path)
    with ZipFile(output) as archive:
        assert len(archive.namelist()) == 2
        content = archive.read(f"{session.name}/events.jsonl").decode()
        assert "secret" not in content
        assert "[REDACTED]" in content


def test_changed_upload_destination_never_retargets_existing_clone(tmp_path, monkeypatch):
    service = TelemetryService(enabled=True, sync_enabled=True, repo_url="https://new.invalid", root=tmp_path)
    (service.repo_path / ".git").mkdir(parents=True)
    calls = []
    def run(git, args, **kwargs):
        calls.append(args)
        return "https://previous.invalid"
    monkeypatch.setattr(service, "_run_git", run)
    with pytest.raises(RuntimeError, match="Destino alterado"):
        service._ensure_repo(Path("git"))
    assert calls == [["remote", "get-url", "origin"]]
