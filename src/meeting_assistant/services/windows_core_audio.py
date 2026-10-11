"""Windows Core Audio device management service for Meeting Assistant AV Setup.

Enumerates audio playback and recording endpoints using Windows Core Audio
(MMDevice API via pycaw / comtypes) and Windows Registry (MMDevices).
Provides deterministic project role identification, batch/single device renaming
via elevated PowerShell script, and audio endpoint disabling.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Standard Project Roles
ROLE_V_OUT_AUX = "V-OUT Aux"
ROLE_V_MIC_AUX = "V-MIC Aux"
ROLE_V_OUT_ZOOM = "V-OUT Zoom (Envio)"
ROLE_V_MIC_ZOOM = "V-MIC Zoom (Captação)"
ROLE_V_OUT_WAPP = "V-OUT Wapp (Envio)"
ROLE_V_MIC_WAPP = "V-MIC Wapp (Captação)"
ROLE_MESA_IN = "Mesa de Som (Entrada USB)"
ROLE_MESA_OUT_P2 = "Mesa de Som (Retorno P2)"
ROLE_BLACKMAGIC = "Blackmagic HDMI Audio"
ROLE_WEBCAM_MIC = "Webcam Mic"

ALL_PROJECT_ROLES = [
    ROLE_V_OUT_AUX,
    ROLE_V_MIC_AUX,
    ROLE_V_OUT_ZOOM,
    ROLE_V_MIC_ZOOM,
    ROLE_V_OUT_WAPP,
    ROLE_V_MIC_WAPP,
    ROLE_MESA_IN,
    ROLE_MESA_OUT_P2,
    ROLE_BLACKMAGIC,
    ROLE_WEBCAM_MIC,
]

# Slug aliases mapping
ROLE_SLUG_MAP: dict[str, str] = {
    "v_out_aux": ROLE_V_OUT_AUX,
    "v_mic_aux": ROLE_V_MIC_AUX,
    "v_out_zoom": ROLE_V_OUT_ZOOM,
    "v_mic_zoom": ROLE_V_MIC_ZOOM,
    "v_out_wapp": ROLE_V_OUT_WAPP,
    "v_mic_wapp": ROLE_V_MIC_WAPP,
    "mesa_in": ROLE_MESA_IN,
    "mesa_out_p2": ROLE_MESA_OUT_P2,
    "blackmagic": ROLE_BLACKMAGIC,
    "webcam_mic": ROLE_WEBCAM_MIC,
}

# Windows MMDevices Registry Keys & PKEYs
REG_MMDEVICES_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"
PKEY_DEVICE_INTERFACE_NAME = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"
PKEY_DEVICE_DESCRIPTION = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
PKEY_DEVICE_FRIENDLY_NAME = "{a45c254e-df1c-4efd-8020-67d146a850e0},14"
PKEY_AUDIO_ENGINE_FORMAT_1 = "{f19f064d-082c-4e27-bc73-6882a1bb8e4c},0"
PKEY_AUDIO_ENGINE_FORMAT_2 = "{f19f064d-0824-4e08-926e-4734c3871982},0"

DEVICE_STATE_ACTIVE = 1  # 0x00000001
DEVICE_STATE_DISABLED = 268435457  # 0x10000001 (Registry DeviceState disabled)
DEVICE_STATE_DISABLED_COM = 2  # 0x00000002 (MMDevice COM AudioDeviceState.Disabled)
DEVICE_STATE_NOTPRESENT = 4  # 0x00000004
DEVICE_STATE_UNPLUGGED = 8  # 0x00000008
DEVICE_STATES_DISABLED = (DEVICE_STATE_DISABLED, DEVICE_STATE_DISABLED_COM)


@dataclass
class AudioEndpoint:
    """Represents a Windows Core Audio endpoint."""

    id: str
    friendly_name: str
    desc: str
    interface_name: str
    flow: str  # "eRender" or "eCapture"
    state: int  # 1=Active, 268435457 or 2=Disabled
    sample_rate_hz: int
    detected_role: str | None = None

    @property
    def is_active(self) -> bool:
        return self.state == DEVICE_STATE_ACTIVE

    @property
    def is_disabled(self) -> bool:
        return self.state in DEVICE_STATES_DISABLED

    @property
    def guid(self) -> str:
        return get_endpoint_guid(self.id)

    @property
    def flow_direction(self) -> str:
        return "Render" if self.flow == "eRender" else "Capture"


def get_endpoint_guid(endpoint_id: str) -> str:
    """Extract GUID from endpoint ID like {0.0.0.00000000}.{guid}."""
    if "." in endpoint_id:
        return endpoint_id.split(".")[-1]
    return endpoint_id


def get_endpoint_flow_name(endpoint_id_or_flow: str) -> str:
    """Return 'Render' or 'Capture' based on endpoint ID prefix or flow name."""
    if endpoint_id_or_flow.startswith("{0.0.0.") or endpoint_id_or_flow.casefold() in (
        "erender",
        "render",
    ):
        return "Render"
    if endpoint_id_or_flow.startswith("{0.0.1.") or endpoint_id_or_flow.casefold() in (
        "ecapture",
        "capture",
    ):
        return "Capture"
    return "Render"


def parse_wave_format_sample_rate(blob: bytes) -> int | None:
    """Extract sample rate from a WAVEFORMATEXTENSIBLE binary registry blob.

    Standard PROPVARIANT VT_BLOB stores WAVEFORMATEX / WAVEFORMATEXTENSIBLE
    with nSamplesPerSec at offset 12 (or after VT header).
    """
    if not blob or len(blob) < 16:
        return None

    try:
        # Check direct offset 12 (standard for Windows MMDevice VT_BLOB)
        rate = struct.unpack_from("<I", blob, 12)[0]
        if 8000 <= rate <= 192000:
            return rate
    except Exception:
        pass

    # Fallback: scan for known standard sample rates or WAVEFORMATEX tags
    for sr in (48000, 44100, 96000, 88200, 32000):
        sr_bytes = struct.pack("<I", sr)
        pos = blob.find(sr_bytes)
        if pos >= 4:
            return sr

    return None


def read_endpoint_registry_properties(direction: str, guid: str) -> dict[str, Any]:
    """Read MMDevices endpoint registry properties for a specific direction and GUID."""
    if sys.platform != "win32":
        return {}

    import winreg

    key_path = rf"{REG_MMDEVICES_PATH}\{direction}\{guid}\Properties"
    results: dict[str, Any] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as pk:
            count = winreg.QueryInfoKey(pk)[1]
            for j in range(count):
                name, val, _ = winreg.EnumValue(pk, j)
                results[name.casefold()] = val
    except Exception as exc:
        logger.debug("Could not read registry properties for %s\\%s: %s", direction, guid, exc)
    return results


def read_endpoint_registry_state(direction: str, guid: str) -> int:
    """Read MMDevices DeviceState DWORD for a specific direction and GUID."""
    if sys.platform != "win32":
        return DEVICE_STATE_ACTIVE

    import winreg

    key_path = rf"{REG_MMDEVICES_PATH}\{direction}\{guid}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as dk:
            val, _ = winreg.QueryValueEx(dk, "DeviceState")
            return int(val)
    except Exception:
        return DEVICE_STATE_ACTIVE


def identify_endpoint_role(endpoint: AudioEndpoint) -> str | None:
    """Identify project role deterministically using interface names and descriptions."""
    intf = endpoint.interface_name.casefold()
    desc = endpoint.desc.casefold()
    friendly = endpoint.friendly_name.casefold()
    combined = f"{intf} {desc} {friendly}"

    # 1. Virtual Cable A (Zoom)
    if "virtual cable a" in intf or "cable-a" in combined or "virtual cable a" in combined:
        return ROLE_V_OUT_ZOOM if endpoint.flow == "eRender" else ROLE_V_MIC_ZOOM
    if "zoom" in combined and any(x in combined for x in ("cable", "virtual", "v-out", "v-mic")):
        return ROLE_V_OUT_ZOOM if endpoint.flow == "eRender" else ROLE_V_MIC_ZOOM

    # 2. Virtual Cable B (WhatsApp)
    if "virtual cable b" in intf or "cable-b" in combined or "virtual cable b" in combined:
        return ROLE_V_OUT_WAPP if endpoint.flow == "eRender" else ROLE_V_MIC_WAPP
    if ("wapp" in combined or "whatsapp" in combined) and (
        "cable" in combined or "virtual" in combined or "v-out" in combined or "v-mic" in combined
    ):
        return ROLE_V_OUT_WAPP if endpoint.flow == "eRender" else ROLE_V_MIC_WAPP

    # 3. Standard Virtual Cable (Aux)
    excluded_cables = ("cable a", "cable-a", "cable b", "cable-b", "zoom", "wapp", "whatsapp")
    is_standard_cable = "vb-audio virtual cable" in intf or (
        ("virtual cable" in combined or "cabo virtual" in combined)
        and not any(x in combined for x in excluded_cables)
    )
    if is_standard_cable:
        return ROLE_V_OUT_AUX if endpoint.flow == "eRender" else ROLE_V_MIC_AUX
    if "aux" in combined and any(x in combined for x in ("cable", "virtual", "v-out", "v-mic")):
        return ROLE_V_OUT_AUX if endpoint.flow == "eRender" else ROLE_V_MIC_AUX

    # 4. Blackmagic HDMI Audio
    if endpoint.flow == "eRender" and any(k in combined for k in ("blackmagic", "decklink", "intensity")):
        return ROLE_BLACKMAGIC

    # 5. Webcam Mic
    if endpoint.flow == "eCapture" and any(
        k in combined for k in ("webcam", "c920", "c922", "brio", "c270", "camera mic", "câmera", "camera")
    ):
        return ROLE_WEBCAM_MIC

    # 6. Mesa de Som (Entrada USB)
    if endpoint.flow == "eCapture" and (
        any(k in intf for k in ("usb audio", "codec", "behringer", "uca202"))
        or any(k in combined for k in ("mesa", "soundboard", "entrada usb", "microfone usb (mesa"))
    ):
        return ROLE_MESA_IN

    # 7. Mesa de Som (Retorno P2)
    if endpoint.flow == "eRender":
        if any(k in combined for k in ("retorno p2", "saída p2", "saida p2", "p2 (mesa")):
            return ROLE_MESA_OUT_P2
        if any(k in intf for k in ("realtek", "high definition audio", "onboard")):
            blocked = ("cable", "virtual", "blackmagic", "hdmi", "telas", "intel", "nvidia")
            if not any(k in combined for k in blocked):
                return ROLE_MESA_OUT_P2

    return None


def enumerate_endpoints() -> list[AudioEndpoint]:
    """Enumerate all playback (eRender) and recording (eCapture) endpoints."""
    endpoints: list[AudioEndpoint] = []

    if sys.platform != "win32":
        return endpoints

    com_initialized = False
    try:
        import pythoncom

        pythoncom.CoInitialize()
        com_initialized = True
    except Exception:
        pass

    try:
        import comtypes
        from pycaw.pycaw import AudioUtilities, IAudioClient

        devices = AudioUtilities.GetAllDevices()
        for device in devices:
            try:
                endpoint_id = str(device.id)
                flow = AudioUtilities.GetEndpointDataFlow(endpoint_id, 0)
                flow_str = "eRender" if flow == "eRender" or flow == 0 else "eCapture"
                direction = "Render" if flow_str == "eRender" else "Capture"

                friendly_name = str(device.FriendlyName or "")
                raw_state = getattr(device.state, "value", device.state)
                try:
                    state = int(raw_state)
                except Exception:
                    state = DEVICE_STATE_ACTIVE

                guid = get_endpoint_guid(endpoint_id)
                reg_props = read_endpoint_registry_properties(direction, guid)

                desc = str(reg_props.get(PKEY_DEVICE_DESCRIPTION.casefold(), "") or "")
                intf = str(reg_props.get(PKEY_DEVICE_INTERFACE_NAME.casefold(), "") or "")

                if not desc:
                    desc = friendly_name
                if not intf and "(" in friendly_name and friendly_name.endswith(")"):
                    intf = friendly_name[friendly_name.rfind("(") + 1 : -1].strip()

                # Determine sample rate
                sample_rate = 48000
                sr_found = False

                if state == DEVICE_STATE_ACTIVE:
                    try:
                        client = (
                            device._dev.Activate(
                                IAudioClient._iid_,
                                comtypes.CLSCTX_ALL,
                                None,
                            ).QueryInterface(IAudioClient)
                        )
                        pwfx = client.GetMixFormat()
                        sample_rate = int(pwfx.contents.nSamplesPerSec)
                        sr_found = True
                    except Exception:
                        pass

                if not sr_found:
                    blob = reg_props.get(PKEY_AUDIO_ENGINE_FORMAT_1.casefold()) or reg_props.get(
                        PKEY_AUDIO_ENGINE_FORMAT_2.casefold()
                    )
                    if isinstance(blob, bytes):
                        parsed_sr = parse_wave_format_sample_rate(blob)
                        if parsed_sr:
                            sample_rate = parsed_sr

                ep = AudioEndpoint(
                    id=endpoint_id,
                    friendly_name=friendly_name,
                    desc=desc,
                    interface_name=intf,
                    flow=flow_str,
                    state=state,
                    sample_rate_hz=sample_rate,
                )
                ep.detected_role = identify_endpoint_role(ep)
                endpoints.append(ep)
            except Exception as item_err:
                logger.debug("Error processing audio endpoint: %s", item_err)

    except Exception as exc:
        logger.debug("Core Audio COM enumeration failed, falling back to registry: %s", exc)
        endpoints = _enumerate_endpoints_from_registry()

    finally:
        if com_initialized:
            with contextlib.suppress(Exception):
                pythoncom.CoUninitialize()

    return endpoints


def _enumerate_endpoints_from_registry() -> list[AudioEndpoint]:
    """Fallback registry-only enumeration for environments where COM fails."""
    if sys.platform != "win32":
        return []

    import winreg

    endpoints: list[AudioEndpoint] = []
    for direction in ("Render", "Capture"):
        flow_str = "eRender" if direction == "Render" else "eCapture"
        flow_prefix = "{0.0.0.00000000}" if direction == "Render" else "{0.0.1.00000000}"
        path = rf"{REG_MMDEVICES_PATH}\{direction}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
                num_subkeys = winreg.QueryInfoKey(k)[0]
                for i in range(num_subkeys):
                    guid = winreg.EnumKey(k, i)
                    dev_path = rf"{path}\{guid}"
                    state = DEVICE_STATE_ACTIVE
                    try:
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, dev_path) as dk:
                            state = int(winreg.QueryValueEx(dk, "DeviceState")[0])
                    except Exception:
                        pass

                    reg_props = read_endpoint_registry_properties(direction, guid)
                    friendly = str(
                        reg_props.get(PKEY_DEVICE_FRIENDLY_NAME.casefold())
                        or reg_props.get(PKEY_DEVICE_DESCRIPTION.casefold())
                        or guid
                    )
                    desc = str(reg_props.get(PKEY_DEVICE_DESCRIPTION.casefold(), friendly))
                    intf = str(reg_props.get(PKEY_DEVICE_INTERFACE_NAME.casefold(), ""))

                    sample_rate = 48000
                    blob = reg_props.get(PKEY_AUDIO_ENGINE_FORMAT_1.casefold()) or reg_props.get(
                        PKEY_AUDIO_ENGINE_FORMAT_2.casefold()
                    )
                    if isinstance(blob, bytes):
                        parsed_sr = parse_wave_format_sample_rate(blob)
                        if parsed_sr:
                            sample_rate = parsed_sr

                    ep = AudioEndpoint(
                        id=f"{flow_prefix}.{guid}",
                        friendly_name=friendly,
                        desc=desc,
                        interface_name=intf,
                        flow=flow_str,
                        state=state,
                        sample_rate_hz=sample_rate,
                    )
                    ep.detected_role = identify_endpoint_role(ep)
                    endpoints.append(ep)
        except Exception:
            pass

    return endpoints


def map_project_roles(endpoints: list[AudioEndpoint]) -> dict[str, AudioEndpoint]:
    """Map detected endpoints to standard project roles and slug aliases.

    Prioritizes active endpoints over disabled ones, and endpoints whose
    friendly name explicitly contains a project role over generic ones.
    Returns a dictionary keyed by both official role names (e.g. 'V-OUT Zoom (Envio)')
    and slug aliases (e.g. 'v_out_zoom').
    """
    role_map: dict[str, AudioEndpoint] = {}

    def role_priority(ep: AudioEndpoint) -> tuple[int, int, str]:
        has_explicit_role = any(r.casefold() in ep.friendly_name.casefold() for r in ALL_PROJECT_ROLES)
        return (0 if ep.is_active else 1, 0 if has_explicit_role else 1, ep.friendly_name)

    # Sort endpoints so active and explicitly-named devices come first
    sorted_endpoints = sorted(endpoints, key=role_priority)

    for ep in sorted_endpoints:
        role = ep.detected_role or identify_endpoint_role(ep)
        if role and role not in role_map:
            role_map[role] = ep

    # Populate slug aliases
    for slug, official_role in ROLE_SLUG_MAP.items():
        if official_role in role_map and slug not in role_map:
            role_map[slug] = role_map[official_role]

    return role_map


def _sanitize_endpoint_guid(ep_id: str) -> str:
    """Sanitize endpoint ID to safely extract GUID without PowerShell injection risk.

    Allows valid alphanumeric identifiers and standard GUIDs, but enforces strict
    hexadecimal-only sanitization if suspicious or injection characters (quotes,
    semicolons, spaces, comment chars) are detected.
    """
    raw_guid = get_endpoint_guid(ep_id)
    inner = raw_guid.strip("{}")
    has_braces = raw_guid.startswith("{") or "{" in ep_id

    if not re.fullmatch(r"[0-9a-zA-Z\-_]+", inner):
        clean_guid = re.sub(r"[^0-9a-fA-F\-]", "", inner)
    else:
        clean_guid = re.sub(r"[^0-9a-zA-Z\-]", "", inner)

    return f"{{{clean_guid}}}" if clean_guid and has_braces else clean_guid


def generate_elevation_script(
    renames: dict[str, str],
    disables: list[str],
    restart_audiosrv: bool = False,
) -> str:
    """Generate self-contained PowerShell script to rename and disable endpoints.

    Sets custom friendly name in PKEY_DEVICE_DESCRIPTION ({a45c254e-df1c-4efd-8020-67d146a850e0},2)
    and disables endpoints by setting DeviceState to 0x10000001 (268435457).
    Optionally restarts Audiosrv to refresh Windows caches.
    """
    lines = [
        "# Meeting Assistant AV Setup - Elevated Registry Modifications",
        "$ErrorActionPreference = 'Stop'",
        "$successCount = 0",
        "try {",
    ]

    # Renames
    if renames:
        lines.append("    # --- Rename Endpoints ---")
        for ep_id, new_name in renames.items():
            guid = _sanitize_endpoint_guid(ep_id)
            flow_dir = get_endpoint_flow_name(ep_id)
            clean_name = re.sub(r"[\r\n]+", " ", new_name).strip()
            escaped_name = clean_name.replace("'", "''")

            lines.append(f"    # Rename {guid} to '{escaped_name}'")
            lines.append(f"    $guid = '{guid}'")
            lines.append(f"    $newName = '{escaped_name}'")
            lines.append(f"    $directions = @('{flow_dir}')")
            lines.append(
                "    foreach ($dir in $directions) {\n"
                "        $propPath = \"HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
                "MMDevices\\Audio\\$dir\\$guid\\Properties\"\n"
                "        if (Test-Path $propPath) {\n"
                "            Set-ItemProperty -Path $propPath "
                "-Name '{a45c254e-df1c-4efd-8020-67d146a850e0},2' "
                "-Value $newName -Type String -Force\n"
                "            $successCount++\n"
                "        }\n"
                "    }"
            )
            lines.append("")

    # Disables
    if disables:
        lines.append("    # --- Disable Endpoints ---")
        for ep_id in disables:
            guid = _sanitize_endpoint_guid(ep_id)
            flow_dir = get_endpoint_flow_name(ep_id)

            lines.append(f"    # Disable endpoint {guid}")
            lines.append(f"    $guid = '{guid}'")
            lines.append(f"    $directions = @('{flow_dir}')")
            lines.append(
                "    foreach ($dir in $directions) {\n"
                "        $devPath = \"HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
                "MMDevices\\Audio\\$dir\\$guid\"\n"
                "        if (Test-Path $devPath) {\n"
                "            Set-ItemProperty -Path $devPath -Name 'DeviceState' "
                "-Value 268435457 -Type DWord -Force\n"
                "            $successCount++\n"
                "        }\n"
                "    }"
            )
            lines.append("")

    if restart_audiosrv:
        lines.append("    # --- Restart Windows Audio Service ---")
        lines.append("    Restart-Service Audiosrv -Force")
        lines.append("")

    lines.append('    Write-Output "SUCCESS: $successCount operations completed"')
    lines.append("    exit 0")
    lines.append("} catch {")
    lines.append("    Write-Error $_.Exception.Message")
    lines.append("    exit 1")
    lines.append("}")
    return "\n".join(lines)


def modify_endpoints_in_registry(
    renames: dict[str, str],
    disables: list[str],
) -> tuple[bool, str]:
    """Modify endpoints directly in Windows registry if running with elevated privileges."""
    if sys.platform != "win32":
        return False, "Modificação de registro suportada apenas em Windows."

    import winreg

    modified_count = 0
    try:
        # Renames
        for ep_id, new_name in renames.items():
            guid = get_endpoint_guid(ep_id)
            flow_dir = get_endpoint_flow_name(ep_id)
            prop_path = rf"{REG_MMDEVICES_PATH}\{flow_dir}\{guid}\Properties"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, prop_path, 0, winreg.KEY_SET_VALUE) as pk:
                winreg.SetValueEx(
                    pk,
                    PKEY_DEVICE_DESCRIPTION,
                    0,
                    winreg.REG_SZ,
                    new_name,
                )
                modified_count += 1

        # Disables
        for ep_id in disables:
            guid = get_endpoint_guid(ep_id)
            flow_dir = get_endpoint_flow_name(ep_id)
            dev_path = rf"{REG_MMDEVICES_PATH}\{flow_dir}\{guid}"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, dev_path, 0, winreg.KEY_SET_VALUE) as dk:
                winreg.SetValueEx(
                    dk,
                    "DeviceState",
                    0,
                    winreg.REG_DWORD,
                    DEVICE_STATE_DISABLED,
                )
                modified_count += 1

        return True, f"{modified_count} modificações aplicadas diretamente no registro."

    except PermissionError as perm_err:
        return False, f"Acesso negado: requer elevação administrativa (UAC): {perm_err}"
    except Exception as exc:
        return False, f"Falha ao gravar no registro: {exc}"


def is_user_admin() -> bool:
    """Check if the current process is running with administrative privileges."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def apply_device_modifications(
    renames: dict[str, str],
    disables: list[str],
    restart_audiosrv: bool = False,
) -> tuple[bool, str]:
    """Apply device renames and disables, elevating via UAC if necessary.

    Returns (success, message).
    """
    if not renames and not disables:
        return True, "Nenhuma modificação especificada."

    if sys.platform != "win32":
        return False, "Recurso exclusivo para Windows 11."

    # If already running elevated, modify directly
    if is_user_admin():
        success, msg = modify_endpoints_in_registry(renames, disables)
        if success and restart_audiosrv:
            try:
                subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command", "Restart-Service Audiosrv -Force"],
                    capture_output=True,
                    check=False,
                    timeout=15,
                )
                msg += " Serviço Audiosrv reiniciado com sucesso."
            except Exception as e:
                msg += f" Aviso: Falha ao reiniciar Audiosrv: {e}"
        return success, msg

    # Non-elevated: generate script and execute with UAC elevation
    script_content = generate_elevation_script(
        renames=renames,
        disables=disables,
        restart_audiosrv=restart_audiosrv,
    )

    temp_script = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".ps1",
            delete=False,
            encoding="utf-8-sig",
        ) as f:
            f.write(script_content)
            temp_script = f.name

        # Launch elevated PowerShell using Start-Process -Verb RunAs with -PassThru to capture exit code
        ps_cmd = (
            f"$p = Start-Process powershell.exe -ArgumentList "
            f"'-NoProfile -ExecutionPolicy Bypass -File \"{temp_script}\"' -Verb RunAs -Wait -PassThru; "
            f"if ($p) {{ exit $p.ExitCode }} else {{ exit 1 }}"
        )
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if proc.returncode == 0:
            return True, "Modificações de áudio aplicadas com elevação UAC com sucesso."
        return False, f"Falha na elevação ou cancelamento pelo usuário (código {proc.returncode})."

    except subprocess.TimeoutExpired:
        return False, "Tempo esgotado aguardando autorização de elevação UAC."
    except Exception as exc:
        return False, f"Erro ao executar script elevado: {exc}"
    finally:
        if temp_script and os.path.exists(temp_script):
            with contextlib.suppress(Exception):
                os.remove(temp_script)
