"""Inspect and complete managed OBS structure without rebuilding working routes.

Runs only on the OBS command worker. No Program switch, source deletion, audio
activation, plugin installation or automatic scene rename belongs in this plan.
"""

from pathlib import Path

from meeting_assistant.services import obs_audio
from meeting_assistant.services.obs_hall_setup import (
    PHOTO_SOURCE,
    apply_yeartext,
    ensure_source,
    fit_and_enable,
    prepare_media,
)
from meeting_assistant.services.obs_jwl_capture import KIND, SOURCE, confirmed_status
from meeting_assistant.services.obs_setup import CAMERA_SOURCE, camera_source_settings
from meeting_assistant.services.yeartext_store import YeartextStore


def call(client, request, **data):
    return client.send(request, data or None, raw=True)


def mapped_scenes(settings):
    names = (settings.scene_background, settings.scene_speaker, settings.scene_media)
    if len(set(names)) != 3 or any(not name.strip() or name == obs_audio.BUS for name in names):
        raise ValueError("Mapeie três cenas distintas em OBS e vídeo → Conexão.")
    return names


def inspect(client, settings, directory):
    scenes = {row["sceneName"] for row in call(client, "GetSceneList")["scenes"]}
    inputs = {row["inputName"]: row for row in call(client, "GetInputList")["inputs"]}
    kinds = set(call(client, "GetInputKindList")["inputKinds"])
    rows = []

    def row(key, label, state, detail):
        rows.append({"key": key, "label": label, "state": state, "detail": detail})

    def placement(scene, source):
        return (
            [item for item in obs_audio.items(client, scene) if item["sourceName"] == source]
            if scene in scenes
            else []
        )

    for name in mapped_scenes(settings):
        conflict = name in inputs
        row(
            "scene:" + name,
            name,
            "attention" if conflict else "ok" if name in scenes else "missing",
            "Nome ocupado por uma fonte; ajuste o mapeamento."
            if conflict
            else "Cena existente preservada."
            if name in scenes
            else "Será criada sem trocar o Program.",
        )
    row(
        "jwl_plugin",
        "Plugin JWL por HWND",
        "ok" if KIND in kinds else "blocked",
        "Carregado no OBS."
        if KIND in kinds
        else "Instale em Instalação e plugins, com OBS fechado; depois reabra OBS.",
    )

    for key, label, scene, source, kind in (
        ("photo", "Foto do Texto do Ano", settings.scene_background, PHOTO_SOURCE, "image_source"),
        ("camera", "Câmera IP em Palco", settings.scene_speaker, CAMERA_SOURCE, "ffmpeg_source"),
        ("media", "Captura da janela JWL", settings.scene_media, SOURCE, KIND),
    ):
        current = inputs.get(source)
        items = placement(scene, source)
        if current and current["inputKind"] != kind or source in scenes:
            row(
                key,
                label,
                "attention",
                "Nome reservado usado por outro tipo; nenhuma substituição automática.",
            )
        elif key == "media" and KIND not in kinds:
            row(key, label, "blocked", "Instale o plugin JWL antes de preparar a captura.")
        elif not current or not items:
            if key == "photo" and not current and YeartextStore(Path(directory)).current() is None:
                row(key, label, "blocked", "Capture e salve a foto na aba Texto do Ano.")
            elif (
                key == "camera"
                and not current
                and not (settings.camera_username and settings.camera_password)
            ):
                row(key, label, "blocked", "Preencha IP, usuário e senha na aba Conexão.")
            else:
                row(key, label, "missing", "Fonte ou vínculo ausente; será completado.")
        elif len(items) != 1:
            row(key, label, "attention", "Há vínculos duplicados; revise os itens no OBS.")
        elif not items[0].get("sceneItemEnabled"):
            row(
                key,
                label,
                "attention",
                "Fonte desativada; preservada. Use a preparação específica para ativá-la.",
            )
        elif key == "photo":
            values = call(client, "GetInputSettings", inputName=source)["inputSettings"]
            valid = bool(values.get("file")) and Path(values["file"]).is_file()
            row(
                key,
                label,
                "ok" if valid else "attention",
                "Foto existente preservada."
                if valid
                else "Arquivo não encontrado. Use Aplicar foto já salva.",
            )
        elif key == "media":
            try:
                confirmed_status(client)
            except ValueError:
                row(key, label, "attention", "Aguarde a segunda janela JWL ou use Preparar captura JWL.")
                continue
            try:
                from meeting_assistant.services.obs_capture_safety import assert_safe_media

                assert_safe_media(client, scene)
            except ValueError:
                row(
                    key,
                    label,
                    "missing",
                    "Captura antiga ou insegura; será desativada após confirmar o HWND.",
                )
                continue
            row(key, label, "ok", "Plugin confirmou a identidade e a imagem da janela JWL.")
        else:
            values = call(client, "GetInputSettings", inputName=source)["inputSettings"]
            valid = bool(values.get("input"))
            row(
                key,
                label,
                "ok" if valid else "attention",
                "Fonte existente preservada; confira a imagem da câmera."
                if valid
                else "Use Aplicar câmera IP.",
            )

    try:
        obs_audio.check_kinds(inputs)
        bus_items = obs_audio.items(client, obs_audio.BUS) if obs_audio.BUS in scenes else []
        if obs_audio.BUS in inputs or any(item["sourceName"] not in obs_audio.SOURCES for item in bus_items):
            raise ValueError("Cena de áudio contém fontes externas ou nome incompatível.")
        counts = [sum(item["sourceName"] == name for item in bus_items) for name in obs_audio.SOURCES]
        if any(count > 1 for count in counts):
            raise ValueError("Cena de áudio contém fontes duplicadas.")
        missing = any(name not in inputs for name in obs_audio.SOURCES) or any(count == 0 for count in counts)
        row(
            "audio",
            "Estrutura de áudio",
            "missing" if missing else "ok",
            "Criará fontes ausentes silenciadas; envio existente preservado."
            if missing
            else "Fontes existentes preservadas. Volumes e envio ficam na categoria Áudio.",
        )
    except ValueError as exc:
        row("audio", "Estrutura de áudio", "attention", str(exc))
    filters = set(call(client, "GetSourceFilterKindList").get("sourceFilterKinds", []))
    required = settings.audio_profile == "whatsapp_zoom"
    row(
        "audio_monitor",
        "Plugin Audio Monitor",
        "ok" if "audio_monitor" in filters else "blocked" if required else "optional",
        "Carregado no OBS."
        if "audio_monitor" in filters
        else "Necessário para enviar participantes do Zoom ao WhatsApp; instale em Instalação e plugins."
        if required
        else "Opcional no perfil que envia o mesmo áudio para Zoom e WhatsApp.",
    )
    return {
        "rows": rows,
        "ready": all(r["state"] in {"ok", "optional"} for r in rows),
        "message": "Verificação concluída. Nenhuma configuração do OBS foi alterada.",
    }


