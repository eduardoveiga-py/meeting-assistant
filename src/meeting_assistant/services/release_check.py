"""Public metadata only; never downloads or installs code in a running meeting."""

import json
import re
from urllib.request import Request, urlopen

RELEASES = "https://github.com/eduardoveiga-py/meeting-assistant/releases/latest"


def version_tuple(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value)
    return tuple(map(int, match.groups())) if match else None


def check_release(installed):
    request = Request(
        "https://api.github.com/repos/eduardoveiga-py/meeting-assistant/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "MeetingAssistant"},
    )
    with urlopen(request, timeout=5) as response:
        data = json.loads(response.read(512_000))
    remote = version_tuple(data.get("tag_name", ""))
    local = version_tuple(installed)
    if data.get("draft") or data.get("prerelease") or remote is None or local is None:
        return "Versão estável não identificada; confira Releases."
    if remote > local:
        return f"Disponível: {data['tag_name']}. Faça backup e atualize fora da reunião."
    return f"Instalada: {installed}. Nenhuma versão estável mais recente."
