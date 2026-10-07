"""Mix-minus contracts and verified OBS filters; no call UI automation here."""

import math
import sys

from meeting_assistant.services.obs_monitor_device import monitoring_device

GAIN = "Meeting Assistant - Ganho"
LIMITER = "Meeting Assistant - Limitador"
WHATSAPP_MONITOR = "Meeting Assistant - WhatsApp"
NOISE_GATE = "Meeting Assistant - Noise Gate"
NOISE_SUPPRESSION = "Meeting Assistant - Redução de Ruído"
DUCKING = "Meeting Assistant - Auto-Ducking"
COMPRESSOR = "Meeting Assistant - Compressor"
LEGACY_FILTERS = {"Gain (WhatsApp)": "gain_filter", "Limiter (WhatsApp)": "limiter_filter"}


def call(client, request, **data):
    return client.send(request, data or None, raw=True)


def virtual_outputs():
    if sys.platform != "win32":
        return []
    import pythoncom
    from pycaw.pycaw import AudioUtilities

    pythoncom.CoInitialize()
    try:
        devices = []
        for device in AudioUtilities.GetAllDevices():
            name = str(device.FriendlyName or "")
            if (
                getattr(device.state, "value", device.state) == 1
                and AudioUtilities.GetEndpointDataFlow(device.id, 1) == 0
                and any(t in name.casefold() for t in ("cable", "virtual", "voicemeeter"))
            ):
                devices.append({"itemName": name, "itemValue": device.id})
        return devices
    finally:
        pythoncom.CoUninitialize()


def validate_route(client, data):
    profile = data.get("profile", "shared")
    if profile not in {"shared", "whatsapp_zoom"}:
        raise ValueError("Perfil de áudio desconhecido.")
    monitor = monitoring_device(client)
    monitor_id, monitor_name = monitor.get("monitorDeviceId", ""), monitor.get("monitorDeviceName", "")
    if monitor_id in {"", "default"} or not any(t in monitor_name.casefold() for t in ("cable", "virtual")):
        raise ValueError("Selecione CABLE Input como dispositivo explícito de monitoramento do OBS.")
    has_zoom = bool(data.get("applications", {}).get("Zoom"))
    destination = data.get("whatsapp_device", "")
    if profile == "shared":
        if has_zoom:
            raise ValueError("Retorno do Zoom não pode entrar no mix enviado ao próprio Zoom.")
    elif destination == monitor_id or destination not in {d["itemValue"] for d in virtual_outputs()}:
        raise ValueError(
            "WhatsApp com retorno Zoom exige uma segunda entrada virtual, diferente do monitoramento OBS."
        )
    gains = data.get("gains_db", {})
    if not isinstance(gains, dict):
        raise ValueError("Ganho de áudio inválido.")
    for gain in gains.values():
        if type(gain) not in (int, float) or not math.isfinite(gain) or not -30 <= gain <= 18:
            raise ValueError("Use ganho entre -30 e 18 dB e confira os medidores.")
    return profile, destination


def ensure_filter(client, source, name, kind, settings, *, enabled=True):
    filters = call(client, "GetSourceFilterList", sourceName=source)["filters"]
    existing = next((f for f in filters if f["filterName"] == name), None)
    if existing and existing["filterKind"] != kind:
        raise ValueError(f"Filtro reservado incompatível: {name}. Revise no OBS.")
    if existing:
        call(
            client,
            "SetSourceFilterSettings",
            sourceName=source,
            filterName=name,
            filterSettings=settings,
            overlay=True,
        )
    else:
        call(
            client,
            "CreateSourceFilter",
            sourceName=source,
            filterName=name,
            filterKind=kind,
            filterSettings=settings,
        )
    call(client, "SetSourceFilterEnabled", sourceName=source, filterName=name, filterEnabled=enabled)
    applied = call(client, "GetSourceFilter", sourceName=source, filterName=name)
    if applied.get("filterEnabled") is not enabled or any(
        applied.get("filterSettings", {}).get(k) != v for k, v in settings.items()
    ):
        raise ValueError(f"OBS não confirmou o filtro {name}.")


def silence_extra_routes(client, source):
    filters = call(client, "GetSourceFilterList", sourceName=source)["filters"]
    for item in filters:
        if item["filterName"] == WHATSAPP_MONITOR:
            if item["filterKind"] != "audio_monitor":
                raise ValueError("Filtro de envio WhatsApp incompatível.")
            call(
                client,
                "SetSourceFilterEnabled",
                sourceName=source,
                filterName=WHATSAPP_MONITOR,
                filterEnabled=False,
            )
            if call(client, "GetSourceFilter", sourceName=source, filterName=WHATSAPP_MONITOR)[
                "filterEnabled"
            ]:
                raise ValueError("Silêncio do envio WhatsApp não confirmado.")


