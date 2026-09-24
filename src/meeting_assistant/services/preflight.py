"""Read-only readiness results; manual evidence is never inferred from a probe."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    category: str
    name: str
    passed: bool | None

    def render(self):
        state = "NÃO VERIFICADO" if self.passed is None else "OK" if self.passed else "PENDENTE"
        return f"{self.category} · {state} · {self.name}"


def inspect_obs(settings, factory):
    rows = []
    client = None
    connected = False
    try:
        client = factory(
            host=settings.obs_host, port=settings.obs_port, password=settings.obs_password, timeout=3
        )
        client.send("GetVersion", raw=True)
        connected = True
    except Exception:
        pass  # Connection errors may contain credentials; never render them.
    rows.append(Check("CONEXÃO", "OBS WebSocket autenticado", connected))
    scenes = None
    camera = None
    try:
        if connected:
            try:
                scenes = {r["sceneName"] for r in client.send("GetSceneList", raw=True)["scenes"]}
            except Exception:
                pass
            try:
                camera = bool(client.send("GetVirtualCamStatus", raw=True)["outputActive"])
            except Exception:
                pass
    finally:
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
    for name in (settings.scene_background, settings.scene_speaker, settings.scene_media):
        rows.append(Check("CONFIGURAÇÃO", f"Cena {name} existe", None if scenes is None else name in scenes))
    rows.append(Check("CONEXÃO", "Câmera virtual OBS ativa", camera))
    return rows
