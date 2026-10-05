from PySide6.QtCore import QObject, QTimer, Signal

from meeting_assistant.services.windows_audio import DefaultSessionProvider, SessionProvider


class JWLMediaDuckingService(QObject):
    """Monitors JW Library audio peak and emits ducking signals to mute the mic."""

    ducking_started = Signal()
    ducking_ended = Signal()

    def __init__(self, settings_provider, provider: SessionProvider | None = None) -> None:
        super().__init__()
        self.provider = provider or DefaultSessionProvider()
        self.settings_provider = settings_provider
        self._is_ducking = False
        self._silent_ticks = 0
        self._ducking_threshold = 0.001
        self._hold_ticks = 10  # 1.0 seconds (10 * 100ms)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check_peak)

    def start(self):
        self._timer.start(100)

    def stop(self):
        self._timer.stop()
        if self._is_ducking:
            self._is_ducking = False
            self.ducking_ended.emit()

    def _check_peak(self):
        try:
            if not self.settings_provider().auto_mute_mic_for_jwl_media:
                return
            peak = 0.0
            found_jwl = False
            for session in self.provider.sessions():
                if session.matches_jwl():
                    found_jwl = True
                    peak = max(peak, session.get_peak_value())

            # Debugging output to temp file
            import tempfile, os
            with open(os.path.join(tempfile.gettempdir(), 'ducking_debug.log'), 'a') as f:
                f.write(f"Found JWL: {found_jwl}, Peak: {peak}, Ducking: {self._is_ducking}
")

            if peak > self._ducking_threshold:
                self._silent_ticks = 0
                if not self._is_ducking:
                    self._is_ducking = True
                    self.ducking_started.emit()
            else:
                if self._is_ducking:
                    self._silent_ticks += 1
                    if self._silent_ticks >= self._hold_ticks:
                        self._is_ducking = False
                        self.ducking_ended.emit()
        except Exception as e:
            import sys
            print(f'DUCKING ERROR: {e}', file=sys.stderr)