def configure_filters(client, source, gain, whatsapp_destination="", extra_filters=None):
    extra_filters = extra_filters or {}
    for item in call(client, "GetSourceFilterList", sourceName=source)["filters"]:
        if LEGACY_FILTERS.get(item["filterName"]) == item["filterKind"]:
            call(
                client,
                "SetSourceFilterEnabled",
                sourceName=source,
                filterName=item["filterName"],
                filterEnabled=False,
            )
            if call(client, "GetSourceFilter", sourceName=source, filterName=item["filterName"])[
                "filterEnabled"
            ]:
                raise ValueError("OBS não confirmou a migração do ganho antigo.")
    ensure_filter(client, source, GAIN, "gain_filter", {"db": float(gain)})
    ensure_filter(client, source, LIMITER, "limiter_filter", {"threshold": -3.0, "release_time": 60})
    
    ng_enabled = extra_filters.get("noise_gate", False)
    ensure_filter(client, source, NOISE_GATE, "noise_gate_filter", {
        "open_threshold": -32.0,
        "close_threshold": -38.0,
        "attack_time": 25,
        "hold_time": 200,
        "release_time": 150
    }, enabled=ng_enabled)

    comp_enabled = extra_filters.get("compressor", False)
    ensure_filter(client, source, COMPRESSOR, "compressor_filter", {
        "ratio": 4.0,
        "threshold": -18.0,
        "attack_time": 2,
        "release_time": 100,
        "output_gain": 0.0
    }, enabled=comp_enabled)
    
    if source == "Meeting Assistant - Mesa":
        ducking_enabled = extra_filters.get("auto_ducking", False)
        ensure_filter(client, source, DUCKING, "compressor_filter", {
            "ratio": 32.0,
            "threshold": -35.0,
            "attack_time": 2,
            "release_time": 800,
            "output_gain": 0.0,
            "sidechain_source": "Meeting Assistant - Áudio JW Library"
        }, enabled=ducking_enabled)
    supp_enabled = extra_filters.get("noise_suppression", False)
    ensure_filter(client, source, NOISE_SUPPRESSION, "noise_suppress_filter", {
        "method": "rnnoise"
    }, enabled=supp_enabled)
    if whatsapp_destination:
        # Exeldro Audio Monitor 0.10.1: mute=2 follows parent-source mute.
        # No global Zoom monitoring: this filter writes only to WhatsApp's cable.
        ensure_filter(
            client,
            source,
            WHATSAPP_MONITOR,
            "audio_monitor",
            {
                "device": whatsapp_destination,
                "volume": 100.0,
                "linked": False,
                "mute": 2,
                "delay": 0,
                "mono": False,
                "mute_stop_start": True,
            },
            enabled=False,
        )
    filters = call(client, "GetSourceFilterList", sourceName=source)["filters"]
    # Put gain/limiter after operator filters, with the dedicated monitor last.
    ordered = [f["filterName"] for f in filters if f["filterName"] not in {GAIN, LIMITER, WHATSAPP_MONITOR, NOISE_GATE, COMPRESSOR, NOISE_SUPPRESSION, DUCKING}]  # noqa: E501
    base_ordered = [NOISE_SUPPRESSION, NOISE_GATE, COMPRESSOR]
    if source == "Meeting Assistant - Mesa":
        base_ordered.append(DUCKING)
    base_ordered.extend([GAIN, LIMITER])
    ordered += base_ordered
    if any(f["filterName"] == WHATSAPP_MONITOR for f in filters):
        ordered.append(WHATSAPP_MONITOR)
    for index, name in enumerate(ordered):
        call(client, "SetSourceFilterIndex", sourceName=source, filterName=name, filterIndex=index)
    actual = call(client, "GetSourceFilterList", sourceName=source)["filters"]
    if [f["filterName"] for f in actual] != ordered:
        raise ValueError("OBS não confirmou a ordem dos filtros de áudio.")


def enable_extra_route(client, source):
    call(client, "SetSourceFilterEnabled", sourceName=source, filterName=WHATSAPP_MONITOR, filterEnabled=True)
    if not call(client, "GetSourceFilter", sourceName=source, filterName=WHATSAPP_MONITOR)["filterEnabled"]:
        raise ValueError("Envio separado ao WhatsApp não confirmado.")
