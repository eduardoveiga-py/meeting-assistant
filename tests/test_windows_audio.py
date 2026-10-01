from meeting_assistant.services.windows_audio import (
    FakeAudioSession,
    FakeSessionProvider,
    WhatsAppAudioGuard,
)


def test_guard_starts_fail_closed_and_mutes_whatsapp_only():
    whatsapp = FakeAudioSession("whatsapp", muted=False)
    other = FakeAudioSession("zoom", whatsapp=False, muted=False)
    guard = WhatsAppAudioGuard(FakeSessionProvider([whatsapp, other]))

    events = []
    guard.state_changed.connect(lambda muted, message: events.append((muted, message)))
    guard.refresh()

    assert guard.muted is True
    assert whatsapp.muted is True
    assert other.muted is False
    assert events[-1][0] is True

    guard.refresh()
    assert len(events) == 1


def test_unmute_requires_a_live_whatsapp_session_and_then_applies():
    provider = FakeSessionProvider([])
    guard = WhatsAppAudioGuard(provider)
    guard.refresh()

    assert guard.set_muted(False) is False
    assert guard.muted is True

    whatsapp = FakeAudioSession("whatsapp", muted=True)
    provider._sessions.append(whatsapp)
    assert guard.set_muted(False) is True
    assert guard.muted is False
    assert whatsapp.muted is False


def test_new_whatsapp_session_inherits_current_safe_state():
    whatsapp = FakeAudioSession("whatsapp", muted=False)
    provider = FakeSessionProvider([whatsapp])
    guard = WhatsAppAudioGuard(provider)
    guard.refresh()
    assert whatsapp.muted is True

    provider._sessions.clear()
    guard.refresh()
    replacement = FakeAudioSession("whatsapp-replacement", muted=False)
    provider._sessions.append(replacement)
    guard.refresh()
    assert replacement.muted is True


def test_stop_restores_original_whatsapp_state():
    whatsapp = FakeAudioSession("whatsapp", muted=False)
    guard = WhatsAppAudioGuard(FakeSessionProvider([whatsapp]))
    guard.refresh()
    assert whatsapp.muted is True

    guard.stop()
    assert whatsapp.muted is False


def test_toggle_unmutes_and_mutes_without_touching_other_sessions():
    whatsapp = FakeAudioSession("whatsapp", muted=False)
    other = FakeAudioSession("other", whatsapp=False, muted=False)
    guard = WhatsAppAudioGuard(FakeSessionProvider([whatsapp, other]))
    guard.refresh()

    assert guard.toggle() is True
    assert guard.muted is False
    assert whatsapp.muted is False
    assert other.muted is False

    assert guard.toggle() is True
    assert guard.muted is True
    assert whatsapp.muted is True
    assert other.muted is False


def test_failed_unmute_returns_to_safe_muted_state():
    class FailingUnmute(FakeAudioSession):
        def set_muted(self, muted: bool) -> None:
            if not muted:
                raise RuntimeError("session rejected unmute")
            super().set_muted(muted)

    whatsapp = FailingUnmute("whatsapp", muted=False)
    guard = WhatsAppAudioGuard(FakeSessionProvider([whatsapp]))
    guard.refresh()

    assert guard.toggle() is False
    assert guard.muted is True
    assert whatsapp.muted is True


def test_provider_failure_fails_closed_even_after_unmute():
    whatsapp = FakeAudioSession("whatsapp", muted=True)

    class FailingProvider:
        def __init__(self):
            self.failed = False

        def sessions(self):
            if self.failed:
                raise RuntimeError("audio service unavailable")
            return [whatsapp]

    provider = FailingProvider()
    guard = WhatsAppAudioGuard(provider)
    assert guard.set_muted(False) is True
    assert guard.muted is False

    provider.failed = True
    guard.refresh()
    assert guard.muted is True
    assert "estado seguro" in guard.last_message
