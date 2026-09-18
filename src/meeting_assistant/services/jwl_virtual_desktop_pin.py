from __future__ import annotations

import ctypes
import queue
import sys
import threading
from ctypes import wintypes
from dataclasses import asdict, dataclass
from uuid import UUID

from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True, slots=True)
class VirtualDesktopPinResult:
    hwnd: int
    ok: bool
    already_pinned: bool
    action: str
    hresult: int | None = None
    error: str = ""
    details: dict[str, int | bool | str] | None = None


class _Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_text(cls, value: str) -> _Guid:
        item = UUID(value.strip("{}"))
        node = item.node.to_bytes(6, "big")
        data4 = (ctypes.c_ubyte * 8)(
            item.clock_seq_hi_variant,
            item.clock_seq_low,
            *node,
        )
        return cls(
            item.time_low,
            item.time_mid,
            item.time_hi_version,
            data4,
        )


_CLSID_IMMERSIVE_SHELL = _Guid.from_text(
    "{C2F03A33-21F5-47FA-B4BB-156362A2F239}"
)
_IID_SERVICE_PROVIDER = _Guid.from_text(
    "{6D5140C1-7436-11CE-8034-00AA006009FA}"
)
_IID_APPLICATION_VIEW_COLLECTION = _Guid.from_text(
    "{1841C6D7-4F9D-42C0-AF41-8747538F10E5}"
)
_CLSID_VIRTUAL_DESKTOP_PINNED_APPS = _Guid.from_text(
    "{B5A399E7-1C87-46B8-88E9-FC5747B171BD}"
)
_IID_VIRTUAL_DESKTOP_PINNED_APPS = _Guid.from_text(
    "{4CE81583-1E4C-4632-A621-07A53543148F}"
)

_CLSCTX_ALL = 0x17
_COINIT_APARTMENTTHREADED = 0x2


def _failed(hr: int) -> bool:
    return int(hr) < 0


