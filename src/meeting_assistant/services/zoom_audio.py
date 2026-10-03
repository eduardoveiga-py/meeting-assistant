"""Serialized, verified actions on the operator's Zoom microphone."""

import logging
import sys
import threading
import time
from functools import partial

from PySide6.QtCore import QObject, Signal

from meeting_assistant.services.zoom_audio_controls import (
    AccessibleMicrophone,
    MicrophoneError,
    find_control,
    microphone_state,
)
from meeting_assistant.services.zoom_audio_session import ZoomAudioSession

__all__ = ["ZoomAudio", "find_control", "microphone_state", "perform"]
logger = logging.getLogger(__name__)


def cancel_worker(cancel, wake, *_args):
    """Also wake idle workers if their Qt owner is destroyed without closeEvent."""
    with wake:
        cancel.set()
        wake.notify_all()


def measured_call(callback, diagnostic, key):
    started = time.monotonic()
    try:
        return callback()
    finally:
        if diagnostic is not None:
            diagnostic[key] = round((time.monotonic() - started) * 1000)


def perform(action, finder=None, cancel=None, *, diagnostic=None):
    if action not in {"inspect", "mute", "unmute", "toggle"}:
        raise MicrophoneError("invalid_action", "Ação de microfone desconhecida.")
    if cancel is not None and cancel.is_set():
        raise RuntimeError("Operação cancelada.")
    finder = finder or find_control
    button, state = measured_call(finder, diagnostic, "read_state_ms")
    if state not in {"live", "muted"}:
        raise MicrophoneError(
            "state_unavailable", "Zoom não informou o estado do microfone; nenhuma ação enviada."
        )
    desired = {"mute": "muted", "unmute": "live"}.get(action)
    if action == "toggle":
        desired = "live" if state == "muted" else "muted"
    if diagnostic is not None:
        diagnostic.update(
            before_state=state, target_state=desired or state,
            dispatch_attempted=False, dispatch_returned=False,
        )
    if desired and state != desired:
        if cancel is not None and cancel.is_set():
            raise RuntimeError("Operação cancelada.")
        if diagnostic is not None:
            diagnostic["dispatch_attempted"] = True
        measured_call(button.invoke, diagnostic, "invoke_ms")
        if diagnostic is not None:
            diagnostic["dispatch_returned"] = True
        started = time.monotonic()
        deadline = started + 1.8
        try:
            # Check immediately; only wait BETWEEN unsuccessful observations.
            # The session refreshes this one control instead of rescanning Zoom.
            for attempt in range(19):
                if cancel is not None and cancel.is_set():
                    raise RuntimeError("Operação cancelada.")
                if attempt and time.monotonic() >= deadline:
                    break
                try:
                    observed_button, state = finder()
                except MicrophoneError as exc:
                    # A rebuilding tree is read again, never toggled twice.
                    if diagnostic is not None:
                        diagnostic["confirmation_read_error"] = exc.code
                else:
                    if diagnostic is not None:
                        diagnostic["last_observed_state"] = (
                            state if state in {"live", "muted"} else "unknown"
                        )
                    if isinstance(button, AccessibleMicrophone) and (
                        not isinstance(observed_button, AccessibleMicrophone)
                        or observed_button.identity != button.identity
                    ):
                        raise MicrophoneError(
                            "control_changed",
                            "O controle do Zoom mudou durante a ação. Confira seu microfone.",
                        )
                    if state == desired:
                        return state
                if attempt < 18:
                    delay = min(0.1, max(0, deadline - time.monotonic()))
                    if delay <= 0:
                        break
                    if cancel is not None:
                        if cancel.wait(delay):
                            raise RuntimeError("Operação cancelada.")
                    else:
                        time.sleep(delay)
        finally:
            if diagnostic is not None:
                diagnostic["confirmation_ms"] = round((time.monotonic() - started) * 1000)
        raise MicrophoneError(
            "not_confirmed", "Zoom não confirmou a mudança. Confira seu microfone; nenhuma ação repetida."
        )
    return state


