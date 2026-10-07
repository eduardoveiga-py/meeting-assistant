"""Dedicated window capture for external presentations. JWL source is untouched."""

from meeting_assistant.services.obs_capture_safety import display_capture_items
from meeting_assistant.services.obs_hall_setup import ensure_source, fit_and_enable

SCENE = "Meeting Assistant - Mídia Externa"
SOURCE = "Meeting Assistant - Player"


def call(client, request, **data):
    return client.send(request, data or None, raw=True)


def begin_external(client):
    """Read-only preflight before the selected player is moved or restored."""
    prior = call(client, "GetCurrentProgramScene")["currentProgramSceneName"]
    if not prior or prior == SCENE:
        raise ValueError("Selecione Palco no OBS antes de iniciar uma nova mídia externa.")
    inputs = {row["inputName"]: row["inputKind"] for row in call(client, "GetInputList")["inputs"]}
    scenes = {row["sceneName"] for row in call(client, "GetSceneList")["scenes"]}
    if SOURCE in scenes or (SOURCE in inputs and inputs[SOURCE] != "window_capture"):
        raise ValueError(
            "O nome da fonte Player está ocupado por outro tipo no OBS. Nenhuma fonte foi substituída."
        )
    if SCENE in inputs:
        raise ValueError("O nome da cena Mídia Externa está ocupado por uma fonte no OBS.")
    if SCENE in scenes and display_capture_items(client, SCENE):
        raise ValueError(
            "Há captura de monitor ativa na cena Mídia Externa. Desative esse item antes de apresentar."
        )
    return {"prior": prior}


def select_external_window(options, selector):
    """OBS matches titles case-insensitively; never guess among duplicate titles."""
    available = [row["itemValue"] for row in options if row.get("itemEnabled", True)]
    matches = [value for value in available if value.casefold() == selector.casefold()]
    if not matches:
        raise ValueError(
            "OBS não encontrou a janela externa selecionada. "
            "Mantenha o player aberto e tente selecionar novamente."
        )
    title = selector.split(":", 1)[0].casefold()
    if len(matches) != 1 or sum(value.split(":", 1)[0].casefold() == title for value in available) != 1:
        raise ValueError(
            "OBS encontrou mais de uma janela com o mesmo título. "
            "Feche a janela duplicada ou altere seu título "
            "antes de selecionar. Não foi usada captura de monitor."
        )
    return matches[0]


def prepare_external(client, selector, audio_bus="Meeting Assistant - Áudio", *, prior=None):
    current = begin_external(client)["prior"]
    if prior is not None and current != prior:
        raise ValueError("Program mudou durante a preparação; a cena escolhida no OBS foi preservada.")
    prior = current
    item_id = ensure_source(client, SCENE, SOURCE, "window_capture", {})
    options = call(client, "GetInputPropertiesListPropertyItems", inputName=SOURCE,
                   propertyName="window")["propertyItems"]
    exact = select_external_window(options, selector)
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


def show_external(client, prior, selector=None):
    if call(client, "GetCurrentProgramScene")["currentProgramSceneName"] != prior:
        raise ValueError("Operador mudou Program durante a preparação; apresentação cancelada.")
    if selector is not None:
        options = call(client, "GetInputPropertiesListPropertyItems", inputName=SOURCE,
                       propertyName="window")["propertyItems"]
        exact = select_external_window(options, selector)
        settings = call(client, "GetInputSettings", inputName=SOURCE)["inputSettings"]
        if settings.get("window") != exact or settings.get("capture_audio") is not False:
            raise ValueError("A captura externa mudou durante a preparação. A cena anterior foi preservada.")
        if display_capture_items(client, SCENE):
            raise ValueError("Captura de monitor ativa na cena Mídia Externa. Program foi preservado.")
    call(client, "SetCurrentProgramScene", sceneName=SCENE)
    if call(client, "GetCurrentProgramScene")["currentProgramSceneName"] != SCENE:
        restore_external(client, prior)
        raise ValueError("OBS não confirmou Program da mídia externa.")
    return {"message": "Mídia externa selecionada no OBS. Confira a imagem no Salão e no preview."}


def restore_external(client, prior):
    if call(client, "GetCurrentProgramScene")["currentProgramSceneName"] == SCENE and prior:
        call(client, "SetCurrentProgramScene", sceneName=prior)
        if call(client, "GetCurrentProgramScene")["currentProgramSceneName"] != prior:
            raise ValueError("OBS não confirmou a cena anterior.")
    return {"message": "Program anterior restaurado quando ainda controlado pela mídia externa."}