class _VirtualDesktopPinSession:
    """Minimal COM bridge for ApplicationViewCollection + PinnedApps.

    Only the stable method slots required to pin/unpin one HWND are used.
    All calls stay on the dedicated STA worker thread.
    """

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("virtual desktop pinning requires Windows")

        self._ole32 = ctypes.WinDLL("ole32")
        self._ole32.CoCreateInstance.argtypes = [
            ctypes.POINTER(_Guid),
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_Guid),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._ole32.CoCreateInstance.restype = ctypes.c_long

        self._service_provider = ctypes.c_void_p()
        hr = int(
            self._ole32.CoCreateInstance(
                ctypes.byref(_CLSID_IMMERSIVE_SHELL),
                None,
                _CLSCTX_ALL,
                ctypes.byref(_IID_SERVICE_PROVIDER),
                ctypes.byref(self._service_provider),
            )
        )
        if _failed(hr) or not self._service_provider.value:
            raise RuntimeError(f"ImmersiveShell unavailable: HRESULT 0x{hr & 0xFFFFFFFF:08X}")

        self._views = self._query_service(
            _IID_APPLICATION_VIEW_COLLECTION,
            _IID_APPLICATION_VIEW_COLLECTION,
        )
        self._pinned_apps = self._query_service(
            _CLSID_VIRTUAL_DESKTOP_PINNED_APPS,
            _IID_VIRTUAL_DESKTOP_PINNED_APPS,
        )

    def close(self) -> None:
        for pointer in (self._pinned_apps, self._views, self._service_provider):
            self._release(pointer)
        self._pinned_apps = ctypes.c_void_p()
        self._views = ctypes.c_void_p()
        self._service_provider = ctypes.c_void_p()

    def pin(self, hwnd: int) -> VirtualDesktopPinResult:
        view = self._view_for_hwnd(hwnd)
        if not view.value:
            return VirtualDesktopPinResult(
                hwnd=hwnd,
                ok=False,
                already_pinned=False,
                action="pin",
                error="ApplicationView not found for HWND",
            )

        try:
            is_pinned = wintypes.BOOL(0)
            method = self._com_method(
                self._pinned_apps,
                6,  # IVirtualDesktopPinnedApps::IsViewPinned
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.BOOL),
            )
            hr = int(method(self._pinned_apps, view, ctypes.byref(is_pinned)))
            if _failed(hr):
                return VirtualDesktopPinResult(
                    hwnd=hwnd,
                    ok=False,
                    already_pinned=False,
                    action="pin",
                    hresult=hr,
                    error="IsViewPinned failed",
                )

            if bool(is_pinned.value):
                return VirtualDesktopPinResult(
                    hwnd=hwnd,
                    ok=True,
                    already_pinned=True,
                    action="pin",
                    hresult=hr,
                )

            pin_method = self._com_method(
                self._pinned_apps,
                7,  # IVirtualDesktopPinnedApps::PinView
                ctypes.c_long,
                ctypes.c_void_p,
            )
            hr = int(pin_method(self._pinned_apps, view))
            return VirtualDesktopPinResult(
                hwnd=hwnd,
                ok=not _failed(hr),
                already_pinned=False,
                action="pin",
                hresult=hr,
                error="" if not _failed(hr) else "PinView failed",
            )
        finally:
            self._release(view)

    def unpin(self, hwnd: int) -> VirtualDesktopPinResult:
        view = self._view_for_hwnd(hwnd)
        if not view.value:
            return VirtualDesktopPinResult(
                hwnd=hwnd,
                ok=False,
                already_pinned=False,
                action="unpin",
                error="ApplicationView not found for HWND",
            )

        try:
            is_pinned = wintypes.BOOL(0)
            check = self._com_method(
                self._pinned_apps,
                6,
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.BOOL),
            )
            hr = int(check(self._pinned_apps, view, ctypes.byref(is_pinned)))
            if _failed(hr):
                return VirtualDesktopPinResult(
                    hwnd=hwnd,
                    ok=False,
                    already_pinned=False,
                    action="unpin",
                    hresult=hr,
                    error="IsViewPinned failed",
                )

            if not bool(is_pinned.value):
                return VirtualDesktopPinResult(
                    hwnd=hwnd,
                    ok=True,
                    already_pinned=False,
                    action="unpin",
                    hresult=hr,
                )

            unpin = self._com_method(
                self._pinned_apps,
                8,  # IVirtualDesktopPinnedApps::UnpinView
                ctypes.c_long,
                ctypes.c_void_p,
            )
            hr = int(unpin(self._pinned_apps, view))
            return VirtualDesktopPinResult(
                hwnd=hwnd,
                ok=not _failed(hr),
                already_pinned=True,
                action="unpin",
                hresult=hr,
                error="" if not _failed(hr) else "UnpinView failed",
            )
        finally:
            self._release(view)

    def recover_shell_cloak(
        self,
        hwnd: int,
        return_hwnd: int = 0,
    ) -> VirtualDesktopPinResult:
        view = self._view_for_hwnd(hwnd)
        if not view.value:
            return VirtualDesktopPinResult(
                hwnd=hwnd,
                ok=False,
                already_pinned=False,
                action="recover",
                error="ApplicationView not found for HWND",
            )

        set_cloak_hr: int | None = None
        switch_hr: int | None = None
        return_hr: int | None = None
        try:
            set_cloak = self._com_method(
                view,
                12,  # IApplicationView::SetCloak
                ctypes.c_long,
                ctypes.c_int,
                ctypes.c_uint,
            )
            set_cloak_hr = int(set_cloak(view, 0, 0))  # AVCT_NONE

            switch_to = self._com_method(
                view,
                7,  # IApplicationView::SwitchTo
                ctypes.c_long,
            )
            switch_hr = int(switch_to(view))

            if return_hwnd > 0 and return_hwnd != hwnd:
                return_view = self._view_for_hwnd(return_hwnd)
                if return_view.value:
                    try:
                        return_switch = self._com_method(
                            return_view,
                            7,
                            ctypes.c_long,
                        )
                        return_hr = int(return_switch(return_view))
                    finally:
                        self._release(return_view)

            ok = not _failed(set_cloak_hr) or not _failed(switch_hr)
            return VirtualDesktopPinResult(
                hwnd=hwnd,
                ok=ok,
                already_pinned=False,
                action="recover",
                hresult=switch_hr if switch_hr is not None else set_cloak_hr,
                error="" if ok else "SetCloak/SwitchTo failed",
                details={
                    "set_cloak_hresult": int(set_cloak_hr or 0),
                    "switch_hresult": int(switch_hr or 0),
                    "return_hresult": int(return_hr or 0),
                    "return_hwnd": int(return_hwnd),
                },
            )
        finally:
            self._release(view)

    def _view_for_hwnd(self, hwnd: int) -> ctypes.c_void_p:
        view = ctypes.c_void_p()
        method = self._com_method(
            self._views,
            6,  # IApplicationViewCollection::GetViewForHwnd
            ctypes.c_long,
            wintypes.HWND,
            ctypes.POINTER(ctypes.c_void_p),
        )
        hr = int(method(self._views, hwnd, ctypes.byref(view)))
        if _failed(hr):
            return ctypes.c_void_p()
        return view

    def _query_service(
        self,
        service: _Guid,
        iid: _Guid,
    ) -> ctypes.c_void_p:
        pointer = ctypes.c_void_p()
        method = self._com_method(
            self._service_provider,
            3,  # IServiceProvider::QueryService
            ctypes.c_long,
            ctypes.POINTER(_Guid),
            ctypes.POINTER(_Guid),
            ctypes.POINTER(ctypes.c_void_p),
        )
        hr = int(
            method(
                self._service_provider,
                ctypes.byref(service),
                ctypes.byref(iid),
                ctypes.byref(pointer),
            )
        )
        if _failed(hr) or not pointer.value:
            raise RuntimeError(
                f"QueryService failed: HRESULT 0x{hr & 0xFFFFFFFF:08X}"
            )
        return pointer

    @staticmethod
    def _com_method(
        pointer: ctypes.c_void_p,
        index: int,
        restype,
        *argtypes,
    ):
        if not pointer.value:
            raise RuntimeError("invalid COM pointer")
        vtable_pointer = ctypes.cast(
            pointer,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
        )
        address = vtable_pointer.contents[index]
        prototype = ctypes.WINFUNCTYPE(
            restype,
            ctypes.c_void_p,
            *argtypes,
        )
        return prototype(address)

    @classmethod
    def _release(cls, pointer: ctypes.c_void_p) -> None:
        if not getattr(pointer, "value", None):
            return
        try:
            method = cls._com_method(pointer, 2, ctypes.c_ulong)
            method(pointer)
        except (OSError, RuntimeError, ValueError):
            pass


