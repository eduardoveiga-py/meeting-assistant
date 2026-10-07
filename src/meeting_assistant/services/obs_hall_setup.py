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
        from obsws_python.error import OBSSDKRequestError
        try:
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
        except OBSSDKRequestError as exc:
            if exc.code == 601:
                raise ValueError(
                    f"A fonte '{name}' já existe como cena ou grupo no OBS. Exclua para continuar."
                ) from exc
            raise
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
        matches = [v for v in available if v.split(":", 1)[0].casefold() == title]
        # OBS title matching cannot distinguish two windows with the same title.
        if len(matches) == 1:
            return selector
    raise ValueError("OBS não identificou uma janela JWL secundária única. Não foi usada captura de monitor.")


def prepare_media(client, scene: str, target: dict, stop_event=None) -> dict:
    """Warm/verify the exact HWND source before migrating managed scene items."""
    import threading

    from meeting_assistant.services.obs_jwl_capture import KIND, SOURCE, bind, wait_for_capture

    if not isinstance(target, dict) or not target.get("hwnd") or not target.get("session"):
        raise ValueError("A identidade da janela secundária JWL não está disponível.")
    kinds = client.send("GetInputKindList", raw=True).get("inputKinds", [])
    if KIND not in kinds:
        raise ValueError(
            "Plugin de captura JWL ausente no OBS. Feche OBS e execute scripts/run.ps1 "
            "para baixar a DLL; depois abra OBS novamente. Requer OBS 31.0.3 ou posterior."
        )
    item_id = ensure_source(client, scene, SOURCE, KIND, {})
    bind(client, target)
    status = wait_for_capture(client, target, stop_event or threading.Event())
    from meeting_assistant.services.obs_capture_safety import disable_managed_display_captures

    disable_managed_display_captures(client, [scene])
    # Preserve the old input and all uses outside this scene. No source removal,
    # replacement by type, or mutation of a shared scene/group's children.
    rows = client.send("GetSceneItemList", {"sceneName": scene}, raw=True)["sceneItems"]
    for row in rows:
        if row["sourceName"] == MEDIA_SOURCE and row.get("sceneItemEnabled"):
            client.send("SetSceneItemEnabled", {"sceneName": scene, "sceneItemId": row["sceneItemId"],
                                               "sceneItemEnabled": False}, raw=True)
    fit_and_enable(client, scene, item_id)
    from meeting_assistant.services.obs_capture_safety import assert_safe_media

    try:
        assert_safe_media(client, scene)
    except ValueError:
        client.send("SetSceneItemEnabled", {"sceneName": scene, "sceneItemId": item_id,
                                           "sceneItemEnabled": False}, raw=True)
        raise
    return status


def virtual_camera_step(client) -> bool:
    if client.send("GetVirtualCamStatus", raw=True).get("outputActive"):
        return True
    client.send("StartVirtualCam", raw=True)
    return bool(client.send("GetVirtualCamStatus", raw=True).get("outputActive"))


def inspect_visual_sources(client, background: str, media: str) -> str:
    from meeting_assistant.services.obs_jwl_capture import KIND, SOURCE, confirmed_status

    inputs = {item["inputName"]: item for item in client.send("GetInputList", raw=True)["inputs"]}
    scenes = {item["sceneName"] for item in client.send("GetSceneList", raw=True)["scenes"]}
    lines = []
    for scene, name, kind in (
        (background, PHOTO_SOURCE, "image_source"),
        (media, SOURCE, KIND),
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
            try:
                from meeting_assistant.services.obs_capture_safety import assert_safe_media

                assert_safe_media(client, scene)
                status = confirmed_status(client)
                lines.append(f"{scene}: captura nativa ativa • HWND {status['hwnd']} • "
                             f"{status['width']}×{status['height']}.")
            except ValueError as exc:
                lines.append(f"{scene}: {exc}")
    active = client.send("GetVirtualCamStatus", raw=True).get("outputActive", False)
    lines.append("Câmera virtual: " + ("ativa." if active else "parada."))
    lines.append("Verificação de configuração; confira o conteúdo visual no OBS antes da reunião.")
    return "\n".join(lines)
