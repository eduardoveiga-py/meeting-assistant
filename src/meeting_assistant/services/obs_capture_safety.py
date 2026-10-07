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


def assert_safe_media(client, scene, expected_target=None):
    from meeting_assistant.services.obs_jwl_capture import KIND, SOURCE, confirmed_status

    if display_capture_items(client, scene):
        raise ValueError("Captura de monitor ativa em Mídias. Prepare a fonte JWL em Ajustes antes de usar.")

    rows = call(client, "GetSceneItemList", sceneName=scene)["sceneItems"]
    kinds = {i["inputName"]: i["inputKind"] for i in call(client, "GetInputList")["inputs"]}
    if kinds.get(SOURCE) != KIND or not any(
        i["sourceName"] == SOURCE and i.get("sceneItemEnabled") for i in rows
    ):
        raise ValueError("Fonte JWL por HWND não preparada. Use Ajustes → Texto do Ano e fontes OBS.")
    scenes = {s["sceneName"] for s in call(client, "GetSceneList")["scenes"]}

    def unsafe(items, visited):
        for row in items:
            if not row.get("sceneItemEnabled"):
                continue
            name = row["sourceName"]
            kind = kinds.get(name)
            if kind in {"window_capture", "game_capture", "monitor_capture"} or (
                kind == KIND and name != SOURCE
            ):
                return True
            if name in visited:
                continue
            if row.get("isGroup") or name in scenes:
                request = "GetGroupSceneItemList" if row.get("isGroup") else "GetSceneItemList"
                children = call(client, request, sceneName=name)["sceneItems"]
                if unsafe(children, visited | {name}):
                    return True
        return False

    if unsafe(rows, {scene}):
        raise ValueError(
            "Outra captura de janela/jogo permanece ativa em Mídias, inclusive em cena/grupo. "
            "Desative esse item nesta cena para impedir retorno do Zoom. Nenhuma fonte foi apagada."
        )
    confirmed_status(client, expected_target)

