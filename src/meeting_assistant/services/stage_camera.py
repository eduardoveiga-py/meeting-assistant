"""Camera provisioning and conservative contingency independent of Hall guards."""

from urllib.parse import urlsplit

from meeting_assistant.services.obs_setup import CAMERA_SOURCE

USB_SOURCE = "Meeting Assistant - Câmera USB"
STREAM_SOURCE = "Meeting Assistant - Câmera de rede"


def call(client, request, **data):
    return client.send(request, data, raw=True)


def camera_health(client, scene, source):
    """False means observed failure; None means hardware health is not exposed."""
    items = call(client, "GetSceneItemList", sceneName=scene)["sceneItems"]
    item = next((x for x in items if x["sourceName"] == source), None)
    if not item or not item.get("sceneItemEnabled", False):
        return False, "Fonte da câmera ausente ou desativada em Palco."
    kinds = {x["inputName"]: x["inputKind"] for x in call(client, "GetInputList")["inputs"]}
    if kinds.get(source) == "dshow_input":
        settings = call(client, "GetInputSettings", inputName=source)["inputSettings"]
        devices = call(
            client, "GetInputPropertiesListPropertyItems", inputName=source, propertyName="video_device_id"
        )["propertyItems"]
        available = {d["itemValue"] for d in devices if d.get("itemEnabled", True)}
        if not settings.get("video_device_id") or settings["video_device_id"] not in available:
            return False, "Dispositivo USB/captura não detectado."
        transform = item.get("sceneItemTransform", {})
        if transform.get("sourceWidth", 0) > 0 and transform.get("sourceHeight", 0) > 0:
            return True, "Dispositivo detectado e vídeo dimensionado no OBS; confira a imagem."
    if kinds.get(source) == "ffmpeg_source":
        status = call(client, "GetMediaInputStatus", inputName=source)["mediaState"]
        if status in {
            "OBS_MEDIA_STATE_ERROR",
            "OBS_MEDIA_STATE_STOPPED",
            "OBS_MEDIA_STATE_ENDED",
            "OBS_MEDIA_STATE_NONE",
        }:
            return False, "A fonte de câmera não está reproduzindo."
        if status == "OBS_MEDIA_STATE_PLAYING":
            return True, "Fluxo da câmera em reprodução no OBS; imagem física não certificada."
    return None, "Esta fonte não informa a saúde da câmera física. Confira a imagem."


def contingency(client, settings):
    try:
        healthy, reason = camera_health(client, settings.scene_speaker, settings.camera_source_name)
    except Exception:
        healthy, reason = None, "Não foi possível verificar a câmera."
    # Unknown does not claim a healthy camera. Use the static fallback conservatively.
    target = settings.scene_speaker if healthy is True else settings.scene_background
    names = {s["sceneName"] for s in call(client, "GetSceneList")["scenes"]}
    if target not in names:
        raise ValueError("Cena de contingência ausente; nenhuma troca foi feita. Confira o OBS.")
    if target == settings.scene_background:
        items = call(client, "GetSceneItemList", sceneName=target)["sceneItems"]
        if not any(i.get("sceneItemEnabled") for i in items):
            raise ValueError("Texto do Ano sem fonte habilitada; nenhuma troca foi feita.")
    call(client, "SetCurrentProgramScene", sceneName=target)
    actual = call(client, "GetCurrentProgramScene")["currentProgramSceneName"]
    if actual != target:
        raise ValueError("OBS não confirmou a cena solicitada.")
    return f"OBS: {target}. {reason} Áudio não foi alterado."


def list_sources(client):
    audio = {"wasapi_input_capture", "wasapi_output_capture", "wasapi_process_output_capture"}
    return [i["inputName"] for i in call(client, "GetInputList")["inputs"] if i["inputKind"] not in audio]


def prepare_camera(client, mode, value):
    """Every camera is attached to Palco. Never delete existing sources or switch Program."""
    rows = {i["inputName"]: i for i in call(client, "GetInputList")["inputs"]}
    if mode == "existing":
        name = value
        if name not in rows:
            raise ValueError("Selecione uma fonte existente no OBS.")
        kind, config = None, None
    elif mode == "usb":
        name, kind, config = (
            USB_SOURCE,
            "dshow_input",
            {"video_device_id": value, "deactivate_when_not_showing": False},
        )
    elif mode == "network":
        parsed = urlsplit(value)
        if not parsed.hostname or parsed.scheme.lower() not in {
            "rtsp",
            "rtsps",
            "http",
            "https",
            "srt",
            "rtmp",
            "rtmps",
        }:
            raise ValueError("Use uma URL RTSP, HTTP, SRT ou RTMP válida.")
        name, kind = STREAM_SOURCE, "ffmpeg_source"
        config = {
            "input": value,
            "is_local_file": False,
            "restart_on_activate": False,
            "close_when_inactive": False,
        }
    else:
        raise ValueError("Tipo de câmera desconhecido.")
    if kind and name in rows and rows[name]["inputKind"] != kind:
        raise ValueError("Nome reservado ocupado por outra fonte; confira o OBS.")
    if mode == "usb" and not value and name in rows:
        return {
            "devices": call(
                client, "GetInputPropertiesListPropertyItems", inputName=name, propertyName="video_device_id"
            )["propertyItems"]
        }
    scenes = {s["sceneName"] for s in call(client, "GetSceneList")["scenes"]}
    if "Palco" not in scenes:
        call(client, "CreateScene", sceneName="Palco")
    if kind:
        if name not in rows:
            call(
                client,
                "CreateInput",
                sceneName="Palco",
                inputName=name,
                inputKind=kind,
                inputSettings=config,
                sceneItemEnabled=False,
            )
        else:
            call(client, "SetInputSettings", inputName=name, inputSettings=config, overlay=True)
        call(client, "SetInputMute", inputName=name, inputMuted=True)
    items = call(client, "GetSceneItemList", sceneName="Palco")["sceneItems"]
    item = next((i for i in items if i["sourceName"] == name), None)
    item_id = (
        item["sceneItemId"]
        if item
        else call(client, "CreateSceneItem", sceneName="Palco", sourceName=name, sceneItemEnabled=False)[
            "sceneItemId"
        ]
    )
    video = call(client, "GetVideoSettings")
    call(
        client,
        "SetSceneItemTransform",
        sceneName="Palco",
        sceneItemId=item_id,
        sceneItemTransform={
            "positionX": 0,
            "positionY": 0,
            "boundsType": "OBS_BOUNDS_SCALE_INNER",
            "alignment": 5,
            "boundsWidth": video["baseWidth"],
            "boundsHeight": video["baseHeight"],
        },
    )
    # USB discovery leaves the unconfigured input disabled.
    if mode == "usb" and not value:
        return {
            "devices": call(
                client, "GetInputPropertiesListPropertyItems", inputName=name, propertyName="video_device_id"
            )["propertyItems"]
        }
    call(client, "SetSceneItemEnabled", sceneName="Palco", sceneItemId=item_id, sceneItemEnabled=True)
    # Only disable other managed camera items, never unrelated personal inputs.
    for other in items:
        if other["sourceName"] != name and other["sourceName"] in {CAMERA_SOURCE, USB_SOURCE, STREAM_SOURCE}:
            call(
                client,
                "SetSceneItemEnabled",
                sceneName="Palco",
                sceneItemId=other["sceneItemId"],
                sceneItemEnabled=False,
            )
    return {"source": name}
