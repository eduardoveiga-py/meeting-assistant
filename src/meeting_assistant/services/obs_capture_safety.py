"""Isolate old monitor captures without deleting an operator's sources.

Disable the item in the managed scene, not a shared scene/group's children.
"""


def call(client, request, **data):
    return client.send(request, data or None, raw=True)


def display_capture_items(client, scene):
    kinds = {i["inputName"]: i["inputKind"] for i in call(client, "GetInputList")["inputs"]}
    scenes = {s["sceneName"] for s in call(client, "GetSceneList")["scenes"]}
    if "monitor_capture" not in kinds.values():
        return []

    def contains(row, visited):
        name = row["sourceName"]
        if kinds.get(name) == "monitor_capture":
            return True
        if name in visited:
            return False
        if row.get("isGroup") or name in scenes:
            request = "GetGroupSceneItemList" if row.get("isGroup") else "GetSceneItemList"
            children = call(client, request, sceneName=name)["sceneItems"]
            return any(contains(item, visited | {name}) for item in children if item.get("sceneItemEnabled"))
        return False

    return [
        row
        for row in call(client, "GetSceneItemList", sceneName=scene)["sceneItems"]
        if row.get("sceneItemEnabled") and contains(row, {scene})
    ]


def disable_managed_display_captures(client, scenes):
    existing = {s["sceneName"] for s in call(client, "GetSceneList")["scenes"]}
    disabled = []
    for scene in dict.fromkeys(scenes):
        if scene not in existing:
            continue
        for row in display_capture_items(client, scene):
            call(
                client,
                "SetSceneItemEnabled",
                sceneName=scene,
                sceneItemId=row["sceneItemId"],
                sceneItemEnabled=False,
            )
            actual = call(client, "GetSceneItemList", sceneName=scene)["sceneItems"]
            if any(i["sceneItemId"] == row["sceneItemId"] and i.get("sceneItemEnabled") for i in actual):
                raise ValueError("OBS não confirmou a desativação da captura de monitor.")
            disabled.append(f"{scene}: {row['sourceName']}")
    return disabled


def assert_safe_media(client, scene):
    from meeting_assistant.services.obs_hall_setup import MEDIA_SOURCE, select_exact_window
    import json
    from pathlib import Path
    
    simulation = False
    try:
        settings_path = Path.home() / ".meeting-assistant" / "settings.json"
        if settings_path.exists():
            simulation = json.loads(settings_path.read_text("utf-8")).get("simulation_enabled", False)
    except Exception:
        pass

    if display_capture_items(client, scene):
        if not simulation:
            raise ValueError("Captura de monitor ativa em Mídias. Prepare a fonte JWL em Ajustes antes de usar.")
            
    rows = call(client, "GetSceneItemList", sceneName=scene)["sceneItems"]
    if not any(i["sourceName"] == MEDIA_SOURCE and i.get("sceneItemEnabled") for i in rows):
        if not simulation:
            raise ValueError("Fonte JWL secundária não preparada. Use Ajustes → Texto do Ano e fontes OBS.")
            
    if simulation:
        return
        
    values = call(client, "GetInputSettings", inputName=MEDIA_SOURCE)["inputSettings"]
    options = call(
        client, "GetInputPropertiesListPropertyItems", inputName=MEDIA_SOURCE, propertyName="window"
    )["propertyItems"]
    select_exact_window(options, [values.get("window", "")])
