"""Read-only readiness results; manual evidence is never inferred from a probe."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    category: str
    name: str
    passed: bool | None

    def render(self):
        state = "NÃO VERIFICADO" if self.passed is None else "OK" if self.passed else "PENDENTE"
        return f"{self.category} · {state} · {self.name}"


def inspect_obs(settings, factory):
    rows = []
    client = None
    connected = False
    from meeting_assistant.services.settings import detect_obs_websocket_password

    try:
        client = factory(
            host=settings.obs_host,
            port=settings.obs_port,
            password=settings.obs_password or detect_obs_websocket_password(),
            timeout=3,
        )
        client.send("GetVersion", raw=True)
        connected = True
    except Exception:
        pass  # Connection errors may contain credentials; never render them.
    rows.append(Check("CONEXÃO", "OBS WebSocket autenticado", connected))
    scenes = None
    camera = None
    try:
        if connected:
            try:
                scenes = {r["sceneName"] for r in client.send("GetSceneList", raw=True)["scenes"]}
            except Exception:
                pass
            try:
                camera = bool(client.send("GetVirtualCamStatus", raw=True)["outputActive"])
            except Exception:
                pass
    finally:
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
    for name in (settings.scene_background, settings.scene_speaker, settings.scene_media):
        rows.append(Check("CONFIGURAÇÃO", f"Cena {name} existe", None if scenes is None else name in scenes))
    rows.append(Check("CONEXÃO", "Câmera virtual OBS ativa", camera))
    return rows


def _extract_vcam_status(res) -> bool:
    if isinstance(res, dict):
        val = res.get("outputActive")
        if val is None:
            val = res.get("output_active", False)
        return bool(val)
    if isinstance(res, bool):
        return res
    val = getattr(res, "output_active", getattr(res, "outputActive", None))
    return bool(val) if val is not None else False


def _make_temp_obs_client(host: str, port: int, password: str | None, timeout: int = 2):
    import obsws_python as obs

    from meeting_assistant.services.settings import detect_obs_websocket_password

    candidates: list[str] = []
    if password is not None and password != "":
        candidates.append(password)
    try:
        detected = detect_obs_websocket_password()
        if detected and detected not in candidates:
            candidates.append(detected)
    except Exception:
        pass
    if "" not in candidates:
        candidates.append("")

    for pwd in candidates:
        try:
            return obs.ReqClient(
                host=host,
                port=port,
                password=pwd,
                timeout=timeout,
            )
        except Exception:
            continue
    return None


def _close_temp_obs_client(client) -> None:
    if client is None:
        return
    try:
        client.disconnect()
    except Exception:
        try:
            base_client = getattr(client, "base_client", None)
            ws = getattr(base_client, "ws", None)
            if ws is not None:
                ws.close()
        except Exception:
            pass


class PreFlightChecker:
    """Automated pre-flight check verifying the 5 critical readiness items:

    1. OBS Studio running and WebSocket connected.
    2. OBS Virtual Camera active (with auto-fix capability).
    3. VB-CABLE virtual audio device installed and available.
    4. Secondary monitor connected and detected.
    5. Zoom Desktop application running.
    """

    def __init__(self, obs_service=None, settings=None):
        self.obs = obs_service
        self.settings = settings

    def check_obs(self) -> Check:
        import psutil

        obs_running = False
        try:
            for p in psutil.process_iter(["name"]):
                if p.info.get("name") and p.info["name"].casefold() in ("obs64.exe", "obs32.exe", "obs.exe"):
                    obs_running = True
                    break
        except Exception:
            pass

        connected = False
        if self.obs:
            conn_val = getattr(self.obs, "is_connected", None)
            if conn_val is not None:
                connected = bool(conn_val() if callable(conn_val) else conn_val)
            elif hasattr(self.obs, "_client") and self.obs._client is not None:
                connected = True

        if not connected and obs_running and self.settings:
            temp_client = _make_temp_obs_client(
                host=self.settings.obs_host,
                port=self.settings.obs_port,
                password=self.settings.obs_password,
                timeout=2,
            )
            if temp_client:
                try:
                    temp_client.send("GetVersion", raw=True)
                    connected = True
                except Exception:
                    pass
                finally:
                    _close_temp_obs_client(temp_client)

        return Check("OBS", "OBS Studio rodando e WebSocket conectado", obs_running and connected)

    def check_virtual_cam(self) -> Check:
        active = False
        if self.obs and hasattr(self.obs, "is_virtual_cam_active"):
            try:
                active = bool(self.obs.is_virtual_cam_active())
            except Exception:
                active = False
        if not active and self.settings:
            temp_client = _make_temp_obs_client(
                host=self.settings.obs_host,
                port=self.settings.obs_port,
                password=self.settings.obs_password,
                timeout=2,
            )
            if temp_client:
                try:
                    res = temp_client.send("GetVirtualCamStatus", raw=True)
                    active = _extract_vcam_status(res)
                except Exception:
                    pass
                finally:
                    _close_temp_obs_client(temp_client)
        return Check("CÂMERA", "Câmera virtual OBS ativa", active)

    def check_vb_cable(self) -> Check:
        import sys

        if sys.platform != "win32":
            return Check("ÁUDIO", "VB-CABLE instalado e ativo", True)
        found = False
        co_init = False
        try:
            import pythoncom

            pythoncom.CoInitialize()
            co_init = True
        except Exception:
            co_init = False
        try:
            from pycaw.pycaw import AudioUtilities

            for dev in AudioUtilities.GetAllDevices():
                name = getattr(dev, "FriendlyName", None) or getattr(dev, "name", "")
                if name and "cable" in name.casefold():
                    found = True
                    break
        except Exception:
            pass
        finally:
            if co_init:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
        return Check("ÁUDIO", "VB-CABLE instalado e ativo", found)

    def check_secondary_monitor(self) -> Check:
        found = False
        try:
            from meeting_assistant.services.window_manager import WindowManager

            monitors = WindowManager.get_monitors_info()
            found = len(monitors) > 1 or any(not m.get("primary", False) for m in monitors)
        except Exception:
            pass
        if not found:
            try:
                from PySide6.QtWidgets import QApplication

                app = QApplication.instance()
                if app and len(app.screens()) > 1:
                    found = True
            except Exception:
                pass
        return Check("MONITOR", "Segundo monitor conectado e detectado", found)

    def check_zoom(self) -> Check:
        import psutil

        found = False
        try:
            for p in psutil.process_iter(["name"]):
                if p.info.get("name") and p.info["name"].casefold() == "zoom.exe":
                    found = True
                    break
        except Exception:
            pass
        return Check("ZOOM", "Zoom Desktop rodando", found)

    def check_all(self) -> list[Check]:
        return [
            self.check_obs(),
            self.check_virtual_cam(),
            self.check_vb_cable(),
            self.check_secondary_monitor(),
            self.check_zoom(),
        ]

    def auto_fix_virtual_cam(self) -> bool:
        """Attempts to start OBS virtual camera if inactive."""
        if self.obs and hasattr(self.obs, "start_virtual_cam"):
            try:
                if bool(self.obs.start_virtual_cam()):
                    return True
            except Exception:
                pass
        if self.settings:
            temp_client = _make_temp_obs_client(
                host=self.settings.obs_host,
                port=self.settings.obs_port,
                password=self.settings.obs_password,
                timeout=3,
            )
            if temp_client:
                try:
                    from meeting_assistant.services.obs_hall_setup import virtual_camera_step

                    return bool(virtual_camera_step(temp_client))
                except Exception:
                    return False
                finally:
                    _close_temp_obs_client(temp_client)
        return False
