"""Explicit player presentation, isolated from the validated JWL/Zoom guardian."""

import ctypes
import time
from ctypes import wintypes
from dataclasses import replace

from meeting_assistant.services.jwl_secondary_window import JwlSecondaryWindowInfo, WindowRect
from meeting_assistant.services.native_window import activate_window, show_window_async
from meeting_assistant.services.window_inventory import WindowBackend, is_jwl


def set_frame_style(hwnd, index, value):
    """Use typed WinDLL calls which release the GIL during cross-thread messages.

    pywin32's custom SetWindowLong wrapper holds the GIL while calling user32.
    A window procedure needing Python can deadlock; even another process may
    stall Qt while its synchronous style notifications are processed. Preserve
    pointer width and distinguish a valid zero previous value from API failure.
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    setter = user32.SetWindowLongPtrW
    setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    setter.restype = ctypes.c_ssize_t
    ctypes.set_last_error(0)
    previous = setter(hwnd, index, value)
    error = ctypes.get_last_error()
    if previous == 0 and error:
        raise ctypes.WinError(error)


def cloak_state(hwnd):
    value = ctypes.c_int()
    result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        ctypes.c_void_p(hwnd), 14, ctypes.byref(value), ctypes.sizeof(value)
    )
    if result != 0:
        raise ValueError("O Windows não confirmou a visibilidade do player.")
    return value.value


def operator_placement(window, monitors):
    """Preserve the saved layout, clamping its normal rect to primary if needed.

    WINDOWPLACEMENT is workspace-relative (screen-relative for tool windows).
    Its normal rect remains useful even when GetWindowRect reports -32000 for
    a minimized player. Do not overwrite the original cycle snapshot.
    """
    primary = [monitor for monitor in monitors if monitor["primary"]]
    if len(primary) != 1:
        return window.placement
    normal = window.placement[4]

    def overlap(monitor):
        left, top, right, bottom = monitor["rect"]
        return max(0, min(right, normal[2]) - max(left, normal[0])) * max(
            0, min(bottom, normal[3]) - max(top, normal[1])
        )

    old = max(monitors, key=overlap)
    tool = bool(window.extended_style & 0x80)  # WS_EX_TOOLWINDOW
    dx, dy = (0, 0) if tool else (old["work"][0] - old["rect"][0],
                                  old["work"][1] - old["rect"][1])
    screen = (normal[0] + dx, normal[1] + dy, normal[2] + dx, normal[3] + dy)
    target = primary[0]
    left, top, right, bottom = target["work"]
    if left <= screen[0] and top <= screen[1] and screen[2] <= right and screen[3] <= bottom:
        return window.placement
    width = min(right - left, max(360, screen[2] - screen[0]))
    height = min(bottom - top, max(240, screen[3] - screen[1]))
    x = max(left, min(screen[0], right - width))
    y = max(top, min(screen[1], bottom - height))
    dx, dy = (0, 0) if tool else (left - target["rect"][0], top - target["rect"][1])
    return (*window.placement[:4], (x - dx, y - dy, x + width - dx, y + height - dy))


class ExternalWindowBackend(WindowBackend):
    def __init__(self, hall_window_provider=None, *, clock=time.monotonic, pause=time.sleep,
                 style_writer=set_frame_style):
        self._hall_window_provider = hall_window_provider or (lambda: None)
        self._hall_original = None
        self._clock, self._pause = clock, pause
        self.last_snapshot = {}
        self.cancelled = lambda: False
        self.return_candidate = None
        self._write_style = style_writer

    @staticmethod
    def _win32():
        import win32con
        import win32gui

        return win32con, win32gui

    def _identified_hall(self, rect):
        # The provider publishes the already identified secondary HWND. Never
        # demote the operator's JWL by guessing among identical window titles.
        identified = self._hall_window_provider()
        if identified is None:
            raise ValueError("Saída JWL não identificada. Use Forçar JWL antes de apresentar mídia externa.")
        con, gui = self._win32()
        root = int(gui.GetAncestor(identified.hwnd, con.GA_ROOT) or identified.hwnd)
        import psutil
        import win32process

        from meeting_assistant.services.window_inventory import NativeWindow
        if not gui.IsWindow(root) or not gui.IsWindowVisible(root):
            raise ValueError(
                f"A saída JWL desapareceu. Confirme o JWL antes de apresentar mídia externa. Root: {root}"
            )
            
        matches = [w for w in self.windows() if w.hwnd == root]
        if matches:
            hall = matches[0]
        else:
            _, pid = win32process.GetWindowThreadProcessId(root)
            try:
                created = psutil.Process(pid).create_time()
            except psutil.Error:
                created = 0
            hall = NativeWindow(
                hwnd=root, pid=pid, created=created, process="jwlibrary.exe",
                title=gui.GetWindowText(root), class_name=gui.GetClassName(root),
                rect=gui.GetWindowRect(root), placement=gui.GetWindowPlacement(root),
                visible=True, minimized=bool(gui.IsIconic(root)),
                topmost=bool(gui.GetWindowLong(root, -20) & 8),
                style=gui.GetWindowLong(root, -16), extended_style=gui.GetWindowLong(root, -20),
                meeting_controls=False
            )
        
        actual_class = hall.class_name if root == identified.hwnd else gui.GetClassName(identified.hwnd)
        if actual_class != identified.class_name:
            raise ValueError("A classe da saída JWL mudou; apresentação cancelada.")
        # UIA may identify the ApplicationFrameHost PID, while inventory resolves
        # its JWLibrary child PID. Validate both identities, never guess by title.
        if identified.pid not in {hall.pid, self._native_pid(identified.hwnd)}:
            raise ValueError("A identidade da saída JWL não foi confirmada.")
        left, top, right, bottom = rect
        x1, y1, x2, y2 = hall.rect
        if min(right, x2) <= max(left, x1) or min(bottom, y2) <= max(top, y1):
            raise ValueError("A saída JWL não está no monitor do Salão.")
        return identified, hall

    def _release_hall(self, rect):
        identified, hall = self._identified_hall(rect)
        con, gui = self._win32()
        self._hall_original = hall
        if isinstance(identified, JwlSecondaryWindowInfo):
            self.return_candidate = replace(
                identified, hwnd=hall.hwnd, pid=hall.pid, process_name=hall.process,
                class_name=hall.class_name, rect=WindowRect(*hall.rect),
            )
        gui.SetWindowPos(hall.hwnd, con.HWND_NOTOPMOST, 0, 0, 0, 0,
                         con.SWP_NOACTIVATE | con.SWP_NOMOVE | con.SWP_NOSIZE
                         | con.SWP_ASYNCWINDOWPOS)
        # Explicit ownership handoff. A UWP fullscreen view may reclaim z-order
        # after demotion, even without our guardian. Hide ONLY this secondary
        # window for this cycle; keep its HWND/process, styles and geometry alive.
        show_window_async(hall.hwnd, con.SW_HIDE)

    @staticmethod
    def _native_pid(hwnd):
        import win32process

        return win32process.GetWindowThreadProcessId(hwnd)[1]

    def _keep_hall_released(self):
        hall = self._hall_original
        if hall is None or not self.same_window(hall):
            raise ValueError("Saída JWL mudou durante a mídia externa; retornando ao JWL.")
        con, gui = self._win32()
        if gui.IsWindowVisible(hall.hwnd):
            show_window_async(hall.hwnd, con.SW_HIDE)
            return True
        return False

    def _restore_hall_order(self, player_hwnd=None):
        hall = self._hall_original
        if hall is None:
            return
        if self.same_window(hall):
            con, gui = self._win32()
            if player_hwnd:
                gui.SetWindowPos(player_hwnd, con.HWND_NOTOPMOST, 0, 0, 0, 0,
                                 con.SWP_NOMOVE | con.SWP_NOSIZE | con.SWP_NOACTIVATE
                                 | con.SWP_ASYNCWINDOWPOS)
            if hall.visible:
                show_window_async(hall.hwnd, con.SW_SHOWNOACTIVATE)
            gui.SetWindowPos(hall.hwnd, con.HWND_TOPMOST if hall.topmost else con.HWND_TOPMOST,
                             0, 0, 0, 0, con.SWP_NOACTIVATE | con.SWP_NOMOVE | con.SWP_NOSIZE
                             | con.SWP_ASYNCWINDOWPOS)
            # We temporarily make JWL TOPMOST to guarantee it covers the demoted player.
            # We will revert it to its original z-order later if needed, but JWL is usually fullscreen anyway.
        else:
            self.return_candidate = None
        self._hall_original = None

    def _position(self, window, rect, *, frame_changed=False):
        con, gui = self._win32()
        flags = con.SWP_SHOWWINDOW | con.SWP_NOACTIVATE | con.SWP_ASYNCWINDOWPOS
        if frame_changed:
            flags |= con.SWP_FRAMECHANGED
        gui.SetWindowPos(window.hwnd, con.HWND_TOPMOST, rect[0], rect[1],
                         rect[2] - rect[0], rect[3] - rect[1], flags)

    def _restore_player(self, window, *, deadline=None):
        """Wait for queued restore before reading/changing its current frame.

        A saved GWL_STYLE includes live WS_MINIMIZE/WS_MAXIMIZE bits. Writing
        that saved style immediately after ShowWindowAsync can undo restoration.
        The original snapshot belongs only to the later rollback.

        We only need visible + non-minimized here. WS_MAXIMIZE is acceptable
        because present() will immediately strip the frame and call SetWindowPos
        with explicit coordinates, which overrides the maximized layout.
        """
        con, gui = self._win32()
        deadline = self._clock() + 2.5 if deadline is None else deadline
        self.last_snapshot = {"stage": "player_restore", "hwnd": window.hwnd,
                              "original_minimized": window.minimized, "ready": False}
        show_window_async(window.hwnd, con.SW_RESTORE)
        while not self.cancelled():
            if not self.same_window(window):
                raise ValueError("[PLAYER_RESTORE] Player mudou durante a restauração.")
            style = gui.GetWindowLong(window.hwnd, con.GWL_STYLE)
            minimized = bool(gui.IsIconic(window.hwnd))
            visible = bool(gui.IsWindowVisible(window.hwnd))
            self.last_snapshot.update(style=style, minimized=minimized, visible=visible)
            if visible and not minimized and not style & con.WS_MINIMIZE:
                return
            if self._clock() >= deadline:
                raise ValueError(
                    "[PLAYER_RESTORE] O player não saiu do estado minimizado em 2,5 s."
                )
            self._pause(0.05)
        raise ValueError("[PLAYER_RESTORE] Restauração cancelada.")

    @staticmethod
    def _presentation_failure(snapshot):
        if snapshot.get("minimized") or not snapshot.get("visible"):
            return "[PLAYER_STATE] O player continua minimizado ou oculto."
        if snapshot.get("cloaked"):
            return "[PLAYER_CLOAKED] O Windows manteve o player fora da área visível."
        if not snapshot.get("geometry_ok"):
            return "[PLAYER_POSITION] O player não confirmou o tamanho/posição no monitor do Salão."
        if not snapshot.get("hall_hidden"):
            return "[JWL_HANDOFF] A saída secundária JWL não confirmou a cessão do monitor."
        return "[PLAYER_EXPOSURE] Player não ficou visível à frente do JWL no Salão."

    def presentation_snapshot(self, window, rect):
        con, gui = self._win32()
        snapshot = {"stage": "player_exposure", "hwnd": window.hwnd, "target_rect": list(rect),
                    "ready": False, "valid": self.same_window(window)}
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
                        exposed=all(hit == root for hit in covers), cover_hwnd=covers[0],
                        cover_hwnds=covers, style=gui.GetWindowLong(window.hwnd, con.GWL_STYLE))
        if not snapshot["exposed"]:
            snapshot["cover_classes"] = [gui.GetClassName(hit) if hit else "" for hit in covers]
        hall = self._hall_original
        snapshot["hall_hidden"] = bool(hall and self.same_window(hall)
                                       and not gui.IsWindowVisible(hall.hwnd))
        snapshot["ready"] = (snapshot["visible"] and not snapshot["minimized"]
                             and not snapshot["cloaked"] and snapshot["geometry_ok"]
                             and snapshot["exposed"] and snapshot["hall_hidden"])
        self.last_snapshot = snapshot
        return snapshot

    def present(self, window, rect):
        con, gui = self._win32()
        if not self.same_window(window):
            raise ValueError("Player mudou de processo.")
        self._hall_original = None
        self.return_candidate = None
        self.last_snapshot = {"stage": "hall_identity", "hwnd": window.hwnd, "ready": False}
        self._identified_hall(rect)  # Refuse an unknown output before changing either window.
        self._restore_player(window)
        self.last_snapshot["stage"] = "jwl_handoff"
        self._release_hall(rect)
        self.last_snapshot["stage"] = "player_frame"
        self._write_style(window.hwnd, con.GWL_STYLE,
                          gui.GetWindowLong(window.hwnd, con.GWL_STYLE)
                          & ~(con.WS_CAPTION | con.WS_THICKFRAME | con.WS_MAXIMIZE))
        self._write_style(window.hwnd, con.GWL_EXSTYLE,
                          gui.GetWindowLong(window.hwnd, con.GWL_EXSTYLE)
                          & ~(con.WS_EX_CLIENTEDGE | con.WS_EX_WINDOWEDGE))
        self.last_snapshot["stage"] = "player_position"
        self._position(window, rect, frame_changed=True)
        deadline = self._clock() + 2.5
        activation_attempted = False
        activation_accepted = None
        while True:
            if self.cancelled():
                raise ValueError("Apresentação cancelada durante o posicionamento.")
            self._keep_hall_released()
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
                raise ValueError(self._presentation_failure(snapshot))
            self._pause(0.05)
            if not self.same_window(window):
                raise ValueError("Player mudou de processo durante a apresentação.")
            self._position(window, rect)

    def confirm_presentation(self, window, rect):
        return self.maintain_presentation(window, rect)

    def maintain_presentation(self, window, rect):
        """Bounded recovery without foreground activation or a new snapshot."""
        deadline = self._clock() + 1.0
        repaired = False
        while not self.cancelled():
            repaired = self._keep_hall_released() or repaired
            snapshot = self.presentation_snapshot(window, rect)
            snapshot["repaired"] = repaired
            if snapshot["ready"]:
                return snapshot
            if not snapshot["valid"]:
                raise ValueError("Player fechado ou substituído; retornando ao JWL.")
            if self._clock() >= deadline:
                raise ValueError("Player perdeu a exibição no Salão; retornando ao JWL.")
            if snapshot["minimized"]:
                self._restore_player(window, deadline=deadline)
            self._position(window, rect)
            repaired = True
            self._pause(0.05)
        raise ValueError("Verificação da mídia externa cancelada.")

    def restore_presentation(self, window):
        con, gui = self._win32()
        try:
            if not self.same_window(window):
                self.last_snapshot = {"hwnd": window.hwnd, "closed_or_replaced": True}
                return  # Never alter a reused HWND or reopen a closed player.
            frame_mask = con.WS_CAPTION | con.WS_THICKFRAME | con.WS_MAXIMIZE
            edge_mask = con.WS_EX_CLIENTEDGE | con.WS_EX_WINDOWEDGE
            self._write_style(window.hwnd, con.GWL_STYLE,
                              (gui.GetWindowLong(window.hwnd, con.GWL_STYLE) & ~frame_mask)
                              | (window.style & frame_mask))
            self._write_style(window.hwnd, con.GWL_EXSTYLE,
                              (gui.GetWindowLong(window.hwnd, con.GWL_EXSTYLE) & ~edge_mask)
                              | (window.extended_style & edge_mask))
            desired = operator_placement(window, self.monitors())
            placement = (desired[0] | 4, *desired[1:])  # WPF_ASYNCWINDOWPLACEMENT
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
                    "placement_ok": all(abs(a - b) <= 150 for a, b in
                                        zip(actual[4], desired[4], strict=True)),
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
