"""Playback state, target boundaries and killable UIA work, without global keys."""

import multiprocessing
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from test_external_window_backend import Clock
from test_review_windows import window

from meeting_assistant.services.external_player_controls import (
    PlayerControlBackend,
    PlayerControlError,
    control_action,
    perform,
)
from meeting_assistant.services.external_player_controls import _Button as AccessibleButton
from meeting_assistant.services.external_player_controls import _uia_lookup as uia_lookup


class Button:
    def __init__(self, label, invoke=lambda: None):
        self.label, self.callback, self.invocations = label, invoke, 0

    def window_text(self):
        return self.label

    def is_enabled(self):
        return True

    def is_visible(self):
        return True

    def invoke(self):
        self.invocations += 1
        self.callback()


@pytest.mark.parametrize("label, action", [
    ("Play (k)", "play"), ("Pause (k)", "pause"), ("Reproduzir", "play"),
    ("Pausar", "pause"), ("Pause the playback (Space)", "pause"),
    ("Stop the playback", "stop"), ("Full screen (f)", "fullscreen"),
    ("Sair da tela cheia (f)", "exit_fullscreen"),
    ("Reproduzir tudo", None), ("Play playlist", None), ("Pesquisar", None),
])
def test_commands_distinguish_video_controls_from_other_page_actions(label, action):
    assert control_action(label) == action


@pytest.mark.parametrize("browser", [False, True])
def test_play_pause_are_idempotent_and_confirm_current_action(browser):
    button = Button("Reproduzir")
    button.callback = lambda: setattr(
        button, "label", "Pausar" if button.label == "Reproduzir" else "Reproduzir"
    )
    def lookup():
        return [button]

    for action in ("play", "play", "pause", "pause"):
        result = perform(action, lookup, lambda: True, browser=browser)
        assert result["confirmed"]
    assert button.invocations == 2


def test_browser_stop_pauses_while_vlc_stop_uses_its_stop_control():
    browser_button = Button("Pausar")
    browser_button.callback = lambda: setattr(browser_button, "label", "Reproduzir")
    assert perform("stop", lambda: [browser_button], lambda: True, browser=True)["confirmed"]
    assert browser_button.invocations == 1
    play, stop = Button("Pause the playback"), Button("Stop the playback")
    stop.callback = lambda: setattr(play, "label", "Play")
    assert perform("stop", lambda: [play, stop], lambda: True, browser=False)["confirmed"]
    assert stop.invocations == 1 and play.invocations == 0


def test_fullscreen_uses_the_player_control_and_confirms_inverse_action():
    button = Button("Full screen (f)")
    button.callback = lambda: setattr(button, "label", "Exit full screen (f)"
                                     if control_action(button.label) == "fullscreen" else "Full screen (f)")
    def lookup():
        return [button]

    assert perform("fullscreen", lookup, lambda: True, browser=True)["fullscreen_entered"]
    assert not perform("exit_fullscreen", lookup, lambda: True, browser=True)["fullscreen_entered"]
    assert button.invocations == 2


@pytest.mark.parametrize("action", ["play", "pause", "stop", "fullscreen"])
def test_ambiguous_players_or_fullscreen_controls_are_never_invoked(action):
    labels = ["Play", "Play"] if action != "fullscreen" else ["Full screen", "Full screen"]
    buttons = [Button(label) for label in labels]
    with pytest.raises(PlayerControlError):
        perform(action, lambda: buttons, lambda: True, browser=True)
    assert not any(button.invocations for button in buttons)


def test_process_replacement_between_lookup_and_dispatch_is_rejected():
    button = Button("Play")
    validity = iter((True, False))
    with pytest.raises(PlayerControlError, match="mudou"):
        perform("play", lambda: [button], lambda: next(validity), browser=True)
    assert button.invocations == 0


def test_unsupported_or_unconfirmed_action_does_not_repeat_or_fallback_to_keys():
    clock, button = Clock(), Button("Play")
    with pytest.raises(PlayerControlError, match="não confirmou"):
        perform("play", lambda: [button], lambda: True, browser=True, clock=clock, pause=clock.pause)
    assert button.invocations == 1 and clock.now <= 1.5
    with pytest.raises(PlayerControlError):
        perform("fullscreen", lambda: [button], lambda: True, browser=True)
    assert button.invocations == 1


def sleeping_provider(pipe, _window, _action):
    time.sleep(30)


def successful_provider(pipe, _window, action):
    pipe.send({"ok": True, "confirmed": True, "fullscreen_entered": action == "fullscreen"})
    pipe.close()


