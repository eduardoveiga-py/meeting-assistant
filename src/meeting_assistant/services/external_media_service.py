"""Explicit window selection and coordinated OBS/Win32 presentation lifecycle."""

import threading

from PySide6.QtCore import QObject, Signal

from meeting_assistant.services.hall_capture import obs_window_key
from meeting_assistant.services.jwl_secondary_window import WindowRect
from meeting_assistant.services.jwl_uia_secondary_window import choose_native_monitor_rect
from meeting_assistant.services.window_inventory import WindowBackend

PLAYERS = {
    "vlc.exe",
    "mpc-hc.exe",
    "mpc-hc64.exe",
    "wmplayer.exe",
    "microsoft.media.player.exe",
    "photos.exe",
    "microsoft.photos.exe",
    "videoui.exe",
    "chrome.exe",
    "msedge.exe",
}


def media_candidates(windows):
    return [w for w in windows if w.process.casefold() in PLAYERS and w.visible and w.title]


class ExternalMediaService(QObject):
    state_changed = Signal(bool, str)
    candidates_ready = Signal(object)
    _native_finished = Signal(str, bool, object)

    def __init__(self, display_provider, controller, zoom_hall, *, backend=None):
        super().__init__()
        self._display_provider = display_provider
        self.obs = controller
        self.zoom_hall = zoom_hall
        self.backend = backend or WindowBackend()
        self.phase = "idle"
        self.window = None
        self._display = None
        self._prior = ""
        self._cancel = threading.Event()
        self._thread = None
        self._native_busy = False
        self._stop_after_show = False
        self._restore_errors = []
        self._native_finished.connect(self._native_result)
        controller.external_task_finished.connect(self._obs_result)
        zoom_hall.returning_changed.connect(self._returned)
        zoom_hall.status_changed.connect(self._return_status)

    @property
    def active(self):
        return self.phase != "idle"

    def _state(self, phase, message):
        self.phase = phase
        self.state_changed.emit(self.active, message)

    def _work(self, action, callback):
        self._native_busy = True

        def work():
            try:
                value = callback()
                self._native_busy = False
                if not self._cancel.is_set():
                    self._native_finished.emit(action, True, value)
            except Exception:
                self._native_busy = False
                if not self._cancel.is_set():
                    self._native_finished.emit(action, False, "Operação da janela não confirmada.")

        self._thread = threading.Thread(target=work, daemon=True, name="External presentation")
        self._thread.start()

    def start_external_media(self):
        if self.active or self.zoom_hall.active or self.zoom_hall.returning:
            self.state_changed.emit(self.active, "Retorne do Zoom ao JWL antes de iniciar mídia externa.")
            return False
        self._display = self._display_provider()
        if self._display is None:
            self.state_changed.emit(False, "Monitor do salão ausente.")
            return False
        self._cancel.clear()
        self._state("choosing", "Selecione a janela que deseja apresentar.")
        self._work("discover", lambda: media_candidates(self.backend.windows()))
        return True

    def select(self, window):
        if self.phase != "choosing":
            return
        if window is None:
            self._state("idle", "Seleção de mídia externa cancelada.")
            return
        if window.process.casefold() not in PLAYERS:
            self._state("idle", "Aplicativo não permitido para mídia externa.")
            return
        self.window = window
        self._state("preparing", "Preparando captura exclusiva da janela selecionada…")
        selector = obs_window_key(window.title, window.class_name, window.process)
        self.obs.external_task("prepare", {"selector": selector})

    def _show(self):
        monitors = self.backend.monitors()
        rect = choose_native_monitor_rect(
            self._display, [(m["primary"], WindowRect(*m["rect"])) for m in monitors]
        )
        if rect is None:
            raise ValueError("Monitor desconectado durante a preparação.")
        return self.backend.present(self.window, (rect.left, rect.top, rect.right, rect.bottom))

    def _native_result(self, action, ok, payload):
        if action == "discover" and self.phase == "choosing":
            if ok and payload:
                self.candidates_ready.emit(payload)
            else:
                self._state("idle", "Nenhuma janela de mídia permitida foi encontrada.")
        elif action == "show" and self.phase == "showing":
            if self._stop_after_show:
                self._stop_after_show = False
                self.stop_external_media()
            elif ok:
                self.obs.external_task("show", {"prior": self._prior})
            else:
                self.stop_external_media()
        elif action == "restore" and self.phase == "stopping":
            self._state("returning", "Restaurando explicitamente o JWL…")
            if not ok:
                self._restore_errors.append("Player não confirmou a disposição anterior")
                self.state_changed.emit(True, "Player não confirmou a disposição anterior; restaurando JWL.")
            if not self.zoom_hall.restore_jwl():
                self._state("return_failed", "Retorno do JWL não confirmado. Confira a tela do salão.")

    def _obs_result(self, action, ok, payload):
        if action == "prepare" and self.phase == "preparing":
            if not ok:
                self._state("idle", str(payload.get("message", "OBS não confirmou a captura.")))
                return
            self._prior = payload["prior"]
            self._state("showing", "Posicionando a janela de mídia no salão…")
            self._work("show", self._show)
        elif action == "show" and self.phase == "showing":
            if ok:
                self._state("presenting", payload["message"])
            else:
                self.stop_external_media()
        elif action == "restore" and self.phase == "stopping":
            if not ok:
                self._restore_errors.append("OBS não confirmou retorno de Program")
                self.state_changed.emit(True, "OBS não confirmou retorno de Program; confira a cena.")
            self._work(
                "restore", lambda: self.backend.restore_presentation(self.window) if self.window else None
            )

    def stop_external_media(self):
        if not self.active:
            return
        if self.phase == "choosing":
            self._cancel.set()
            self._state("idle", "Seleção cancelada.")
            return
        if self.phase in {"stopping", "returning"}:
            return
        # Do not start a competing native worker during placement. Queue the
        # return once the current operation resolves on the GUI thread.
        if self.phase == "showing" and self._native_busy:
            self._stop_after_show = True
            return
        self._restore_errors.clear()
        self._state("stopping", "Retornando Program e disposição do player…")
        self.obs.external_task("restore", {"prior": self._prior})

    def _returned(self, returning):
        # Wait for the accompanying verified status; returning=False alone
        # also occurs when the JWL window could not be restored.
        return

    def _return_status(self, ok, message):
        if self.phase == "returning":
            if self.zoom_hall.returning:
                return  # Accepted request is not verified restoration.
            if ok and not self._restore_errors:
                self._state("idle", message)
                self.window, self._prior = None, ""
            elif ok:
                self._state("return_failed", message + "; pendências: " + "; ".join(self._restore_errors))
            else:
                self._state("return_failed", "Retorno JWL não confirmado: " + message)

    def stop(self):
        self._cancel.set()
        if self._prior:
            self.obs.external_task("restore", {"prior": self._prior})
        self._state("idle", "Mídia externa parada para encerramento.")