class ZoomAudio(QObject):
    result = Signal(str, str)
    activity = Signal(bool)
    command_finished = Signal(str, str)
    diagnostic = Signal(dict)

    def __init__(self, parent=None, *, finder=None, platform=None):
        super().__init__(parent)
        self.busy = False
        self._finder = finder
        self._platform = platform or sys.platform
        self._cancel = threading.Event()
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)
        self._thread = None
        self._retiring = False
        self._pending = None
        self._next = None
        self._command_pending = False
        self._stopped = False
        self._last_inspection = None
        self.destroyed.connect(partial(cancel_worker, self._cancel, self._wake))

    @property
    def command_pending(self):
        with self._lock:
            return self._command_pending

    def request(self, action="inspect"):
        if action not in {"inspect", "mute", "unmute", "toggle"}:
            raise ValueError("Ação de microfone desconhecida.")
        command = action != "inspect"
        queued_at = time.monotonic()
        with self._lock:
            if self._stopped or self._cancel.is_set() or (command and self._command_pending):
                return False
            if self.busy:
                if not command:
                    return False
                # Keep one explicit click when background inspection is busy.
                self._pending = (action, queued_at)
                self._command_pending = True
                start = False
            else:
                self.busy = True
                self._command_pending = command
                self._next = (action, queued_at)
                start = self._retiring or self._thread is None or not self._thread.is_alive()
                if start:
                    self._retiring = False
                    self._thread = threading.Thread(
                        target=self._work, daemon=True, name="Zoom audio control"
                    )
                    worker = self._thread
                else:
                    self._wake.notify()
        if command:
            self.activity.emit(True)
        if start:
            try:
                worker.start()
            except RuntimeError:
                with self._lock:
                    pending_command = self._command_pending
                    self._pending = self._next = None
                    self.busy = self._command_pending = False
                self.activity.emit(False)
                message = "Não foi possível iniciar o controle de microfone. Tente novamente."
                self.diagnostic.emit({
                    "diagnostic_revision": 2, "action": action,
                    "code": "worker_start_failed", "state": "unknown",
                })
                self.result.emit("unknown", message)
                if pending_command:
                    self.command_finished.emit("unknown", message)
                return False
        return True

    def _execute(self, action, queued_at, started, finder):
        details = {
            "diagnostic_revision": 2, "action": action,
            "queue_wait_ms": round((started - queued_at) * 1000),
            "backend_setup_ms": round((time.monotonic() - started) * 1000),
        }
        state = "unknown"
        message = "Microfone não confirmado."
        try:
            if isinstance(finder, ZoomAudioSession):
                finder.begin(details)
            state = perform(action, finder, self._cancel, diagnostic=details)
            details["code"] = "observed" if action == "inspect" else "confirmed"
            message = "Microfone Zoom confirmado " + ("aberto." if state == "live" else "silenciado.")
        except MicrophoneError as exc:
            details["code"] = exc.code
            message = str(exc)
        except Exception as exc:
            # Exception text can include inaccessible UI/participant data.
            details.update(code="backend_error", error_type=type(exc).__name__)
            message = (
                "Falha na acessibilidade do Zoom (" + type(exc).__name__ + "). "
                "Confira os controles da reunião."
            )
            if isinstance(exc, ImportError):
                message = (
                    "Dependências do controle Zoom ausentes. Feche o app e execute "
                    "scripts/run.ps1 para atualizar o ambiente."
                )
            hresult = getattr(exc, "hresult", None)
            if isinstance(hresult, int):
                details["hresult"] = f"0x{hresult & 0xFFFFFFFF:08X}"
                if hresult & 0xFFFFFFFF == 0x80070005:
                    message = (
                        "Acesso ao Zoom negado. Abra Zoom e Meeting Assistant "
                        "com o mesmo nível de permissão."
                    )
        # stop() must finish before Qt destroys this QObject. Hold the short
        # notification section together; native calls/waits never hold this lock.
        with self._lock:
            if self._cancel.is_set():
                return
            details["state"] = state
            # Repeated polling reports only changes; explicit actions always report.
            observation = {key: value for key, value in details.items() if not key.endswith("_ms")}
            if action != "inspect" or observation != self._last_inspection:
                self._last_inspection = observation if action == "inspect" else self._last_inspection
                self.diagnostic.emit(dict(
                    details, elapsed_ms=round((time.monotonic() - started) * 1000),
                    request_elapsed_ms=round((time.monotonic() - queued_at) * 1000),
                ))
            self.result.emit(state, message)
            if action != "inspect":
                self.command_finished.emit(state, message)

    def _work(self):
        com, session, finder = None, None, None
        try:
            while True:
                with self._wake:
                    while self._next is None and not self._cancel.is_set():
                        self._wake.wait()
                    if self._cancel.is_set():
                        break
                    action, queued_at = self._next
                    self._next = None
                started = time.monotonic()
                setup_failed = False
                finder = self._finder
                if finder is None:
                    try:
                        if self._platform != "win32":
                            raise MicrophoneError(
                                "unsupported_platform", "Controle do microfone disponível apenas no Windows."
                            )
                        if com is None:
                            import pythoncom

                            pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
                            com = pythoncom
                            session = ZoomAudioSession(lambda **kwargs: find_control(**kwargs))
                        finder = session
                    except Exception as exc:
                        setup_failed = True
                        def unavailable(error=exc):
                            raise error

                        finder = unavailable
                self._execute(action, queued_at, started, finder)
                with self._wake:
                    if self._cancel.is_set():
                        break
                    if self._pending is None or self._stopped:
                        self.busy = False
                        self._command_pending = False
                        self.activity.emit(False)
                        if setup_failed:
                            # There is no apartment/session worth retaining.
                            # Allow the next request to start a new worker even
                            # if this one is still finishing its cleanup.
                            self._retiring = True
                            break
                    else:
                        self._next, self._pending = self._pending, None
        finally:
            finder = None
            if session is not None:
                session.clear()
                session = None
            if com is not None:
                try:
                    com.CoUninitialize()
                except Exception as exc:
                    # Qt may already be destroyed at shutdown. Log only type,
                    # without emitting a late signal or private exception text.
                    logger.warning("Zoom microphone COM cleanup failed (%s)", type(exc).__name__)
            with self._lock:
                if self._thread is threading.current_thread():
                    self._retiring = True
                    self.busy = False
                    self._pending = self._next = None
                    self._command_pending = False
                if not self._cancel.is_set():
                    self.activity.emit(False)

    def stop(self):
        with self._wake:
            self._stopped = True
            self._pending = self._next = None
            self._cancel.set()
            self._wake.notify_all()
