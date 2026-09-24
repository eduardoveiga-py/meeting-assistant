"""Explicit Zoom audio actions through accessible controls, never a blind toggle."""

import re
import threading
import time
import unicodedata

from PySide6.QtCore import QObject, Signal


def microphone_state(label):
    value = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower().strip()
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


def perform(action, finder=find_control):
    button, state = finder()
    desired = {"mute": "muted", "unmute": "live"}.get(action)
    if desired and state != desired:
        button.invoke()
        for _ in range(8):
            time.sleep(0.15)
            _, state = finder()
            if state == desired:
                break
        if state != desired:
            raise ValueError("Zoom não confirmou a mudança. Confira o microfone no Zoom.")
    return state


class ZoomAudio(QObject):
    result = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False

    def request(self, action="inspect"):
        if self.busy:
            return
        self.busy = True

        def work():
            import pythoncom

            pythoncom.CoInitialize()
            try:
                state = perform(action)
                self.result.emit(state, "Estado observado no Zoom.")
            except Exception:
                self.result.emit("unknown", "Microfone não confirmado. Confira os controles no Zoom.")
            finally:
                pythoncom.CoUninitialize()
                self.busy = False

        threading.Thread(target=work, daemon=True, name="Zoom audio control").start()
