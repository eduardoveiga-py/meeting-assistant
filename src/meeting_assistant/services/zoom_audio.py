"""Serialized, verified actions on the operator's Zoom microphone."""

import sys
import threading
import time

from PySide6.QtCore import QObject, Signal

from meeting_assistant.services.zoom_audio_controls import (
    AccessibleMicrophone,
    MicrophoneError,
    find_control,
    microphone_state,
)

__all__ = ["ZoomAudio", "find_control", "microphone_state", "perform"]


def perform(action, finder=None, cancel=None, *, diagnostic=None):
    if action not in {"inspect", "mute", "unmute", "toggle"}:
        raise MicrophoneError("invalid_action", "Ação de microfone desconhecida.")
    if cancel is not None and cancel.is_set():
        raise RuntimeError("Operação cancelada.")
    finder = finder or find_control
    button, state = finder()
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
        button.invoke()
        if diagnostic is not None:
            diagnostic["dispatch_returned"] = True
        for _ in range(12):
            if cancel is not None:
                if cancel.wait(0.15):
                    raise RuntimeError("Operação cancelada.")
            else:
                time.sleep(0.15)
            try:
                observed_button, state = finder()
            except MicrophoneError:
                # The accessibility tree may briefly change after dispatch.
                # Re-read only; a second toggle could undo the first.
                continue
            if diagnostic is not None:
                diagnostic["last_observed_state"] = state if state in {"live", "muted"} else "unknown"
            if isinstance(button, AccessibleMicrophone) and (
                not isinstance(observed_button, AccessibleMicrophone)
                or observed_button.identity != button.identity
            ):
                raise MicrophoneError(
                    "control_changed", "O controle do Zoom mudou durante a ação. Confira seu microfone."
                )
            if state == desired:
                return state
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
        self._thread = None
        self._pending = None
        self._command_pending = False
        self._stopped = False
        self._last_inspection = None

    @property
    def command_pending(self):
        with self._lock:
            return self._command_pending

    def request(self, action="inspect"):
        if action not in {"inspect", "mute", "unmute", "toggle"}:
            raise ValueError("Ação de microfone desconhecida.")
        command = action != "inspect"
        with self._lock:
            if self._stopped or (command and self._command_pending):
                return False
            if self.busy:
                if not command:
                    return False
                # Keep one explicit click when background inspection is busy.
                self._pending = action
                self._command_pending = True
                start = False
            else:
                self.busy = True
                self._command_pending = command
                start = True
                self._thread = threading.Thread(
                    target=self._work, args=(action,), daemon=True, name="Zoom audio control"
                )
                worker = self._thread
        if command:
            self.activity.emit(True)
        if start:
            try:
                worker.start()
            except RuntimeError:
                with self._lock:
                    pending_command = self._command_pending
                    self._pending = None
                    self.busy = self._command_pending = False
                self.activity.emit(False)
                message = "Não foi possível iniciar o controle de microfone. Tente novamente."
                self.diagnostic.emit({
                    "diagnostic_revision": 1, "action": action,
                    "code": "worker_start_failed", "state": "unknown",
                })
                self.result.emit("unknown", message)
                if pending_command:
                    self.command_finished.emit("unknown", message)
                return False
        return True

    def _execute(self, action):
        com = None
        details = {"diagnostic_revision": 1, "action": action}
        started = time.monotonic()
        state = "unknown"
        message = "Microfone não confirmado."
        try:
            if self._finder is None:
                if self._platform != "win32":
                    raise MicrophoneError(
                        "unsupported_platform", "Controle do microfone disponível apenas no Windows."
                    )
                import pythoncom

                # UI Automation runs in a COM MTA worker, never the GUI thread.
                pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
                com = pythoncom
            finder = self._finder or (lambda: find_control(diagnostic=details))
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
        finally:
            if com is not None:
                try:
                    com.CoUninitialize()
                except Exception as exc:
                    details.update(code="com_cleanup_error", error_type=type(exc).__name__)
                    state = "unknown"
                    message = "Falha ao encerrar a consulta de acessibilidade. Confira seu microfone no Zoom."
        # stop() must finish before Qt destroys this QObject. Hold the short
        # notification section together; native calls/waits never hold this lock.
        with self._lock:
            if self._cancel.is_set():
                return
            details["state"] = state
            # Repeated polling reports only changes; explicit actions always report.
            if action != "inspect" or details != self._last_inspection:
                self._last_inspection = dict(details) if action == "inspect" else self._last_inspection
                self.diagnostic.emit(dict(details, elapsed_ms=round((time.monotonic() - started) * 1000)))
            self.result.emit(state, message)
            if action != "inspect":
                self.command_finished.emit(state, message)

    def _work(self, action):
        try:
            while not self._cancel.is_set():
                self._execute(action)
                with self._lock:
                    if self._pending is None or self._stopped:
                        self.busy = False
                        self._command_pending = False
                        break
                    action, self._pending = self._pending, None
        finally:
            with self._lock:
                # A new request may have started after this worker became idle.
                # Its ownership/flags must not be overwritten by our cleanup.
                if self._thread is threading.current_thread():
                    self.busy = False
                    self._pending = None
                    self._command_pending = False
                if not self._cancel.is_set():
                    self.activity.emit(False)

    def stop(self):
        with self._lock:
            self._stopped = True
            self._pending = None
            self._cancel.set()