def complete(client, settings, directory, target_provider, stop_event, local_connection):
    snapshot = inspect(client, settings, directory)
    changed, failures = {}, []
    for row in snapshot["rows"]:
        if stop_event.is_set():
            failures.append("Operação interrompida; itens já criados foram preservados.")
            break
        if row["state"] != "missing":
            continue
        key = row["key"]
        try:
            if key.startswith("scene:"):
                name = key.removeprefix("scene:")
                call(client, "CreateScene", sceneName=name)
                if name not in {r["sceneName"] for r in call(client, "GetSceneList")["scenes"]}:
                    raise ValueError("OBS não confirmou a cena.")
            elif key == "audio":
                obs_audio.prepare(client)
            elif key == "media":
                if local_connection is not True:
                    raise ValueError("Captura JWL exige OBS neste computador.")
                prepare_media(client, settings.scene_media, target_provider(), stop_event)
            elif key == "photo":
                if local_connection is not True:
                    raise ValueError("Arquivo da foto exige OBS neste computador.")
                existing = {r["inputName"] for r in call(client, "GetInputList")["inputs"]}
                if PHOTO_SOURCE not in existing:
                    store = YeartextStore(Path(directory))
                    photo = store.current()
                    if photo is None:
                        raise ValueError("Capture e salve a foto primeiro.")
                    apply_yeartext(client, photo, settings.scene_background)
                    store.mark_applied(photo["sha256"], photo["file"])
                else:
                    item = ensure_source(client, settings.scene_background, PHOTO_SOURCE, "image_source", {})
                    fit_and_enable(client, settings.scene_background, item)
            elif key == "camera":
                existing = {r["inputName"] for r in call(client, "GetInputList")["inputs"]}
                values = {} if CAMERA_SOURCE in existing else camera_source_settings(settings)
                item = ensure_source(client, settings.scene_speaker, CAMERA_SOURCE, "ffmpeg_source", values)
                if values:
                    call(client, "SetInputMute", inputName=CAMERA_SOURCE, inputMuted=True)
                    if not call(client, "GetInputMute", inputName=CAMERA_SOURCE)["inputMuted"]:
                        raise ValueError("OBS não confirmou o silêncio da câmera IP.")
                fit_and_enable(client, settings.scene_speaker, item)
            changed[key] = row["label"]
        except ValueError as exc:
            failures.append(f"{row['label']}: {exc}")
        except Exception:
            failures.append(f"{row['label']}: OBS não confirmou. Verifique e tente novamente.")
    result = inspect(client, settings, directory)
    for row in result["rows"]:
        if row["key"] in changed and row["state"] != "ok":
            changed.pop(row["key"])
            failures.append(f"{row['label']}: resultado ainda pendente no OBS; confira o relatório.")
    changes = list(changed.values())
    result["changes"], result["failures"] = changes, failures
    result["message"] = (
        ("Completado: " + ", ".join(changes) + ". " if changes else "Nenhuma fonte precisou ser criada. ")
        + "Fontes existentes, volumes e Program preservados."
        + (" Há pendências no relatório." if not result["ready"] else "")
        + ("\n" + "\n".join(failures) if failures else "")
    )
    return result


def apply_camera(client, settings):
    """Explicit IP change; preserve scene names and all unrelated sources."""
    mapped_scenes(settings)
    source_settings = camera_source_settings(settings)
    item = ensure_source(
        client, settings.scene_speaker, CAMERA_SOURCE, "ffmpeg_source", source_settings
    )
    values = call(client, "GetInputSettings", inputName=CAMERA_SOURCE)["inputSettings"]
    if values.get("input") != source_settings["input"]:
        raise ValueError("OBS não confirmou a configuração da câmera IP.")
    call(client, "SetInputMute", inputName=CAMERA_SOURCE, inputMuted=True)
    if not call(client, "GetInputMute", inputName=CAMERA_SOURCE)["inputMuted"]:
        raise ValueError("OBS não confirmou o silêncio do microfone da câmera IP.")
    fit_and_enable(client, settings.scene_speaker, item)
    return {
        "message": "OBS confirmou a fonte IP em Palco, com áudio silenciado. "
        "Confira a imagem; nenhuma cena Program foi trocada."
    }
