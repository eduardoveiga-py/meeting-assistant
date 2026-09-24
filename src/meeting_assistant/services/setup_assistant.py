"""Explicit, resumable provisioning for packaged installs. No startup mutations."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from uuid import uuid4

import psutil

from meeting_assistant.services.meeting_launcher import zoom_join_uri
from meeting_assistant.services.obs_setup import find_obs_executable
from meeting_assistant.services.preflight import Check, inspect_obs

PACKAGES = {"OBS": "OBSProject.OBSStudio", "Zoom": "Zoom.Zoom"}
SCHEMA = 1


def review_key():
    try:
        release = version("meeting-assistant")
    except PackageNotFoundError:
        release = "development"
    return f"{release}/setup-{SCHEMA}"


def needs_setup(settings, packaged=None):
    packaged = getattr(sys, "frozen", False) if packaged is None else packaged
    return bool(packaged and settings.setup_review_version != review_key())


def validate_settings(settings):
    if not 1 <= settings.obs_port <= 65535:
        raise ValueError("Porta OBS inválida.")
    if settings.zoom_join_url:
        zoom_join_uri(settings.zoom_join_url)
    if not all((settings.scene_background, settings.scene_speaker, settings.scene_media)):
        raise ValueError("Preencha os nomes das três cenas.")
    if len({settings.scene_background, settings.scene_speaker, settings.scene_media}) != 3:
        raise ValueError("As três cenas precisam ter nomes diferentes.")


def process_running(name):
    for process in psutil.process_iter(["name"]):
        try:
            if (process.info["name"] or "").casefold() == name.casefold():
                return True
        except psutil.Error:
            continue
    return False


def configure_websocket(settings, directory=None):
    if os.name != "nt" and directory is None:
        raise ValueError("Configuração local disponível somente no Windows.")
    if settings.obs_host.casefold() not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Esta preparação exige OBS neste computador.")
    if process_running("obs64.exe") or process_running("obs32.exe"):
        raise ValueError("Feche o OBS antes de configurar o WebSocket. Depois use Abrir OBS.")
    if not settings.obs_password or not 1 <= settings.obs_port <= 65535:
        raise ValueError("Preencha a senha e uma porta válida do WebSocket e salve os ajustes.")
    # OBS standard installation only; portable profiles must be configured in OBS.
    if directory is None:
        executable = find_obs_executable(settings.obs_executable)
        if executable is None:
            raise ValueError("Instale ou localize o OBS primeiro.")
        root = executable.parent.parent.parent
        if any((root / marker).exists() for marker in ("portable_mode.txt", "portable_mode")):
            raise ValueError("OBS portátil: configure o WebSocket pelo próprio OBS.")
        directory = Path(os.environ["APPDATA"]) / "obs-studio/plugin_config/obs-websocket"
    path = Path(directory) / "config.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("Configuração OBS inválida; arquivo preservado.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(f"config.backup-{uuid4().hex}.json"))
    data.update(
        first_load=False,
        server_enabled=True,
        auth_required=True,
        server_port=settings.obs_port,
        server_password=settings.obs_password,
    )
    temporary = path.with_name(f"config.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return "WebSocket configurado com autenticação. Abra o OBS e execute Verificar novamente."


def installation_command(app):
    if app not in PACKAGES:
        raise ValueError("Aplicativo fora da lista de instalação.")
    winget = shutil.which("winget")
    if not winget:
        raise ValueError(
            "WinGet ausente. Instale o Instalador de Aplicativo pela Microsoft Store e tente novamente."
        )
    return [
        winget,
        "install",
        "--id",
        PACKAGES[app],
        "--exact",
        "--source",
        "winget",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--disable-interactivity",
    ]


def install_application(app):
    if os.name != "nt":
        raise ValueError("Instalação disponível somente no Windows.")
    result = subprocess.run(
        installation_command(app), capture_output=True, timeout=900, creationflags=subprocess.CREATE_NO_WINDOW
    )
    if result.returncode:
        raise ValueError(
            f"{app}: instalação não confirmada (código {result.returncode}). "
            "Verifique internet, permissões ou reinício pendente e tente novamente."
        )
    return f"{app}: instalador terminou. Use Verificar novamente para confirmar a detecção."


def inspect_environment(settings):
    """Worker-only: bounded disk/process/OBS probes; never logs passwords or URLs."""
    rows = [Check("INSTALAÇÃO", "OBS detectado", find_obs_executable(settings.obs_executable) is not None)]
    candidates = [
        Path(os.environ[env]) / tail
        for env, tail in (
            ("APPDATA", "Zoom/bin/Zoom.exe"),
            ("LOCALAPPDATA", "Zoom/bin/Zoom.exe"),
            ("LOCALAPPDATA", "Programs/Zoom/bin/Zoom.exe"),
            ("ProgramFiles", "Zoom/bin/Zoom.exe"),
        )
        if os.environ.get(env)
    ]
    if settings.zoom_executable:
        candidates = [Path(settings.zoom_executable)]
    rows.append(Check("INSTALAÇÃO", "Zoom detectado", any(p.is_file() for p in candidates)))
    jwl = None
    if os.name == "nt":
        try:
            result = subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                    "Get-AppxPackage -Name WatchtowerBibleandTractSo.45909CDBADF3C | "
                    "Select-Object -ExpandProperty Name",
                ],
                capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                jwl = b"Watchtower" in result.stdout
        except (OSError, subprocess.TimeoutExpired):
            pass
    rows.append(Check("INSTALAÇÃO", "JW Library detectado", jwl))
    rows.append(Check(
        "CONFIGURAÇÃO", "Link Zoom preenchido (entrada não testada)", bool(settings.zoom_join_url)
    ))
    import obsws_python as obs

    rows.extend(inspect_obs(settings, obs.ReqClient))
    return rows


def create_standard_scenes(settings):
    import obsws_python as obs

    from meeting_assistant.services.obs_setup import STANDARD_SCENES

    client = obs.ReqClient(
        host=settings.obs_host, port=settings.obs_port, password=settings.obs_password, timeout=3
    )
    try:
        names = {r["sceneName"] for r in client.send("GetSceneList", raw=True)["scenes"]}
        for name in STANDARD_SCENES:
            if name not in names:
                client.send("CreateScene", {"sceneName": name}, raw=True)
        verified = {r["sceneName"] for r in client.send("GetSceneList", raw=True)["scenes"]}
        if not set(STANDARD_SCENES) <= verified:
            raise ValueError("OBS não confirmou as três cenas.")
        return "Cenas padrão confirmadas. Fontes e câmera ainda precisam ser preparadas e testadas."
    finally:
        client.disconnect()

