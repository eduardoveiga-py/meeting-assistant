"""Explicit Zoom audio actions through accessible controls, never a blind toggle."""

import re
import sys
import threading
import time
import unicodedata

from PySide6.QtCore import QObject, Signal


def microphone_state(label):
    value = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower().strip()
    if re.search(r"\b(all|todos|todas|participants?|participantes?)\b", value):
        return None
    if re.match(r"^(unmute|ativar (o )?(audio|som)|reativar (o )?(audio|som))($|[\s(])", value):
        return "muted"
    if re.match(r"^(mute|desativar (o )?(audio|som)|silenciar (meu )?(audio|microfone))($|[\s(])", value):
        if "all" not in value and "todos" not in value:
            return "live"
    return None


def find_control():
    import psutil
    from pywinauto import Desktop

    pids = set()
    for process in psutil.process_iter(["name"]):
        try:
            if (process.info["name"] or "").lower() == "zoom.exe":
                pids.add(process.pid)
        except psutil.Error:
            continue
    candidates = []
    for window in Desktop(backend="uia").windows():
        if window.process_id() not in pids or window.class_name() != "ConfMultiTabContentWndClass":
            continue
        for button in window.descendants(control_type="Button"):
            state = microphone_state(button.window_text())
            if state and button.is_enabled():
                candidates.append((button, state))
    if len(candidates) != 1:
        raise ValueError("Controle do microfone não identificado. Abra os controles de áudio no Zoom.")
    return candidates[0]


def perform(action, finder=find_control, cancel=None):
    if action not in {"inspect", "mute", "unmute"}:
        raise ValueError("Ação de microfone desconhecida.")
    if cancel is not None and cancel.is_set():
        raise RuntimeError("Operação cancelada.")
    button, state = finder()
    desired = {"mute": "muted", "unmute": "live"}.get(action)
    if desired and state != desired:
        if cancel is not None and cancel.is_set():
            raise RuntimeError("Operação cancelada.")
        button.invoke()
        for _ in range(8):
            if cancel is not None:
                if cancel.wait(0.15):
                    raise RuntimeError("Operação cancelada.")
            else:
                time.sleep(0.15)
            _, state = finder()
            if state == desired:
                break
        if state != desired:
            raise ValueError("Zoom não confirmou a mudança. Confira o microfone no Zoom.")
    return state


class ZoomAudio(QObject):
    result = Signal(str, str)

    def __init__(self, parent=None, *, finder=None, platform=None):
        super().__init__(parent)
        self.busy = False
        self._finder = finder
        self._platform = platform or sys.platform
        self._cancel = threading.Event()
        self._thread = None

    def request(self, action="inspect"):
        if self.busy:
            return
        self.busy = True
        self._cancel.clear()

        def work():
            com = None
            try:
                if self._finder is None:
                    if self._platform != "win32":
                        raise RuntimeError("Controle disponível apenas no Windows.")
                    import pythoncom

                    pythoncom.CoInitialize()
                    com = pythoncom
                state = perform(action, self._finder or find_control, self._cancel)
                if not self._cancel.is_set():
                    self.result.emit(state, "Estado observado no Zoom; controla apenas seu microfone.")
            except Exception:
                if not self._cancel.is_set():
                    self.result.emit("unknown", "Microfone não confirmado. Confira os controles no Zoom.")
            finally:
                try:
                    if com is not None:
                        com.CoUninitialize()
                finally:
                    self.busy = False

        self._thread = threading.Thread(target=work, daemon=True, name="Zoom audio control")
        self._thread.start()

    def stop(self):
        self._cancel.set()
