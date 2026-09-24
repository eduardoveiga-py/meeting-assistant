"""Independent low-resolution OBS preview; latest frame only, no queue backlog."""

import base64
import threading
import time

import obsws_python as obs


class PreviewStream:
    def __init__(self, factory=obs.ReqClient):
        self.factory = factory
        self.config = None
        self.scene = None
        self.visible = True
        self.frame = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name="OBS preview")
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def set_scene(self, scene):
        with self.lock:
            if scene != self.scene:
                self.scene = scene
                self.frame = None

    def take(self):
        with self.lock:
            frame, self.frame = self.frame, None
        return frame

    def _run(self):
        client = None
        config = None
        try:
            while not self.stop_event.is_set():
                started = time.monotonic()
                try:
                    if not self.visible or not self.config or not self.scene:
                        self.stop_event.wait(0.2)
                        continue
                    if config != self.config:
                        if client:
                            client.disconnect()
                        client = None
                        config = self.config
                    if client is None:
                        client = self.factory(
                            host=config.host, port=config.port, password=config.password, timeout=1
                        )
                    scene = self.scene
                    payload = client.send(
                        "GetSourceScreenshot",
                        {
                            "sourceName": scene,
                            "imageFormat": "jpeg",
                            "imageWidth": 480,
                            "imageHeight": 270,
                            "imageCompressionQuality": 55,
                        },
                        raw=True,
                    )
                    frame = base64.b64decode(payload["imageData"].split(",", 1)[-1], validate=True)
                    if scene == self.scene and config == self.config:
                        with self.lock:
                            self.frame = (time.monotonic(), frame)
                except Exception:
                    if client:
                        try:
                            client.disconnect()
                        except Exception:
                            pass
                    client = None
                    self.stop_event.wait(1)
                # At most 20 FPS; slow requests drop rate instead of accumulating work.
                self.stop_event.wait(max(0, 0.05 - (time.monotonic() - started)))
        finally:
            if client:
                try:
                    client.disconnect()
                except Exception:
                    pass
