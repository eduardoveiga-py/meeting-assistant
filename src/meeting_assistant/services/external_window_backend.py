"""Explicit player presentation, isolated from the validated JWL/Zoom guardian."""

import ctypes
import time

from meeting_assistant.services.native_window import activate_window, show_window_async
from meeting_assistant.services.window_inventory import WindowBackend, is_jwl


def cloak_state(hwnd):
    value = ctypes.c_int()
    result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        ctypes.c_void_p(hwnd), 14, ctypes.byref(value), ctypes.sizeof(value)
    )
    if result != 0:
        raise ValueError("O Windows não confirmou a visibilidade do player.")
    return value.value


class ExternalWindowBackend(WindowBackend):
    def __init__(self, hall_window_provider=None, *, clock=time.monotonic, pause=time.sleep):
        self._hall_window_provider = hall_window_provider or (lambda: None)
        self._hall_original = None
        self._clock, self._pause = clock, pause
        self.last_snapshot = {}

    @staticmethod
    def _win32():
        import win32con
        import win32gui

        return win32con, win32gui

    def _release_hall(self, rect):
        # The provider publishes the already identified secondary HWND. Never
        # demote the operator's JWL by guessing among identical window titles.
        identified = self._hall_window_provider()
        if identified is None:
            return
        matches = [w for w in self.windows() if is_jwl(w) and w.hwnd == identified.hwnd
                   and w.pid == identified.pid and w.class_name == identified.class_name]
        if len(matches) != 1 or not self.same_window(matches[0]):
            return
        hall = matches[0]
        left, top, right, bottom = rect
        x1, y1, x2, y2 = hall.rect
        if min(right, x2) <= max(left, x1) or min(bottom, y2) <= max(top, y1):
            return
        self._hall_original = hall
        con, gui = self._win32()
        gui.SetWindowPos(hall.hwnd, con.HWND_NOTOPMOST, 0, 0, 0, 0,
                         con.SWP_NOACTIVATE | con.SWP_NOMOVE | con.SWP_NOSIZE
                         | con.SWP_ASYNCWINDOWPOS)

    def _restore_hall_order(self):
        hall = self._hall_original
        if hall is None:
            return
        if self.same_window(hall):
            con, gui = self._win32()
            gui.SetWindowPos(hall.hwnd, con.HWND_TOPMOST if hall.topmost else con.HWND_NOTOPMOST,
                             0, 0, 0, 0, con.SWP_NOACTIVATE | con.SWP_NOMOVE | con.SWP_NOSIZE
                             | con.SWP_ASYNCWINDOWPOS)
        self._hall_original = None

    def _position(self, window, rect, *, frame_changed=False):
        con, gui = self._win32()
        flags = con.SWP_SHOWWINDOW | con.SWP_NOACTIVATE | con.SWP_ASYNCWINDOWPOS
        if frame_changed:
            flags |= con.SWP_FRAMECHANGED
        gui.SetWindowPos(window.hwnd, con.HWND_TOPMOST, rect[0], rect[1],
                         rect[2] - rect[0], rect[3] - rect[1], flags)

    def presentation_snapshot(self, window, rect):
        con, gui = self._win32()
        snapshot = {"hwnd": window.hwnd, "target_rect": list(rect), "ready": False,
                    "valid": self.same_window(window)}
        if not snapshot["valid"]:
            self.last_snapshot = snapshot
            return snapshot
        actual = gui.GetWindowRect(window.hwnd)
        left, top, right, bottom = rect
        width, height = right - left, bottom - top
        points = [(left + width // 2, top + height // 2)]
        points.extend((left + width * x // 4, top + height * y // 4)
                      for x, y in ((1, 1), (3, 1), (1, 3), (3, 3)))
        root = int(gui.GetAncestor(window.hwnd, con.GA_ROOT) or window.hwnd)
        covers = []
        for point in points:
            hit = int(gui.WindowFromPoint(point) or 0)
            covers.append(int(gui.GetAncestor(hit, con.GA_ROOT) or hit) if hit else 0)
        snapshot.update(rect=list(actual), visible=bool(gui.IsWindowVisible(window.hwnd)),
                        minimized=bool(gui.IsIconic(window.hwnd)), cloaked=cloak_state(window.hwnd),
                        geometry_ok=all(abs(a - b) <= 12 for a, b in zip(actual, rect, strict=True)),
                        exposed=all(hit == root for hit in covers), cover_hwnd=covers[0])
        snapshot["ready"] = (snapshot["visible"] and not snapshot["minimized"]
                             and not snapshot["cloaked"] and snapshot["geometry_ok"]
                             and snapshot["exposed"])
        self.last_snapshot = snapshot
        return snapshot

    def present(self, window, rect):
        con, gui = self._win32()
        if not self.same_window(window):
            raise ValueError("Player mudou de processo.")
        self._hall_original = None
        self._release_hall(rect)
        show_window_async(window.hwnd, con.SW_RESTORE)
        gui.SetWindowLong(window.hwnd, con.GWL_STYLE,
                          window.style & ~(con.WS_CAPTION | con.WS_THICKFRAME))
        gui.SetWindowLong(window.hwnd, con.GWL_EXSTYLE,
                          window.extended_style & ~(con.WS_EX_CLIENTEDGE | con.WS_EX_WINDOWEDGE))
        self._position(window, rect, frame_changed=True)
        deadline = self._clock() + 2.5
        activation_attempted = False
        activation_accepted = None
        while True:
            snapshot = self.presentation_snapshot(window, rect)
            snapshot.update(activation_attempted=activation_attempted,
                            activation_accepted=activation_accepted)
            if snapshot["ready"]:
                return True
            if not snapshot["valid"]:
                raise ValueError("Player mudou de processo durante a apresentação.")
            if not snapshot["exposed"] and not activation_attempted:
                # Use the operator's explicit click once, as in the validated
                # Zoom flow. Never run a background foreground-stealing loop.
                activation_attempted = True
                activation_accepted = activate_window(window.hwnd)
            if self._clock() >= deadline:
                snapshot.update(activation_attempted=activation_attempted,
                                activation_accepted=activation_accepted)
                raise ValueError("Player não ficou visível à frente do JWL no Salão.")
            self._pause(0.05)
            if not self.same_window(window):
                raise ValueError("Player mudou de processo durante a apresentação.")
            self._position(window, rect)

    def confirm_presentation(self, window, rect):
        snapshot = self.presentation_snapshot(window, rect)
        if not snapshot["ready"]:
            raise ValueError("Player deixou de estar visível no Salão; retornando ao JWL.")
        return snapshot

    def restore_presentation(self, window):
        con, gui = self._win32()
        try:
            if not self.same_window(window):
                self.last_snapshot = {"hwnd": window.hwnd, "closed_or_replaced": True}
                return  # Never alter a reused HWND or reopen a closed player.
            frame_mask = con.WS_CAPTION | con.WS_THICKFRAME
            edge_mask = con.WS_EX_CLIENTEDGE | con.WS_EX_WINDOWEDGE
            gui.SetWindowLong(window.hwnd, con.GWL_STYLE,
                              (gui.GetWindowLong(window.hwnd, con.GWL_STYLE) & ~frame_mask)
                              | (window.style & frame_mask))
            gui.SetWindowLong(window.hwnd, con.GWL_EXSTYLE,
                              (gui.GetWindowLong(window.hwnd, con.GWL_EXSTYLE) & ~edge_mask)
                              | (window.extended_style & edge_mask))
            placement = (window.placement[0] | 4, *window.placement[1:])  # WPF_ASYNCWINDOWPLACEMENT
            gui.SetWindowPlacement(window.hwnd, placement)
            gui.SetWindowPos(window.hwnd, con.HWND_TOPMOST if window.topmost else con.HWND_NOTOPMOST,
                             0, 0, 0, 0, con.SWP_NOMOVE | con.SWP_NOSIZE | con.SWP_NOACTIVATE
                             | con.SWP_FRAMECHANGED | con.SWP_ASYNCWINDOWPOS)
            deadline = self._clock() + 2.5
            while True:
                if not self.same_window(window):
                    return
                actual = gui.GetWindowPlacement(window.hwnd)
                self.last_snapshot = {
                    "hwnd": window.hwnd,
                    "placement_ok": all(abs(a - b) <= 12 for a, b in
                                        zip(actual[4], window.placement[4], strict=True)),
                    "show_state_ok": actual[1] == window.placement[1],
                    "minimized_ok": bool(gui.IsIconic(window.hwnd)) == window.minimized,
                    "topmost_ok": bool(gui.GetWindowLong(window.hwnd, con.GWL_EXSTYLE)
                                       & con.WS_EX_TOPMOST) == window.topmost,
                    "frame_ok": (gui.GetWindowLong(window.hwnd, con.GWL_STYLE) & frame_mask)
                                == (window.style & frame_mask),
                    "edges_ok": (gui.GetWindowLong(window.hwnd, con.GWL_EXSTYLE) & edge_mask)
                                == (window.extended_style & edge_mask),
                }
                if all(self.last_snapshot[name] for name in
                       ("placement_ok", "show_state_ok", "minimized_ok",
                        "topmost_ok", "frame_ok", "edges_ok")):
                    return
                if self._clock() >= deadline:
                    raise ValueError("Player não confirmou a disposição anterior em 2,5 s.")
                self._pause(0.05)
        finally:
            # Restore ordering even after a partial player rollback. The
            # existing explicit JWL return then confirms actual hall exposure.
            self._restore_hall_order()
