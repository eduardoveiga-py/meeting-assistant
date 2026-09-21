from __future__ import annotations

import base64
import binascii
import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import obsws_python as obs
from obsws_python.error import OBSSDKRequestError
from PySide6.QtCore import QObject, Signal
from websocket import WebSocketTimeoutException

from meeting_assistant.services.obs_hall_setup import (
    apply_yeartext,
    inspect_visual_sources,
    prepare_media,
    virtual_camera_step,
)
from meeting_assistant.services.obs_setup import prepare_obs
from meeting_assistant.services.yeartext_store import YeartextStore


def is_obs_not_ready(exc: BaseException | None) -> bool:
    return isinstance(exc, OBSSDKRequestError) and exc.code == 207


class _TransientObsLogFilter(logging.Filter):
    """The controller reports these expected lifecycle errors through its UI.

    Keep all other SDK errors and tracebacks, including authentication failures.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        return not (
            is_obs_not_ready(exc)
            or isinstance(exc, (TimeoutError, ConnectionRefusedError, WebSocketTimeoutException))
        )


def _install_transient_log_filter() -> None:
    for name in ("obsws_python.reqs.ReqClient", "obsws_python.baseclient.ObsClient"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, _TransientObsLogFilter) for item in logger.filters):
            logger.addFilter(_TransientObsLogFilter())


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


def ensure_fade_transition(client: obs.ReqClient, duration_ms: int = 350) -> None:
    """Seleciona a transição Fade/Esmaecer do OBS e ajusta sua duração.

    É best-effort: se uma versão do OBS não expuser a lista de transições, a troca
    de cena continua funcionando com a transição que já estiver selecionada.
    """

    try:
        payload = client.send("GetSceneTransitionList", raw=True)
        transitions = payload.get("transitions", [])
        fade_name: str | None = None
        for item in transitions:
            if not isinstance(item, dict):
                continue
            name = item.get("transitionName") or item.get("transition_name")
            kind = item.get("transitionKind") or item.get("transition_kind")
            if not isinstance(name, str) or not name:
                continue
            normalized_name = name.casefold()
            normalized_kind = str(kind or "").casefold()
            if normalized_kind == "fade_transition" or any(
                token in normalized_name for token in ("fade", "esmaecer")
            ):
                fade_name = name
                break

        if fade_name:
            client.send(
                "SetCurrentSceneTransition",
                {"transitionName": fade_name},
                raw=True,
            )
        client.send(
            "SetCurrentSceneTransitionDuration",
            {"transitionDuration": int(duration_ms)},
            raw=True,
        )
    except Exception:
        pass


class ObsController(QObject):
    connected_changed = Signal(bool, str)
    scenes_changed = Signal(list)
    scene_changed = Signal(str)
    preview_changed = Signal(bytes)
    preview_error = Signal(str)
    error = Signal(str)
    setup_finished = Signal(bool, str)
    hall_task_finished = Signal(str, bool, str)
    audio_task_finished = Signal(str, str, bool, object)

    def __init__(self, poll_interval: float = 0.5, preview_interval: float = 0.15) -> None:
        super().__init__()
        _install_transient_log_filter()
        self._poll_interval = max(0.25, poll_interval)
        self._preview_interval = max(0.12, preview_interval)
        self._commands: queue.Queue[tuple[str, object | None]] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._config: ObsConnectionConfig | None = None
        self._client: obs.ReqClient | None = None
        self._last_connected: bool | None = None
        self._last_connection_status: tuple[bool, str] | None = None
        self._last_scenes: list[str] = []
        self._last_scene: str | None = None
        self._last_preview_error: str | None = None
        self._virtual_deadline = 0.0
        self._next_virtual_check = 0.0

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

    def prepare_stage(self, settings) -> None:
        from dataclasses import replace

        self._commands.put(("prepare_stage", replace(settings)))

    def hall_task(self, action: str, data: dict | None = None) -> None:
        self._commands.put(("hall_task", (action, dict(data or {}))))

    def audio_task(self, token: str, action: str, data: dict) -> None:
        from copy import deepcopy

        self._commands.put(("audio_task", (token, action, deepcopy(data))))

    def _handle_audio_task(self, token: str, action: str, data: dict) -> None:
        from meeting_assistant.services.obs_audio import run_audio_task

        if self._client is None:
            self.audio_task_finished.emit(token, action, False, {"message": "OBS desconectado."})
            return
        try:
            result = run_audio_task(self._client, action, data)
            self.audio_task_finished.emit(token, action, True, result)
        except ValueError as exc:
            self.audio_task_finished.emit(token, action, False, {"message": str(exc)})
        except Exception:
            self.audio_task_finished.emit(token, action, False, {
                "message": "Configuração de áudio incompleta. Confira o OBS e, se necessário, "
                           "silencie o microfone no Zoom antes de tentar novamente."
            })

    def ensure_virtual_camera(self) -> None:
        self._commands.put(("virtual_camera", None))

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
            try:
                command, payload = self._commands.get(timeout=0.05)
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
                elif command == "prepare_stage":
                    self._handle_prepare_stage(payload)
                elif command == "hall_task":
                    self._handle_hall_task(*payload)
                elif command == "audio_task":
                    self._handle_audio_task(*payload)
                elif command == "virtual_camera":
                    self._virtual_deadline = time.monotonic() + 60.0
                    self._next_virtual_check = 0.0
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
                    # Count the retry delay after a potentially blocking timeout.
                    next_reconnect = time.monotonic() + 2.0

            if self._virtual_deadline:
                if now >= self._virtual_deadline:
                    self._virtual_deadline = 0.0
                    self.hall_task_finished.emit(
                        "virtual_camera", False, "Câmera virtual não confirmou em 60 s."
                    )
                elif self._client is not None and now >= self._next_virtual_check:
                    self._next_virtual_check = now + 1.0
                    try:
                        if virtual_camera_step(self._client):
                            self._virtual_deadline = 0.0
                            self.hall_task_finished.emit(
                                "virtual_camera", True, "Câmera virtual confirmada ativa."
                            )
                    except Exception:
                        self._virtual_deadline = 0.0
                        self.hall_task_finished.emit(
                            "virtual_camera", False, "Falha ao iniciar a câmera virtual. Confira o OBS."
                        )

            if self._client is not None and now >= next_poll:
                self._poll()
                if self._client is None:
                    next_reconnect = time.monotonic() + 2.0
                next_poll = now + self._poll_interval

            if self._client is not None and now >= next_preview:
                self._refresh_preview()
                if self._client is None:
                    next_reconnect = time.monotonic() + 2.0
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
            self._client = client
            version = client.send("GetVersion", raw=True)
            obs_version = version.get("obsVersion", "versão desconhecida")
            self._refresh_scene_list()
            self._refresh_current_scene()
            ensure_fade_transition(client)
            self._set_connected(True, f"OBS {obs_version} conectado")
            return True
        except Exception as exc:
            self._disconnect()
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
            "imageWidth": 640,
            "imageHeight": 360,
            "imageCompressionQuality": 78,
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
            if is_obs_not_ready(exc):
                self._set_connected(False, self._friendly_connection_error(exc))
                self._disconnect()
                return
            self._emit_preview_error(f"Preview indisponível: {exc}")

    def _handle_set_scene(self, scene_name: str) -> None:
        if self._client is None:
            self.error.emit("OBS desconectado; não foi possível trocar a cena.")
            return
        try:
            ensure_fade_transition(self._client)
            self._client.send(
                "SetCurrentProgramScene",
                {"sceneName": scene_name},
                raw=True,
            )
            self._refresh_current_scene()
        except Exception as exc:
            self.error.emit(f"Falha ao trocar para '{scene_name}': {exc}")

    def _handle_prepare_stage(self, settings) -> None:
        if self._client is None:
            self.setup_finished.emit(False, "OBS desconectado. Conecte e solicite a preparação novamente.")
            return
        try:
            prepare_obs(self._client, settings)
            self._refresh_scene_list()
            self.setup_finished.emit(
                True, "Cenas padronizadas e fonte IP configurada. A imagem da câmera ainda não foi validada. "
                "Confira fontes de Texto do Ano/Mídias e possíveis fontes antigas em Palco."
            )
        except ValueError as exc:
            self.setup_finished.emit(False, str(exc))
        except Exception:
            # SDK exceptions may contain the request, including credentials.
            self.setup_finished.emit(
                False, "Preparação incompleta no OBS. Revise as cenas/fontes antes de tentar novamente."
            )

    def _handle_hall_task(self, action: str, data: dict) -> None:
        if self._client is None:
            self.hall_task_finished.emit(action, False, "OBS desconectado; configuração pendente.")
            return
        try:
            if action == "yeartext":
                store = YeartextStore(Path(data["directory"]))
                photo = store.current()
                if photo is None:
                    raise ValueError("Foto ausente ou inválida; capture novamente.")
                apply_yeartext(self._client, photo, data["scene"])
                store.mark_applied(photo["sha256"], photo["file"])
                message = (
                    "Foto existente aplicada ao OBS. "
                    "Para substituí-la, capture uma nova foto, confirme e salve."
                )
            elif action == "media":
                prepare_media(self._client, data["scene"], data["selectors"])
                message = "Fonte JWL configurada. Confira a imagem no OBS; nenhuma cena Program foi trocada."
            elif action == "inspect":
                message = inspect_visual_sources(self._client, data["background"], data["media"])
            else:
                raise ValueError("Operação OBS desconhecida.")
            self._refresh_scene_list()
            self.hall_task_finished.emit(action, True, message)
        except ValueError as exc:
            self.hall_task_finished.emit(action, False, str(exc))
        except Exception:
            self.hall_task_finished.emit(
                action, False, "Operação OBS incompleta. Confira cenas/fontes e tente novamente."
            )

    def _emit_preview_error(self, message: str) -> None:
        if message == self._last_preview_error:
            return
        self._last_preview_error = message
        self.preview_error.emit(message)

    def _set_connected(self, connected: bool, message: str) -> None:
        status = (connected, message)
        if self._last_connection_status == status:
            return
        self._last_connection_status = status
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
        if is_obs_not_ready(exc):
            return "OBS está iniciando ou encerrando; aguardando ficar disponível."
        text = str(exc).strip()
        lowered = text.lower()
        if "authentication" in lowered or "identify" in lowered or "4009" in lowered:
            return "Falha de autenticação no OBS WebSocket. Verifique a senha."
        if "refused" in lowered or "10061" in lowered:
            return "OBS WebSocket indisponível em host/porta configurados."
        if "timed out" in lowered or "timeout" in lowered:
            return "Tempo esgotado ao conectar ao OBS WebSocket."
        return f"OBS WebSocket desconectado: {text or type(exc).__name__}"
