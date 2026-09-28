"""Windows 10/11 x64 DirectShow backend; no changes to hall windows or OBS scenes."""

import ctypes
import os
import platform
from pathlib import Path

CLSID = "{B316823F-42CF-4F77-9190-319D1B245EC8}"
GATE_NAME = r"Local\MeetingAssistant.CompatVideo.Enabled.v1"


def registered_camera():
    if platform.system() != "Windows" or platform.machine().lower() not in ("amd64", "x86_64"):
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            rf"SOFTWARE\Classes\CLSID\{CLSID}\InprocServer32",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            path, _ = winreg.QueryValueEx(key, None)
        return Path(os.path.expandvars(path)).is_file()
    except (OSError, TypeError):
        return False


def resolve_backend(mode, modern_supported):
    return ("modern" if modern_supported else "compat") if mode == "auto" else mode


class CompatibilityGate:
    """Session-local opt-in. Native filter emits black unless this event is signalled."""

    def __init__(self):
        from ctypes import wintypes as w

        self.handle = None
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateEventW.argtypes = [ctypes.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR]
        self.kernel.CreateEventW.restype = w.HANDLE
        for name in ("SetEvent", "ResetEvent", "CloseHandle"):
            fn = getattr(self.kernel, name)
            fn.argtypes = [w.HANDLE]
            fn.restype = w.BOOL
        handle = self.kernel.CreateEventW(None, True, False, GATE_NAME)
        if not handle:
            raise OSError("Não foi possível preparar a câmera de compatibilidade.")
        if ctypes.get_last_error() == 183:
            self.kernel.CloseHandle(handle)
            raise OSError("Outro teste de compatibilidade está aberto. Feche-o antes de continuar.")
        self.handle = handle
        if not self.kernel.SetEvent(handle):
            self.close()
            raise OSError("Não foi possível ativar a câmera de compatibilidade.")

    def close(self):
        if self.handle is not None:
            self.kernel.ResetEvent(self.handle)
            self.kernel.CloseHandle(self.handle)
            self.handle = None
