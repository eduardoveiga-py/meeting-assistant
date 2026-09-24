"""Explicit, isolated OBS audio provisioning; never changes Program or windows.

The monitoring device and Zoom devices require operator confirmation. OBS owns
persistence. Discovery/preparation mutes our sources; activation is never automatic.
"""

from obsws_python.error import OBSSDKRequestError

BUS = "Meeting Assistant - Áudio Zoom"
MIC = "Meeting Assistant - Mesa"
APPS = {"JW Library": "jwlibrary.exe", "VLC": "vlc.exe", "Chrome": "chrome.exe", "Edge": "msedge.exe"}
MIC_KIND = "wasapi_input_capture"
APP_KIND = "wasapi_process_output_capture"
NONE = "OBS_MONITORING_TYPE_NONE"
MONITOR = "OBS_MONITORING_TYPE_MONITOR_ONLY"
SOURCES = {MIC: MIC_KIND, **{f"Meeting Assistant - Áudio {label}": APP_KIND for label in APPS}}


def app_name(label):
    return f"Meeting Assistant - Áudio {label}"


def call(client, request, **data):
    return client.send(request, data, raw=True)


def inputs(client):
    return {x["inputName"]: x for x in call(client, "GetInputList")["inputs"]}


def check_kinds(rows):
    for name, kind in SOURCES.items():
        if name in rows and rows[name]["inputKind"] != kind:
            raise ValueError(f"Nome reservado usado por outra fonte: {name}. Renomeie-a no OBS.")


def mute_managed(client):
    """Try every source even if one request fails; never report unverified silence."""
    rows = inputs(client)
    failed = []
    for name, kind in SOURCES.items():
        if name not in rows or rows[name]["inputKind"] != kind:
            continue
        try:
            call(client, "SetInputMute", inputName=name, inputMuted=True)
            call(client, "SetInputAudioMonitorType", inputName=name, monitorType=NONE)
            if not call(client, "GetInputMute", inputName=name)["inputMuted"]:
                failed.append(name)
        except Exception:
            failed.append(name)
    if failed:
        raise ValueError("Silêncio não confirmado. Silencie o microfone no Zoom e confira o OBS.")
    return {
        "message": "Fontes de áudio do app silenciadas. Para voltar à ligação antiga, "
        "selecione a entrada física da mesa no microfone do Zoom."
    }


def items(client, scene):
    return call(client, "GetSceneItemList", sceneName=scene)["sceneItems"]


def set_item(client, scene, item_id, enabled):
    call(client, "SetSceneItemEnabled", sceneName=scene, sceneItemId=item_id, sceneItemEnabled=enabled)


def prepare(client):
    kinds = call(client, "GetInputKindList")["inputKinds"]
    if MIC_KIND not in kinds or APP_KIND not in kinds:
        raise ValueError(
            "OBS/Windows sem captura de áudio por aplicativo. Requer OBS 28+ e Windows 10 2004+."
        )
    rows = inputs(client)
    check_kinds(rows)
    scenes = {s["sceneName"] for s in call(client, "GetSceneList")["scenes"]}
    if BUS in rows:
        raise ValueError("O nome da cena de áudio já está em uso por uma fonte.")
    if BUS in scenes:
        if any(x["sourceName"] not in SOURCES for x in items(client, BUS)):
            raise ValueError("A cena de áudio contém fontes externas. Revise antes de preparar.")
    else:
        call(client, "CreateScene", sceneName=BUS)
    mute_managed(client)
    for name, kind in SOURCES.items():
        if name not in rows:
            call(
                client,
                "CreateInput",
                sceneName=BUS,
                inputName=name,
                inputKind=kind,
                inputSettings={"device_id": "__unconfigured__"} if name == MIC else {"window": ""},
                sceneItemEnabled=False,
            )
            call(client, "SetInputMute", inputName=name, inputMuted=True)
            call(client, "SetInputAudioMonitorType", inputName=name, monitorType=NONE)
        if not any(x["sourceName"] == name for x in items(client, BUS)):
            call(client, "CreateSceneItem", sceneName=BUS, sourceName=name, sceneItemEnabled=False)
    return discover(client)


def choices(client, name, prop):
    rows = call(client, "GetInputPropertiesListPropertyItems", inputName=name, propertyName=prop)[
        "propertyItems"
    ]
    return [x for x in rows if x.get("itemEnabled", True) and isinstance(x.get("itemValue"), str)]


def physical_choices(client):
    # Never use the default device: installing a cable may change it silently.
    return [
        x
        for x in choices(client, MIC, "device_id")
        if x["itemValue"] not in ("", "default")
        and not any(t in x["itemName"].casefold() for t in ("cable", "voicemeeter", "virtual"))
    ]


