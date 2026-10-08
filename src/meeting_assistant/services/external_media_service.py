"""Explicit window selection and coordinated OBS/Win32 presentation lifecycle."""

import threading
import time
import uuid

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal

from meeting_assistant.services.external_player_controls import PlayerControlBackend
from meeting_assistant.services.external_window_backend import ExternalWindowBackend
from meeting_assistant.services.hall_capture import obs_window_key
from meeting_assistant.services.jwl_secondary_window import WindowRect
from meeting_assistant.services.jwl_uia_secondary_window import choose_native_monitor_rect

PLAYERS = {
    "vlc.exe", "mpc-hc.exe", "mpc-hc64.exe", "wmplayer.exe", "microsoft.media.player.exe",
    "photos.exe", "microsoft.photos.exe", "videoui.exe", "chrome.exe", "msedge.exe",
}


def media_candidates(windows):
    return [w for w in windows if w.process.casefold() in PLAYERS and w.visible and w.title]


def same_identity(left, right):
    return (left.hwnd, left.pid, left.created, left.class_name, left.process.casefold()) == (
        right.hwnd, right.pid, right.created, right.class_name, right.process.casefold()
    )


def jwl_return_candidate(current, external):
    """A hidden output can temporarily disappear from UIA's visible inventory."""
    return current or (external.return_candidate if external is not None and external.active else None)


class PlacementError(ValueError):
    def __init__(self, message, window):
        super().__init__(message)
        self.window = window


