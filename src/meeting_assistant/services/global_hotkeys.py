"""Optional Windows hotkeys; only registered combinations, never keyboard hooks."""

import ctypes
import os
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

KEYS = {2: 0x71, 3: 0x72, 4: 0x73, 5: 0x74, 7: 0x76}  # Ctrl+Alt+F2/F3/F4/F5/F7


class GlobalHotkeys(QObject):
    pressed = Signal(int)
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = False
        self.thread = None
        self.thread_id = 0
        self.stop_event = threading.Event()

    def set_enabled(self, enabled):
        if enabled == self.enabled:
            return
        self.enabled = enabled
        if not enabled:
            self.stop_event.set()
            if self.thread_id:
                ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x12, 0, 0)
            return
        if os.name != "nt" or (self.thread and self.thread.is_alive()):
            self.enabled = False
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name="Operator hotkeys")
        self.thread.start()

    def _run(self):
        user32 = ctypes.windll.user32
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        # Create the thread message queue before a shutdown request can be posted.
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        registered = []
        try:
            for key, vk in KEYS.items():
                if user32.RegisterHotKey(None, key, 0x4003, vk):  # NOREPEAT | CTRL | ALT
                    registered.append(key)
            self.status.emit(
                "Atalhos globais ativos"
                if len(registered) == len(KEYS)
                else "Alguns atalhos globais estão ocupados por outro aplicativo."
            )
            while not self.stop_event.is_set() and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x312 and msg.wParam in registered and self.enabled:
                    self.pressed.emit(int(msg.wParam))
        finally:
            for key in registered:
                user32.UnregisterHotKey(None, key)
            self.thread_id = 0
