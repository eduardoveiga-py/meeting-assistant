from pathlib import Path

import pytest

from meeting_assistant.services import packaged_native as service


def test_source_install_directs_to_python_launcher(monkeypatch):
    monkeypatch.setattr(service.sys, "frozen", False, raising=False)
    with pytest.raises(ValueError, match="run.ps1"):
        service.bundled_package()


def test_bundle_is_beside_installed_executable(monkeypatch, tmp_path):
    package = tmp_path / "native"
    package.mkdir()
    (package / "install-video-native.ps1").write_text("param()")
    monkeypatch.setattr(service.sys, "frozen", True, raising=False)
    monkeypatch.setattr(service.sys, "executable", str(tmp_path / "MeetingAssistant.exe"))
    assert service.bundled_package() == package


def test_elevation_preserves_spaces_and_literal_apostrophe():
    script = service.installation_script(Path("C:/Users/O'Brien/App/native"), "D:/OBS Studio")
    assert "O''Brien" in script
    assert "D:/OBS Studio" in script
    assert "-Verb RunAs" in script
    assert "-Wait -PassThru" in script
