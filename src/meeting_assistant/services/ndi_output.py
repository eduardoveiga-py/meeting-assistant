"""DistroAV Program output only; independent connection, no scene/audio changes."""

from __future__ import annotations

import os
from pathlib import Path

OUTPUT_NAME = "NDI Main Output"
OUTPUT_KIND = "ndi_output"
SETUP_HELP = (
    "No OBS, abra Ferramentas → DistroAV NDI Settings (ou NDI Output Settings), "
    "habilite Main Output/Saída principal e nomeie a transmissão Meeting Assistant. "
    "Confirme e clique em Verificar novamente. Se o menu não existir, instale DistroAV."
)


class NdiUnavailable(ValueError):
    pass


def control_output(client, action="inspect"):
    if action not in {"inspect", "start", "stop"}:
        raise ValueError("Ação NDI inválida.")
    outputs = client.send("GetOutputList", raw=True).get("outputs", [])
    matches = [
        o for o in outputs if o.get("outputName") == OUTPUT_NAME and o.get("outputKind") == OUTPUT_KIND
    ]
    if len(matches) != 1:
        raise NdiUnavailable(SETUP_HELP)
    args = {"outputName": OUTPUT_NAME}
    before = client.send("GetOutputStatus", args, raw=True)
    active = before.get("outputActive")
    if not isinstance(active, bool):
        raise NdiUnavailable("O OBS não confirmou o estado da saída NDI.")
    if action == "start" and not active:
        client.send("StartOutput", args, raw=True)
    elif action == "stop" and active:
        client.send("StopOutput", args, raw=True)
    status = client.send("GetOutputStatus", args, raw=True)
    active = status.get("outputActive")
    if not isinstance(active, bool):
        raise NdiUnavailable("O OBS não confirmou o estado da saída NDI.")
    # A start/stop may still be transitioning. Report observed state, never infer success.
    result = {
        "output": OUTPUT_NAME,
        "active": active,
        "action": action,
        "confirmed": action == "inspect" or active == (action == "start"),
        "whatsapp_video_confirmed": False,
    }
    try:
        settings = client.send("GetOutputSettings", args, raw=True).get("outputSettings", {})
        result["source_name"] = str(settings.get("ndi_name", ""))[:200]
    except Exception:
        result["source_name"] = ""
    return result


def run_action(action):
    import obsws_python as obs

    from meeting_assistant.services.settings import SettingsService

    settings = SettingsService().load()
    client = obs.ReqClient(
        host=settings.obs_host, port=settings.obs_port, password=settings.obs_password, timeout=3
    )
    try:
        return control_output(client, action)
    finally:
        client.disconnect()


def find_webcam_input():
    if os.name != "nt":
        return None
    root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NDI"
    if not root.is_dir():
        return None
    # Search only the vendor directory, never arbitrary PATH executables.
    found = sorted(root.glob("*/Webcam Input/Application.Network.WebCam.x64.exe"), reverse=True)
    return next((p for p in found if p.is_file()), None)