class ExternalMediaService(QObject):
    state_changed = Signal(bool, str)
    candidates_ready = Signal(object)
    diagnostic = Signal(object)
    control_changed = Signal(bool, str)
    operator_layout_requested = Signal()
    _native_finished = Signal(str, str, bool, object)

    def __init__(self, display_provider, controller, zoom_hall, *, backend=None,
                 hall_window_provider=None, controls=None):
        super().__init__()
        self._display_provider = display_provider
        self.obs = controller
        self.zoom_hall = zoom_hall
        self.backend = backend or ExternalWindowBackend(hall_window_provider)
        self.controls = controls or PlayerControlBackend()
        self.phase = "idle"
        self.window = None
        self._display = None
        self._target_rect = None
        self._prior = ""
        self._selector = ""
        self._token = ""
        self._pending_obs = ""
        self._failure = ""
        self._cancel = threading.Event()
        self._thread = None
        self._native_busy = False
        self._stop_after_show = False
        self._restore_errors = []
        self._media_warning = ""
        self._has_presented = False
        self._control_cancel = threading.Event()
        self._watch = QTimer(self)
        self._watch.setInterval(350)
        self._watch.timeout.connect(self._monitor)
        if isinstance(self.backend, ExternalWindowBackend):
            self.backend.cancelled = self._cancel.is_set
        self._native_finished.connect(self._native_event)
        controller.external_task_finished.connect(self._obs_result)
        zoom_hall.status_changed.connect(self._return_status)

    @property
    def active(self):
        return self.phase != "idle"

    @property
    def return_candidate(self):
        return getattr(self.backend, "return_candidate", None) if self.active else None

    def _state(self, phase, message):
        self.phase = phase
        if phase == "presenting" and QCoreApplication.instance() is not None:
            self._watch.start()
        else:
            self._watch.stop()
        suspend = getattr(self.obs, "set_external_media_active", None)
        if callable(suspend):
            suspend(self.active)
        self.state_changed.emit(self.active, message)

    def _request_obs(self, action, data):
        self._pending_obs = action
        if self._token:
            data = {**data, "token": self._token}
        self.obs.external_task(action, data)

    def _work(self, action, callback):
        self._native_busy = True
        token = self._token

        def work():
            started = time.monotonic()
            try:
                value, ok = callback(), True
            except ValueError as exc:
                value, ok = {"message": str(exc), "window": getattr(exc, "window", None)}, False
            except Exception:
                value, ok = {"message": "Operação da janela não confirmada."}, False
            finally:
                self._native_busy = False
            if isinstance(value, dict):
                value = {**value, "elapsed_ms": round((time.monotonic() - started) * 1000)}
            if not self._cancel.is_set():
                self._native_finished.emit(token, action, ok, value)

        self._thread = threading.Thread(target=work, daemon=True, name="External presentation")
        self._thread.start()

    def _native_event(self, token, action, ok, payload):
        if token == self._token:
            snapshot = getattr(self.backend, "last_snapshot", {})
            if not isinstance(snapshot, dict):
                snapshot = {}
            if action != "monitor" or not ok or snapshot.get("repaired"):
                details = payload if isinstance(payload, dict) else {}
                self.diagnostic.emit({
                    "action": "native_" + action, "ok": ok, "phase": self.phase,
                    "snapshot": dict(snapshot), "elapsed_ms": details.get("elapsed_ms"),
                    "message": details.get("message", ""),
                })
            self._native_result(action, ok, payload)

    def start_external_media(self):
        if self.active:
            self.state_changed.emit(
                True, "Mídia externa em andamento; aguarde a operação ou solicite o retorno."
            )
            return False
        if self.zoom_hall.active or self.zoom_hall.returning:
            self.state_changed.emit(False, "Retorne do Zoom ao JWL antes de iniciar mídia externa.")
            return False
        # Native work has finished before its Qt result is emitted. The thread
        # may still be unwinding that emission when an immediate next click
        # arrives; that is not a second inventory/presentation in progress.
        if self._native_busy:
            self.state_changed.emit(False, "Aguarde a consulta de janelas anterior terminar.")
            return False
        self._display = self._display_provider()
        if self._display is None:
            self.state_changed.emit(False, "Monitor do salão ausente.")
            return False
        self._cancel.clear()
        if isinstance(self.backend, ExternalWindowBackend):
            self.backend.return_candidate = None
        self._token = uuid.uuid4().hex
        self.window, self._prior, self._selector = None, "", ""
        self._target_rect = None
        self._pending_obs = self._failure = ""
        self._stop_after_show = False
        self._restore_errors.clear()
        self._media_warning = ""
        self._has_presented = False
        self._control_cancel.clear()
        self.controls.fullscreen_owned = False
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
        self.operator_layout_requested.emit()
        self._state("checking", "Conferindo o OBS antes de apresentar a janela…")
        self._request_obs("begin", {})

    def _show(self):
        selected, display = self.window, self._display
        candidates = [w for w in self.backend.windows() if same_identity(w, selected)]
        if len(candidates) != 1 or not self.backend.same_window(candidates[0]):
            raise ValueError("A janela externa foi fechada ou mudou de processo. Selecione novamente.")
        original = candidates[0]
        rect = choose_native_monitor_rect(
            display, [(m["primary"], WindowRect(*m["rect"])) for m in self.backend.monitors()]
        )
        if rect is None:
            raise ValueError("Monitor desconectado durante a preparação.")
        self._target_rect = (rect.left, rect.top, rect.right, rect.bottom)
        if self._cancel.is_set():
            raise ValueError("Apresentação cancelada antes de mover a janela.")
        try:
            confirmed = self.backend.present(original, self._target_rect)
            if self._cancel.is_set():
                self.backend.restore_presentation(original)
                raise ValueError("Apresentação cancelada durante o posicionamento.")
            live = [w for w in self.backend.windows() if same_identity(w, original)]
            if confirmed is not True or len(live) != 1 or live[0].minimized or not live[0].visible:
                raise ValueError("Janela não confirmou a apresentação.")
            if not live[0].title:
                raise ValueError("Player ainda não confirmou o título.")
        except Exception as exc:
            # Return the fresh pre-placement snapshot even when styles/position
            # partially changed before the native operation failed.
            if isinstance(exc, ValueError):
                message = str(exc)
            else:
                # Keep the native stage/code without private exception text
                # (titles, paths, URLs). A generic exposure message hid API
                # failures occurring before the player ever moved.
                snapshot = getattr(self.backend, "last_snapshot", {})
                stage = (snapshot.get("stage", "player_position")
                         if isinstance(snapshot, dict) else "player_position")
                code = getattr(exc, "winerror", None)
                native = f"; WinError={code}" if isinstance(code, int) else ""
                message = (f"Posicionamento não confirmado [WINDOW_API:{stage}]: "
                           f"{type(exc).__name__}{native}.")
            raise PlacementError(message + " Restaurando a janela.", original) from exc
        return {"window": original, "selector": obs_window_key(
            live[0].title, live[0].class_name, live[0].process
        )}

    def _native_result(self, action, ok, payload):
        if action == "discover" and self.phase == "choosing":
            if ok and payload:
                self.candidates_ready.emit(payload)
            else:
                self._state("idle", "Nenhuma janela de mídia permitida foi encontrada.")
        elif action == "show" and self.phase in {"placing", "showing"}:
            if isinstance(payload, dict) and payload.get("window"):
                self.window = payload["window"]
            if not ok:
                self._failure = payload.get("message", "Janela externa não confirmada.")
            if self._stop_after_show or not ok:
                self._stop_after_show = False
                self.phase = "placed"  # The native result has arrived; rollback may now run.
                self.stop_external_media()
            else:
                self._selector = payload["selector"]
                self._state("preparing", "Preparando captura exclusiva da janela restaurada…")
                self._request_obs("prepare", {"selector": self._selector, "prior": self._prior})
        elif action == "confirm" and self.phase == "confirming":
            if not ok:
                self._failure = payload.get("message", "Player não confirmou a visibilidade no Salão.")
            if self._stop_after_show or not ok:
                self._stop_after_show = False
                self.phase = "placed"
                self.stop_external_media()
            else:
                self._state("showing", "Solicitando a mídia externa no Program…")
                self._request_obs("show", {"prior": self._prior, "selector": self._selector})
        elif action == "restore" and self.phase == "stopping":
            self._state("returning", "Restaurando explicitamente o JWL…")
            if not ok:
                self._restore_errors.append(
                    payload.get("message", "Player não confirmou a disposição anterior")
                )
            if not self.zoom_hall.restore_jwl() and self.phase == "returning":
                self._state("return_failed", "Retorno do JWL não confirmado. Confira a tela do salão.")
        elif action == "monitor" and self.phase == "presenting":
            if not ok:
                self._failure = payload.get("message", "Player perdeu a exibição no Salão.")
            if not ok or self._stop_after_show:
                self._stop_after_show = False
                self.stop_external_media()
        elif action.startswith("control:") and self.phase == "presenting":
            message = ("Comando confirmado no vídeo." if ok else
                       payload.get("message", "Controle de vídeo não confirmado."))
            self.control_changed.emit(False, message)
            if self._stop_after_show:
                self._stop_after_show = False
                self.stop_external_media()
        elif action == "stop_media" and self.phase == "stopping_media":
            if not ok:
                self._media_warning = payload.get("message", "Confira se a mídia parou no aplicativo.")
            self._state("stopping", "Retornando Program e disposição do player…")
            self._request_obs("restore", {"prior": self._prior})

    def _confirm(self):
        # Preserve the original snapshot and explicit handoff throughout this
        # cycle. Repair z-order without repeated foreground activation.
        return self.backend.confirm_presentation(self.window, self._target_rect)

    def _monitor(self):
        if self.phase == "presenting" and not self._native_busy:
            self._work("monitor", self._confirm)

    def command(self, action):
        if self.phase != "presenting" or self._native_busy:
            return False
        if action not in {"play", "pause", "fullscreen", "maximize"}:
            return False
        self._control_cancel.clear()
        self.control_changed.emit(True, "Controlando o vídeo escolhido…")

        def run():
            if action != "maximize":
                self.controls.command(self.window, action, self._control_cancel)
            return self._confirm()

        self._work("control:" + action, run)
        return True

    def _stop_media(self):
        errors = []
        # A failed/cancelled Play must finish before Pause; never dispatch a late
        # command after return. Only stop content which was actually presented.
        self._control_cancel.clear()
        for action in ("stop", "exit_fullscreen"):
            if action == "exit_fullscreen" and not self.controls.fullscreen_owned:
                continue
            try:
                self.controls.command(self.window, action, self._control_cancel)
            except ValueError as exc:
                errors.append(str(exc))
        if errors:
            raise ValueError("Retorno solicitado; confira a mídia no aplicativo: " + "; ".join(errors))

    def _obs_result(self, action, ok, payload):
        if payload.get("token", "") != self._token:
            return
        if self._pending_obs and action != self._pending_obs:
            return
        self._pending_obs = ""
        self.diagnostic.emit({"action": action, "ok": ok, "phase": self.phase,
                              "error_code": payload.get("error_code"),
                              "message": payload.get("message", "")})
        if action == "begin" and self.phase == "checking":
            if not ok:
                self._state("idle", payload.get("message", "OBS não confirmou a preparação."))
            elif self._stop_after_show:
                self._stop_after_show = False
                self._state("idle", "Seleção de mídia externa cancelada.")
            else:
                self._prior = payload["prior"]
                self._state("placing", "Restaurando e posicionando a janela de mídia…")
                self._work("show", self._show)
        elif action == "prepare" and self.phase == "preparing":
            if ok:
                self._prior = payload["prior"]
            else:
                self._failure = payload.get("message", "OBS não confirmou a captura externa.")
            if self._stop_after_show or not ok:
                self._stop_after_show = False
                self.stop_external_media()
            else:
                self._state("confirming", "Confirmando a mídia externa visível no Salão…")
                self._work("confirm", self._confirm)
        elif action == "show" and self.phase == "showing":
            if not ok:
                self._failure = payload.get("message", "OBS não confirmou a cena externa.")
            if self._stop_after_show or not ok:
                self._stop_after_show = False
                self.stop_external_media()
            else:
                self._has_presented = True
                self._state("presenting", payload["message"])
        elif action == "restore" and self.phase == "stopping":
            if not ok:
                self._restore_errors.append("OBS não confirmou retorno de Program")
            self._work(
                "restore", lambda: self.backend.restore_presentation(self.window) if self.window else None
            )

    def stop_external_media(self):
        if not self.active or self.phase in {"stopping_media", "stopping", "returning"}:
            return
        if self.phase == "choosing":
            self._cancel.set()
            self._state("idle", "Seleção cancelada.")
            return
        if self.phase in {"checking", "placing", "preparing", "confirming"} or self._pending_obs == "show":
            # Consume the in-flight response before rollback: it owns the fresh
            # prior scene/snapshot. Do not overlap native workers.
            if self._pending_obs or self._native_busy or self.phase in {"placing", "confirming"}:
                self._stop_after_show = True
                self.state_changed.emit(True, "Cancelamento solicitado; aguardando a operação em andamento…")
                return
        if self.phase == "showing" and self._native_busy:
            self._stop_after_show = True
            return
        if self.phase == "presenting" and self._native_busy:
            self._watch.stop()
            self._stop_after_show = True
            self._control_cancel.set()
            self.state_changed.emit(True, "Retorno solicitado; concluindo o comando em andamento…")
            return
        self._restore_errors.clear()
        if self._has_presented and self.phase != "return_failed":
            self._state("stopping_media", "Parando a mídia antes de retornar ao JWL…")
            self._work("stop_media", self._stop_media)
            return
        self._state("stopping", "Retornando Program e disposição do player…")
        self._request_obs("restore", {"prior": self._prior})

    def _return_status(self, ok, message):
        if self.phase != "returning" or self.zoom_hall.returning:
            return
        if ok and not self._restore_errors:
            if self._failure:
                message = f"Falha na mídia externa: {self._failure} {message}"
            if self._media_warning:
                message += " Aviso: " + self._media_warning
            self.operator_layout_requested.emit()
            self._state("idle", message)
            self.window, self._prior, self._selector = None, "", ""
        elif ok:
            self.operator_layout_requested.emit()
            self._state("return_failed", message + "; pendências: " + "; ".join(self._restore_errors))
        else:
            self._state("return_failed", "Retorno JWL não confirmado: " + message)

    def stop(self):
        original = self.window if self.active else None
        pending = self._thread
        self._watch.stop()
        self._cancel.set()
        self._control_cancel.set()
        self.controls.close()
        if original is not None:
            backend = self.backend

            def cleanup():
                if pending is not None and pending.is_alive():
                    pending.join(timeout=1.0)
                try:
                    backend.restore_presentation(original)
                except Exception:
                    # This path is process teardown, after Qt owners may have
                    # gone. Preserve an explicit native failure for local logs.
                    import logging

                    logging.getLogger(__name__).exception("External window cleanup failed")

            # Do not leave the secondary JWL hidden at process exit. Native
            # restoration is bounded by its backend deadline and runs off GUI.
            threading.Thread(target=cleanup, name="External window cleanup").start()
        self._token = uuid.uuid4().hex  # Ignore queued replies from the previous cycle.
        if self._prior:
            self._request_obs("restore", {"prior": self._prior})
        self._state("idle", "Mídia externa parada para encerramento.")
