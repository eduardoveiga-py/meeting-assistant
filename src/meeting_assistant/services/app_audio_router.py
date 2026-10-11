"""Per-app call audio routing and virtual camera management.

Handles independent routing for Zoom and WhatsApp (R3) and virtual camera controls
via multi-tier strategy (CLI automation, Windows settings, session queries).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from meeting_assistant.services.virtual_camera import camera_support

logger = logging.getLogger(__name__)

# Standard target application process names
ZOOM_APP = "Zoom.exe"
WHATSAPP_APP = "WhatsApp.exe"

# Standard standardized project device names
DEFAULT_ZOOM_CAPTURE_NAME = "V-MIC Zoom (Captação)"
DEFAULT_ZOOM_RENDER_NAME = "Mesa de Som (Retorno P2)"
DEFAULT_WHATSAPP_CAPTURE_NAME = "V-MIC Wapp (Captação)"
DEFAULT_WHATSAPP_RENDER_NAME = "Mesa de Som (Retorno P2)"

POLICY_CONFIG_REG_PATH = (
    r"Software\Microsoft\Internet Explorer\LowRegistry\Audio\PolicyConfig\PropertyStore"
)


@dataclass
class AppAudioRoute:
    """Represents per-app audio routing configuration and status."""

    app_name: str
    target_render_id: str | None = None
    target_capture_id: str | None = None
    current_render_id: str | None = None
    current_capture_id: str | None = None
    status: str = "unconfigured"  # "configured", "active", "not_running", "unconfigured", "error"
    details: str = ""
    active_sessions: list[dict[str, Any]] = field(default_factory=list)


def find_cli_tool(tool_name: str = "svcl.exe") -> Path | None:
    """Locate automated audio configuration CLI utility if available.

    Checks PATH, project tools directory, and standard install locations.
    """
    found = shutil.which(tool_name)
    if found:
        return Path(found)

    # Check alternative name SoundVolumeView.exe if checking svcl.exe
    if tool_name.lower() in ("svcl.exe", "svcl"):
        alt_found = shutil.which("SoundVolumeView.exe") or shutil.which("SoundVolumeView")
        if alt_found:
            return Path(alt_found)

    # Project root tools/
    project_root = Path(__file__).resolve().parents[3]
    candidate = project_root / "tools" / tool_name
    if candidate.is_file():
        return candidate

    # Standard ProgramFiles / LocalAppData directories
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "SoundVolumeView" / tool_name,
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "SoundVolumeView" / tool_name,
        Path(r"C:\Tools") / tool_name,
    ]
    for p in candidates:
        if p.is_file():
            return p

    return None


def launch_apps_volume_settings() -> tuple[bool, str]:
    """Tier 2: Launch Windows 11 'ms-settings:apps-volume' for manual per-app audio assignment.

    Returns:
        tuple[bool, str]: (Success flag, user guidance or error message).
    """
    if sys.platform != "win32":
        return False, "O painel de volume por aplicativo requer Windows 11."

    try:
        os.startfile("ms-settings:apps-volume")
        return (
            True,
            "Painel de volume por aplicativo aberto no Windows. "
            "Localize o Zoom e o WhatsApp para definir saída e entrada conforme o padrão.",
        )
    except Exception as exc:
        # Fallback via start command in shell
        try:
            subprocess.Popen(["cmd", "/c", "start", "ms-settings:apps-volume"], shell=True)
            return (
                True,
                "Comando de abertura do painel de volume por aplicativo enviado ao Windows.",
            )
        except Exception as fallback_exc:
            return False, f"Não foi possível abrir as configurações do Windows: {exc} ({fallback_exc})"


def read_policy_config_routes() -> dict[str, dict[str, str]]:
    """Query persisted per-app audio routing from the Windows PolicyConfig registry store.

    Returns:
        dict[str, dict[str, str]]: Map of app name (e.g. 'Zoom.exe') to device bindings.
    """
    if sys.platform != "win32":
        return {}

    try:
        import winreg
    except ImportError:
        return {}

    routes: dict[str, dict[str, str]] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, POLICY_CONFIG_REG_PATH) as key:
            num_subkeys, _, _ = winreg.QueryInfoKey(key)
            for i in range(num_subkeys):
                try:
                    sub_name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, sub_name) as sub_key:
                        _, num_values, _ = winreg.QueryInfoKey(sub_key)
                        for j in range(num_values):
                            val_name, val_data, _ = winreg.EnumValue(sub_key, j)
                            if isinstance(val_data, str):
                                val_lower = val_data.casefold()
                                if "zoom" in val_lower or "whatsapp" in val_lower:
                                    app = ZOOM_APP if "zoom" in val_lower else WHATSAPP_APP
                                    routes.setdefault(app, {})
                                    # Parse endpoint reference and app path
                                    routes[app][f"{sub_name}:{val_name}"] = val_data
                except OSError:
                    continue
    except OSError:
        pass

    return routes


def get_active_sessions_for_app(app_target: str) -> list[dict[str, Any]]:
    """Query active Windows audio render sessions matching target app using pycaw.

    Args:
        app_target: Substring to match against process name, display name, or identifier.

    Returns:
        list[dict[str, Any]]: Detected session information summaries.
    """
    if sys.platform != "win32":
        return []

    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError:
        return []

    target_norm = app_target.casefold().replace(".exe", "")
    matches = []
    try:
        sessions = AudioUtilities.GetAllSessions()
        for s in sessions:
            proc = getattr(s, "Process", None)
            proc_name = getattr(proc, "name", lambda: "")() if proc else ""
            disp_name = getattr(s, "DisplayName", "") or ""
            ident = getattr(s, "Identifier", "") or ""

            haystack = f"{proc_name} {disp_name} {ident}".casefold()
            if target_norm in haystack:
                state = getattr(s, "State", 0)
                pid = getattr(proc, "pid", None) if proc else None
                muted = False
                vol = 1.0
                try:
                    simple = getattr(s, "SimpleAudioVolume", None)
                    if simple:
                        muted = bool(simple.GetMute())
                        vol = float(simple.GetMasterVolume())
                except Exception:
                    pass

                matches.append(
                    {
                        "process_name": proc_name,
                        "pid": pid,
                        "display_name": disp_name,
                        "identifier": ident,
                        "state": state,
                        "muted": muted,
                        "volume": vol,
                    }
                )
    except Exception as exc:
        logger.debug("Failed querying pycaw sessions: %s", exc)

    return matches


def check_app_routes() -> dict[str, dict[str, Any]]:
    """Tier 3: Check current audio routing status and active sessions for Zoom and WhatsApp.

    Returns:
        dict[str, dict[str, Any]]: Mapping of app names to route status dictionaries.
    """
    policy_routes = read_policy_config_routes()
    results: dict[str, dict[str, Any]] = {}

    for app, def_render, def_capture in (
        (ZOOM_APP, DEFAULT_ZOOM_RENDER_NAME, DEFAULT_ZOOM_CAPTURE_NAME),
        (WHATSAPP_APP, DEFAULT_WHATSAPP_RENDER_NAME, DEFAULT_WHATSAPP_CAPTURE_NAME),
    ):
        active = get_active_sessions_for_app(app)
        app_policies = policy_routes.get(app, {})

        is_running = len(active) > 0
        has_policy = len(app_policies) > 0

        if is_running and has_policy:
            status = "active_and_routed"
            details = (
                f"Sessão ativa detectada e roteamento persistido no Windows ({len(active)} sessão(ões))."
            )
        elif is_running:
            status = "active_default"
            details = f"Sessão ativa no dispositivo padrão ({len(active)} sessão(ões))."
        elif has_policy:
            status = "configured"
            details = "Roteamento persistido no registro do Windows (aplicativo não aberto no momento)."
        else:
            status = "unconfigured"
            details = "Nenhum direcionamento personalizado configurado para este aplicativo."

        results[app] = {
            "app_name": app,
            "target_render": def_render,
            "target_capture": def_capture,
            "configured_render": def_render if has_policy else None,
            "configured_capture": def_capture if has_policy else None,
            "is_running": is_running,
            "active_sessions": active,
            "status": status,
            "details": details,
            "policies": app_policies,
        }

    return results


def configure_app_route(
    app_name: str,
    render_id: str | None = None,
    capture_id: str | None = None,
    cli_path: Path | str | None = None,
) -> tuple[bool, str]:
    """Tier 1 with fallback to Tier 2: Configure independent audio devices for an application.

    Attempts automated CLI assignment via SoundVolumeView / svcl. If not present,
    provides informative guidance and launches Tier 2 Settings.

    Args:
        app_name: Target application (e.g. 'Zoom.exe' or 'WhatsApp.exe').
        render_id: Device ID or friendly name for playback/speaker.
        capture_id: Device ID or friendly name for recording/mic.
        cli_path: Optional explicit path to svcl/SoundVolumeView executable.

    Returns:
        tuple[bool, str]: (Success flag, result explanation or guidance).
    """
    if not render_id and not capture_id:
        return False, "Nenhum dispositivo de reprodução ou gravação informado."

    # Locate CLI tool (Tier 1)
    tool = Path(cli_path) if cli_path else find_cli_tool()
    if tool and tool.is_file():
        successes = []
        errors = []

        # svcl /SetAppDefault <Device Name or ID> <Type> <AppName>
        # Type: 1 = Playback (render), 2 = Capture (recording), all = Both
        if render_id:
            cmd = [str(tool), "/SetAppDefault", str(render_id), "1", app_name]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
                if res.returncode == 0:
                    successes.append(f"Saída definida para '{render_id}'")
                else:
                    errors.append(f"Erro ao definir saída: {res.stderr.strip() or res.stdout.strip()}")
            except Exception as exc:
                errors.append(f"Falha ao executar ferramenta de saída: {exc}")

        if capture_id:
            cmd = [str(tool), "/SetAppDefault", str(capture_id), "2", app_name]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
                if res.returncode == 0:
                    successes.append(f"Entrada definida para '{capture_id}'")
                else:
                    errors.append(f"Erro ao definir entrada: {res.stderr.strip() or res.stdout.strip()}")
            except Exception as exc:
                errors.append(f"Falha ao executar ferramenta de entrada: {exc}")

        if successes and not errors:
            return True, f"Roteamento de {app_name} configurado com sucesso via CLI: " + ", ".join(successes)
        if successes and errors:
            msg = f"Roteamento parcial de {app_name}: " + ", ".join(successes) + ". " + "; ".join(errors)
            return False, msg
        return False, f"Falha na configuração CLI para {app_name}: " + "; ".join(errors)

    # Tier 1 CLI not available: Fallback to Tier 2 guidance
    msg = (
        f"Ferramenta de automação CLI (svcl/SoundVolumeView) não encontrada no sistema. "
        f"Configuração automática direta indisponível. "
        f"Para definir {app_name} manualmente, use o painel do Windows ('ms-settings:apps-volume'). "
        f"Recomendado para {app_name}: Saída='{render_id or DEFAULT_ZOOM_RENDER_NAME}', "
        f"Entrada='{capture_id or DEFAULT_ZOOM_CAPTURE_NAME}'."
    )
    return False, msg


def configure_all_routes(
    zoom_render: str = DEFAULT_ZOOM_RENDER_NAME,
    zoom_capture: str = DEFAULT_ZOOM_CAPTURE_NAME,
    whatsapp_render: str = DEFAULT_WHATSAPP_RENDER_NAME,
    whatsapp_capture: str = DEFAULT_WHATSAPP_CAPTURE_NAME,
    cli_path: Path | str | None = None,
) -> dict[str, tuple[bool, str]]:
    """Configure standardized audio routes for both Zoom and WhatsApp.

    Returns:
        dict[str, tuple[bool, str]]: Results per application.
    """
    results = {
        ZOOM_APP: configure_app_route(ZOOM_APP, zoom_render, zoom_capture, cli_path=cli_path),
        WHATSAPP_APP: configure_app_route(
            WHATSAPP_APP, whatsapp_render, whatsapp_capture, cli_path=cli_path
        ),
    }
    return results


def is_virtual_camera_supported() -> tuple[bool, str]:
    """Check whether the Windows 11 Media Foundation native virtual camera is supported."""
    return camera_support()


def get_virtual_cam_status(obs_client: Any = None) -> dict[str, Any]:
    """Query status of both OBS Virtual Camera and Native Meeting Assistant Virtual Camera.

    Args:
        obs_client: Optional obsws_python.ReqClient instance.

    Returns:
        dict[str, Any]: Diagnostic status of both virtual camera systems.
    """
    obs_cam_active = False
    obs_cam_available = False
    obs_cam_error = None

    if obs_client is not None:
        try:
            res = obs_client.send("GetVirtualCamStatus", raw=True)
            obs_cam_active = bool(res.get("outputActive", False))
            obs_cam_available = True
        except Exception as exc:
            obs_cam_error = str(exc)
    else:
        obs_cam_error = "Cliente OBS não conectado."

    native_supported, native_reason = camera_support()
    native_exec = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "MeetingAssistant"
        / "VirtualCamera"
        / "meeting-assistant-camera.exe"
    )
    native_installed = native_exec.is_file()

    return {
        "obs_virtual_cam": {
            "active": obs_cam_active,
            "available": obs_cam_available,
            "error": obs_cam_error,
        },
        "native_virtual_cam": {
            "supported": native_supported,
            "reason": native_reason,
            "installed": native_installed,
            "executable_path": str(native_exec) if native_installed else None,
        },
    }


def start_obs_virtual_cam(obs_client: Any = None) -> tuple[bool, str]:
    """Start OBS Virtual Camera via obs-websocket.

    Args:
        obs_client: Connected obsws_python.ReqClient instance.

    Returns:
        tuple[bool, str]: (Success flag, message).
    """
    if obs_client is None:
        return False, "OBS não conectado. Conecte ao OBS antes de iniciar a Câmera Virtual."

    try:
        status = obs_client.send("GetVirtualCamStatus", raw=True)
        if status.get("outputActive"):
            return True, "Câmera Virtual do OBS já está em execução."

        obs_client.send("StartVirtualCam", raw=True)
        status_after = obs_client.send("GetVirtualCamStatus", raw=True)
        if status_after.get("outputActive"):
            return True, "Câmera Virtual do OBS iniciada com sucesso."
        return False, "Comando enviado, mas o OBS não confirmou ativação da Câmera Virtual."
    except Exception as exc:
        return False, f"Falha ao iniciar Câmera Virtual do OBS: {exc}"


def stop_obs_virtual_cam(obs_client: Any = None) -> tuple[bool, str]:
    """Stop OBS Virtual Camera via obs-websocket.

    Args:
        obs_client: Connected obsws_python.ReqClient instance.

    Returns:
        tuple[bool, str]: (Success flag, message).
    """
    if obs_client is None:
        return False, "OBS não conectado."

    try:
        status = obs_client.send("GetVirtualCamStatus", raw=True)
        if not status.get("outputActive"):
            return True, "Câmera Virtual do OBS já está parada."

        obs_client.send("StopVirtualCam", raw=True)
        status_after = obs_client.send("GetVirtualCamStatus", raw=True)
        if not status_after.get("outputActive"):
            return True, "Câmera Virtual do OBS parada com sucesso."
        return False, "Comando enviado, mas o OBS não confirmou parada da Câmera Virtual."
    except Exception as exc:
        return False, f"Falha ao parar Câmera Virtual do OBS: {exc}"
