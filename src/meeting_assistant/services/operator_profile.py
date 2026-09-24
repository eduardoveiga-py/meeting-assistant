"""Portable preferences only: never copy equipment identifiers or credentials."""

import json
from dataclasses import replace

FIELDS = {"scene_background", "scene_speaker", "scene_media", "always_on_top", "congregation_language"}


def export_profile(settings, path):
    path.write_text(
        json.dumps(
            {"schema": 1, "preferences": {k: getattr(settings, k) for k in FIELDS}},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def import_profile(settings, path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("preferences"), dict):
        raise ValueError("Perfil inválido.")
    values = data["preferences"]
    if not set(values) <= FIELDS:
        raise ValueError("Perfil contém campos não portáveis.")
    for key, value in values.items():
        if type(value) is not type(getattr(settings, key)) or (isinstance(value, str) and not value.strip()):
            raise ValueError("Preferência inválida.")
    pending = replace(settings, **values)
    if len({pending.scene_background, pending.scene_speaker, pending.scene_media}) != 3:
        raise ValueError("Cenas devem ser distintas.")
    return pending
