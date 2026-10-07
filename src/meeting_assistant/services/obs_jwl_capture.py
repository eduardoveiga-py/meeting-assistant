"""Protocol and lifecycle of the independent native JWL source.

All calls are serialized by ObsController's worker, including rediscovery. The
native source is silent and independent of the Program bridge and camera.
"""

from __future__ import annotations

import json
import threading
import time
from uuid import uuid4

from meeting_assistant.services.jwl_capture_target import capture_binding

SOURCE = "Meeting Assistant - JWL (HWND)"
KIND = "meeting_assistant_jwl_capture"
STATUS_PROPERTY = "__ma_capture_status"
IDENTITY_KEYS = ("hwnd", "pid", "created", "jwl_hwnd", "jwl_pid", "jwl_created", "session")


def call(client, request, **data):
    return client.send(request, data or None, raw=True)


def read_status(client) -> dict:
    values = call(client, "GetInputPropertiesListPropertyItems", inputName=SOURCE,
                  propertyName=STATUS_PROPERTY).get("propertyItems", [])
    if len(values) != 1:
        raise ValueError("OBS não retornou o diagnóstico do plugin JWL. Reinicie OBS após instalar a DLL.")
    try:
        status = json.loads(values[0]["itemValue"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Diagnóstico nativo da captura JWL inválido.") from exc
    if not isinstance(status, dict) or status.get("protocol") != 1:
        raise ValueError("Atualize o componente nativo da captura JWL pelo scripts/run.ps1.")
    return status


def confirmed_status(client, expected: dict | None = None) -> dict:
    settings = call(client, "GetInputSettings", inputName=SOURCE).get("inputSettings", {})
    status = read_status(client)
    if expected is not None and any(settings.get(k) != v for k, v in expected.items()):
        raise ValueError("OBS não confirmou a identidade solicitada da janela JWL.")
    dimensions_valid = all(type(status.get(k)) is int and 0 < status[k] <= 16384 for k in ("width", "height"))
    if status.get("state") != "active" or not dimensions_valid:
        raise ValueError(f"Captura JWL ainda não confirmou imagem ({status.get('state', 'desconhecido')}).")
    if any(not settings.get(key) or status.get(key) != settings[key] for key in IDENTITY_KEYS):
        raise ValueError("A imagem da captura não corresponde ao vínculo JWL atual.")
    return status


def bind(client, target: dict) -> None:
    current = call(client, "GetInputSettings", inputName=SOURCE).get("inputSettings", {})
    if any(current.get(k) != v for k, v in target.items()):
        call(client, "SetInputSettings", inputName=SOURCE, inputSettings=target, overlay=True)


def wait_for_capture(client, target: dict, stop_event: threading.Event, timeout: float = 4) -> dict:
    deadline = time.monotonic() + timeout
    last = "Captura não confirmada."
    while not stop_event.is_set():
        try:
            return confirmed_status(client, target)
        except ValueError as exc:
            last = str(exc)
        if time.monotonic() >= deadline:
            break
        stop_event.wait(0.1)
    raise ValueError(
        last + " Confira a segunda janela JWL e o log do OBS; nenhuma captura de monitor foi usada."
    )


class JwlCaptureRuntime:
    """Snapshot handoff from Qt; binding and Win32 reads happen on OBS worker."""

    def __init__(self):
        self.session = uuid4().hex
        self._snapshot = (None, None)
        self._configured = None
        self._last_status = None

    def update_snapshot(self, candidate, display):
        self._snapshot = (candidate, display)  # immutable references, atomic tuple publication

    def reset_connection(self):
        self._configured = None
        self._last_status = None

    def target(self) -> dict:
        return capture_binding(*self._snapshot, self.session)

    def sync(self, client) -> dict | None:
        if self._configured is not True:
            inputs = call(client, "GetInputList").get("inputs", [])
            self._configured = any(
                i.get("inputName") == SOURCE and i.get("inputKind") == KIND for i in inputs
            )
        if not self._configured:
            return None  # preparing remains an explicit operator action
        try:
            target = self.target()
        except (ValueError, OSError) as exc:
            # Invalidate a disappeared HWND; no title fallback, no restored window.
            bind(client, {"hwnd": "0", "session": self.session})
            status = {"protocol": 1, "state": "unavailable", "message": str(exc)}
        else:
            bind(client, target)
            status = read_status(client)
        if status == self._last_status:
            return None
        self._last_status = status
        return status
