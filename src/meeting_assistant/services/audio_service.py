"""Intelligent WASAPI audio monitor with fast attack and anti-dramatic-pause hold."""

from __future__ import annotations

import logging
import sys
import threading
import time

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class AudioService(QObject):
    """Monitors WASAPI audio peak meters for media players, preventing premature cuts during pauses."""

    media_audio_started = Signal()
    media_audio_stopped = Signal()
    peak_level_changed = Signal(float)

    def __init__(
        self,
        media_player_executables: list[str] | None = None,
        audio_trigger_threshold: float = 0.015,
        audio_silence_hold_seconds: float = 4.5,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.media_player_executables = [
            exe.casefold()
            for exe in (media_player_executables or ["JWLibrary.exe", "vlc.exe", "MediaPlayer.exe"])
        ]
        self.audio_trigger_threshold = audio_trigger_threshold
        self.audio_silence_hold_seconds = audio_silence_hold_seconds

        self._in_media_audio = False
        self._consecutive_attack_count = 0
        self._silence_start_time: float | None = None
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._poll_interval = 0.1  # 100ms interval for 2-read ~200ms attack

    @property
    def is_playing(self) -> bool:
        return self._in_media_audio

    def start(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._run,
            name="AudioService-WASAPI",
            daemon=True,
        )
        self._worker_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)

    def reset(self) -> None:
        """Reset internal detection state."""
        self._in_media_audio = False
        self._consecutive_attack_count = 0
        self._silence_start_time = None

    def _run(self) -> None:
        com_initialized = False
        try:
            import comtypes

            comtypes.CoInitialize()
            com_initialized = True
        except Exception:
            pass

        try:
            while not self._stop_event.is_set():
                peak = self._poll_media_peak()
                self._evaluate_peak(peak)
                self._stop_event.wait(self._poll_interval)
        finally:
            if com_initialized:
                try:
                    import comtypes

                    comtypes.CoUninitialize()
                except Exception:
                    pass

    def _poll_media_peak(self) -> float:
        """Poll the highest peak meter value among matching media player sessions."""
        if sys.platform != "win32":
            return 0.0

        try:
            from pycaw.pycaw import AudioUtilities, IAudioMeterInformation

            sessions = AudioUtilities.GetAllSessions()
            max_peak = 0.0

            for session in sessions:
                if not session.Process:
                    continue
                proc_name = session.Process.name().casefold()
                if proc_name in self.media_player_executables:
                    try:
                        meter = session._ctl.QueryInterface(IAudioMeterInformation)
                        peak = float(meter.GetPeakValue())
                        if peak > max_peak:
                            max_peak = peak
                    except Exception:
                        continue

            return max_peak
        except Exception:
            return 0.0

    def _evaluate_peak(self, peak: float) -> None:
        """Process peak with attack counter and release silence timer."""
        self.peak_level_changed.emit(peak)

        if peak >= self.audio_trigger_threshold:
            self._consecutive_attack_count += 1
            # Reset silence timer since audio is active
            self._silence_start_time = None

            # Fast attack: 2 consecutive positive reads (~200ms)
            if self._consecutive_attack_count >= 2 and not self._in_media_audio:
                self._in_media_audio = True
                logger.info("Mídia com áudio detectada (peak=%.3f). Mutando microfone.", peak)
                self.media_audio_started.emit()

        else:
            self._consecutive_attack_count = 0

            # If audio dropped below threshold during active video playback
            if self._in_media_audio:
                now = time.monotonic()
                if self._silence_start_time is None:
                    self._silence_start_time = now
                else:
                    elapsed = now - self._silence_start_time
                    if elapsed >= self.audio_silence_hold_seconds:
                        self._in_media_audio = False
                        self._silence_start_time = None
                        logger.info(
                            "Silêncio prolongado (%.1fs). Retornando para câmera do orador.",
                            elapsed,
                        )
                        self.media_audio_stopped.emit()