class JwlVirtualDesktopPinService(QObject):
    """Keep only the JW Library Hall-output view visible across virtual desktops."""

    result = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.Queue[tuple[str, int, int]] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pinned_hwnds: set[int] = set()
        self._requested_hwnd = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="MeetingAssistant-VirtualDesktopPin",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if not self._thread:
            return
        for hwnd in tuple(self._pinned_hwnds):
            self._queue.put(("unpin", hwnd, 0))
        self._queue.put(("stop", 0, 0))
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def ensure_pinned(self, hwnd: int) -> None:
        hwnd = int(hwnd)
        if hwnd <= 0 or hwnd == self._requested_hwnd:
            return
        self._requested_hwnd = hwnd
        self._queue.put(("pin", hwnd, 0))

    def recover_shell_cloak(self, hwnd: int, return_hwnd: int = 0) -> None:
        hwnd = int(hwnd)
        return_hwnd = int(return_hwnd)
        if hwnd <= 0:
            return
        self._queue.put(("recover", hwnd, return_hwnd))

    def _run(self) -> None:
        if sys.platform != "win32":
            return

        ole32 = ctypes.WinDLL("ole32")
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        ole32.CoInitializeEx.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = []
        ole32.CoUninitialize.restype = None

        init_hr = int(ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED))
        initialized_here = init_hr in (0, 1)
        session: _VirtualDesktopPinSession | None = None

        try:
            if _failed(init_hr):
                self.result.emit(
                    VirtualDesktopPinResult(
                        hwnd=0,
                        ok=False,
                        already_pinned=False,
                        action="init",
                        hresult=init_hr,
                        error="CoInitializeEx failed",
                    )
                )
                return

            try:
                session = _VirtualDesktopPinSession()
            except Exception as exc:  # noqa: BLE001 - optional Windows integration
                self.result.emit(
                    VirtualDesktopPinResult(
                        hwnd=0,
                        ok=False,
                        already_pinned=False,
                        action="init",
                        error=repr(exc),
                    )
                )
                return

            while True:
                try:
                    action, hwnd, extra_hwnd = self._queue.get(timeout=0.5)
                except queue.Empty:
                    if self._stop.is_set():
                        break
                    continue

                if action == "stop":
                    break

                try:
                    if action == "pin":
                        item = session.pin(hwnd)
                        if item.ok:
                            self._pinned_hwnds.add(hwnd)
                        else:
                            self._requested_hwnd = 0
                        self.result.emit(item)
                    elif action == "unpin":
                        item = session.unpin(hwnd)
                        if item.ok:
                            self._pinned_hwnds.discard(hwnd)
                        self.result.emit(item)
                    elif action == "recover":
                        item = session.recover_shell_cloak(hwnd, extra_hwnd)
                        self.result.emit(item)
                except Exception as exc:  # noqa: BLE001 - best-effort integration
                    if action == "pin":
                        self._requested_hwnd = 0
                    self.result.emit(
                        VirtualDesktopPinResult(
                            hwnd=hwnd,
                            ok=False,
                            already_pinned=False,
                            action=action,
                            error=repr(exc),
                        )
                    )
        finally:
            if session is not None:
                session.close()
            if initialized_here:
                ole32.CoUninitialize()


def pin_result_to_dict(value: object) -> dict[str, object]:
    if isinstance(value, VirtualDesktopPinResult):
        return asdict(value)
    return {"value": repr(value)}
