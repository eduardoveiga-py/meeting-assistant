import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from meeting_assistant.core.state import AppState
from meeting_assistant.services.settings import AppSettings, SettingsService
from meeting_assistant.services.zoom_audio import ZoomAudio, microphone_state, perform
from meeting_assistant.services.zoom_audio_controls import (
    AccessibleMicrophone,
    MicrophoneError,
    find_control,
)
from meeting_assistant.ui.main_window import MainWindow


def wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(10)
    QApplication.processEvents()
    assert predicate()


@pytest.mark.parametrize(
    "label",
    ["Ativar vídeo", "Desativar vídeo", "Ativar legendas", "Audio settings", "Muted participants"],
)
def test_non_microphone_actions_cannot_be_treated_as_microphone(label):
    assert microphone_state(label) is None


@pytest.mark.parametrize("observed,expected", [("muted", "live"), ("live", "muted")])
def test_toggle_reads_current_state_before_invoking(observed, expected):
    button = Mock()
    finder = Mock(side_effect=[(button, observed), (button, expected)])
    assert perform("toggle", finder) == expected
    button.invoke.assert_called_once()


@pytest.mark.parametrize("cached", ["unknown", "live"])
def test_actual_ui_click_opens_muted_microphone_using_fresh_state(tmp_path, cached):
    services = [MagicMock() for _ in range(6)]
    services[1].snapshot.return_value = []
    services[2].snapshot.return_value = []
    services[4].busy = False
    services[5].active = services[5].returning = False
    window = MainWindow(AppState(), AppSettings(), SettingsService(tmp_path / "settings.json"), *services)
    window._operator_timer.stop()
    window.resize(520, 780)
    window.show()
    button = Mock()
    observed = ["muted"]
    button.invoke.side_effect = lambda: observed.__setitem__(0, "live")
    window.zoom_audio._finder = lambda: (button, observed[0])
    window._zoom_audio_result(cached, "Observed earlier")
    QApplication.processEvents()
    try:
        QTest.mouseClick(window.zoom_mic_button, Qt.MouseButton.LeftButton)
        wait_until(lambda: not window.zoom_audio.busy)
        button.invoke.assert_called_once()
        assert observed[0] == "live"
        assert window.zoom_mic_button.property("state") == "live"
        assert window.zoom_mic_button.isEnabled()
    finally:
        window.close()
        QApplication.processEvents()


@pytest.mark.parametrize(
    "label,state",
    [
        ("Áudio", None),
        ("Ativar", None),
        ("Desativar mudo (Alt+A)", "muted"),
        ("Microfone silenciado", "muted"),
        ("Áudio desativado", "muted"),
        ("Microphone is unmuted", "live"),
        ("Microfone aberto", "live"),
        ("Mute my audio, Unmute my audio", None),
        ("Microfone não silenciado", None),
        ("Ativar som original", None),
    ],
)
def test_action_and_status_labels_are_explicit_and_consistent(label, state):
    assert microphone_state(label) == state


class Node:
    def __init__(self, kind="Window", class_name="ConfMultiTabContentWndClass", parent=None):
        self.element_info = SimpleNamespace(control_type=kind)
        self._class = class_name
        self._parent = parent

    def class_name(self):
        return self._class

    def parent(self):
        return self._parent


class Button(Node):
    def __init__(
        self, name, *, help_text="", status="", legacy=None, parent=None, visible=True, enabled=True
    ):
        super().__init__("Button", "button", parent)
        self._name = name
        self._legacy = legacy or {}
        self._visible, self._enabled = visible, enabled
        self.element_info.element = SimpleNamespace(CurrentHelpText=help_text, CurrentItemStatus=status)
        self.element_info.runtime_id = (42, id(self))
        self.iface_invoke = Mock()
        self.iface_legacy_iaccessible = Mock()

    def window_text(self):
        return self._name

    def legacy_properties(self):
        return self._legacy

    def is_visible(self):
        return self._visible

    def is_enabled(self):
        return self._enabled


