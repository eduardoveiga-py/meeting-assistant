"""OBS Studio AV Provisioning Service.

Connects to OBS Studio via obs-websocket (port 4455), provisions audio monitoring
device, standard scenes, anti-display-capture enforcement, native JW Library HWND
capture, and process audio isolation (R4).
"""

from __future__ import annotations

import configparser
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from obsws_python.error import OBSSDKRequestError

from meeting_assistant.services.obs_capture_safety import disable_managed_display_captures
from meeting_assistant.services.obs_hall_setup import fit_and_enable
from meeting_assistant.services.obs_jwl_capture import (
    KIND as JWL_KIND,
)
from meeting_assistant.services.obs_jwl_capture import (
    SOURCE as JWL_SOURCE,
)

logger = logging.getLogger(__name__)

MANAGED_SCENES = ("Texto do Ano", "Palco", "Mídias")
AUDIO_BUS_SCENE = "Meeting Assistant - Áudio"

DEFAULT_ZOOM_MONITOR_DEVICE_NAME = "V-OUT Zoom (Envio)"

JWL_AUDIO_SOURCE = "Meeting Assistant - Áudio JW Library"
ZOOM_AUDIO_SOURCE = "Meeting Assistant - Áudio Zoom"
PROCESS_AUDIO_KIND = "wasapi_process_output_capture"

MONITOR_ONLY = "OBS_MONITORING_TYPE_MONITOR_ONLY"
MONITOR_NONE = "OBS_MONITORING_TYPE_NONE"


@dataclass
class OBSProvisionResult:
    """Result of full OBS Studio AV provisioning."""

    monitoring_device_set: bool = False
    scenes_created: list[str] = field(default_factory=list)
    jwl_hwnd_capture_configured: bool = False
    display_captures_disabled: list[str] = field(default_factory=list)
    process_audio_configured: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


def connect_obs(
    host: str = "127.0.0.1",
    port: int = 4455,
    password: str = "",
    timeout: float = 3.0,
) -> Any:
    """Establish obs-websocket client connection using obsws_python.ReqClient.

    Args:
        host: Host address (defaults to localhost).
        port: WebSocket port (defaults to 4455).
        password: Authentication password.
        timeout: Socket timeout in seconds.

    Returns:
        obsws_python.ReqClient instance.
    """
    import obsws_python as obs

    return obs.ReqClient(
        host=host,
        port=port,
        password=password,
        timeout=timeout,
    )


def set_obs_monitoring_device(
    client: Any,
    device_id: str,
    device_name: str = DEFAULT_ZOOM_MONITOR_DEVICE_NAME,
    profiles_dir: Path | str | None = None,
) -> tuple[bool, str]:
    """Configure OBS audio monitoring device to target virtual cable (Cable A).

    Applies settings via obs-websocket SetProfileParameter and updates
    basic.ini on disk for persistence.

    Args:
        client: Connected obs-websocket client.
        device_id: Windows audio endpoint ID or GUID.
        device_name: Device friendly name (defaults to 'V-OUT Zoom (Envio)').
        profiles_dir: Optional custom path to OBS profiles directory.

    Returns:
        tuple[bool, str]: (Success flag, descriptive message).
    """
    if not device_id:
        return False, "ID do dispositivo de monitoramento não informado."

    ws_updated = False
    ini_updated = False

    # 1. Update active OBS profile via obs-websocket SetProfileParameter
    try:
        client.send(
            "SetProfileParameter",
            {
                "parameterCategory": "Audio",
                "parameterName": "MonitoringDeviceId",
                "parameterValue": device_id,
            },
            raw=True,
        )
        if device_name:
            client.send(
                "SetProfileParameter",
                {
                    "parameterCategory": "Audio",
                    "parameterName": "MonitoringDeviceName",
                    "parameterValue": device_name,
                },
                raw=True,
            )
        ws_updated = True
    except Exception as exc:
        logger.warning("Falha ao definir dispositivo de monitoramento via WebSocket: %s", exc)

    # 2. Update basic.ini on disk for persistence across OBS restarts
    try:
        curr_profile = ""
        try:
            curr_profile = client.send("GetProfileList", raw=True).get("currentProfileName", "")
        except Exception:
            pass

        root = (
            Path(profiles_dir)
            if profiles_dir is not None
            else Path(os.environ.get("APPDATA", "")) / "obs-studio" / "basic" / "profiles"
        )

        if root.is_dir():
            for path in root.glob("*/basic.ini"):
                settings = configparser.ConfigParser(interpolation=None, strict=False)
                settings.read(path, encoding="utf-8-sig")

                name = settings.get("General", "Name", fallback="")
                if not curr_profile or name == curr_profile:
                    if not settings.has_section("Audio"):
                        settings.add_section("Audio")
                    settings.set("Audio", "MonitoringDeviceId", device_id)
                    if device_name:
                        settings.set("Audio", "MonitoringDeviceName", device_name)
                    with open(path, "w", encoding="utf-8-sig") as f:
                        settings.write(f)
                    ini_updated = True
                    break
    except Exception as exc:
        logger.warning("Falha ao persistir basic.ini no disco: %s", exc)

    if ws_updated or ini_updated:
        return True, f"Dispositivo de monitoramento configurado para '{device_name}' ({device_id})."
    return False, "Não foi possível definir o dispositivo de monitoramento nem no WebSocket nem no disco."


