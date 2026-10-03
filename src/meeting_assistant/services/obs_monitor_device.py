"""Read the locally saved OBS profile; WebSocket has no monitor-device getter.

The operator must still confirm the live device. This is a persisted snapshot,
not an assertion that OBS's runtime audio output has been measured.
"""

import configparser
import os
from pathlib import Path


def monitoring_device(client, directory=None):
    current = client.send("GetProfileList", raw=True)["currentProfileName"]
    root = (
        Path(directory)
        if directory is not None
        else Path(os.environ.get("APPDATA", "")) / "obs-studio" / "basic" / "profiles"
    )
    matches = []
    if not root.is_dir():
        raise ValueError(
            "Perfil local OBS não encontrado. Confira instalação/perfil e dispositivo de monitoramento."
        )
    for path in root.glob("*/basic.ini"):
        settings = configparser.ConfigParser(interpolation=None, strict=False)
        settings.read(path, encoding="utf-8-sig")
        if settings.get("General", "Name", fallback="") == current:
            matches.append(
                {
                    "monitorDeviceId": settings.get("Audio", "MonitoringDeviceId", fallback="default"),
                    "monitorDeviceName": settings.get("Audio", "MonitoringDeviceName", fallback=""),
                    "measurement": "saved_local_profile_operator_confirmation_required",
                }
            )
    if len(matches) != 1:
        raise ValueError("Perfil OBS local ausente ou ambíguo. Abra e salve os ajustes de áudio do OBS.")
    return matches[0]
