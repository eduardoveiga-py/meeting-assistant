"""OBS visual sources and virtual camera, without changing Program or the hall guard."""

from __future__ import annotations

from pathlib import Path

PHOTO_SOURCE = "Meeting Assistant - Texto do Ano"
MEDIA_SOURCE = "Meeting Assistant - JWL"


def ensure_source(client, scene: str, name: str, kind: str, settings: dict) -> int:
    inputs = client.send("GetInputList", raw=True)["inputs"]
    existing = next((item for item in inputs if item["inputName"] == name), None)
    if existing and existing["inputKind"] != kind:
        raise ValueError(f"A fonte '{name}' já existe com outro tipo. Nenhuma substituição foi feita.")
    scenes = client.send("GetSceneList", raw=True)["scenes"]
    if not any(item["sceneName"] == scene for item in scenes):
        client.send("CreateScene", {"sceneName": scene}, raw=True)
    if existing:
        if settings:
            client.send(
                "SetInputSettings",
                {
                    "inputName": name,
                    "inputSettings": settings,
                    "overlay": True,
                },
                raw=True,
            )
    else:
        client.send(
            "CreateInput",
            {
                "sceneName": scene,
                "inputName": name,
                "inputKind": kind,
                "inputSettings": settings,
                "sceneItemEnabled": False,
            },
            raw=True,
        )
    items = client.send("GetSceneItemList", {"sceneName": scene}, raw=True)["sceneItems"]
    item = next((item for item in items if item["sourceName"] == name), None)
    if item:
        return item["sceneItemId"]
    return client.send(
        "CreateSceneItem",
        {
            "sceneName": scene,
            "sourceName": name,
            "sceneItemEnabled": False,
        },
        raw=True,
    )["sceneItemId"]


def fit_and_enable(client, scene: str, item_id: int) -> None:
    video = client.send("GetVideoSettings", raw=True)
    client.send(
        "SetSceneItemTransform",
        {
            "sceneName": scene,
            "sceneItemId": item_id,
            "sceneItemTransform": {
                "positionX": 0.0,
                "positionY": 0.0,
                "rotation": 0.0,
                "alignment": 5,
                "cropLeft": 0,
                "cropTop": 0,
                "cropRight": 0,
                "cropBottom": 0,
                "boundsType": "OBS_BOUNDS_SCALE_INNER",
                "boundsAlignment": 0,
                "boundsWidth": float(video["baseWidth"]),
                "boundsHeight": float(video["baseHeight"]),
            },
        },
        raw=True,
    )
    items = client.send("GetSceneItemList", {"sceneName": scene}, raw=True)["sceneItems"]
    client.send(
        "SetSceneItemIndex",
        {
            "sceneName": scene,
            "sceneItemId": item_id,
            "sceneItemIndex": len(items) - 1,
        },
        raw=True,
    )
    client.send(
        "SetSceneItemEnabled",
        {
            "sceneName": scene,
            "sceneItemId": item_id,
            "sceneItemEnabled": True,
        },
        raw=True,
    )


def apply_yeartext(client, photo: dict, scene: str) -> None:
    path = Path(photo["path"])
    if not path.is_file():
        raise ValueError("A foto salva não está disponível neste computador.")
    item_id = ensure_source(client, scene, PHOTO_SOURCE, "image_source", {"file": str(path)})
    applied = client.send("GetInputSettings", {"inputName": PHOTO_SOURCE}, raw=True)["inputSettings"]
    if applied.get("file") != str(path):
        raise ValueError("OBS não confirmou o caminho da foto.")
    fit_and_enable(client, scene, item_id)


def select_exact_window(items: list[dict], selectors: list[str]) -> str:
    available = [item["itemValue"] for item in items if item.get("itemEnabled", True)]
    for selector in selectors:
        if selector not in available:
            continue
        title = selector.split(":", 1)[0].casefold()
        # OBS title matching cannot distinguish two windows with the same title.
        if sum(value.split(":", 1)[0].casefold() == title for value in available) == 1:
            return selector
    raise ValueError("OBS não identificou uma janela JWL secundária única. Não foi usada captura de monitor.")


def prepare_media(client, scene: str, selectors: list[str]) -> str:
    if not selectors:
        raise ValueError("A identidade da janela secundária JWL não está disponível.")
    item_id = ensure_source(client, scene, MEDIA_SOURCE, "window_capture", {})
    items = client.send(
        "GetInputPropertiesListPropertyItems",
        {
            "inputName": MEDIA_SOURCE,
            "propertyName": "window",
        },
        raw=True,
    )["propertyItems"]
    selector = select_exact_window(items, selectors)
    client.send(
        "SetInputSettings",
        {
            "inputName": MEDIA_SOURCE,
            "inputSettings": {
                "window": selector,
                "priority": 0,
                "method": 2,
                "cursor": False,
                "client_area": True,
                "capture_audio": False,
            },
            "overlay": True,
        },
        raw=True,
    )
    applied = client.send("GetInputSettings", {"inputName": MEDIA_SOURCE}, raw=True)["inputSettings"]
    if applied.get("window") != selector:
        raise ValueError("OBS não confirmou o vínculo da janela JWL.")
    client.send("SetInputMute", {"inputName": MEDIA_SOURCE, "inputMuted": True}, raw=True)
    fit_and_enable(client, scene, item_id)
    return selector


def virtual_camera_step(client) -> bool:
    if client.send("GetVirtualCamStatus", raw=True).get("outputActive"):
        return True
    client.send("StartVirtualCam", raw=True)
    return bool(client.send("GetVirtualCamStatus", raw=True).get("outputActive"))


def inspect_visual_sources(client, background: str, media: str) -> str:
    inputs = {item["inputName"]: item for item in client.send("GetInputList", raw=True)["inputs"]}
    scenes = {item["sceneName"] for item in client.send("GetSceneList", raw=True)["scenes"]}
    lines = []
    for scene, name, kind in (
        (background, PHOTO_SOURCE, "image_source"),
        (media, MEDIA_SOURCE, "window_capture"),
    ):
        if scene not in scenes:
            lines.append(f"{scene}: cena ausente.")
            continue
        items = client.send("GetSceneItemList", {"sceneName": scene}, raw=True)["sceneItems"]
        item = next((item for item in items if item["sourceName"] == name), None)
        if not item or not item.get("sceneItemEnabled") or inputs.get(name, {}).get("inputKind") != kind:
            lines.append(f"{scene}: fonte gerenciada ausente, desativada ou incompatível.")
            continue
        values = client.send("GetInputSettings", {"inputName": name}, raw=True)["inputSettings"]
        if kind == "image_source":
            ok = bool(values.get("file")) and Path(values["file"]).is_file()
            lines.append(f"{scene}: " + ("arquivo encontrado." if ok else "arquivo ausente."))
        else:
            options = client.send(
                "GetInputPropertiesListPropertyItems",
                {
                    "inputName": name,
                    "propertyName": "window",
                },
                raw=True,
            )["propertyItems"]
            ok = any(o.get("itemEnabled", True) and o["itemValue"] == values.get("window") for o in options)
            lines.append(f"{scene}: " + ("janela cadastrada disponível." if ok else "janela indisponível."))
    active = client.send("GetVirtualCamStatus", raw=True).get("outputActive", False)
    lines.append("Câmera virtual: " + ("ativa." if active else "parada."))
    lines.append("Verificação de configuração; confira o conteúdo visual no OBS antes da reunião.")
    return "\n".join(lines)
