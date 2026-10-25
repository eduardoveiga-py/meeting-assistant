"""Background watchdog for periodic health checks, HDMI/audio re-attachment, and auto-recovery."""

from __future__ import annotations

import logging
import sys
import threading
from typing import Any

from PySide6.QtCore import QObject, Signal

from meeting_assistant.services.window_manager import WindowManager

logger = logging.getLogger(__name__)


class WatchdogService(QObject):
    """Monitors OBS connection, Virtual Camera, virtual audio cable, and secondary monitor."""

    health_status_updated = Signal(dict)
    recovery_triggered = Signal(str)

    def __init__(
        self,
        obs_service: Any = None,
        virtual_cable_name: str = "CABLE",
        check_interval_seconds: float = 3.0,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.obs = obs_service
        self.virtual_cable_name = virtual_cable_name.casefold()
        self.check_interval_seconds = max(1.0, check_interval_seconds)

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_state: dict[str, bool] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="WatchdogService-Thread",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            status = self.check_health()
            self._handle_reconnect_triggers(status)
            self._last_state = status
            self.health_status_updated.emit(status)
            self._stop_event.wait(self.check_interval_seconds)

    def check_health(self) -> dict[str, bool]:
        """Check all 4 health parameters."""
        obs_connected = False
        vcam_active = False

        if self.obs:
            conn_val = getattr(self.obs, "is_connected", False)
            obs_connected = bool(conn_val() if callable(conn_val) else conn_val)
            if not obs_connected and hasattr(self.obs, "_client") and self.obs._client is not None:
                obs_connected = True
            if obs_connected and hasattr(self.obs, "is_virtual_cam_active"):
                try:
                    vcam_active = bool(self.obs.is_virtual_cam_active())
                except Exception:
                    vcam_active = False

        cable_present = self._check_virtual_cable()
        secondary_monitor = self._check_secondary_monitor()

        return {
            "obs_connected": obs_connected,
            "vcam_active": vcam_active,
            "virtual_cable_present": cable_present,
            "secondary_monitor": secondary_monitor,
        }

    def _check_virtual_cable(self) -> bool:
        """Check presence of VB-CABLE or equivalent virtual audio endpoint."""
        if sys.platform != "win32":
            return True

        try:
            from pycaw.pycaw import AudioUtilities

            devices = AudioUtilities.GetAllDevices()
            for dev in devices:
                name = getattr(dev, "FriendlyName", None) or getattr(dev, "name", "")
                if name and self.virtual_cable_name in name.casefold():
                    return True
        except Exception:
            pass

        return False

    def _check_secondary_monitor(self) -> bool:
        """Check if at least one non-primary monitor is connected."""
        try:
            monitors = WindowManager.get_monitors_info()
            return len(monitors) > 1
        except Exception:
            return False

    def _handle_reconnect_triggers(self, current: dict[str, bool]) -> None:
        """Trigger auto-recovery when a peripheral is reconnected."""
        if not self._last_state:
            return

        # Secondary monitor re-attached (e.g. HDMI cable re-plugged)
        if not self._last_state.get("secondary_monitor") and current.get("secondary_monitor"):
            logger.info("Segundo monitor reconectado. Reaproveitando proteção de posicionamento.")
            WindowManager.enforce_secondary_screen_protection(media_hwnd=0)
            self.recovery_triggered.emit("secondary_monitor_reconnected")

        # OBS Virtual Camera re-attached / activated
        if not self._last_state.get("vcam_active") and current.get("vcam_active"):
            logger.info("Câmera virtual do OBS ativada.")
            self.recovery_triggered.emit("vcam_activated")