def provision_scenes(client: Any) -> tuple[list[str], list[str]]:
    """Idempotently create standard scenes and nest audio bus without modifying live Program.

    Scenes created if missing:
    - Texto do Ano
    - Palco
    - Mídias
    - Meeting Assistant - Áudio

    Nests 'Meeting Assistant - Áudio' as a scene item across all visual scenes.
    NEVER calls SetCurrentProgramScene.

    Args:
        client: Connected obs-websocket client.

    Returns:
        tuple[list[str], list[str]]: (Created scenes list, error list).
    """
    created_scenes: list[str] = []
    errors: list[str] = []

    try:
        scenes_data = client.send("GetSceneList", raw=True)
        existing_scenes = {s["sceneName"] for s in scenes_data.get("scenes", [])}
    except Exception as exc:
        return [], [f"Falha ao consultar lista de cenas: {exc}"]

    all_target_scenes = (*MANAGED_SCENES, AUDIO_BUS_SCENE)
    for scene in all_target_scenes:
        if scene not in existing_scenes:
            try:
                client.send("CreateScene", {"sceneName": scene}, raw=True)
                created_scenes.append(scene)
                existing_scenes.add(scene)
            except Exception as exc:
                errors.append(f"Erro ao criar cena '{scene}': {exc}")

    # Nest AUDIO_BUS_SCENE in Texto do Ano, Palco, and Mídias
    for scene in MANAGED_SCENES:
        if scene not in existing_scenes:
            continue
        try:
            items_data = client.send("GetSceneItemList", {"sceneName": scene}, raw=True)
            scene_items = items_data.get("sceneItems", [])
            bus_item = next((i for i in scene_items if i.get("sourceName") == AUDIO_BUS_SCENE), None)

            if not bus_item:
                client.send(
                    "CreateSceneItem",
                    {
                        "sceneName": scene,
                        "sourceName": AUDIO_BUS_SCENE,
                        "sceneItemEnabled": True,
                    },
                    raw=True,
                )
            elif not bus_item.get("sceneItemEnabled"):
                client.send(
                    "SetSceneItemEnabled",
                    {
                        "sceneName": scene,
                        "sceneItemId": bus_item["sceneItemId"],
                        "sceneItemEnabled": True,
                    },
                    raw=True,
                )
        except Exception as exc:
            errors.append(f"Erro ao aninhar cena de áudio em '{scene}': {exc}")

    return created_scenes, errors


def enforce_no_display_captures(
    client: Any,
    scenes: tuple[str, ...] = (*MANAGED_SCENES, AUDIO_BUS_SCENE),
) -> tuple[list[str], list[str]]:
    """Scan and explicitly disable all monitor_capture (display capture) sources across scenes.

    Prevents infinite feedback loops with Zoom on monitor 2.

    Args:
        client: Connected obs-websocket client.
        scenes: Sequence of scenes to clean.

    Returns:
        tuple[list[str], list[str]]: (Disabled items description list, error list).
    """
    errors: list[str] = []
    disabled: list[str] = []

    try:
        disabled = disable_managed_display_captures(client, list(scenes))
    except Exception as exc:
        errors.append(f"Falha ao desativar capturas de tela: {exc}")

    return disabled, errors


