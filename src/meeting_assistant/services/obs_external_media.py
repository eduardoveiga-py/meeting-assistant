"""Dedicated window capture for external presentations. JWL source is untouched."""

from meeting_assistant.services.obs_hall_setup import ensure_source, fit_and_enable, select_exact_window

SCENE = "Meeting Assistant - Mídia Externa"
SOURCE = "Meeting Assistant - Player"


def call(client, request, **data):
    return client.send(request, data or None, raw=True)


def prepare_external(client, selector, audio_bus="Meeting Assistant - Áudio"):
    prior = call(client, "GetCurrentProgramScene")["currentProgramSceneName"]
    item_id = ensure_source(client, SCENE, SOURCE, "window_capture", {})
    options = call(client, "GetInputPropertiesListPropertyItems", inputName=SOURCE,
                   propertyName="window")["propertyItems"]
    exact = select_exact_window(options, [selector])
    settings = {"window": exact, "priority": 0, "method": 2, "cursor": False,
                "client_area": True, "capture_audio": False}
    call(client, "SetInputSettings", inputName=SOURCE, inputSettings=settings, overlay=True)
    actual = call(client, "GetInputSettings", inputName=SOURCE)["inputSettings"]
    if any(actual.get(k) != v for k, v in settings.items()):
        raise ValueError("OBS não confirmou a janela externa selecionada.")
    call(client, "SetInputMute", inputName=SOURCE, inputMuted=True)
    fit_and_enable(client, SCENE, item_id)
    scenes = {s["sceneName"] for s in call(client, "GetSceneList")["scenes"]}
    if audio_bus in scenes:
        rows = call(client, "GetSceneItemList", sceneName=SCENE)["sceneItems"]
        if not any(i["sourceName"] == audio_bus for i in rows):
            call(client, "CreateSceneItem", sceneName=SCENE, sourceName=audio_bus, sceneItemEnabled=True)
    # Preparing cannot change Program. It is committed only after placement.
    return {"prior": prior, "scene": SCENE, "selector": exact}


def show_external(client, prior):
    if call(client, "GetCurrentProgramScene")["currentProgramSceneName"] != prior:
        raise ValueError("Operador mudou Program durante a preparação; apresentação cancelada.")
    call(client, "SetCurrentProgramScene", sceneName=SCENE)
    if call(client, "GetCurrentProgramScene")["currentProgramSceneName"] != SCENE:
        restore_external(client, prior)
        raise ValueError("OBS não confirmou Program da mídia externa.")
    return {"message": "Mídia externa confirmada no OBS e na tela do salão."}


def restore_external(client, prior):
    if call(client, "GetCurrentProgramScene")["currentProgramSceneName"] == SCENE and prior:
        call(client, "SetCurrentProgramScene", sceneName=prior)
        if call(client, "GetCurrentProgramScene")["currentProgramSceneName"] != prior:
            raise ValueError("OBS não confirmou a cena anterior.")
    return {"message": "Program anterior restaurado quando ainda controlado pela mídia externa."}