class Window(Node):
    def __init__(self, buttons, *, class_name="ConfMultiTabContentWndClass", pid=7, minimized=False):
        super().__init__(class_name=class_name)
        self.buttons = buttons
        self._pid, self._minimized = pid, minimized
        self.handle = id(self)

    def process_id(self):
        return self._pid

    def is_minimized(self):
        return self._minimized

    def descendants(self, *, control_type):
        assert control_type == "Button"
        return self.buttons


@pytest.mark.parametrize("source", ["help", "status", "legacy", "default_action"])
def test_generic_audio_caption_uses_accessibility_state_in_modern_zoom_window(source):
    options = {
        "help": {"help_text": "Ativar áudio (Alt+A)"},
        "status": {"status": "Muted", "legacy": {"KeyboardShortcut": "Alt+A"}},
        "legacy": {"legacy": {"Description": "Unmute my audio (Alt+A)"}},
        "default_action": {"legacy": {"DefaultAction": "Unmute", "KeyboardShortcut": "Alt+A"}},
    }[source]
    microphone = Button("Áudio", **options)
    video = Button("Ativar vídeo", help_text="Start my video (Alt+V)")
    window = Window([microphone, video], class_name="ModernZoomMeetingWindow")
    details = {}
    selected, state = find_control(windows=[window], pids={7}, diagnostic=details)
    assert selected.button is microphone
    assert state == "muted"
    assert details["candidates"] == 1
    assert details["window_classes"] == ["ModernZoomMeetingWindow"]
    assert "Áudio" not in str(details) and "Alt+A" not in str(details)


def test_mute_participant_row_is_never_used_when_own_audio_state_is_unknown():
    root = Node()
    toolbar = Node("ToolBar", "ZPControlPanelClass", root)
    participant_row = Node("ListItem", "participant", root)
    own = Button("Áudio", parent=toolbar)
    participant = Button("Mute", parent=participant_row)
    everyone = Button("Unmute all", parent=toolbar)
    with pytest.raises(MicrophoneError, match="não informa mudo/aberto") as caught:
        find_control(windows=[Window([own, participant, everyone])], pids={7})
    assert caught.value.code == "state_unavailable"
    for button in (own, participant, everyone):
        button.iface_invoke.Invoke.assert_not_called()


def test_toolbar_can_identify_plain_mute_but_unscoped_participant_command_cannot():
    toolbar = Node("ToolBar", "ZPControlPanelClass", Node())
    own, unscoped = Button("Mute", parent=toolbar), Button("Unmute")
    selected, state = find_control(windows=[Window([own, unscoped])], pids={7})
    assert selected.button is own and state == "live"


@pytest.mark.parametrize("option", [{"visible": False}, {"enabled": False}])
def test_hidden_or_disabled_microphone_is_not_clicked(option):
    button = Button("Unmute my audio (Alt+A)", **option)
    with pytest.raises(MicrophoneError):
        find_control(windows=[Window([button])], pids={7})
    button.iface_invoke.Invoke.assert_not_called()


def test_minimized_zoom_can_expose_its_own_accessible_microphone():
    button = Button("Mute my audio (Alt+A)", visible=False)
    selected, state = find_control(windows=[Window([button], minimized=True)], pids={7})
    assert selected.button is button and state == "live"


def test_wrong_process_and_conflicting_accessibility_state_never_dispatch():
    button = Button("Unmute my audio", status="Unmuted")
    details = {}
    with pytest.raises(MicrophoneError):
        find_control(windows=[Window([button], pid=99), Window([button])], pids={7}, diagnostic=details)
    assert details["candidates"] == 0
    assert details["controls_examined"] == 1
    button.iface_invoke.Invoke.assert_not_called()


