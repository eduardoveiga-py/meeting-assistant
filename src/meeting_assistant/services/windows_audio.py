"""Small Windows Core Audio helpers used by the operator controls.

The audio mix itself remains owned by OBS.  This module only controls the
rendering session belonging to WhatsApp so an operator can keep WhatsApp
participants silent in the hall without muting Zoom, JW Library, or the
system output.  The Windows-only dependency is imported lazily so the rest
of the project and its tests remain importable on non-Windows builders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from PySide6.QtCore import QObject, QTimer, Signal


class AudioSession(Protocol):
    """Minimal session surface required by :class:`WhatsAppAudioGuard`."""

    def get_muted(self) -> bool: ...

    def set_muted(self, muted: bool) -> None: ...

    def matches_whatsapp(self) -> bool: ...

    @property
    def key(self) -> str: ...


@dataclass(frozen=True, slots=True)
class AudioSessionSnapshot:
    key: str
    process_name: str
    display_name: str
    identifier: str


class _PycawSession:
    """Adapter around one pycaw session.

    pycaw has kept the ``SimpleAudioVolume`` surface stable, but packaged
    Windows applications can expose a useful display name while their
    process name is ``ApplicationFrameHost.exe``.  Matching therefore checks
    both the process and display/identifier text.
    """

    def __init__(self, session: Any) -> None:
        self._session = session
        process = getattr(session, "Process", None)
        self.process_name = _process_name(process)
        self.display_name = _text_value(session, "DisplayName", "displayName")
        self.identifier = _text_value(session, "Identifier", "identifier")
        pid = getattr(process, "pid", None) if process is not None else None
        self.key = "|".join((str(pid or ""), self.identifier, self.display_name, self.process_name))

    def matches_whatsapp(self) -> bool:
        haystack = " ".join(
            (self.process_name, self.display_name, self.identifier)
        ).casefold()
        return "whatsapp" in haystack

    def get_muted(self) -> bool:
        return bool(self._session.SimpleAudioVolume.GetMute())

    def set_muted(self, muted: bool) -> None:
        self._session.SimpleAudioVolume.SetMute(1 if muted else 0, None)

    def snapshot(self) -> AudioSessionSnapshot:
        return AudioSessionSnapshot(
            key=self.key,
            process_name=self.process_name,
            display_name=self.display_name,
            identifier=self.identifier,
        )


def _text_value(obj: Any, *names: str) -> str:
    for name in names:
        value = getattr(obj, name, "")
        if callable(value):
            try:
                value = value()
            except Exception:
                value = ""
        if value:
            return str(value)
    return ""


def _process_name(process: Any) -> str:
    if process is None:
        return ""
    value = getattr(process, "name", "")
    if callable(value):
        try:
            value = value()
        except Exception:
            value = ""
    return str(value or "")


def pycaw_sessions() -> list[_PycawSession]:
    """Return current Windows render sessions, or raise a useful error."""

    if __import__("sys").platform != "win32":
        raise RuntimeError("O controle de sessões de áudio requer Windows 11.")
    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError as exc:
        raise RuntimeError(
            "Dependência pycaw ausente. Reinstale o Meeting Assistant para ativar o controle de áudio."
        ) from exc
    return [_PycawSession(session) for session in AudioUtilities.GetAllSessions()]


class SessionProvider(Protocol):
    def sessions(self) -> list[AudioSession]: ...


class DefaultSessionProvider:
    def sessions(self) -> list[AudioSession]:
        return pycaw_sessions()


class WhatsAppAudioGuard(QObject):
    """Safely mute/unmute WhatsApp's speaker sessions.

    The guard is deliberately fail-closed: it starts muted, refuses to
    unmute when no WhatsApp session is visible, and reapplies the requested
    state while a call creates/recreates audio sessions.
    """

    state_changed = Signal(bool, str)

    def __init__(
        self,
        provider: SessionProvider | None = None,
        parent: QObject | None = None,
        *,
        refresh_ms: int = 1000,
    ) -> None:
        super().__init__(parent)
        self._provider = provider or DefaultSessionProvider()
        self._desired_muted = True
        self._running = False
        self._last_message = "WhatsApp: retorno silenciado por segurança."
        self._last_emitted: tuple[bool, str] | None = None
        self._original: dict[str, bool] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(max(250, refresh_ms))
        self._timer.timeout.connect(self.refresh)

    @property
    def muted(self) -> bool:
        return self._desired_muted

    @property
    def last_message(self) -> str:
        return self._last_message

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.refresh()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._running = False
        self._restore_original_states()

    def toggle(self) -> bool:
        """Toggle the desired state; return whether it was applied."""

        if not self._desired_muted:
            self._desired_muted = True
            self.refresh()
            return True

        sessions = self._safe_matching_sessions()
        if not sessions:
            if sessions is not None:
                self._emit(
                    self._desired_muted,
                    "WhatsApp ainda não possui uma sessão de áudio. O retorno continua silenciado.",
                )
            return False
        self._desired_muted = False
        return self._apply(sessions)

    def set_muted(self, muted: bool) -> bool:
        muted = bool(muted)
        if not muted:
            sessions = self._safe_matching_sessions()
            if not sessions:
                if sessions is not None:
                    self._emit(
                        True,
                        "WhatsApp ainda não possui uma sessão de áudio. O retorno continua silenciado.",
                    )
                return False
        self._desired_muted = muted
        self.refresh()
        return True

    def refresh(self) -> None:
        try:
            sessions = self._matching_sessions()
            if not sessions:
                self._emit(
                    self._desired_muted,
                    "WhatsApp não encontrado; o retorno ficará silenciado quando a chamada iniciar.",
                )
                return
            self._apply(sessions)
        except Exception as exc:
            # The app must never turn an audio-control failure into a meeting
            # failure.  Keep the safe desired state and expose a clear status.
            self._fail_safe(exc)

    def snapshots(self) -> list[AudioSessionSnapshot]:
        snapshots: list[AudioSessionSnapshot] = []
        for session in self._matching_sessions():
            snapshot = getattr(session, "snapshot", None)
            if callable(snapshot):
                snapshots.append(snapshot())
            else:
                snapshots.append(
                    AudioSessionSnapshot(
                        key=session.key,
                        process_name="",
                        display_name="",
                        identifier="",
                    )
                )
        return snapshots

    def _matching_sessions(self) -> list[AudioSession]:
        return [session for session in self._provider.sessions() if session.matches_whatsapp()]

    def _safe_matching_sessions(self) -> list[AudioSession] | None:
        try:
            return self._matching_sessions()
        except Exception as exc:
            self._fail_safe(exc)
            return None

    def _fail_safe(self, exc: Exception) -> None:
        self._desired_muted = True
        self._emit(
            True,
            f"Controle do retorno do WhatsApp indisponível; estado seguro mantido ({exc}).",
        )

    def _apply(self, sessions: list[AudioSession]) -> bool:
        failed = 0
        for session in sessions:
            if session.key not in self._original:
                self._original[session.key] = bool(session.get_muted())
            try:
                session.set_muted(self._desired_muted)
                if bool(session.get_muted()) != self._desired_muted:
                    failed += 1
            except Exception:
                failed += 1
        if failed:
            # An unmute failure must never leave the UI claiming that the
            # remote WhatsApp audio is live.  Return to the safe state and
            # make a best-effort second mute pass.
            if not self._desired_muted:
                self._desired_muted = True
                for session in sessions:
                    try:
                        session.set_muted(True)
                    except Exception:
                        pass
            self._emit(
                self._desired_muted,
                "Nem todas as sessões do WhatsApp confirmaram o mute; verifique o áudio do salão.",
            )
            return False
        verb = "silenciado" if self._desired_muted else "liberado"
        self._emit(self._desired_muted, f"Retorno do WhatsApp {verb} no salão.")
        return True

    def _restore_original_states(self) -> None:
        if not self._original:
            return
        try:
            sessions = {session.key: session for session in self._matching_sessions()}
            for key, muted in self._original.items():
                session = sessions.get(key)
                if session is not None:
                    session.set_muted(muted)
        except Exception:
            # Restoration is best effort at shutdown and must not delay exit.
            return

    def _emit(self, muted: bool, message: str) -> None:
        state = (bool(muted), message)
        if state == self._last_emitted:
            return
        self._last_emitted = state
        self._last_message = message
        self.state_changed.emit(*state)


class FakeAudioSession:
    """Tiny test helper kept here so behavior can be tested without Windows."""

    def __init__(self, key: str, *, whatsapp: bool = True, muted: bool = False) -> None:
        self.key = key
        self.whatsapp = whatsapp
        self.muted = muted
        self.set_calls: list[bool] = []

    def matches_whatsapp(self) -> bool:
        return self.whatsapp

    def get_muted(self) -> bool:
        return self.muted

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)
        self.set_calls.append(self.muted)


class FakeSessionProvider:
    def __init__(self, sessions: list[AudioSession] | None = None) -> None:
        self._sessions = list(sessions or [])

    def sessions(self) -> list[AudioSession]:
        return list(self._sessions)


__all__ = [
    "AudioSessionSnapshot",
    "FakeAudioSession",
    "FakeSessionProvider",
    "WhatsAppAudioGuard",
    "pycaw_sessions",
]
