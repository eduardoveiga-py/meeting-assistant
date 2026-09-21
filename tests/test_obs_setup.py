from urllib.parse import urlsplit

import pytest

from meeting_assistant.services.obs_setup import CAMERA_SOURCE, camera_url, prepare_obs
from meeting_assistant.services.settings import AppSettings


class FakeObs:
    def __init__(self):
        self.scenes = {"Texto do Ano", "Palco", "Mídias"}
        self.inputs = []
        self.items = []
        self.calls = []
        self.fail_create = False

    def send(self, request, data=None, raw=True):
        self.calls.append((request, data))
        if request == "GetSceneList":
            return {"scenes": [{"sceneName": s} for s in self.scenes]}
        if request == "GetInputList":
            return {"inputs": self.inputs}
        if request == "SetSceneName":
            self.scenes.remove(data["sceneName"])
            self.scenes.add(data["newSceneName"])
        if request == "CreateScene":
            self.scenes.add(data["sceneName"])
        if request == "CreateInput":
            if self.fail_create:
                raise RuntimeError("simulated OBS failure")
            self.inputs.append({"inputName": data["inputName"], "inputKind": data["inputKind"]})
            self.items.append({"sourceName": data["inputName"], "sceneItemId": 9})
        if request == "GetSceneItemList":
            return {"sceneItems": self.items}
        if request == "GetVideoSettings":
            return {"baseWidth": 1920, "baseHeight": 1080}
        return {}


def settings():
    return AppSettings(camera_username="test", camera_password="dummy-only")


def test_url_encodes_credentials_without_changing_host():
    url = camera_url("10.0.0.40", "user@name", "a:/?#%")
    assert urlsplit(url).hostname == "10.0.0.40"
    assert "user%40name:a%3A%2F%3F%23%25@" in url
    assert url.endswith(":554/cam/realmonitor?channel=1&subtype=0")


@pytest.mark.parametrize("host,user,password", [
    ("10.0.0.40/path", "user", "secret"), ("10.0.0.40", "", ""),
])
def test_invalid_configuration_never_calls_obs(host, user, password):
    client = FakeObs()
    config = AppSettings(camera_ip=host, camera_username=user, camera_password=password)
    with pytest.raises(ValueError):
        prepare_obs(client, config)
    assert client.calls == []


def test_repeated_setup_keeps_single_camera_and_does_not_switch_program():
    client = FakeObs()
    prepare_obs(client, settings())
    prepare_obs(client, settings())
    assert len(client.inputs) == len(client.items) == 1
    assert sum(name == "CreateInput" for name, _ in client.calls) == 1
    assert not any(name in {"SetCurrentProgramScene", "RemoveInput", "RemoveScene"}
                   for name, _ in client.calls)
    assert ("SetInputMute", {"inputName": CAMERA_SOURCE, "inputMuted": True}) in client.calls


def test_scene_name_conflict_is_detected_before_changes():
    client = FakeObs()
    client.scenes.add("Camera antiga")
    config = settings()
    config.scene_speaker = "Camera antiga"
    with pytest.raises(ValueError, match="conflito"):
        prepare_obs(client, config)
    assert all(name.startswith("Get") for name, _ in client.calls)


def test_failure_restores_original_scene_mapping():
    client = FakeObs()
    client.scenes.remove("Palco")
    client.scenes.add("Camera antiga")
    client.fail_create = True
    config = settings()
    config.scene_speaker = "Camera antiga"
    with pytest.raises(RuntimeError):
        prepare_obs(client, config)
    assert "Camera antiga" in client.scenes
    assert "Palco" not in client.scenes


def test_wrong_source_kind_does_not_mutate_obs():
    client = FakeObs()
    client.inputs.append({"inputName": CAMERA_SOURCE, "inputKind": "image_source"})
    with pytest.raises(ValueError, match="outro tipo"):
        prepare_obs(client, settings())
    assert all(name.startswith("Get") for name, _ in client.calls)


def test_logon_shortcut_sets_working_directory_and_only_removes_own_file(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from meeting_assistant.services import obs_setup

    shortcut = SimpleNamespace(Save=lambda: None)
    shell = SimpleNamespace(
        SpecialFolders=lambda name: str(tmp_path),
        CreateShortcut=lambda path: shortcut,
    )
    monkeypatch.setitem(sys.modules, "win32com.client", SimpleNamespace(Dispatch=lambda name: shell))
    monkeypatch.setattr(obs_setup, "os", SimpleNamespace(name="nt"))
    executable = tmp_path / "OBS" / "obs64.exe"
    monkeypatch.setattr(obs_setup, "find_obs_executable", lambda configured: executable)
    obs_setup.configure_obs_logon(True)
    assert shortcut.TargetPath == str(executable)
    assert shortcut.WorkingDirectory == str(executable.parent)
    assert shortcut.Arguments == "--minimize-to-tray --startvirtualcam"
    own = tmp_path / "Meeting Assistant - OBS.lnk"
    other = tmp_path / "Other OBS.lnk"
    own.touch()
    other.touch()
    obs_setup.configure_obs_logon(False)
    assert not own.exists()
    assert other.exists()