def test_multiple_matching_controls_are_refused():
    buttons = [Button("Unmute my audio (Alt+A)") for _ in range(2)]
    with pytest.raises(MicrophoneError) as caught:
        find_control(windows=[Window(buttons)], pids={7})
    assert caught.value.code == "ambiguous_control"
    for button in buttons:
        button.iface_invoke.Invoke.assert_not_called()


def install_pattern_exception(monkeypatch):
    class NoPatternInterfaceError(Exception):
        pass

    monkeypatch.setitem(sys.modules, "pywinauto.uia_defines", SimpleNamespace(
        NoPatternInterfaceError=NoPatternInterfaceError
    ))
    return NoPatternInterfaceError


def test_legacy_action_only_used_if_invoke_pattern_is_absent(monkeypatch):
    missing = install_pattern_exception(monkeypatch)
    legacy = Mock()

    class LegacyButton:
        @property
        def iface_invoke(self):
            raise missing()

        iface_legacy_iaccessible = legacy

    AccessibleMicrophone(LegacyButton(), (7, 1, (42,))).invoke()
    legacy.DoDefaultAction.assert_called_once()


def test_invoke_error_never_causes_a_second_default_action(monkeypatch):
    install_pattern_exception(monkeypatch)
    button = Button("Unmute my audio")
    button.iface_invoke.Invoke.side_effect = RuntimeError("Invocation may already have completed")
    with pytest.raises(RuntimeError):
        AccessibleMicrophone(button, (7, 1, (42,))).invoke()
    button.iface_invoke.Invoke.assert_called_once()
    button.iface_legacy_iaccessible.DoDefaultAction.assert_not_called()


def test_real_uia_adapter_dispatches_once_and_observes_afterwards(monkeypatch):
    install_pattern_exception(monkeypatch)
    button = Button("Áudio", help_text="Unmute my audio (Alt+A)")
    window = Window([button])
    button.iface_invoke.Invoke.side_effect = lambda: setattr(
        button.element_info.element, "CurrentHelpText", "Mute my audio (Alt+A)"
    )
    assert perform("toggle", lambda: find_control(windows=[window], pids={7})) == "live"
    button.iface_invoke.Invoke.assert_called_once()


def test_no_action_is_dispatched_if_the_fresh_state_is_unknown():
    button = Mock()
    with pytest.raises(MicrophoneError) as caught:
        perform("toggle", lambda: (button, "unknown"))
    assert caught.value.code == "state_unavailable"
    button.invoke.assert_not_called()


def test_verification_tolerates_temporary_tree_change_without_second_click():
    button = Mock()
    finder = Mock(side_effect=[
        (button, "muted"), MicrophoneError("control_not_found", "Tree rebuilding"), (button, "live")
    ])
    assert perform("toggle", finder) == "live"
    button.invoke.assert_called_once()


def test_unconfirmed_action_is_reported_and_not_repeated(monkeypatch):
    monkeypatch.setattr("meeting_assistant.services.zoom_audio.time.sleep", lambda _: None)
    button = Mock()
    with pytest.raises(MicrophoneError) as caught:
        perform("toggle", lambda: (button, "muted"))
    assert caught.value.code == "not_confirmed"
    button.invoke.assert_called_once()


def test_meeting_control_replacement_cannot_confirm_action_from_other_meeting(monkeypatch):
    install_pattern_exception(monkeypatch)
    first = AccessibleMicrophone(Button("Unmute my audio"), (7, 11, (42,)))
    other = AccessibleMicrophone(Button("Mute my audio"), (7, 12, (43,)))
    finder = Mock(side_effect=[(first, "muted"), (other, "live")])
    with pytest.raises(MicrophoneError) as caught:
        perform("toggle", finder)
    assert caught.value.code == "control_changed"
    first.button.iface_invoke.Invoke.assert_called_once()
    other.button.iface_invoke.Invoke.assert_not_called()


