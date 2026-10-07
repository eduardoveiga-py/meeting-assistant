"""Verified plugin delivery, no UAC for unchanged files, literal installer paths."""

import base64
import hashlib
import io
import subprocess
import sys
import zipfile
from pathlib import PurePosixPath
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from meeting_assistant.services import obs_plugins as service
from meeting_assistant.services.settings import AppSettings


def archive(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        for name, data in entries.items():
            # ZipInfo normalizes backslashes on Windows. Restore the raw member
            # name so malformed ZIP paths are tested on every host platform.
            member = zipfile.ZipInfo(name)
            member.filename = name
            package.writestr(member, data)
    return buffer.getvalue()


def test_invalid_download_is_rejected_before_any_file_is_extracted(tmp_path):
    with pytest.raises(ValueError, match="SHA-256"):
        service.extract_monitor(b"bad-download", tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "bad_path", ["../escape.dll", "/escape.dll", "data/../escape.dll", "data\\escape.dll"]
)
def test_verified_archive_still_rejects_escaping_paths(tmp_path, monkeypatch, bad_path):
    data = archive({bad_path: b"bad"})
    monkeypatch.setattr(service, "MONITOR_SHA256", hashlib.sha256(data).hexdigest())
    with pytest.raises(ValueError, match="Caminho inválido"):
        service.extract_monitor(data, tmp_path)


def test_only_x64_plugin_and_its_locales_are_extracted(tmp_path, monkeypatch):
    data = archive(
        {
            "obs-plugins/64bit/audio-monitor.dll": b"x64",
            "data/obs-plugins/audio-monitor/locale/pt-BR.ini": b"locale",
            "obs-plugins/32bit/audio-monitor.dll": b"x86",
            "obs-plugins/64bit/audio-monitor.pdb": b"debug",
            "other-plugin.dll": b"unrelated",
        }
    )
    monkeypatch.setattr(service, "MONITOR_SHA256", hashlib.sha256(data).hexdigest())
    paths = service.extract_monitor(data, tmp_path)
    assert len(paths) == 2
    assert (tmp_path / "obs-plugins/64bit/audio-monitor.dll").read_bytes() == b"x64"
    assert not (tmp_path / "obs-plugins/32bit/audio-monitor.dll").exists()
    assert not (tmp_path / "other-plugin.dll").exists()


def test_repeated_plugin_installation_does_not_recopy_or_request_elevation(tmp_path, monkeypatch):
    contents = {
        "obs-plugins/64bit/audio-monitor.dll": b"current",
        "data/obs-plugins/audio-monitor/locale/pt-BR.ini": b"current-locale",
    }
    data = archive(contents)
    monkeypatch.setattr(service, "MONITOR_SHA256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(service, "obs_directory", lambda _: tmp_path)
    monkeypatch.setattr(service, "urlopen", lambda *args, **kwargs: io.BytesIO(data))
    run = Mock()
    monkeypatch.setattr(service, "subprocess", SimpleNamespace(run=run, CREATE_NO_WINDOW=0))
    for name, value in contents.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    assert "já instalado" in service.install_audio_monitor(AppSettings())
    run.assert_not_called()
    assert not list(tmp_path.rglob("*.backup-*"))


def test_obs_must_be_closed_before_download_or_install(monkeypatch):
    monkeypatch.setattr(service, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(service, "process_running", lambda _: True)
    download = Mock()
    monkeypatch.setattr(service, "urlopen", download)
    with pytest.raises(ValueError, match="Feche OBS"):
        service.install_audio_monitor(AppSettings())
    download.assert_not_called()


@pytest.mark.parametrize("installer", ["install_jwl_plugin", "install_camera_bridge"])
def test_python_maintenance_uses_ready_dll_launchers_without_compilation_or_forced_refresh(
    tmp_path, monkeypatch, installer
):
    monkeypatch.setattr(service, "obs_directory", lambda _: tmp_path / "OBS")
    monkeypatch.setattr(service.sys, "frozen", False, raising=False)
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(service, "subprocess", SimpleNamespace(run=run, CREATE_NO_WINDOW=0))
    result = getattr(service, installer)(AppSettings())
    args = run.call_args.args[0]
    assert any("ensure-" in arg for arg in args)
    assert not any("build" in arg or "compile" in arg or arg == "-Refresh" for arg in args)
    assert args[-1] == str(tmp_path / "OBS")
    assert "instalado/verificado" in result


def test_generated_installer_escapes_paths_and_is_valid_windows_powershell(tmp_path):
    source = tmp_path / "origem com espaço e O'Brien"
    relative = PurePosixPath("obs-plugins/64bit/audio-monitor.dll")
    path = source.joinpath(*relative.parts)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"payload")
    script = service.monitor_install_script(source, tmp_path / "OBS com espaço", [relative])
    assert "O''Brien" in script and "Get-Process obs64,obs32" in script
    assert "Get-FileHash" in script and ".backup-" in script and "if ($current -ne" in script
    if sys.platform == "win32":
        file = tmp_path / "parse-only.ps1"
        file.write_text(script, encoding="utf-8-sig")
        command = (
            "$tokens=$null; $errors=$null; "
            "[System.Management.Automation.Language.Parser]::ParseFile("
            + service._literal(file)
            + ",[ref]$tokens,[ref]$errors) | Out-Null; if ($errors.Count) { $errors; exit 1 }"
        )
        encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
        parsed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert parsed.returncode == 0, parsed.stdout + parsed.stderr


def test_native_installation_failure_does_not_claim_success(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "obs_directory", lambda _: tmp_path)
    monkeypatch.setattr(service.sys, "frozen", False, raising=False)
    run = Mock(return_value=SimpleNamespace(returncode=1))
    monkeypatch.setattr(service, "subprocess", SimpleNamespace(run=run, CREATE_NO_WINDOW=0))
    with pytest.raises(ValueError, match="não confirmada"):
        service.install_jwl_plugin(AppSettings())
