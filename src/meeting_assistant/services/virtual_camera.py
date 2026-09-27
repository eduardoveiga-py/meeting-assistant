"""Versioned local OBS video transport. No screenshots, scene changes or audio."""

from __future__ import annotations

import ctypes
import platform
import struct
import sys
from dataclasses import asdict, dataclass

WIDTH, HEIGHT = 1280, 720
FRAME_BYTES = WIDTH * HEIGHT * 3 // 2
HEADER = struct.Struct("<8I2Q")
MAGIC = 0x3143414D
PIPE_PREFIX = r"\\.\pipe\MeetingAssistant."


@dataclass(frozen=True)
class FrameStatus:
    enabled: bool
    fresh: bool
    sequence: int
    tick_ms: int
    width: int = WIDTH
    height: int = HEIGHT

    def diagnostic(self):
        return asdict(self)


def camera_support(system=None, build=None, machine=None):
    system = system or platform.system()
    machine = machine or platform.machine()
    if system != "Windows":
        return False, "Requer Windows; diagnóstico do protocolo disponível nos testes automatizados."
    if build is None:
        build = sys.getwindowsversion().build
    if machine.casefold() not in ("amd64", "x86_64"):
        return False, "Este protótipo exige Windows x64; ARM64 ainda não foi validado."
    if build < 22000:
        return (
            False,
            "Câmera própria requer Windows 11 (build 22000+). Ponte OBS pode ser testada no Windows 10.",
        )
    return True, "Windows compatível com a API. Reconhecimento no WhatsApp ainda exige teste real."


def decode_header(data):
    if len(data) != HEADER.size:
        raise ValueError("Cabeçalho de vídeo incompleto.")
    magic, version, size, width, height, payload, flags, reserved, sequence, tick_ms = HEADER.unpack(data)
    if (
        magic != MAGIC
        or version != 1
        or size != HEADER.size
        or width != WIDTH
        or height != HEIGHT
        or payload not in (0, FRAME_BYTES)
        or flags & ~3
        or reserved
    ):
        raise ValueError("Protocolo de vídeo incompatível; atualize app e plugin juntos.")
    if flags & 2 and not flags & 1:
        raise ValueError("Estado de vídeo inconsistente.")
    if payload and flags != 3:
        raise ValueError("Quadro sem confirmação de atualização.")
    return FrameStatus(bool(flags & 1), bool(flags & 2), sequence, tick_ms), payload


class WindowsPipe:
    """Overlapped I/O with cancellation; never creates a missing server."""

    def __init__(self, path):
        if sys.platform != "win32":
            raise OSError("A ponte requer Windows.")
        from ctypes import wintypes as w

        class Overlapped(ctypes.Structure):
            _fields_ = [
                ("Internal", ctypes.c_size_t),
                ("InternalHigh", ctypes.c_size_t),
                ("Offset", w.DWORD),
                ("OffsetHigh", w.DWORD),
                ("hEvent", w.HANDLE),
            ]

        self.Overlapped = Overlapped
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateFileW": (
                [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE],
                w.HANDLE,
            ),
            "CreateEventW": ([ctypes.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR], w.HANDLE),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
            "CancelIoEx": ([w.HANDLE, ctypes.POINTER(Overlapped)], w.BOOL),
            "GetOverlappedResult": (
                [w.HANDLE, ctypes.POINTER(Overlapped), ctypes.POINTER(w.DWORD), w.BOOL],
                w.BOOL,
            ),
        }
        for name in ("ReadFile", "WriteFile"):
            signatures[name] = (
                [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.POINTER(Overlapped)],
                w.BOOL,
            )
        for name, (args, restype) in signatures.items():
            getattr(self.k, name).argtypes = args
            getattr(self.k, name).restype = restype
        self.handle = self.k.CreateFileW(path, 0xC0000000, 0, None, 3, 0x40000000, None)
        if self.handle == ctypes.c_void_p(-1).value:
            raise OSError("Ponte OBS indisponível ou ocupada. Confira plugin, OBS e mesma sessão de usuário.")

    def transfer(self, size, data=None):
        from ctypes import wintypes as w

        if not 0 < size <= FRAME_BYTES:
            raise ValueError("Tamanho de transferência inválido.")
        buffer = (
            ctypes.create_string_buffer(data, size) if data is not None else ctypes.create_string_buffer(size)
        )
        ov = self.Overlapped()
        ov.hEvent = self.k.CreateEventW(None, True, False, None)
        if not ov.hEvent:
            raise OSError("Não foi possível criar evento de leitura.")
        count = w.DWORD()
        try:
            fn = self.k.WriteFile if data is not None else self.k.ReadFile
            ok = fn(self.handle, buffer, size, ctypes.byref(count), ctypes.byref(ov))
            if not ok and ctypes.get_last_error() == 997:
                if self.k.WaitForSingleObject(ov.hEvent, 400) != 0:
                    self.k.CancelIoEx(self.handle, ctypes.byref(ov))
                    self.k.GetOverlappedResult(self.handle, ctypes.byref(ov), ctypes.byref(count), True)
                    raise TimeoutError("A ponte OBS não respondeu no prazo.")
                ok = self.k.GetOverlappedResult(self.handle, ctypes.byref(ov), ctypes.byref(count), False)
            if not ok or count.value != size:
                raise OSError("Transferência interrompida; nenhum quadro foi confirmado.")
            return buffer.raw
        finally:
            self.k.CloseHandle(ov.hEvent)

    def close(self):
        self.k.CloseHandle(self.handle)


def request(command="I", pipe_factory=WindowsPipe):
    if command not in ("I", "S", "T", "F"):
        raise ValueError("Comando de vídeo desconhecido.")
    pipe = pipe_factory(PIPE_PREFIX + ("Program.v1" if command == "F" else "Control.v1"))
    try:
        pipe.transfer(1, command.encode("ascii"))
        status, size = decode_header(pipe.transfer(HEADER.size))
        if command != "F" and size:
            raise ValueError("Resposta de controle contém vídeo inesperado.")
        pixels = pipe.transfer(size) if size else b""
        pipe.transfer(1, b"A")
        return status, pixels
    finally:
        pipe.close()