def test_ui_click_is_retained_while_background_inspection_is_busy(tmp_path):
    services = [MagicMock() for _ in range(6)]
    services[1].snapshot.return_value = services[2].snapshot.return_value = []
    services[4].busy = services[5].active = services[5].returning = False
    window = MainWindow(AppState(), AppSettings(), SettingsService(tmp_path / "settings.json"), *services)
    window._operator_timer.stop()
    window.resize(520, 780)
    window.show()
    entered, release = threading.Event(), threading.Event()
    button = Mock()
    observed = ["muted"]
    button.invoke.side_effect = lambda: observed.__setitem__(0, "live")
    calls = []

    def finder():
        calls.append(True)
        if len(calls) == 1:
            entered.set()
            assert release.wait(2)
        return button, observed[0]

    window.zoom_audio._finder = finder
    pulses = []
    try:
        window.zoom_audio.request()
        wait_until(entered.is_set)
        QTest.mouseClick(window.zoom_mic_button, Qt.MouseButton.LeftButton)
        assert window.zoom_audio.command_pending
        assert not window.zoom_mic_button.isEnabled()
        assert "Verificando" in window.zoom_mic_button.text()
        assert not window.zoom_audio.request("toggle")
        window._operator_tick()
        QTimer.singleShot(0, lambda: pulses.append(True))
        QTest.qWait(20)
        assert pulses
        release.set()
        wait_until(lambda: not window.zoom_audio.busy)
        button.invoke.assert_called_once()
        assert observed[0] == "live"
        assert window.zoom_mic_button.isEnabled()
        assert "Silenciar" in window.zoom_mic_button.text()
    finally:
        release.set()
        window.close()
        QApplication.processEvents()


def test_stop_discards_pending_action_and_never_restarts():
    entered, release = threading.Event(), threading.Event()
    button = Mock()

    def finder():
        entered.set()
        assert release.wait(2)
        return button, "muted"

    service = ZoomAudio(finder=finder)
    service.request()
    wait_until(entered.is_set)
    assert service.request("toggle")
    service.stop()
    release.set()
    wait_until(lambda: not service.busy)
    assert not service.command_pending
    assert not service.request("toggle")
    button.invoke.assert_not_called()


def test_com_lifecycle_and_sanitized_diagnostics_are_connected(monkeypatch):
    com = SimpleNamespace(CoInitializeEx=Mock(), COINIT_MULTITHREADED=0, CoUninitialize=Mock())
    button = Mock()
    reports, outcomes = [], []
    monkeypatch.setitem(sys.modules, "pythoncom", com)
    monkeypatch.setattr("meeting_assistant.services.zoom_audio.find_control", lambda **_: (button, "muted"))
    service = ZoomAudio(platform="win32")
    service.diagnostic.connect(reports.append)
    service.result.connect(lambda state, message: outcomes.append((state, message)))
    for _ in range(2):
        assert service.request()
        wait_until(lambda: not service.busy)
    assert com.CoInitializeEx.call_count == com.CoUninitialize.call_count == 2
    com.CoInitializeEx.assert_called_with(com.COINIT_MULTITHREADED)
    assert len(reports) == 1
    assert reports[0]["code"] == "observed" and reports[0]["state"] == "muted"
    assert outcomes[-1][0] == "muted"
    service.stop()


def test_backend_failure_exposes_reason_but_never_private_exception_text():
    secret = "private meeting participant name"

    def finder():
        raise RuntimeError(secret)

    reports, outcomes = [], []
    service = ZoomAudio(finder=finder)
    service.diagnostic.connect(reports.append)
    service.command_finished.connect(lambda state, message: outcomes.append((state, message)))
    service.request("toggle")
    wait_until(lambda: not service.busy)
    assert not service.command_pending
    assert reports[0]["code"] == "backend_error"
    assert reports[0]["error_type"] == "RuntimeError"
    assert outcomes[0][0] == "unknown"
    assert secret not in str(reports) + str(outcomes)
    service.stop()


