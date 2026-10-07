"""Read and change existing gain filters without touching live audio routes."""

import math

from meeting_assistant.services.audio_routes import GAIN, LIMITER, WHATSAPP_MONITOR


def call(client, request, **data):
    return client.send(request, data, raw=True)


def gain_state(client, source):
    filters = call(client, "GetSourceFilterList", sourceName=source)["filters"]
    try:
        sync_res = call(client, "GetInputAudioSyncOffset", inputName=source)
        sync_offset = sync_res.get("inputAudioSyncOffset", 0)
    except Exception:
        sync_offset = 0

    gain = next((f for f in filters if f["filterName"] == GAIN), None)
    limiter = next((f for f in filters if f["filterName"] == LIMITER), None)
    value = gain.get("filterSettings", {}).get("db") if gain else None
    valid_value = type(value) in (int, float) and math.isfinite(value) and -30 <= value <= 18
    names = [f["filterName"] for f in filters]
    ready = bool(
        gain and limiter and valid_value
        and gain["filterKind"] == "gain_filter" and gain.get("filterEnabled") is True
        and limiter["filterKind"] == "limiter_filter" and limiter.get("filterEnabled") is True
        and names.index(GAIN) < names.index(LIMITER)
        and (WHATSAPP_MONITOR not in names or names.index(LIMITER) < names.index(WHATSAPP_MONITOR))
    )
    return {"gain_db": float(value) if valid_value else None, "gain_ready": ready, "sync_offset_ms": sync_offset}  # noqa: E501


def apply_gains(client, gains, source_kinds, sync_offsets=None):
    sync_offsets = {} if sync_offsets is None else sync_offsets
    if not isinstance(gains, dict) or not gains:
        raise ValueError("Altere o ganho de uma fonte antes de salvar os volumes.")
    for source, value in gains.items():
        if source not in source_kinds:
            raise ValueError("Fonte não gerenciada pelo app. O ganho não foi alterado.")
        if type(value) not in (int, float) or not math.isfinite(value) or not -30 <= value <= 18:
            raise ValueError("Use ganho entre -30 e 18 dB.")
    validate_sync_offsets(sync_offsets, set(gains))
    rows = {r["inputName"]: r for r in call(client, "GetInputList")["inputs"]}
    previous = {}
    previous_syncs = {}
    # Validate the complete request before any change; never create/enable a route here.
    for source in gains:
        if source not in rows or rows[source]["inputKind"] != source_kinds[source]:
            raise ValueError(f"Fonte ausente ou incompatível: {source}. Atualize a lista.")
        state = gain_state(client, source)
        if not state["gain_ready"]:
            raise ValueError(f"Configure o envio de {source} antes de ajustar seu volume.")
        previous[source] = state["gain_db"]
        if source in sync_offsets:
            previous_syncs[source] = call(
                client, "GetInputAudioSyncOffset", inputName=source
            )["inputAudioSyncOffset"]
    attempted = []
    try:
        for source, value in gains.items():
            attempted.append(source)
            if value != previous[source]:
                _set_verified(client, source, value)
            if source in sync_offsets:
                set_sync_verified(client, source, sync_offsets[source])
    except Exception as exc:
        failed = []
        for source in reversed(attempted):
            try:
                if gains[source] != previous[source]:
                    _set_verified(client, source, previous[source])
                if source in sync_offsets:
                    set_sync_verified(client, source, previous_syncs[source])
            except Exception:
                failed.append(source)
        if failed:
            raise ValueError(
                "Volume não confirmado e restauração incompleta. Confira os ganhos no OBS "
                "e atualize a lista. O roteamento não foi alterado."
            ) from exc
        raise ValueError(
            "OBS não confirmou o volume. Ganhos anteriores restaurados; tente novamente."
        ) from exc
    return {
        "message": "OBS confirmou os volumes. O envio e os dispositivos foram preservados.",
        "gains_db": {source: float(value) for source, value in gains.items()},
        "sync_offsets_ms": sync_offsets,
    }


def _set_verified(client, source, value):
    call(
        client, "SetSourceFilterSettings", sourceName=source, filterName=GAIN,
        filterSettings={"db": float(value)}, overlay=True,
    )
    actual = call(client, "GetSourceFilter", sourceName=source, filterName=GAIN)
    if (
        actual.get("filterKind") != "gain_filter" or actual.get("filterEnabled") is not True
        or actual.get("filterSettings", {}).get("db") != float(value)
    ):
        raise ValueError("OBS não confirmou o ganho.")


def validate_sync_offsets(offsets, sources):
    if not isinstance(offsets, dict) or any(
        name not in sources or type(value) is not int or not -950 <= value <= 20000
        for name, value in offsets.items()
    ):
        raise ValueError("Use atraso entre -950 e 20000 ms, nas fontes selecionadas.")


def set_sync_verified(client, source, value):
    current = call(client, "GetInputAudioSyncOffset", inputName=source)["inputAudioSyncOffset"]
    if current != value:
        call(client, "SetInputAudioSyncOffset", inputName=source, inputAudioSyncOffset=value)
    actual = call(client, "GetInputAudioSyncOffset", inputName=source)["inputAudioSyncOffset"]
    if actual != value:
        raise ValueError("OBS não confirmou o atraso de áudio.")
