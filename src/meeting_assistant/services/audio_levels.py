"""Read-only OBS meter subscription with latest-value delivery."""

import math
import threading
import time

import obsws_python as obs

from meeting_assistant.services.obs_audio import MIC, SOURCES


def summarize(inputs):
    voice, media = None, None
    for row in inputs:
        name = row.get("inputName")
        if name not in SOURCES:
            continue
        # OBS channel tuples are magnitude, peak, input peak in linear amplitude.
        peaks = [channel[1] for channel in row.get("inputLevelsMul", []) if len(channel) > 1]
        if not peaks:
            continue
        peak = max(peaks)
        db = max(-60.0, min(0.0, 20 * math.log10(peak))) if peak > 0 else -60.0
        if name == MIC:
            voice = db
        else:
            media = max(media, db) if media is not None else db
    return voice, media


class AudioLevels:
    def __init__(self):
        self.config = None
        self.latest = (0.0, None, None)
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name="OBS audio levels")
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def on_input_volume_meters(self, data):
        self.latest = (time.monotonic(), *summarize(data.inputs))

    def _run(self):
        while not self.stop_event.is_set():
            client = None
            try:
                config = self.config
                if config is None:
                    self.stop_event.wait(1)
                    continue
                client = obs.EventClient(
                    host=config.host, port=config.port, password=config.password, timeout=2, subs=1 << 16
                )
                client.callback.register(self.on_input_volume_meters)
                while not self.stop_event.wait(1) and config == self.config and client.worker.is_alive():
                    pass
            except Exception:
                self.latest = (0.0, None, None)
            finally:
                if client:
                    try:
                        client.disconnect()
                    except Exception:
                        pass
            self.stop_event.wait(2)
