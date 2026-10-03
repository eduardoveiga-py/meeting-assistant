"""Normal, asynchronous closure. Host prompts are reported as pending."""

import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from meeting_assistant.services.window_inventory import WindowBackend, main_jwl

TARGETS = {"obs64.exe", "obs32.exe", "obs.exe", "zoom.exe", "jwlibrary.exe", "whatsapp.exe"}


@dataclass(frozen=True)
class EndSummary:
    requested: tuple[str, ...]
    pending: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def complete(self):
        return not self.pending and not self.errors

    @property
    def message(self):
        if self.complete:
            return "Encerramento confirmado dos programas detectados."
        return (
            "Encerramento pendente: "
            + "; ".join((*self.pending, *self.errors))
            + ". Confira confirmações nos programas."
        )


class MeetingShutdownService(QObject):
    progress_changed = Signal(str)
    finished = Signal(object)

    def __init__(self, *, backend=None, timeout=8):
        super().__init__()
        self.backend = backend or WindowBackend()
        self.timeout = timeout
        self._thread = None
        self._cancel = threading.Event()

    @property
    def busy(self):
        return bool(self._thread and self._thread.is_alive())

    def stop(self):
        self._cancel.set()

    def start(self):
        if self.busy:
            return False
        self._cancel.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="Meeting shutdown")
        self._thread.start()
        return True

    def _run(self):
        requested, errors, pending = [], [], []
        try:
            windows = [w for w in self.backend.windows() if w.process in TARGETS]
            # Close a main window per process. Do not close a secondary call
            # window to approximate ending the call; hidden OBS is included.
            processes = {}
            for window in windows:
                processes.setdefault((window.pid, window.created), []).append(window)
            monitors = self.backend.monitors()
            work = next((m["work"] for m in monitors if m["primary"]), None)
            jwl = main_jwl(windows, work) if work else None
            if hasattr(self.backend, "processes"):
                for pid, created, name in self.backend.processes():
                    if (pid, created) not in processes:
                        errors.append(name + " sem janela disponível para fechamento normal")
            tracked = []
            for candidates in processes.values():
                primary = [
                    w
                    for w in candidates
                    if (w == jwl)
                    or (w.process.startswith("obs") and w.title.startswith("OBS"))
                    or (
                        w.process == "zoom.exe"
                        and (
                            w.meeting_controls
                            or w.class_name in {"ZPPTopWndClass", "ConfMultiTabContentWndClass"}
                        )
                    )
                    or (w.process == "whatsapp.exe" and w.title)
                ]
                if not primary:
                    errors.append(candidates[0].process + " sem janela principal identificada")
                    continue
                # Prefer the operator's main/root window over an owned dialog.
                window = primary[0]
                tracked.append(window)
                self.progress_changed.emit(f"Solicitando fechamento normal: {window.process}")
                try:
                    self.backend.close(window)
                    requested.append(window.process)
                except Exception:
                    errors.append(window.process + " não aceitou o pedido de fechamento")
            deadline = time.monotonic() + self.timeout
            while not self._cancel.is_set():
                pending = sorted({w.process for w in tracked if self.backend.same_process(w)})
                if not pending or time.monotonic() >= deadline:
                    break
                self._cancel.wait(0.2)
            if self._cancel.is_set():
                errors.append("verificação cancelada")
        except Exception:
            errors.append("inventário dos programas indisponível")
        self.finished.emit(EndSummary(tuple(sorted(set(requested))), tuple(pending), tuple(errors)))
