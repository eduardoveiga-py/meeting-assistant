"""Exercise real presentation commands against a fullscreen-aware Win32 model."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox
from test_external_media_flow import PlayerObs, start_worker, wait_for_phase
from test_review_capture_external import Controls, Zoom
from test_review_ui import make_window
from test_review_windows import window

from meeting_assistant.services import external_window_backend as module
from meeting_assistant.services.display_service import DisplayInfo
from meeting_assistant.services.external_media_service import ExternalMediaService, jwl_return_candidate
from meeting_assistant.services.external_window_backend import ExternalWindowBackend, operator_placement
from meeting_assistant.services.hall_policy import hall_runtime_flags
from meeting_assistant.services.jwl_secondary_window import JwlSecondaryWindowInfo, WindowRect
from meeting_assistant.services.obs_controller import ObsController
from meeting_assistant.services.obs_external_media import SCENE
from meeting_assistant.services.window_inventory import WindowBackend
from meeting_assistant.ui.external_media_dialog import ExternalMediaDialog

CON = SimpleNamespace(
    SW_RESTORE=9, GWL_STYLE=-16, GWL_EXSTYLE=-20, HWND_TOPMOST=-1, HWND_NOTOPMOST=-2,
    WS_CAPTION=0xC00000, WS_THICKFRAME=0x40000, WS_EX_CLIENTEDGE=0x200,
    WS_EX_WINDOWEDGE=0x100, WS_EX_TOPMOST=8, SWP_NOSIZE=1, SWP_NOMOVE=2,
    SWP_NOACTIVATE=16, SWP_SHOWWINDOW=64, SWP_FRAMECHANGED=32, SWP_ASYNCWINDOWPOS=0x4000,
    GA_ROOT=2, SW_HIDE=0, SW_SHOWNOACTIVATE=4,
    WS_MINIMIZE=0x20000000, WS_MAXIMIZE=0x1000000, WS_VISIBLE=0x10000000,
)
HALL_RECT = (1920, 0, 3840, 1080)


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def pause(self, seconds):
        self.now += seconds


class Win32:
    def __init__(self, player, hall, *, activate=True, restore_reads=0):
        self.player, self.hall = player, hall
        self.current = {w.hwnd: w for w in (player, hall)}
        self.others = []
        self.calls = []
        self.cover = hall.hwnd
        self.activation_allowed = activate
        self.restore_reads = restore_reads
        self.pending_placement = None
        self.cloaked = 0

    def GetWindowRect(self, hwnd):
        return self.current[hwnd].rect

    def GetClassName(self, hwnd):
        return self.current[hwnd].class_name if hwnd in self.current else "UnrelatedFixtureWindow"

    def IsWindowVisible(self, hwnd):
        return self.current[hwnd].visible

    def IsIconic(self, hwnd):
        return self.current[hwnd].minimized

    def GetAncestor(self, hwnd, _kind):
        return hwnd - 1000 if hwnd > 1000 else hwnd

    def WindowFromPoint(self, _point):
        cover = self.cover
        if cover == self.hall.hwnd and not self.current[self.hall.hwnd].visible:
            cover = self.player.hwnd
        return cover + 1000  # A child control must resolve to its root.

    def GetWindowLong(self, hwnd, kind):
        w = self.current[hwnd]
        return w.style if kind == CON.GWL_STYLE else w.extended_style

    def SetWindowLong(self, hwnd, kind, value):
        self.calls.append(("style", hwnd, kind, value))
        key = "style" if kind == CON.GWL_STYLE else "extended_style"
        runtime = {"minimized": bool(value & CON.WS_MINIMIZE)} if kind == CON.GWL_STYLE else {}
        self.current[hwnd] = replace(self.current[hwnd], **{key: value}, **runtime)

    def SetWindowPos(self, hwnd, order, left, top, width, height, flags):
        self.calls.append(("position", hwnd, order, flags))
        w = self.current[hwnd]
        rect = w.rect if flags & CON.SWP_NOMOVE else (left, top, left + width, top + height)
        topmost = order == CON.HWND_TOPMOST
        style = w.extended_style & ~CON.WS_EX_TOPMOST
        placement = w.placement if flags & CON.SWP_NOMOVE else (0, w.placement[1], *w.placement[2:4], rect)
        self.current[hwnd] = replace(w, rect=rect, placement=placement, topmost=topmost,
                                     extended_style=style | (CON.WS_EX_TOPMOST if topmost else 0))
        # UWP full-screen stays exposed until foreground activation. Merely
        # placing another TOPMOST window is deliberately insufficient here.

    def SetWindowPlacement(self, hwnd, placement):
        self.calls.append(("placement", hwnd, placement))
        self.pending_placement = (hwnd, placement)

    def GetWindowPlacement(self, hwnd):
        if self.pending_placement and self.pending_placement[0] == hwnd:
            if self.restore_reads:
                self.restore_reads -= 1
            else:
                placement = self.pending_placement[1]
                self.current[hwnd] = replace(self.current[hwnd], placement=(0, *placement[1:]),
                                             rect=placement[4], minimized=placement[1] == 2,
                                             style=(self.current[hwnd].style
                                                    & ~(CON.WS_MINIMIZE | CON.WS_MAXIMIZE))
                                             | (CON.WS_MINIMIZE if placement[1] == 2 else 0)
                                             | (CON.WS_MAXIMIZE if placement[1] == 3 else 0))
                self.pending_placement = None
        return self.current[hwnd].placement

    def show(self, hwnd, command):
        self.calls.append(("show", hwnd, command))
        w = self.current[hwnd]
        if command == CON.SW_HIDE:
            self.current[hwnd] = replace(w, visible=False)
            return
        self.current[hwnd] = replace(w, minimized=False, visible=True,
                                     placement=(0, 1, *w.placement[2:]),
                                     style=w.style & ~(CON.WS_MINIMIZE | CON.WS_MAXIMIZE))

    def activate(self, hwnd):
        self.calls.append(("activate", hwnd))
        if self.activation_allowed:
            self.cover = hwnd
        return self.activation_allowed


def make_backend(monkeypatch, *, activate=True, restore_reads=0, minimized=True):
    player = replace(window(41, process="vlc.exe", title="video"),
                     style=CON.WS_CAPTION | CON.WS_THICKFRAME
                     | (CON.WS_MINIMIZE if minimized else 0),
                     extended_style=CON.WS_EX_CLIENTEDGE | CON.WS_EX_WINDOWEDGE,
                     minimized=minimized, placement=(0, 2 if minimized else 1, (0, 0), (0, 0),
                                                     (520, 40, 1200, 720)))
    hall = replace(window(51, rect=HALL_RECT), topmost=True, extended_style=CON.WS_EX_TOPMOST)
    gui, clock = Win32(player, hall, activate=activate, restore_reads=restore_reads), Clock()
    backend = ExternalWindowBackend(lambda: hall, clock=clock, pause=clock.pause)
    backend.windows = lambda: [*gui.current.values(), *gui.others]
    backend.same_window = lambda w: w.hwnd in gui.current and (
        gui.current[w.hwnd].pid, gui.current[w.hwnd].created) == (w.pid, w.created)
    backend._win32 = lambda: (CON, gui)
    backend.monitors = lambda: [
        {"primary": True, "rect": (0, 0, 1920, 1080), "work": (0, 0, 1920, 1040)},
        {"primary": False, "rect": HALL_RECT, "work": (1920, 0, 3840, 1040)},
    ]
    backend._native_pid = lambda hwnd: gui.current[hwnd].pid
    monkeypatch.setattr(module, "cloak_state", lambda _hwnd: gui.cloaked)
    monkeypatch.setattr(module, "activate_window", gui.activate)
    monkeypatch.setattr(module, "show_window_async", gui.show)
    return backend, gui, clock


@pytest.mark.parametrize("runtime_style", [CON.WS_MINIMIZE, CON.WS_MAXIMIZE])
def test_present_does_not_reapply_saved_minimized_or_maximized_style(monkeypatch, runtime_style):
    backend, gui, _ = make_backend(monkeypatch, minimized=False)
    original = replace(gui.player, style=gui.player.style | runtime_style,
                       minimized=runtime_style == CON.WS_MINIMIZE)
    gui.current[original.hwnd] = original
    assert backend.present(original, HALL_RECT)
    writes = [call[3] for call in gui.calls if call[:3] == ("style", original.hwnd, CON.GWL_STYLE)]
    assert writes and not any(style & (CON.WS_MINIMIZE | CON.WS_MAXIMIZE) for style in writes)
    assert not gui.current[original.hwnd].minimized


def test_async_restore_is_confirmed_before_hiding_jwl_or_changing_player_styles(monkeypatch):
    backend, gui, clock = make_backend(monkeypatch)
    original_show, original_pause, original_style = gui.show, clock.pause, gui.SetWindowLong
    pending = []
    extra_runtime_flag = 0x2000000  # A style change delivered while processing restore.

    def async_show(hwnd, command):
        if hwnd == gui.player.hwnd and command == CON.SW_RESTORE:
            gui.calls.append(("restore_requested", hwnd))
            pending.append((hwnd, command))
        else:
            assert not pending  # JWL must remain visible until restoration is confirmed.
            original_show(hwnd, command)

    def pump(seconds):
        original_pause(seconds)
        if pending and clock.now >= 0.15:
            hwnd, command = pending.pop()
            original_show(hwnd, command)
            gui.current[hwnd] = replace(gui.current[hwnd], style=gui.current[hwnd].style | extra_runtime_flag)

    def write_style(hwnd, kind, value):
        assert not pending
        original_style(hwnd, kind, value)

    monkeypatch.setattr(module, "show_window_async", async_show)
    gui.SetWindowLong = write_style
    backend._pause = pump
    assert backend.present(gui.player, HALL_RECT)
    assert clock.now >= 0.15
    assert gui.current[gui.player.hwnd].style & extra_runtime_flag
    assert not pending


def test_restore_timeout_does_not_hide_jwl_or_rewrite_player_runtime_state(monkeypatch):
    backend, gui, clock = make_backend(monkeypatch)
    monkeypatch.setattr(module, "show_window_async",
                        lambda hwnd, command: gui.calls.append(("show", hwnd, command)))
    with pytest.raises(ValueError, match="PLAYER_RESTORE"):
        backend.present(gui.player, HALL_RECT)
    assert gui.current[gui.hall.hwnd].visible and gui.current[gui.hall.hwnd].topmost
    assert not [call for call in gui.calls if call[0] in {"style", "position"}]
    assert 2.5 <= clock.now < 2.6
    assert backend.last_snapshot["stage"] == "player_restore"


@pytest.mark.parametrize("field,code", [
    ("minimized", "PLAYER_STATE"), ("cloaked", "PLAYER_CLOAKED"),
    ("geometry_ok", "PLAYER_POSITION"), ("hall_hidden", "JWL_HANDOFF"),
    ("exposed", "PLAYER_EXPOSURE"),
])
def test_failure_identifies_the_actual_unconfirmed_stage(field, code):
    snapshot = {"minimized": False, "visible": True, "cloaked": False,
                "geometry_ok": True, "hall_hidden": True, "exposed": True}
    snapshot[field] = field in {"minimized", "cloaked"}
    assert code in ExternalWindowBackend._presentation_failure(snapshot)


def test_old_geometry_confirmation_accepts_player_behind_fullscreen_jwl(monkeypatch):
    backend, gui, _ = make_backend(monkeypatch)
    # Reproduce the published implementation, including its geometry-only exit.
    monkeypatch.setitem(__import__("sys").modules, "win32con", CON)
    monkeypatch.setitem(__import__("sys").modules, "win32gui", gui)
    monkeypatch.setattr("meeting_assistant.services.native_window.show_window_async", gui.show)
    assert WindowBackend.present(backend, gui.player, HALL_RECT)
    assert gui.cover == gui.hall.hwnd
    assert not backend.presentation_snapshot(gui.player, HALL_RECT)["ready"]


def test_external_player_demotes_only_secondary_jwl_and_activates_once(monkeypatch):
    backend, gui, _ = make_backend(monkeypatch)
    operator = replace(window(61), topmost=True)
    gui.others.append(operator)
    assert backend.present(gui.player, HALL_RECT)
    assert backend.last_snapshot["exposed"] and backend.last_snapshot["hall_hidden"]
    assert not [c for c in gui.calls if c[0] == "activate"]
    assert not gui.current[gui.hall.hwnd].topmost
    assert gui.current[gui.hall.hwnd].rect == HALL_RECT
    assert all(c[1] != operator.hwnd for c in gui.calls)
    assert all(c[0] in {"position", "show"} for c in gui.calls if c[1] == gui.hall.hwnd)


def test_denied_foreground_is_not_success_even_with_correct_geometry(monkeypatch):
    backend, gui, clock = make_backend(monkeypatch, activate=False)
    gui.cover = 91  # An unrelated fullscreen view must not be hidden.
    with pytest.raises(ValueError, match="visível à frente"):
        backend.present(gui.player, HALL_RECT)
    assert gui.current[gui.player.hwnd].rect == HALL_RECT
    assert not backend.last_snapshot["exposed"] and clock.now <= 2.6
    assert len([c for c in gui.calls if c[0] == "activate"]) == 1
    backend.restore_presentation(gui.player)
    assert gui.current[gui.hall.hwnd].topmost


@pytest.mark.parametrize("minimized", [False, True])
def test_return_waits_for_async_placement_and_preserves_original_show_state(monkeypatch, minimized):
    backend, gui, clock = make_backend(monkeypatch, minimized=minimized, restore_reads=3)
    original = gui.player
    assert backend.present(original, HALL_RECT)
    backend.restore_presentation(original)
    restored = gui.current[original.hwnd]
    assert restored.placement[4] == original.placement[4]
    assert restored.minimized is minimized and not restored.topmost
    assert restored.style == original.style and restored.extended_style == original.extended_style
    assert gui.current[gui.hall.hwnd].topmost
    assert clock.now >= 0.15
    placement = next(c for c in gui.calls if c[0] == "placement")
    assert placement[2][0] & 4  # No cross-thread synchronous SetWindowPlacement.


def test_post_preparation_handoff_is_repaired_without_foreground_activation(monkeypatch):
    backend, gui, _ = make_backend(monkeypatch)
    backend.present(gui.player, HALL_RECT)
    gui.current[gui.hall.hwnd] = replace(gui.current[gui.hall.hwnd], visible=True)
    gui.cover = gui.hall.hwnd
    assert backend.confirm_presentation(gui.player, HALL_RECT)["ready"]
    assert not gui.current[gui.hall.hwnd].visible
    assert not [c for c in gui.calls if c[0] == "activate"]


def test_cloaked_or_partially_covered_player_is_not_presented(monkeypatch):
    backend, gui, _ = make_backend(monkeypatch)
    backend.present(gui.player, HALL_RECT)
    gui.cloaked = 1
    assert not backend.presentation_snapshot(gui.player, HALL_RECT)["ready"]
    gui.cloaked = 0
    center = (2880, 540)
    gui.WindowFromPoint = lambda point: gui.player.hwnd if point == center else gui.hall.hwnd
    snapshot = backend.presentation_snapshot(gui.player, HALL_RECT)
    assert snapshot["geometry_ok"] and not snapshot["exposed"] and not snapshot["ready"]


def test_restore_timeout_keeps_failure_and_restores_hall_order(monkeypatch):
    backend, gui, clock = make_backend(monkeypatch, restore_reads=1000)
    backend.present(gui.player, HALL_RECT)
    with pytest.raises(ValueError, match="disposição anterior"):
        backend.restore_presentation(gui.player)
    assert clock.now <= 2.7 and gui.current[gui.hall.hwnd].topmost
    assert not backend.last_snapshot["show_state_ok"]


def test_reused_player_and_jwl_handles_are_never_modified_on_return(monkeypatch):
    backend, gui, _ = make_backend(monkeypatch)
    backend.present(gui.player, HALL_RECT)
    for hwnd, w in list(gui.current.items()):
        gui.current[hwnd] = replace(w, created=2.0)
    gui.calls.clear()
    backend.restore_presentation(gui.player)
    assert not gui.calls
    assert backend.last_snapshot["closed_or_replaced"]


def test_uia_frame_host_pid_and_inventory_child_pid_are_both_validated(monkeypatch):
    backend, gui, _ = make_backend(monkeypatch)
    backend._hall_window_provider = lambda: replace(gui.hall, pid=777)
    backend._native_pid = lambda _hwnd: 777
    assert backend.present(gui.player, HALL_RECT)
    assert not gui.current[gui.hall.hwnd].visible
    backend.restore_presentation(gui.player)
    assert gui.current[gui.hall.hwnd].visible


def test_uia_core_child_resolves_only_to_its_identified_secondary_frame(monkeypatch):
    backend, gui, _ = make_backend(monkeypatch)
    child = SimpleNamespace(hwnd=1051, pid=gui.hall.pid, class_name="Windows.UI.Core.CoreWindow")
    backend._hall_window_provider = lambda: child
    gui.GetClassName = lambda hwnd: child.class_name if hwnd == child.hwnd else gui.current[hwnd].class_name
    backend._native_pid = lambda _hwnd: gui.hall.pid
    assert backend.present(gui.player, HALL_RECT)
    assert backend._hall_original.hwnd == gui.hall.hwnd
    assert all(call[1] != child.hwnd for call in gui.calls)


def test_missing_or_replaced_identified_hall_is_not_guessed_by_title(monkeypatch):
    backend, gui, _ = make_backend(monkeypatch)
    backend._hall_window_provider = lambda: None
    with pytest.raises(ValueError, match="não identificada"):
        backend.present(gui.player, HALL_RECT)
    assert not gui.calls
    backend._hall_window_provider = lambda: replace(gui.hall, pid=999)
    with pytest.raises(ValueError, match="identidade"):
        backend.present(gui.player, HALL_RECT)
    assert not gui.calls


def test_late_jwl_reassertion_is_recovered_without_changing_saved_geometry(monkeypatch):
    backend, gui, _ = make_backend(monkeypatch)
    original = gui.player
    backend.present(original, HALL_RECT)
    for _ in range(3):
        gui.current[gui.hall.hwnd] = replace(gui.current[gui.hall.hwnd], visible=True, topmost=True)
        gui.cover = gui.hall.hwnd
        snapshot = backend.maintain_presentation(original, HALL_RECT)
        assert snapshot["ready"] and snapshot["repaired"]
        assert gui.current[gui.hall.hwnd].rect == HALL_RECT
    assert not [call for call in gui.calls if call[0] == "activate"]
    backend.restore_presentation(original)
    assert gui.current[gui.player.hwnd].placement[4] == original.placement[4]
    assert gui.current[gui.hall.hwnd].visible and gui.current[gui.hall.hwnd].topmost


@pytest.mark.parametrize("tool", [False, True])
def test_return_to_primary_uses_workspace_coordinates_and_retains_original_snapshot(tool):
    original = replace(window(41, process="chrome.exe"), extended_style=0x80 if tool else 0,
                       placement=(0, 2, (0, 0), (0, 0), (2100, 40, 3000, 740)))
    monitors = [
        {"primary": True, "rect": (0, 0, 1920, 1080), "work": (40, 30, 1920, 1080)},
        {"primary": False, "rect": HALL_RECT, "work": (1920, 0, 3840, 1080)},
    ]
    desired = operator_placement(original, monitors)
    offset = (0, 0) if tool else (40, 30)
    normal = desired[4]
    screen = (normal[0] + offset[0], normal[1] + offset[1],
              normal[2] + offset[0], normal[3] + offset[1])
    assert 40 <= screen[0] < screen[2] <= 1920 and 30 <= screen[1] < screen[3] <= 1080
    assert desired[1] == 2 and desired[:4] == original.placement[:4]
    assert original.placement[4] == (2100, 40, 3000, 740)


def test_process_exit_cleanup_releases_jwl_even_without_a_qt_return_signal(monkeypatch):
    import time

    backend, gui, _ = make_backend(monkeypatch)
    client, controller, zoom = PlayerObs(SimpleNamespace(current=gui.player)), ObsController(), Zoom()
    controller._client, controller.local_connection = client, True
    display = DisplayInfo("hall", "hall", "", "", "", 1920, 0, 1920, 1080, False, 1)
    service = ExternalMediaService(lambda: display, controller, zoom, backend=backend, controls=Controls())
    service.window, service.phase = gui.player, "presenting"
    backend.present(gui.player, HALL_RECT)
    assert not gui.current[gui.hall.hwnd].visible
    service.stop()
    deadline = time.monotonic() + 2
    while not gui.current[gui.hall.hwnd].visible and time.monotonic() < deadline:
        QTest.qWait(5)
    assert gui.current[gui.hall.hwnd].visible and not service.active
    assert gui.current[gui.player.hwnd].placement[4] == gui.player.placement[4]


def test_hidden_uia_inventory_can_return_via_retained_verified_frame_candidate(monkeypatch):
    from meeting_assistant.services import zoom_hall_service as zoom_module

    backend, gui, _ = make_backend(monkeypatch)
    identified = JwlSecondaryWindowInfo(
        hwnd=1051, pid=gui.hall.pid, process_name="JWLibrary.exe", title="JW Library",
        class_name="Windows.UI.Core.CoreWindow", rect=WindowRect(*HALL_RECT),
        visible=True, minimized=False, topmost=True, title_bar_visible=False,
        has_jwl_core_window=True, monitor_primary=False, score=2000,
    )
    backend._hall_window_provider = lambda: identified
    backend._native_pid = lambda _hwnd: gui.hall.pid
    gui.GetClassName = lambda hwnd: (
        identified.class_name if hwnd == identified.hwnd else gui.current[hwnd].class_name
    )
    backend.present(gui.player, HALL_RECT)
    controller = ObsController()
    display = DisplayInfo("hall", "hall", "", "", "", 1920, 0, 1920, 1080, False, 1)
    holder = {}
    zoom = zoom_module.ZoomHallService(
        lambda: display, lambda: jwl_return_candidate(None, holder.get("service"))
    )
    service = ExternalMediaService(lambda: display, controller, zoom, backend=backend, controls=Controls())
    holder["service"] = service
    service.window, service.phase = gui.player, "returning"
    backend.restore_presentation(gui.player)
    retained = service.return_candidate
    assert isinstance(retained, JwlSecondaryWindowInfo) and retained.hwnd == gui.hall.hwnd
    assert retained.class_name == gui.hall.class_name
    fresh = replace(retained, hwnd=71)
    assert jwl_return_candidate(fresh, service) is fresh
    monkeypatch.setattr(zoom_module.sys, "platform", "win32")
    monkeypatch.setattr(zoom_module, "win32gui", gui)
    monkeypatch.setattr(zoom_module, "win32con", CON)
    zoom._is_window = lambda hwnd: hwnd in gui.current
    zoom._native_target_rect = lambda _target: WindowRect(*HALL_RECT)
    requests = []
    zoom._request_return = lambda: requests.append(zoom._jwl_hwnd)
    zoom._activate_return_if_needed = lambda *_args: None
    try:
        assert zoom.restore_jwl() and zoom.returning
        assert requests == [gui.hall.hwnd] and service.active
        service.phase = "idle"
        assert jwl_return_candidate(None, service) is None
    finally:
        zoom._return_timer.stop()
        service.stop()


@pytest.mark.parametrize("automation", [False, True])
def test_ui_selector_player_priority_obs_and_stop_run_as_one_lifecycle(tmp_path, monkeypatch, automation):
    import threading

    backend, gui, _ = make_backend(monkeypatch, restore_reads=3)
    backend.monitors = lambda: [{"primary": False, "rect": HALL_RECT}]

    class CurrentPlayer:
        @property
        def current(self):
            return gui.current[gui.player.hwnd]

    client = PlayerObs(CurrentPlayer())
    controller = ObsController()
    controller._client, controller.local_connection = client, True
    zoom = Zoom()
    display = DisplayInfo("hall", "hall", "", "", "", 1920, 0, 1920, 1080, False, 1)
    service = ExternalMediaService(lambda: display, controller, zoom, backend=backend, controls=Controls())
    owner = make_window(tmp_path)
    owner.external_media = service
    owner.state.automation_enabled = automation
    service.state_changed.connect(owner._external_state)
    policies, diagnostics, threads = [], [], []
    service.state_changed.connect(lambda active, _: policies.append(
        hall_runtime_flags(automation, False, zoom.returning, external_active=active)
    ))
    service.diagnostic.connect(diagnostics.append)
    original_windows = backend.windows

    def inventory():
        threads.append(threading.get_ident())
        return original_windows()

    backend.windows = inventory

    def select_player():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, ExternalMediaDialog)
        dialog.windows.setCurrentRow(0)
        QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.LeftButton)

    service.candidates_ready.connect(lambda _candidates: QTimer.singleShot(0, select_player))
    service.candidates_ready.connect(owner._choose_external_media)
    owner.show()
    start_worker(controller)
    try:
        for _ in range(2):
            QTest.mouseClick(owner.ext_media_button, Qt.LeftButton)
            wait_for_phase(service, "presenting")
            assert client.program == SCENE and backend.last_snapshot["exposed"]
            assert not gui.current[gui.hall.hwnd].topmost
            assert owner.ext_media_button.isChecked() and "Parar" in owner.ext_media_button.text()
            assert policies and all(flags == (False, False) for flags in policies)
            QTest.mouseClick(owner.ext_media_button, Qt.LeftButton)
            assert not owner.ext_media_button.isEnabled()
            wait_for_phase(service, "returning")
            assert client.program == "Palco" and gui.current[gui.player.hwnd].minimized
            assert gui.current[gui.player.hwnd].placement[4] == gui.player.placement[4]
            assert gui.current[gui.hall.hwnd].topmost and service.active
            # Model the existing verified JWL return, without modifying that service.
            gui.activate(gui.hall.hwnd)
            zoom.status_changed.emit(True, "JWL confirmado visível")
            assert gui.cover == gui.hall.hwnd and not service.active
            assert owner.ext_media_button.isEnabled() and not owner.ext_media_button.isChecked()
            assert policies.pop() == (automation, automation)
        assert threading.get_ident() not in threads
        confirms = [d for d in diagnostics if d["action"] == "native_confirm"]
        assert len(confirms) == 2 and all(d["ok"] and d["snapshot"]["exposed"] for d in confirms)
        restored = [d for d in diagnostics if d["action"] == "native_restore"]
        assert len(restored) == 2 and all(d["snapshot"]["minimized_ok"] for d in restored)
        assert all("title" not in d.get("snapshot", {}) for d in diagnostics)
    finally:
        service.stop()
        controller.stop()
        owner.close()
