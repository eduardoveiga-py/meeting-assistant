"""Install ready, verified components on explicit maintenance requests.

Invoked by the setup worker, never the GUI. No compiler, no process termination.
"""

import base64
import hashlib
import io
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

from meeting_assistant.services.obs_setup import find_obs_executable
from meeting_assistant.services.setup_assistant import process_running

MONITOR_URL = (
    "https://github.com/exeldro/obs-audio-monitor/releases/download/0.10.1/audio-monitor-0.10.1-windows.zip"
)
MONITOR_SHA256 = "99a0419594e5affabdfd87accf716f0aaf33dd932f850c06f54145311be7b588"
MAX_PACKAGE_BYTES = 20 * 1024 * 1024


def obs_directory(settings):
    if os.name != "nt":
        raise ValueError("Instalação de plugins disponível no Windows 11.")
    if process_running("obs64.exe") or process_running("obs32.exe"):
        raise ValueError("Feche OBS antes de instalar plugins. Nenhum processo foi encerrado.")
    executable = find_obs_executable(settings.obs_executable)
    if executable is None:
        raise ValueError("Instale ou localize o OBS e salve o caminho em Reunião e janelas.")
    return executable.parent.parent.parent


def _source_script(name, settings):
    directory = obs_directory(settings)
    script = Path(__file__).resolve().parents[3] / "scripts" / name
    if not script.is_file():
        raise ValueError(
            "Componente de instalação ausente. Atualize o projeto pelo Git ou use o instalador completo."
        )
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-ObsDirectory",
        str(directory),
    ]
    result = subprocess.run(args, capture_output=True, timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise ValueError(
            "Instalação não confirmada. Feche OBS; para câmera/ponte, feche também "
            "WhatsApp, Zoom e pare a câmera do app. Aceite a permissão do Windows e tente novamente."
        )
    return "Componente instalado/verificado. Abra o OBS e verifique em OBS e vídeo → Fontes."


def install_jwl_plugin(settings):
    if getattr(sys, "frozen", False):
        raise ValueError("Use o instalador completo para reparar o plugin JWL nesta distribuição.")
    return _source_script("ensure-jwl-capture.ps1", settings)


def install_camera_bridge(settings):
    if getattr(sys, "frozen", False):
        from meeting_assistant.services.packaged_native import install_bundled

        obs_directory(settings)
        return install_bundled(settings)
    return _source_script("ensure-video-native.ps1", settings)


def extract_monitor(data, target):
    if hashlib.sha256(data).hexdigest() != MONITOR_SHA256:
        raise ValueError("O plugin baixado não corresponde ao SHA-256 oficial fixado. Nada foi instalado.")
    files = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(member.file_size for member in archive.infolist()) > MAX_PACKAGE_BYTES:
            raise ValueError("Pacote de plugin maior que o esperado.")
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
                raise ValueError("Caminho inválido no pacote do plugin.")
            allowed = str(path) == "obs-plugins/64bit/audio-monitor.dll" or str(path).startswith(
                "data/obs-plugins/audio-monitor/"
            )
            if not allowed or member.is_dir():
                continue
            destination = Path(target).joinpath(*path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(member))
            files.append(path)
    if PurePosixPath("obs-plugins/64bit/audio-monitor.dll") not in files:
        raise ValueError("A DLL x64 do Audio Monitor não está no pacote esperado.")
    return files


def _literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def monitor_install_script(source, target, files):
    lines = [
        "$ErrorActionPreference = 'Stop'",
        "if (Get-Process obs64,obs32 -ErrorAction SilentlyContinue) { throw 'Feche OBS antes de instalar.' }",
    ]
    for relative in files:
        src, dest = Path(source).joinpath(*relative.parts), Path(target).joinpath(*relative.parts)
        digest = hashlib.sha256(src.read_bytes()).hexdigest()
        lines += [
            f"$src = {_literal(src)}; $dest = {_literal(dest)}",
            f"if ((Get-FileHash -LiteralPath $src -Algorithm SHA256).Hash -ne '{digest}') "
            "{ throw 'Payload alterado.' }",
            "$current = if (Test-Path -LiteralPath $dest) { "
            "(Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash } else { '' }",
            f"if ($current -ne '{digest}') {{",
            "New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null",
            "if (Test-Path -LiteralPath $dest) { Copy-Item -LiteralPath $dest "
            "-Destination ($dest + '.backup-' + [guid]::NewGuid().ToString('N')) }",
            "Copy-Item -LiteralPath $src -Destination $dest -Force",
            f"if ((Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash -ne '{digest}') "
            "{ throw 'Instalacao nao confirmada.' }",
            "}",
        ]
    return "\n".join(lines)


def install_audio_monitor(settings):
    directory = obs_directory(settings)
    with tempfile.TemporaryDirectory(prefix="ma-audio-monitor-") as temporary:
        stage = Path(temporary)
        with urlopen(MONITOR_URL, timeout=30) as response:
            data = response.read(MAX_PACKAGE_BYTES + 1)
        if len(data) > MAX_PACKAGE_BYTES:
            raise ValueError("Download de plugin maior que o esperado. Nada foi instalado.")
        files = extract_monitor(data, stage / "package")
        if all(
            directory.joinpath(*relative.parts).is_file()
            and hashlib.sha256(directory.joinpath(*relative.parts).read_bytes()).digest()
            == hashlib.sha256((stage / "package").joinpath(*relative.parts).read_bytes()).digest()
            for relative in files
        ):
            return "Audio Monitor já instalado e verificado. Reabra OBS para conferir o plugin carregado."
        script = stage / "install.ps1"
        script.write_text(monitor_install_script(stage / "package", directory, files), encoding="utf-8-sig")
        arguments = f'-NoProfile -ExecutionPolicy Bypass -File "{script}"'
        elevate = (
            "$ErrorActionPreference='Stop'; try { $p = Start-Process powershell.exe "
            "-Verb RunAs -Wait -PassThru -ArgumentList "
            + _literal(arguments)
            + "; exit $p.ExitCode } catch { exit 1 }"
        )
        encoded = base64.b64encode(elevate.encode("utf-16le")).decode("ascii")
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            raise ValueError(
                "Instalação do Audio Monitor não confirmada. Confira OBS fechado "
                "e permissão do Windows; tente novamente."
            )
        for relative in files:
            installed = directory.joinpath(*relative.parts)
            original = (stage / "package").joinpath(*relative.parts)
            if (
                not installed.is_file()
                or hashlib.sha256(installed.read_bytes()).digest()
                != hashlib.sha256(original.read_bytes()).digest()
            ):
                raise ValueError("Arquivo instalado não confirmado. Verifique a pasta do OBS.")
    return (
        "Audio Monitor 0.10.1 instalado e verificado. Reabra OBS e confira o plugin em OBS e vídeo → Fontes."
    )