def provision_jwl_hwnd_capture(
    client: Any,
    scene: str = "Mídias",
    target: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Configure JW Library window capture strictly via native HWND plugin in Mídias scene.

    Ensures Meeting Assistant - JWL (HWND) uses meeting_assistant_jwl_capture
    and scales to inner canvas bounds without using display capture.

    Args:
        client: Connected obs-websocket client.
        scene: Destination scene (defaults to 'Mídias').
        target: Optional HWND binding metadata dictionary.

    Returns:
        tuple[bool, str]: (Success flag, description).
    """
    try:
        inputs_data = client.send("GetInputList", raw=True)
        inputs = inputs_data.get("inputs", [])
        existing = next((i for i in inputs if i.get("inputName") == JWL_SOURCE), None)

        if existing and existing.get("inputKind") != JWL_KIND:
            kind_found = existing.get("inputKind")
            msg = (
                f"A fonte '{JWL_SOURCE}' já existe com tipo incompatível '{kind_found}'; "
                f"requer '{JWL_KIND}'."
            )
            return False, msg

        item_id: int | None = None
        if existing:
            if target:
                client.send(
                    "SetInputSettings",
                    {
                        "inputName": JWL_SOURCE,
                        "inputSettings": target,
                        "overlay": True,
                    },
                    raw=True,
                )
        else:
            try:
                client.send(
                    "CreateInput",
                    {
                        "sceneName": scene,
                        "inputName": JWL_SOURCE,
                        "inputKind": JWL_KIND,
                        "inputSettings": target or {},
                        "sceneItemEnabled": True,
                    },
                    raw=True,
                )
            except OBSSDKRequestError as exc:
                if exc.code == 601:
                    return False, f"Fonte '{JWL_SOURCE}' colidiu com recurso existente no OBS."
                raise

        # Check scene item in scene
        items_data = client.send("GetSceneItemList", {"sceneName": scene}, raw=True)
        items = items_data.get("sceneItems", [])
        item = next((i for i in items if i.get("sourceName") == JWL_SOURCE), None)

        if item:
            item_id = item["sceneItemId"]
        else:
            created_item = client.send(
                "CreateSceneItem",
                {
                    "sceneName": scene,
                    "sourceName": JWL_SOURCE,
                    "sceneItemEnabled": True,
                },
                raw=True,
            )
            item_id = created_item.get("sceneItemId")

        if item_id is not None:
            fit_and_enable(client, scene, item_id)

        return True, f"Captura JWL por HWND configurada com sucesso na cena '{scene}'."
    except Exception as exc:
        return False, f"Erro ao configurar captura JWL por HWND: {exc}"


def provision_process_audio(client: Any) -> tuple[list[str], list[str]]:
    """Configure isolated application process audio outputs in Meeting Assistant - Áudio.

    Configures:
    - Meeting Assistant - Áudio JW Library: jwlibrary.exe, MONITOR_ONLY, track 6.
    - Meeting Assistant - Áudio Zoom: zoom.exe, MONITOR_NONE, track 6.

    Tracks 1-5 are set to False, track 6 is set to True to prevent audio bleed into
    stream/recording tracks while allowing proper monitoring and mix-minus.

    Args:
        client: Connected obs-websocket client.

    Returns:
        tuple[list[str], list[str]]: (Configured sources list, error list).
    """
    configured: list[str] = []
    errors: list[str] = []

    app_targets = [
        (JWL_AUDIO_SOURCE, "jwlibrary.exe", MONITOR_ONLY),
        (ZOOM_AUDIO_SOURCE, "zoom.exe", MONITOR_NONE),
    ]

    try:
        inputs_data = client.send("GetInputList", raw=True)
        inputs = {i["inputName"]: i for i in inputs_data.get("inputs", [])}
    except Exception as exc:
        return [], [f"Falha ao consultar entradas de áudio do OBS: {exc}"]

    try:
        bus_items_data = client.send("GetSceneItemList", {"sceneName": AUDIO_BUS_SCENE}, raw=True)
        bus_items = {i["sourceName"]: i for i in bus_items_data.get("sceneItems", [])}
    except Exception as exc:
        return [], [f"Falha ao consultar itens da cena '{AUDIO_BUS_SCENE}': {exc}"]

    for name, exe_name, monitor_type in app_targets:
        try:
            settings = {"window": f"Qualquer:Qualquer:{exe_name}", "priority": 2}

            if name not in inputs:
                try:
                    client.send(
                        "CreateInput",
                        {
                            "sceneName": AUDIO_BUS_SCENE,
                            "inputName": name,
                            "inputKind": PROCESS_AUDIO_KIND,
                            "inputSettings": settings,
                            "sceneItemEnabled": True,
                        },
                        raw=True,
                    )
                except OBSSDKRequestError as exc:
                    if exc.code == 601:
                        errors.append(f"Nome '{name}' já reservado no OBS.")
                        continue
                    raise
            else:
                client.send(
                    "SetInputSettings",
                    {
                        "inputName": name,
                        "inputSettings": settings,
                        "overlay": True,
                    },
                    raw=True,
                )

            # Ensure item exists and is enabled in AUDIO_BUS_SCENE
            if name not in bus_items:
                client.send(
                    "CreateSceneItem",
                    {
                        "sceneName": AUDIO_BUS_SCENE,
                        "sourceName": name,
                        "sceneItemEnabled": True,
                    },
                    raw=True,
                )
            else:
                item_id = bus_items[name]["sceneItemId"]
                client.send(
                    "SetSceneItemEnabled",
                    {
                        "sceneName": AUDIO_BUS_SCENE,
                        "sceneItemId": item_id,
                        "sceneItemEnabled": True,
                    },
                    raw=True,
                )

            # Track isolation: Tracks 1-5 = False, Track 6 = True
            tracks = {str(i): False for i in range(1, 7)}
            tracks["6"] = True
            client.send(
                "SetInputAudioTracks",
                {
                    "inputName": name,
                    "inputAudioTracks": tracks,
                },
                raw=True,
            )

            # Monitor type
            client.send(
                "SetInputAudioMonitorType",
                {
                    "inputName": name,
                    "monitorType": monitor_type,
                },
                raw=True,
            )

            # Unmute
            client.send(
                "SetInputMute",
                {
                    "inputName": name,
                    "inputMuted": False,
                },
                raw=True,
            )

            configured.append(name)
        except Exception as exc:
            errors.append(f"Erro ao configurar áudio de processo '{name}': {exc}")

    return configured, errors


def provision_obs_av(
    host: str = "127.0.0.1",
    port: int = 4455,
    password: str = "",
    zoom_cable_id: str = "",
    zoom_cable_name: str = DEFAULT_ZOOM_MONITOR_DEVICE_NAME,
    client: Any = None,
    profiles_dir: Path | str | None = None,
    jwl_target: dict[str, Any] | None = None,
) -> OBSProvisionResult:
    """Master idempotent provisioning of OBS Studio audio and video services.

    1. Connects to OBS Studio (if client not provided).
    2. Configures OBS monitoring device to Zoom virtual cable.
    3. Provisions scenes (Texto do Ano, Palco, Mídias, Meeting Assistant - Áudio).
    4. Enforces anti-display-capture safety (disables monitor_capture).
    5. Configures HWND-based JW Library capture in Mídias.
    6. Configures application process audio outputs with mix-minus & track 6 isolation.

    NEVER changes Program scene or deletes operator sources.

    Args:
        host: OBS WebSocket host.
        port: OBS WebSocket port.
        password: OBS WebSocket password.
        zoom_cable_id: Endpoint ID of Cable A for audio monitoring.
        zoom_cable_name: Friendly name for monitoring device.
        client: Optional pre-connected obs-websocket client.
        profiles_dir: Optional custom profiles directory.
        jwl_target: Optional HWND binding metadata for JW Library.

    Returns:
        OBSProvisionResult: Detailed provisioning report.
    """
    result = OBSProvisionResult()

    # 1. Connect
    owns_client = False
    if client is None:
        try:
            client = connect_obs(host=host, port=port, password=password)
            owns_client = True
        except Exception as exc:
            result.errors.append(f"Não foi possível conectar ao OBS Studio ({host}:{port}): {exc}")
            return result

    try:
        # 2. Monitoring Device
        if zoom_cable_id:
            mon_ok, mon_msg = set_obs_monitoring_device(
                client=client,
                device_id=zoom_cable_id,
                device_name=zoom_cable_name,
                profiles_dir=profiles_dir,
            )
            result.monitoring_device_set = mon_ok
            if not mon_ok:
                result.errors.append(mon_msg)

        # 3. Provision Scenes & Audio Bus
        created_scenes, scene_errors = provision_scenes(client)
        result.scenes_created = created_scenes
        result.errors.extend(scene_errors)

        # 4. Anti-Display Capture Enforcement
        disabled_displays, safety_errors = enforce_no_display_captures(client)
        result.display_captures_disabled = disabled_displays
        result.errors.extend(safety_errors)

        # 5. JW Library HWND Capture
        jwl_ok, jwl_msg = provision_jwl_hwnd_capture(client, scene="Mídias", target=jwl_target)
        result.jwl_hwnd_capture_configured = jwl_ok
        if not jwl_ok:
            result.errors.append(jwl_msg)

        # 6. Process Audio Outputs
        audio_configured, audio_errors = provision_process_audio(client)
        result.process_audio_configured = audio_configured
        result.errors.extend(audio_errors)

    finally:
        if owns_client:
            try:
                if hasattr(client, "disconnect"):
                    client.disconnect()
            except Exception:
                pass

    return result
