"""Non-blocking OBS WebSocket service with event listening, auto-reconnection, and audio fade."""

from __future__ import annotations

import logging
import threading
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

try:
    import obsws_python as obs
except ImportError:
    obs = None

logger = logging.getLogger(__name__)


class VolumeFader(QObject):
    """Smooth non-blocking volume fader using QTimer steps."""

    finished = Signal()

    def __init__(
        self,
        service: ObsService,
        input_name: str,
        start_db: float,
        end_db: float,
        duration_ms: int = 400,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.input_name = input_name
        self.start_db = start_db
        self.end_db = end_db
        self.duration_ms = max(50, duration_ms)
        self.step_interval_ms = 25
        self.total_steps = max(1, self.duration_ms // self.step_interval_ms)
        self.current_step = 0

        self.timer = QTimer(self)
        self.timer.setInterval(self.step_interval_ms)
        self.timer.timeout.connect(self._on_step)

    def start(self) -> None:
        self.current_step = 0
        self.service.set_input_volume_db(self.input_name, self.start_db)
        self.timer.start()

    def _on_step(self) -> None:
        self.current_step += 1
        fraction = min(1.0, self.current_step / self.total_steps)
        current_db = self.start_db + (self.end_db - self.start_db) * fraction
        self.service.set_input_volume_db(self.input_name, current_db)

        if fraction >= 1.0:
            self.timer.stop()
            self.finished.emit()
            self.deleteLater()


class ObsService(QObject):
    """Threaded OBS Studio WebSocket controller with automatic reconnect and event dispatching."""

    connected_changed = Signal(bool, str)
    scene_changed = Signal(str)
    media_playback_started = Signal(str)
    media_playback_ended = Signal(str)
    virtual_cam_state_changed = Signal(bool)
    error_occurred = Signal(str)

    def __init__(
        self,
        host: str = "localhost",
        port: int = 4455,
        password: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.host = host
        self.port = port
        self.password = password

        self._req_client: Any = None
        self._event_client: Any = None
        self._connected = False
        self._stop_event = threading.Event()
        self._reconnect_thread: threading.Thread | None = None
        self._active_faders: list[VolumeFader] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        """Start the background connection worker."""
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            return
        self._stop_event.clear()
        self._reconnect_thread = threading.Thread(
            target=self._worker_loop,
            name="ObsService-Worker",
            daemon=True,
        )
        self._reconnect_thread.start()

    def stop(self) -> None:
        """Stop connection loop and disconnect."""
        self._stop_event.set()
        self._disconnect_clients()
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            self._reconnect_thread.join(timeout=2.0)

    def configure(self, host: str, port: int, password: str) -> None:
        self.host = host
        self.port = port
        self.password = password
        self._disconnect_clients()

    def _worker_loop(self) -> None:
        backoffs = [1.0, 2.0, 4.0, 8.0, 15.0]
        backoff_idx = 0

        while not self._stop_event.is_set():
            if not self._connected:
                success = self._try_connect()
                if success:
                    backoff_idx = 0
                else:
                    delay = backoffs[min(backoff_idx, len(backoffs) - 1)]
                    backoff_idx += 1
                    self._stop_event.wait(delay)
                    continue

            # Heartbeat check while connected
            if self._connected:
                try:
                    if self._req_client:
                        self._req_client.send("GetVersion", raw=True)
                except Exception:
                    logger.warning("Conexão com OBS perdida, agendando reconexão.")
                    self._handle_disconnect("Conexão perdida com o OBS Studio.")
                    continue

            self._stop_event.wait(2.5)

    def _try_connect(self) -> bool:
        if obs is None:
            self._handle_disconnect("Biblioteca obsws-python não instalada.")
            return False

        try:
            req = obs.ReqClient(
                host=self.host,
                port=self.port,
                password=self.password,
                timeout=3,
            )
            # Verify version call
            req.send("GetVersion", raw=True)
            self._req_client = req

            # Set up event client
            try:
                evt = obs.EventClient(
                    host=self.host,
                    port=self.port,
                    password=self.password,
                )
                self._bind_events(evt)
                self._event_client = evt
            except Exception as e:
                logger.debug("Não foi possível inicializar EventClient do OBS: %s", e)

            self._connected = True
            self.connected_changed.emit(True, "Conectado ao OBS Studio")
            logger.info("Conectado ao OBS WebSocket com sucesso (%s:%s)", self.host, self.port)
            return True
        except Exception as exc:
            self._req_client = None
            self._event_client = None
            self._connected = False
            self.connected_changed.emit(False, f"Falha na conexão: {exc}")
            return False

    def _bind_events(self, evt: Any) -> None:
        def on_scene_changed(data):
            name = getattr(data, "scene_name", None) or getattr(data, "sceneName", "")
            if name:
                self.scene_changed.emit(name)

        def on_media_started(data):
            name = getattr(data, "input_name", None) or getattr(data, "inputName", "")
            if name:
                self.media_playback_started.emit(name)

        def on_media_ended(data):
            name = getattr(data, "input_name", None) or getattr(data, "inputName", "")
            if name:
                self.media_playback_ended.emit(name)

        def on_vcam_state(data):
            active = bool(getattr(data, "output_active", False) or getattr(data, "outputActive", False))
            self.virtual_cam_state_changed.emit(active)

        try:
            evt.callback.register(on_scene_changed, "CurrentProgramSceneChanged")
            evt.callback.register(on_media_started, "MediaInputPlaybackStarted")
            evt.callback.register(on_media_ended, "MediaInputPlaybackEnded")
            evt.callback.register(on_vcam_state, "VirtualcamStateChanged")
        except Exception as exc:
            logger.debug("Falha registrando callbacks do OBS: %s", exc)

    def _disconnect_clients(self) -> None:
        self._connected = False
        if self._event_client:
            try:
                self._event_client.unsubscribe()
            except Exception:
                pass
            self._event_client = None

        if self._req_client:
            try:
                self._req_client.disconnect()
            except Exception:
                pass
            self._req_client = None

    def _handle_disconnect(self, message: str) -> None:
        self._disconnect_clients()
        self.connected_changed.emit(False, message)

    def switch_scene(self, scene_name: str) -> bool:
        """Switch Program scene."""
        if not self._req_client:
            return False
        try:
            self._req_client.send(
                "SetCurrentProgramScene",
                {"sceneName": scene_name},
                raw=True,
            )
            return True
        except Exception as exc:
            msg = f"Falha ao trocar cena para '{scene_name}': {exc}"
            logger.warning(msg)
            self.error_occurred.emit(msg)
            return False

    def set_program_scene(self, scene_name: str) -> bool:
        return self.switch_scene(scene_name)

    def get_scene_list(self) -> list[str]:
        if not self._req_client:
            return []
        try:
            res = self._req_client.send("GetSceneList", raw=True)
            return [s["sceneName"] for s in res.get("scenes", []) if "sceneName" in s]
        except Exception:
            return []

    def set_input_mute(self, input_name: str, muted: bool) -> bool:
        """Mute or unmute an input source safely."""
        if not self._req_client:
            return False
        try:
            self._req_client.send(
                "SetInputMute",
                {"inputName": input_name, "inputMuted": bool(muted)},
                raw=True,
            )
            return True
        except Exception as exc:
            logger.warning("Falha ao ajustar mute de '%s' para %s: %s", input_name, muted, exc)
            return False

    def set_muted(self, input_name: str, muted: bool) -> bool:
        return self.set_input_mute(input_name, muted)

    def set_input_volume_db(self, input_name: str, db: float) -> bool:
        """Adjust input volume in decibels."""
        if not self._req_client:
            return False
        try:
            self._req_client.send(
                "SetInputVolume",
                {"inputName": input_name, "inputVolumeDb": float(db)},
                raw=True,
            )
            return True
        except Exception as exc:
            logger.warning("Falha ao ajustar volume de '%s' para %s dB: %s", input_name, db, exc)
            return False

    def fade_input_volume(
        self,
        input_name: str,
        start_db: float,
        end_db: float,
        duration_ms: int = 400,
    ) -> None:
        """Fade volume smoothly using non-blocking QTimer steps."""
        fader = VolumeFader(self, input_name, start_db, end_db, duration_ms, parent=self)
        self._active_faders.append(fader)
        fader.finished.connect(
            lambda: self._active_faders.remove(fader) if fader in self._active_faders else None
        )
        fader.start()

    def is_virtual_cam_active(self) -> bool:
        """Query if OBS Virtual Camera output is running."""
        if not self._req_client:
            return False
        try:
            res = self._req_client.send("GetVirtualCamStatus", raw=True)
            return bool(res.get("outputActive", False))
        except Exception:
            return False

    def start_virtual_cam(self) -> bool:
        """Start OBS Virtual Camera output."""
        if not self._req_client:
            return False
        try:
            self._req_client.send("StartVirtualCam", raw=True)
            self.virtual_cam_state_changed.emit(True)
            return True
        except Exception as exc:
            logger.warning("Falha ao iniciar Câmera Virtual do OBS: %s", exc)
            return False

    def stop_virtual_cam(self) -> bool:
        """Stop OBS Virtual Camera output."""
        if not self._req_client:
            return False
        try:
            self._req_client.send("StopVirtualCam", raw=True)
            self.virtual_cam_state_changed.emit(False)
            return True
        except Exception as exc:
            logger.warning("Falha ao parar Câmera Virtual do OBS: %s", exc)
            return False