def test_hung_provider_is_terminated_with_deadline_and_no_lingering_process():
    context = multiprocessing.get_context("spawn")
    backend = PlayerControlBackend(timeout=0.6, context=context, worker=sleeping_provider, platform="win32")
    before = {process.pid for process in multiprocessing.active_children()}
    started = time.monotonic()
    with pytest.raises(PlayerControlError, match="sem resposta"):
        backend.command(window(41, process="chrome.exe"), "pause", threading.Event())
    assert time.monotonic() - started < 2.0
    assert backend._process is None
    assert {process.pid for process in multiprocessing.active_children()} == before


def test_isolated_worker_reply_and_fullscreen_ownership_do_not_leak_com_objects():
    backend = PlayerControlBackend(timeout=5.0, worker=successful_provider, platform="win32")
    cancel = threading.Event()
    for action in ("fullscreen", "exit_fullscreen"):
        reply = backend.command(window(41, process="chrome.exe"), action, cancel)
        assert reply["confirmed"] and backend._process is None
        assert backend.fullscreen_owned == (action == "fullscreen")
    cancel.set()
    with pytest.raises(PlayerControlError, match="cancelado"):
        backend.command(window(41), "play", cancel)


def test_cancel_interrupts_hung_provider_and_releases_process():
    backend = PlayerControlBackend(timeout=5, worker=sleeping_provider, platform="win32")
    cancel, outcome = threading.Event(), []

    def work():
        try:
            backend.command(window(41), "play", cancel)
        except PlayerControlError:
            outcome.append("cancelled")

    thread = threading.Thread(target=work)
    thread.start()
    deadline = time.monotonic() + 2
    while backend._process is None and time.monotonic() < deadline:
        time.sleep(0.01)
    cancel.set()
    thread.join(timeout=2)
    assert not thread.is_alive() and outcome == ["cancelled"] and backend._process is None


class Element:
    def __init__(self, kind, *, parent=None, buttons=(), documents=(), visible=True):
        self.element_info = SimpleNamespace(control_type=kind)
        self._parent, self._buttons, self._documents = parent, buttons, documents
        self._visible = visible

    def parent(self):
        return self._parent

    def is_visible(self):
        return self._visible

    def descendants(self, control_type, depth):
        return self._documents if control_type == "Document" else self._buttons


def scoped_desktop(monkeypatch, root, target):
    handles = []

    class Desktop:
        def __init__(self, **_options):
            pass

        def window(self, handle):
            handles.append(handle)
            return SimpleNamespace(wrapper_object=lambda: root)

    root.handle = target.hwnd
    root.class_name = lambda: target.class_name
    root.process_id = lambda: target.pid
    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=Desktop))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda _hwnd: (1, target.pid)
    ))
    return handles


def test_browser_lookup_excludes_toolbar_and_inactive_tabs_but_includes_embedded_player(monkeypatch):
    target, root = window(41, process="chrome.exe"), Element("Window")
    outside, hidden, embedded = Button("Play"), Button("Play"), Button("Pause")
    document = Element("Document", parent=root, buttons=(embedded,))
    inactive = Element("Document", parent=root, buttons=(hidden,), visible=False)
    iframe = Element("Document", parent=document)
    root._buttons, root._documents = (outside,), (document, inactive, iframe)
    handles = scoped_desktop(monkeypatch, root, target)
    buttons = uia_lookup(target, True)
    assert [button.wrapper for button in buttons] == [embedded]
    assert handles == [target.hwnd]


def test_multiple_visible_documents_are_rejected_without_an_arbitrary_browser_tab(monkeypatch):
    target, root = window(41, process="msedge.exe"), Element("Window")
    root._documents = (Element("Document", parent=root), Element("Document", parent=root))
    scoped_desktop(monkeypatch, root, target)
    with pytest.raises(PlayerControlError, match="aba visível"):
        uia_lookup(target, True)


def test_lookup_accepts_validated_uwp_host_but_never_another_root_handle(monkeypatch):
    target, root = window(41, process="microsoft.media.player.exe"), Element("Window")
    scoped_desktop(monkeypatch, root, target)
    root.process_id = lambda: 777
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda _hwnd: (1, 777)
    ))
    assert not uia_lookup(target, False)
    root.handle += 1
    with pytest.raises(PlayerControlError, match="mudou"):
        uia_lookup(target, False)


def test_icon_only_vlc_button_reads_current_help_without_assuming_play_pause_toggle():
    element = SimpleNamespace(CurrentHelpText="Pause the playback (Space)", CurrentItemStatus="")
    wrapper = SimpleNamespace(
        element_info=SimpleNamespace(element=element, set_cache_strategy=lambda _cache: None),
        window_text=lambda: "", legacy_properties=lambda: {},
    )
    button = AccessibleButton(wrapper)
    assert control_action(button.window_text()) == "pause"
    element.CurrentHelpText = "Play the media"
    assert control_action(button.window_text()) == "play"
    wrapper.legacy_properties = lambda: {"Description": "Pause"}
    assert control_action(button.window_text()) is None  # Conflicting evidence cannot toggle playback.
