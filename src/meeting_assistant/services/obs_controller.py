from __future__ import annotations

import base64
import binascii
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

import obsws_python as obs
from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True, slots=True)
class ObsConnectionConfig:
    host: str
    port: int
    password: str


def extract_scene_names(payload: dict[str, Any]) -> list[str]:
    scenes = payload.get("scenes", [])
    names: list[str] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        name = scene.get("sceneName") or scene.get("scene_name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def extract_current_scene(payload: dict[str, Any]) -> str | None:
    for key in ("sceneName", "currentProgramSceneName", "scene_name"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def decode_image_data(image_data: str) -> bytes | None:
    if not image_data:
        return None
    encoded = image_data.split(",", 1)[1] if "," in image_data else image_data
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None


class ObsController(QObject):
    connected_changed = Signal(bool, str)
    scenes_changed = Signal(list)
    scene_changed = Signal(str)
    preview_changed = Signal(bytes)
    preview_error = Signal(str)
    error = Signal(str)

    def __init__(self, poll_interval: float = 1.0, preview_interval: float = 1.0) -> None:
        super().__init__()
        self._poll_interval = max(0.5, poll_interval)
        self._preview_interval = max(0.75, preview_interval)
        self._commands: queue.Queue[tuple[str, object | None]] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._config: ObsConnectionConfig | None = None
        self._client: obs.ReqClient | None = None
        self._last_connected: bool | None = None
        self._last_scenes: list[str] = []
        self._last_scene: str | None = None
        self._last_preview_error: str | None = None

    def start(self, config: ObsConnectionConfig) -> None:
        self._config = config
        if self._thread and self._thread.is_alive():
            self.reconfigure(config)
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="MeetingAssistant-OBS",
            daemon=True,
        )
        self._thread.start()

    def reconfigure(self, config: ObsConnectionConfig) -> None:
        self._commands.put(("configure", config))

    def set_program_scene(self, scene_name: str) -> None:
        scene_name = scene_name.strip()
        if not scene_name:
            self.error.emit("Nome de cena vazio; troca cancelada.")
            return
        self._commands.put(("set_scene", scene_name))

    def refresh(self) -> None:
        self._commands.put(("refresh", None))

    def refresh_preview(self) -> None:
        self._commands.put(("preview", None))

    def stop(self) -> None:
        self._stop_event.set()
        self._commands.put(("stop", None))
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._disconnect()

    def _run(self) -> None:
        next_poll = 0.0
        next_preview = 0.0
        next_reconnect = 0.0

        while not self._stop_event.is_set():
            now = time.monotonic()
            try:
                command, payload = self._commands.get(timeout=0.2)
                if command == "stop":
                    break
                if command == "configure" and isinstance(payload, ObsConnectionConfig):
                    self._config = payload
                    self._disconnect()
                    next_reconnect = 0.0
                    next_poll = 0.0
                    next_preview = 0.0
                elif command == "set_scene" and isinstance(payload, str):
                    self._handle_set_scene(payload)
                    next_preview = 0.0
                elif command == "refresh":
                    next_poll = 0.0
                elif command == "preview":
                    next_preview = 0.0
            except queue.Empty:
                pass

            now = time.monotonic()
            if self._client is None and now >= next_reconnect:
                if self._connect():
                    next_poll = 0.0
                    next_preview = 0.0
                else:
                    next_reconnect = now + 2.0

            if self._client is not None and now >= next_poll:
                self._poll()
                next_poll = now + self._poll_interval

            if self._client is not None and now >= next_preview:
                self._refresh_preview()
                next_preview = now + self._preview_interval

        self._disconnect()

    def _connect(self) -> bool:
        if self._config is None:
            return False

        try:
            client = obs.ReqClient(
                host=self._config.host,
                port=self._config.port,
                password=self._config.password,
                timeout=2,
            )
            version = client.send("GetVersion", raw=True)
            obs_version = version.get("obsVersion", "versão desconhecida")
            self._client = client
            self._set_connected(True, f"OBS {obs_version} conectado")
            self._refresh_scene_list()
            self._refresh_current_scene()
            return True
        except Exception as exc:  # obsws-python expõe vários tipos de erro
            self._client = None
            self._set_connected(False, self._friendly_connection_error(exc))
            return False

    def _poll(self) -> None:
        if self._client is None:
            return
        try:
            self._refresh_current_scene()
        except Exception as exc:
            self._set_connected(False, self._friendly_connection_error(exc))
            self._disconnect()

    def _refresh_scene_list(self) -> None:
        if self._client is None:
            return
        payload = self._client.send("GetSceneList", raw=True)
        scenes = extract_scene_names(payload)
        if scenes != self._last_scenes:
            self._last_scenes = scenes
            self.scenes_changed.emit(scenes)

    def _refresh_current_scene(self) -> None:
        if self._client is None:
            return
        payload = self._client.send("GetCurrentProgramScene", raw=True)
        scene = extract_current_scene(payload)
        if scene and scene != self._last_scene:
            self._last_scene = scene
            self.scene_changed.emit(scene)

    def _refresh_preview(self) -> None:
        if self._client is None or not self._last_scene:
            return
        request_data = {
            "sourceName": self._last_scene,
            "imageFormat": "jpeg",
            "imageWidth": 320,
            "imageHeight": 180,
            "imageCompressionQuality": 55,
        }
        try:
            payload = self._client.send("GetSourceScreenshot", request_data, raw=True)
            image_data = payload.get("imageData") or payload.get("image_data")
            if not isinstance(image_data, str):
                self._emit_preview_error("OBS não retornou imagem para o preview.")
                return
            decoded = decode_image_data(image_data)
            if not decoded:
                self._emit_preview_error("OBS retornou um preview inválido.")
                return
            self._last_preview_error = None
            self.preview_changed.emit(decoded)
        except Exception as exc:
            self._emit_preview_error(f"Preview indisponível: {exc}")

    def _handle_set_scene(self, scene_name: str) -> None:
        if self._client is None:
            self.error.emit("OBS desconectado; não foi possível trocar a cena.")
            return
        try:
            self._client.send(
                "SetCurrentProgramScene",
                {"sceneName": scene_name},
                raw=True,
            )
            self._refresh_current_scene()
        except Exception as exc:
            self.error.emit(f"Falha ao trocar para '{scene_name}': {exc}")

    def _emit_preview_error(self, message: str) -> None:
        if message == self._last_preview_error:
            return
        self._last_preview_error = message
        self.preview_error.emit(message)

    def _set_connected(self, connected: bool, message: str) -> None:
        if self._last_connected == connected and connected:
            return
        self._last_connected = connected
        self.connected_changed.emit(connected, message)

    def _disconnect(self) -> None:
        client = self._client
        self._client = None
        self._last_scene = None
        self._last_scenes = []
        self._last_preview_error = None
        if client is None:
            return
        try:
            base_client = getattr(client, "base_client", None)
            websocket = getattr(base_client, "ws", None)
            if websocket is not None:
                websocket.close()
        except Exception:
            pass

    @staticmethod
    def _friendly_connection_error(exc: Exception) -> str:
        text = str(exc).strip()
        lowered = text.lower()
        if "authentication" in lowered or "identify" in lowered or "4009" in lowered:
            return "Falha de autenticação no OBS WebSocket. Verifique a senha."
        if "refused" in lowered or "10061" in lowered:
            return "OBS WebSocket indisponível em host/porta configurados."
        if "timed out" in lowered or "timeout" in lowered:
            return "Tempo esgotado ao conectar ao OBS WebSocket."
        return f"OBS WebSocket desconectado: {text or type(exc).__name__}"