def application_choices(client, label):
    return [
        x
        for x in choices(client, app_name(label), "window")
        if x["itemValue"].rsplit(":", 1)[-1].casefold() == APPS[label]
    ]


def discover(client):
    return {
        "message": "Preparado, envio silenciado. Selecione as fontes e confira o roteamento abaixo.",
        "microphones": physical_choices(client),
        "applications": {label: application_choices(client, label) for label in APPS},
        "selected": {
            name: call(client, "GetInputSettings", inputName=name)["inputSettings"] for name in SOURCES
        },
    }


def validate_selection(client, data):
    if data.get("routing_confirmed") is not True:
        raise ValueError("Confirme CABLE Input no OBS, CABLE Output no Zoom e o retorno separado da mesa.")
    mic = data.get("microphone", "")
    if mic not in {x["itemValue"] for x in physical_choices(client)}:
        raise ValueError("Selecione a entrada física da mesa conectada; atualize as listas se necessário.")
    selected = {MIC: {"device_id": mic}}
    for label, value in data.get("applications", {}).items():
        if label not in APPS:
            raise ValueError("Aplicativo não permitido na mistura.")
        if not value:
            continue
        if value not in {x["itemValue"] for x in application_choices(client, label)}:
            raise ValueError(f"{label} não está disponível. Abra o aplicativo e atualize as listas.")
        selected[app_name(label)] = {"window": value, "priority": 2}
    return selected


def activate(client, data):
    rows = inputs(client)
    check_kinds(rows)
    if not all(name in rows for name in SOURCES):
        raise ValueError("Prepare as fontes antes de ativar o envio.")
    selected = validate_selection(client, data)
    scenes = tuple(dict.fromkeys(data.get("scenes", [])))
    existing = {s["sceneName"] for s in call(client, "GetSceneList")["scenes"]}
    if len(scenes) != 3 or BUS in scenes or not set(scenes).issubset(existing):
        raise ValueError("Configure as três cenas distintas de Texto do Ano, Palco e Mídias antes de ativar.")
    bus_items = items(client, BUS)
    if {x["sourceName"] for x in bus_items} != set(SOURCES) or len(bus_items) != len(SOURCES):
        raise ValueError("A cena de áudio foi modificada. Revise as fontes antes de ativar.")
    # Monitoring is global. Other monitored sources could feed Zoom back into itself.
    for name in rows:
        if name in SOURCES:
            continue
        try:
            monitor = call(client, "GetInputAudioMonitorType", inputName=name)["monitorType"]
        except OBSSDKRequestError as exc:
            if exc.code == 604:  # OBS: this input does not support audio
                continue
            raise
        if monitor != NONE:
            raise ValueError(f'Desative o monitoramento da fonte "{name}" no OBS antes de ativar.')
    mute_managed(client)
    try:
        for item in bus_items:
            set_item(client, BUS, item["sceneItemId"], item["sourceName"] in selected)
        for name, settings in selected.items():
            call(client, "SetInputSettings", inputName=name, inputSettings=settings, overlay=True)
            actual = call(client, "GetInputSettings", inputName=name)["inputSettings"]
            if any(actual.get(k) != v for k, v in settings.items()):
                raise ValueError("OBS não confirmou as fontes selecionadas.")
        for scene in scenes:
            matches = [x for x in items(client, scene) if x["sourceName"] == BUS]
            if len(matches) > 1:
                raise ValueError("Cena de áudio duplicada. Remova a duplicata no OBS.")
            if matches:
                set_item(client, scene, matches[0]["sceneItemId"], True)
            else:
                call(client, "CreateSceneItem", sceneName=scene, sourceName=BUS, sceneItemEnabled=True)
        for name in selected:
            call(client, "SetInputAudioMonitorType", inputName=name, monitorType=MONITOR)
            call(client, "SetInputMute", inputName=name, inputMuted=False)
            if (
                call(client, "GetInputMute", inputName=name)["inputMuted"]
                or call(client, "GetInputAudioMonitorType", inputName=name)["monitorType"] != MONITOR
            ):
                raise ValueError("OBS não confirmou a ativação do áudio.")
    except Exception:
        mute_managed(client)
        raise
    return {
        "message": "OBS confirmou as fontes e o monitoramento. Faça o teste de escuta remota no Zoom. "
        "O OBS mantém essa configuração ao fechar o app."
    }


def run_audio_task(client, action, data):
    if action == "prepare":
        try:
            return prepare(client)
        except Exception:
            mute_managed(client)
            raise
    if action == "activate":
        return activate(client, data)
    if action == "mute":
        return mute_managed(client)
    raise ValueError("Operação de áudio desconhecida.")

