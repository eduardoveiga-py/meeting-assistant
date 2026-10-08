"""Real HWND/API probe in an isolated Windows process; no operator apps touched."""

import json
import os
import sys
import threading
import time

import psutil
import win32api
import win32con
import win32gui

from meeting_assistant.services.external_window_backend import ExternalWindowBackend
from meeting_assistant.services.window_inventory import NativeWindow


def probe(initial_state):
    hwnds = []
    class_name = f"MAExternalFixture{os.getpid()}"
    wc = win32gui.WNDCLASS()
    wc.hInstance = win32api.GetModuleHandle(None)
    wc.lpszClassName = class_name
    wc.lpfnWndProc = win32gui.DefWindowProc
    win32gui.RegisterClass(wc)
    work = win32api.GetMonitorInfo(win32api.MonitorFromPoint((0, 0)))["Work"]
    target = (work[0] + 20, work[1] + 20, work[2] - 20, work[3] - 20)

    def create(style, rect):
        hwnd = win32gui.CreateWindowEx(
            0, class_name, "External native test", style, rect[0], rect[1],
            rect[2] - rect[0], rect[3] - rect[1], 0, 0, wc.hInstance, None,
        )
        hwnds.append(hwnd)
        return hwnd

    def capture(hwnd, name):
        return NativeWindow(
            hwnd, os.getpid(), psutil.Process().create_time(), name, "External native test",
            class_name, win32gui.GetWindowRect(hwnd), win32gui.GetWindowPlacement(hwnd),
            bool(win32gui.IsWindowVisible(hwnd)), bool(win32gui.IsIconic(hwnd)),
            bool(win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOPMOST),
            win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE),
            win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE),
        )

    result = {}
    try:
        player = create(win32con.WS_OVERLAPPEDWINDOW, (work[0] + 60, work[1] + 60,
                                                      work[0] + 520, work[1] + 380))
        hall = create(win32con.WS_POPUP, target)
        win32gui.ShowWindow(player, win32con.SW_SHOWNORMAL)
        win32gui.ShowWindow(player, {"normal": win32con.SW_SHOWNORMAL,
                                    "minimized": win32con.SW_MINIMIZE,
                                    "maximized": win32con.SW_MAXIMIZE}[initial_state])
        win32gui.SetWindowPos(hall, win32con.HWND_TOPMOST, *target[:2],
                             target[2] - target[0], target[3] - target[1],
                             win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE)
        original, hall_original = capture(player, "python.exe"), capture(hall, "jwlibrary.exe")
        if initial_state == "minimized":
            assert original.style & win32con.WS_MINIMIZE
        if initial_state == "maximized":
            assert original.style & win32con.WS_MAXIMIZE
        backend = ExternalWindowBackend(lambda: hall_original)
        # Only these fixture HWNDs are enumerated. Native identity, showing,
        # style writes, root lookup, DWM, hit tests and placement remain real.
        backend.windows = lambda: [capture(player, "python.exe"), capture(hall, "jwlibrary.exe")]

        def cycle():
            try:
                assert backend.present(original, target)
                assert backend.last_snapshot["ready"]
                assert not win32gui.IsIconic(player)
                assert not win32gui.GetWindowLong(player, win32con.GWL_STYLE) & (
                    win32con.WS_MINIMIZE | win32con.WS_MAXIMIZE
                )
                assert not win32gui.IsWindowVisible(hall)
                presented = dict(backend.last_snapshot)
                assert backend.maintain_presentation(original, target)["ready"]
                backend.restore_presentation(original)
                assert all(backend.last_snapshot[key] for key in (
                    "placement_ok", "show_state_ok", "minimized_ok", "topmost_ok", "frame_ok", "edges_ok"
                ))
                result.update(ok=True, initial_state=initial_state, presented=presented,
                              restored=dict(backend.last_snapshot))
            except Exception as exc:
                result.update(ok=False, initial_state=initial_state,
                              error=f"{type(exc).__name__}: {exc}", snapshot=backend.last_snapshot)

        worker = threading.Thread(target=cycle, daemon=True)
        worker.start()
        deadline = time.monotonic() + 14
        while worker.is_alive() and time.monotonic() < deadline:
            win32gui.PumpWaitingMessages()  # ShowWindowAsync must reach the owning GUI thread.
            time.sleep(0.005)
        assert not worker.is_alive(), "Native fixture worker exceeded 14 seconds"
        win32gui.PumpWaitingMessages()
        assert result.get("ok"), result
        assert win32gui.IsWindowVisible(hall)
        assert win32gui.IsIconic(player) == original.minimized
        return result
    finally:
        for hwnd in reversed(hwnds):
            if win32gui.IsWindow(hwnd):
                win32gui.DestroyWindow(hwnd)
        win32gui.UnregisterClass(class_name, wc.hInstance)


if __name__ == "__main__":
    print(json.dumps(probe(sys.argv[1])))
