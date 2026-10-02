"""Install the bundled native package after OBS is installed or relocated."""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

from meeting_assistant.services.obs_setup import find_obs_executable


def bundled_package():
    if not getattr(sys, "frozen", False):
        raise ValueError("No modo Python, use scripts/run.ps1 -Refresh para os componentes nativos.")
    package = Path(sys.executable).parent / "native"
    if not (package / "install-video-native.ps1").is_file():
        raise ValueError("Pacote nativo ausente. Reinstale usando o instalador completo.")
    return package


def installation_script(package, obs_directory):
    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"

    installer = literal(Path(package) / "install-video-native.ps1")
    directory = literal(obs_directory)
    # Start-Process joins ArgumentList strings; explicitly quote the two paths.
    arguments = (
        f"'-NoProfile -ExecutionPolicy Bypass -File \"' + {installer} + "
        f"'\" -Component All -ObsDirectory \"' + {directory} + '\"'"
    )
    return (
        "$ErrorActionPreference = 'Stop'; "
        "try { $p = Start-Process -FilePath powershell.exe -Verb RunAs "
        f"-ArgumentList ({arguments}) -Wait -PassThru; exit $p.ExitCode "
        "} catch { exit 1 }"
    )


def install_bundled(settings):
    if os.name != "nt":
        raise ValueError("Instalação nativa disponível somente no Windows 11.")
    package = bundled_package()
    executable = find_obs_executable(settings.obs_executable)
    if executable is None:
        raise ValueError("Instale ou localize o OBS primeiro e salve os ajustes.")
    script = installation_script(package, executable.parent.parent.parent)
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        timeout=300,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise ValueError(
            "Instalação nativa não concluída. Feche OBS, WhatsApp e a câmera do app, "
            "aceite a permissão do Windows e tente novamente."
        )
    return "Câmera e ponte instaladas. Abra o OBS e reinicie o app para verificar o vídeo."
