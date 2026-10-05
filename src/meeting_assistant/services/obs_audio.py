"""Explicit, isolated OBS audio provisioning; never changes Program or windows.

The monitoring device and Zoom/WhatsApp devices require operator confirmation.
OBS owns persistence. Discovery preserves live audio; preparation mutes our
sources and activation is never automatic. The shared profile sends the same
local mix to both calls. Adding Zoom participants to WhatsApp uses a separate
virtual cable. Physical speakers are handled by the Windows audio-session guard.
"""

from obsws_python.error import OBSSDKRequestError

from meeting_assistant.services.audio_routes import (
    configure_filters,
    enable_extra_route,
    silence_extra_routes,
    validate_route,
    virtual_outputs,
)
from meeting_assistant.services.obs_audio_gain import apply_gains, gain_state
from meeting_assistant.services.obs_monitor_device import monitoring_device

BUS = "Meeting Assistant - Áudio"
MIC = "Meeting Assistant - Mesa"
APPS = {
    "JW Library": "jwlibrary.exe",
    "Zoom": "zoom.exe",
    "VLC": "vlc.exe",
    "Chrome": "chrome.exe",
    "Edge": "msedge.exe",
}
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
        # A filter failure must not prevent the independent mute/monitor
        # commands. Attempt each path before reporting unverified silence.
        try:
            silence_extra_routes(client, name)
        except Exception:
            failed.append(name)
        try:
            call(client, "SetInputMute", inputName=name, inputMuted=True)
            if not call(client, "GetInputMute", inputName=name)["inputMuted"]:
                failed.append(name)
        except Exception:
            failed.append(name)
        try:
            call(client, "SetInputAudioMonitorType", inputName=name, monitorType=NONE)
            if call(client, "GetInputAudioMonitorType", inputName=name)["monitorType"] != NONE:
                failed.append(name)
        except Exception:
            failed.append(name)
    if failed:
        raise ValueError(
            "Silêncio do mix não confirmado. Silencie o microfone no Zoom/WhatsApp "
            "e confira o monitoramento do OBS."
        )
    return {
        "message": "Fontes de áudio do app silenciadas. Para voltar à ligação antiga, "
        "selecione a entrada física da mesa no microfone do Zoom e do WhatsApp."
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
            try:
                call(
                    client,
                    "CreateInput",
                    sceneName=BUS,
                    inputName=name,
                    inputKind=kind,
                    inputSettings={"device_id": "__unconfigured__"} if name == MIC else {"window": ""},
                    sceneItemEnabled=False,
                )
            except OBSSDKRequestError as exc:
                if exc.code == 601:
                    raise ValueError(
                        f"Já existe cena ou grupo chamado '{name}' no OBS. Exclua para continuar."
                    ) from exc
                raise
            call(client, "SetInputMute", inputName=name, inputMuted=True)
            call(client, "SetInputAudioMonitorType", inputName=name, monitorType=NONE)
        if not any(x["sourceName"] == name for x in items(client, BUS)):
            call(client, "CreateSceneItem", sceneName=BUS, sourceName=name, sceneItemEnabled=False)
    result = discover(client)
    result["message"] = "Fontes preparadas. Envio silenciado até clicar em Ativar envio."
    return result


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
    generic = {"itemName": f"Qualquer janela ({label})", "itemValue": f"Qualquer:Qualquer:{APPS[label]}"}
    return [generic] + [
        x
        for x in choices(client, app_name(label), "window")
        if x["itemValue"].rsplit(":", 1)[-1].casefold() == APPS[label]
    ]


def discover(client):
    """Read existing sources and devices; opening/refreshing the UI never mutes audio."""
    rows = inputs(client)
    check_kinds(rows)
    present = {name for name in SOURCES if name in rows}
    selected = {
        name: call(client, "GetInputSettings", inputName=name)["inputSettings"]
        if name in present else {} for name in SOURCES
    }
    scenes = {s["sceneName"] for s in call(client, "GetSceneList")["scenes"]}
    if BUS in scenes:
        enabled = {r["sourceName"] for r in items(client, BUS) if r["sceneItemEnabled"]}
        for label in APPS:
            name = app_name(label)
            if name not in enabled:
                selected[name] = selected[name] | {"window": ""}
    states = {name: gain_state(client, name) for name in present}
    destinations = {
        f["filterSettings"].get("device", "")
        for name in present
        for f in call(client, "GetSourceFilterList", sourceName=name)["filters"]
        if f["filterName"] == "Meeting Assistant - WhatsApp" and f["filterKind"] == "audio_monitor"
    } - {""}
    monitor, monitor_error = {}, ""
    try:
        monitor = monitoring_device(client)
    except ValueError as exc:
        monitor_error = str(exc)
    return {
        "message": "Configuração lida do OBS. O envio atual foi preservado."
        if len(present) == len(SOURCES) else "Clique em Criar fontes para preparar o áudio no OBS.",
        "microphones": physical_choices(client) if MIC in present else [],
        "applications": {
            label: application_choices(client, label) if app_name(label) in present else []
            for label in APPS
        },
        "outputs": virtual_outputs(),
        "selected": selected,
        "source_states": states,
        "missing_sources": [name for name in SOURCES if name not in present],
        "needs_prepare": len(present) != len(SOURCES) or BUS not in scenes,
        "monitor": monitor,
        "monitor_error": monitor_error,
        "whatsapp_device": next(iter(destinations)) if len(destinations) == 1 else "",
    }


def validate_selection(client, data):
    if data.get("routing_confirmed") is not True:
        raise ValueError("Confirme os microfones virtuais do perfil escolhido e o retorno separado da mesa.")
    mic = data.get("microphone", "")
    if mic not in {x["itemValue"] for x in physical_choices(client)}:
        raise ValueError("Selecione a entrada física da mesa conectada; atualize as listas se necessário.")
    selected = {MIC: {"device_id": mic}}
    for label, value in data.get("applications", {}).items():
        if label not in APPS:
            raise ValueError("Aplicativo não permitido na mistura.")
        if not value:
            continue
        choices_values = {x["itemValue"] for x in application_choices(client, label)}
        if value not in choices_values and value.rsplit(":", 1)[-1].casefold() != APPS[label]:
            raise ValueError(f"{label} não está disponível. Abra o aplicativo e atualize as listas.")
        selected[app_name(label)] = {"window": value, "priority": 2}
    return selected


def activate(client, data):
    rows = inputs(client)
    check_kinds(rows)
    if not all(name in rows for name in SOURCES):
        raise ValueError("Prepare as fontes antes de ativar o envio.")
    mute_managed(client)
    selected = validate_selection(client, data)
    profile, whatsapp_device = validate_route(client, data)
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
            print(f"ERROR on global monitor check for {name}: {repr(exc)}")
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
        gains = data.get("gains_db", {})
        extra = data.get("extra_filters", {})
        for name in selected:
            configure_filters(
                client, name, gains.get(name, 0), whatsapp_device if profile == "whatsapp_zoom" else "", extra.get(name, {})
            )
        for name in selected:
            tracks = {str(i): False for i in range(1, 7)}
            tracks["6"] = True  # OBS 30+ warns if no tracks are selected; assign to unused track 6.
            call(
                client,
                "SetInputAudioTracks",
                inputName=name,
                inputAudioTracks=tracks,
            )
            actual_tracks = call(client, "GetInputAudioTracks", inputName=name)["inputAudioTracks"]
            if any(actual_tracks[str(i)] for i in range(1, 6)):
                raise ValueError("OBS não confirmou o isolamento do áudio das faixas Program principais.")

        for name in selected:
            monitor = NONE if name == app_name("Zoom") else MONITOR
            call(client, "SetInputAudioMonitorType", inputName=name, monitorType=monitor)
            if profile == "whatsapp_zoom":
                enable_extra_route(client, name)
            call(client, "SetInputMute", inputName=name, inputMuted=False)
            if (
                call(client, "GetInputMute", inputName=name)["inputMuted"]
                or call(client, "GetInputAudioMonitorType", inputName=name)["monitorType"] != monitor
            ):
                raise ValueError("OBS não confirmou a ativação do áudio.")
    except Exception:
        mute_managed(client)
        raise
    microphones = (
        "a saída do cabo de monitoramento do OBS no Zoom e no WhatsApp"
        if profile == "shared"
        else "a saída do primeiro cabo no Zoom e a saída de gravação do segundo cabo no WhatsApp"
    )
    return {
        "message": f"OBS confirmou o envio. Use {microphones}. "
        "Confira volumes durante uma chamada de teste.",
        "profile": profile,
        "whatsapp_device": whatsapp_device,
        "gains_db": gains,
    }


def run_audio_task(client, action, data):
    if action == "inspect":
        return discover(client)
    if action == "gains":
        return apply_gains(client, data.get("gains_db"), SOURCES)
    if action == "prepare":
        try:
            return prepare(client)
        except Exception:
            mute_managed(client)
            raise
    if action == "activate":
        return activate(client, data)
    if action == "ducking_start":
        call(client, "SetInputMute", inputName=MIC, inputMuted=True)
        return {"ok": True}
    if action == "ducking_end":
        call(client, "SetInputMute", inputName=MIC, inputMuted=False)
        return {"ok": True}
    if action == "mute":
        return mute_managed(client)
    raise ValueError("Operação de áudio desconhecida.")