def test_missing_runtime_identity_is_refused_before_any_command():
    button = Button("Unmute my audio (Alt+A)")
    button.element_info.runtime_id = 0
    with pytest.raises(MicrophoneError) as caught:
        find_control(windows=[Window([button])], pids={7})
    assert caught.value.code == "identity_unavailable"
    button.iface_invoke.Invoke.assert_not_called()


def test_failed_com_cleanup_reports_failure_and_releases_service(monkeypatch):
    com = SimpleNamespace(
        CoInitializeEx=Mock(), COINIT_MULTITHREADED=0,
        CoUninitialize=Mock(side_effect=RuntimeError("cleanup")),
    )
    reports, outcomes = [], []
    monkeypatch.setitem(sys.modules, "pythoncom", com)
    monkeypatch.setattr("meeting_assistant.services.zoom_audio.find_control", lambda **_: (Mock(), "muted"))
    service = ZoomAudio(platform="win32")
    service.diagnostic.connect(reports.append)
    service.result.connect(lambda state, message: outcomes.append((state, message)))
    service.request()
    wait_until(lambda: not service.busy)
    assert reports[0]["code"] == "com_cleanup_error"
    assert outcomes[0][0] == "unknown"
    service.stop()


def test_worker_start_failure_is_reported_and_can_be_retried(monkeypatch):
    service = ZoomAudio(finder=lambda: (Mock(), "muted"))
    reports, outcomes = [], []
    service.diagnostic.connect(reports.append)
    service.command_finished.connect(lambda state, message: outcomes.append((state, message)))
    with monkeypatch.context() as context:
        context.setattr(threading.Thread, "start", Mock(side_effect=RuntimeError("cannot start")))
        assert not service.request("toggle")
    assert not service.busy and not service.command_pending
    assert reports[0]["code"] == "worker_start_failed"
    assert outcomes[0][0] == "unknown"
    assert service.request()
    wait_until(lambda: not service.busy)
    service.stop()


def test_action_diagnostic_records_fresh_state_dispatch_and_confirmation():
    button = Mock()
    state = ["muted"]
    button.invoke.side_effect = lambda: state.__setitem__(0, "live")
    service = ZoomAudio(finder=lambda: (button, state[0]))
    reports = []
    service.diagnostic.connect(reports.append)
    service.request("toggle")
    wait_until(lambda: not service.busy)
    report = reports[0]
    assert report["before_state"] == "muted" and report["target_state"] == "live"
    assert report["dispatch_attempted"] and report["dispatch_returned"]
    assert report["last_observed_state"] == report["state"] == "live"
    assert report["code"] == "confirmed"
    service.stop()


@pytest.mark.parametrize("height", [600, 780])
def test_ui_click_failure_is_visible_and_controls_remain_accessible(tmp_path, height):
    from PySide6.QtWidgets import QScrollArea

    services = [MagicMock() for _ in range(6)]
    services[1].snapshot.return_value = services[2].snapshot.return_value = []
    services[4].busy = services[5].active = services[5].returning = False
    window = MainWindow(AppState(), AppSettings(), SettingsService(tmp_path / "settings.json"), *services)
    window._operator_timer.stop()
    window.resize(520, height)
    window.show()
    message = (
        "Microfone do operador não localizado. "
        "Exiba a barra de controles da reunião no Zoom e tente novamente."
    )

    def finder():
        raise MicrophoneError("control_not_found", message)

    window.zoom_audio._finder = finder
    try:
        QTest.mouseClick(window.zoom_mic_button, Qt.MouseButton.LeftButton)
        wait_until(lambda: not window.zoom_audio.busy)
        assert window.mode_label.text() == window.zoom_mic_button.toolTip() == message
        assert window.zoom_mic_button.isEnabled()
        assert window.zoom_mic_button.property("state") == "unknown"
        assert window.findChild(QScrollArea).horizontalScrollBar().maximum() == 0
        assert window.zoom_mic_button.sizeHint().width() <= window.zoom_mic_button.width()
    finally:
        window.close()
        QApplication.processEvents()
