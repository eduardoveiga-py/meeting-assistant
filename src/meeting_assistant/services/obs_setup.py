"""Explicit OBS provisioning; never invoked by the window automation."""
from __future__ import annotations

import ipaddress
import os
import shutil
from pathlib import Path
from urllib.parse import quote

STANDARD_SCENES = ("Texto do Ano", "Palco", "Mídias")
CAMERA_SOURCE = "Meeting Assistant - Câmera IP"
OBS_FLAGS = ("--minimize-to-tray", "--startvirtualcam")


def camera_url(host: str, username: str, password: str, port: int = 554) -> str:
    try:
        address = ipaddress.ip_address(host.strip())
    except ValueError:
        raise ValueError("Informe um endereço IP válido para a câmera.") from None
    if not 1 <= port <= 65535:
        raise ValueError("Porta RTSP inválida.")
    if not username.strip() or not password:
        raise ValueError("Preencha usuário e senha da câmera.")
    host_part = f"[{address}]" if address.version == 6 else str(address)
    return (
        f"rtsp://{quote(username.strip(), safe='')}:{quote(password, safe='')}@"
        f"{host_part}:{port}/cam/realmonitor?channel=1&subtype=0"
    )


def prepare_obs(client, settings) -> None:
    renamed = []
    try:
        _prepare_obs(client, settings, renamed)
    except Exception:
        # Keep the saved old mappings valid if provisioning fails after a rename.
        for old, new in reversed(renamed):
            try:
                client.send("SetSceneName", {"sceneName": new, "newSceneName": old}, raw=True)
            except Exception:
                pass  # Controller reports incomplete provisioning; never claim success.
        raise


def _prepare_obs(client, settings, renamed) -> None:
    # Validate everything that can be checked before changing OBS.
    url = camera_url(settings.camera_ip, settings.camera_username,
                     settings.camera_password, settings.camera_rtsp_port)
    scenes = {s["sceneName"] for s in client.send("GetSceneList", raw=True)["scenes"]}
    old_names = (settings.scene_background, settings.scene_speaker, settings.scene_media)
    if len(set(old_names)) != 3:
        raise ValueError("Os três modos precisam ter cenas distintas antes da padronização.")
    migrations = []
    for old, new in zip(old_names, STANDARD_SCENES, strict=True):
        if old != new and old in scenes:
            if new in scenes or old in STANDARD_SCENES:
                raise ValueError("Há conflito entre cenas existentes e nomes padrão. Revise o mapeamento.")
            migrations.append((old, new))
    inputs = client.send("GetInputList", raw=True)["inputs"]
    camera = next((i for i in inputs if i["inputName"] == CAMERA_SOURCE), None)
    if camera and camera["inputKind"] != "ffmpeg_source":
        raise ValueError("O nome da fonte da câmera já é usado por outro tipo de fonte.")

    for old, new in migrations:
        client.send("SetSceneName", {"sceneName": old, "newSceneName": new}, raw=True)
        renamed.append((old, new))
        scenes.remove(old)
        scenes.add(new)
    for name in STANDARD_SCENES:
        if name not in scenes:
            client.send("CreateScene", {"sceneName": name}, raw=True)
    source_settings = {
        "is_local_file": False, "input": url, "input_format": "rtsp",
        "ffmpeg_options": "rtsp_transport=tcp", "restart_on_activate": False,
        "close_when_inactive": False,
    }
    if camera:
        client.send("SetInputSettings", {
            "inputName": CAMERA_SOURCE, "inputSettings": source_settings, "overlay": True,
        }, raw=True)
    else:
        client.send("CreateInput", {
            "sceneName": "Palco", "inputName": CAMERA_SOURCE, "inputKind": "ffmpeg_source",
            "inputSettings": source_settings, "sceneItemEnabled": True,
        }, raw=True)
    # Avoid accidental inclusion of the camera microphone in the existing audio mix.
    client.send("SetInputMute", {"inputName": CAMERA_SOURCE, "inputMuted": True}, raw=True)
    items = client.send("GetSceneItemList", {"sceneName": "Palco"}, raw=True)["sceneItems"]
    camera_item = next((i for i in items if i["sourceName"] == CAMERA_SOURCE), None)
    if camera_item:
        item_id = camera_item["sceneItemId"]
    else:
        item_id = client.send("CreateSceneItem", {
            "sceneName": "Palco", "sourceName": CAMERA_SOURCE, "sceneItemEnabled": True,
        }, raw=True)["sceneItemId"]
    video = client.send("GetVideoSettings", raw=True)
    client.send("SetSceneItemTransform", {
        "sceneName": "Palco", "sceneItemId": item_id,
        "sceneItemTransform": {
            "positionX": 0.0, "positionY": 0.0, "rotation": 0.0,
            "alignment": 5, "boundsType": "OBS_BOUNDS_SCALE_INNER",
            "boundsAlignment": 0, "boundsWidth": float(video["baseWidth"]),
            "boundsHeight": float(video["baseHeight"]),
        },
    }, raw=True)
    client.send("SetSceneItemEnabled", {
        "sceneName": "Palco", "sceneItemId": item_id, "sceneItemEnabled": True,
    }, raw=True)
    # Do not change Program, delete existing sources, or claim the stream was tested.


def find_obs_executable(configured: str = "") -> Path | None:
    if configured.strip():
        path = Path(configured.strip().strip('"'))
        return path if path.is_file() else None
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "obs-studio/bin/64bit/obs64.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/obs-studio/bin/64bit/obs64.exe",
    ]
    for name in ("obs64.exe", "obs32.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    return next((p for p in candidates if p.is_file()), None)


def configure_obs_logon(enabled: bool, configured: str = "") -> None:
    """Only manage our own per-user shortcut, with the required working directory."""
    if os.name != "nt":
        raise ValueError("Inicialização automática do OBS disponível somente no Windows.")
    from win32com.client import Dispatch

    shell = Dispatch("WScript.Shell")
    shortcut_path = Path(shell.SpecialFolders("Startup")) / "Meeting Assistant - OBS.lnk"
    if not enabled:
        shortcut_path.unlink(missing_ok=True)
        return
    executable = find_obs_executable(configured)
    if executable is None:
        raise ValueError("OBS não encontrado. Informe o executável antes de ativar a inicialização.")
    for other in shortcut_path.parent.glob("*.lnk"):
        if other == shortcut_path:
            continue
        existing = shell.CreateShortcut(str(other))
        if str(existing.TargetPath).casefold() == str(executable).casefold():
            raise ValueError(
                "Já existe um atalho do OBS na inicialização do Windows. Revise-o antes de criar outro."
            )
    shortcut = shell.CreateShortcut(str(shortcut_path))
    shortcut.TargetPath = str(executable)
    shortcut.Arguments = " ".join(OBS_FLAGS)
    shortcut.WorkingDirectory = str(executable.parent)
    shortcut.Description = "OBS na bandeja com câmera virtual - Meeting Assistant"
    shortcut.Save()
