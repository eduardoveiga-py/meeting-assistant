"""Real popup clicks, continuous ownership, cancellation and primary-screen return."""

import threading
import time
from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_external_media_flow import make_service, start_worker, wait_for_phase
from test_review_ui import make_window

from meeting_assistant.services.obs_external_media import SCENE


def wait_until(callback, timeout=3):
    deadline = time.monotonic() + timeout
    while not callback() and time.monotonic() < deadline:
        QTest.qWait(5)
    assert callback()


def connect_owner(owner, service):
    owner.external_media = service
    service.state_changed.connect(owner._external_state)
    service.control_changed.connect(owner._external_control_status)
    service.operator_layout_requested.connect(owner._external_operator_layout)


@pytest.mark.parametrize("automation", [False, True])
def test_popup_play_pause_fullscreen_maximize_and_stop_preserve_whole_cycle(tmp_path, automation):
    owner = make_window(tmp_path)
    service, controller, client, backend, zoom = make_service(inline=False)
    backend.original = replace(backend.original, process="chrome.exe")
    backend.current = backend.original
    connect_owner(owner, service)
    owner.state.automation_enabled = automation
    commands = service.controls.commands
    owner.show()
    start_worker(controller)
    try:
        assert owner._external_popup is None
        for _ in range(2):
            QTest.mouseClick(owner.ext_media_button, Qt.LeftButton)
            wait_for_phase(service, "presenting")
            popup = owner._external_popup
            assert popup.isVisible() and popup.windowModality() == Qt.NonModal
            assert QApplication.primaryScreen().availableGeometry().contains(popup.frameGeometry())
            assert client.program == SCENE
            for command in ("play", "pause", "fullscreen", "maximize"):
                count = len(commands)
                QTest.mouseClick(popup.buttons[command], Qt.LeftButton)
                wait_until(lambda popup=popup, command=command:
                           not service._native_busy and popup.buttons[command].isEnabled())
                if command != "maximize":
                    assert commands[-1] == (backend.original.hwnd, command)
                else:
                    assert len(commands) == count  # Native placement, not another player's fullscreen key.
            owner.move(1000, 80)  # Simulate the app having been dragged away from primary.
            QTest.mouseClick(popup.stop_button, Qt.LeftButton)
            assert not popup.stop_button.isEnabled()
            wait_for_phase(service, "returning")
            assert client.program == "Palco" and backend.current == backend.original
            assert commands[-2:] == [(backend.original.hwnd, "stop"),
                                     (backend.original.hwnd, "exit_fullscreen")]
            zoom.status_changed.emit(True, "JWL confirmado visível")
            assert not service.active and owner._external_popup is None
            assert QApplication.primaryScreen().availableGeometry().contains(owner.frameGeometry())
            assert owner.state.automation_enabled == automation
    finally:
        service.stop()
        controller.stop()
        owner.close()


def test_closing_popup_requests_return_instead_of_leaving_external_mode_hidden(tmp_path):
    owner = make_window(tmp_path)
    service, controller, client, backend, zoom = make_service(inline=False)
    connect_owner(owner, service)
    owner.show()
    start_worker(controller)
    try:
        service.start_external_media()
        wait_for_phase(service, "presenting")
        popup = owner._external_popup
        assert not popup.buttons["fullscreen"].isVisible()  # VLC uses native Maximizar.
        popup.close()
        wait_for_phase(service, "returning")
        assert client.program == "Palco" and backend.current == backend.original
        zoom.status_changed.emit(True, "JWL visível")
        assert owner._external_popup is None
    finally:
        service.stop()
        controller.stop()
        owner.close()


def test_stop_cancels_slow_control_before_restoring_window_and_jwl(tmp_path):
    owner = make_window(tmp_path)
    service, controller, client, backend, zoom = make_service(inline=False)
    connect_owner(owner, service)
    entered, released, order = threading.Event(), threading.Event(), []
    original = service.controls.command

    def slow(window, action, cancel):
        order.append(action)
        if action == "play":
            entered.set()
            assert cancel.wait(timeout=2)
            released.set()
            raise ValueError("Play cancelado")
        assert released.is_set()
        return original(window, action, cancel)

    service.controls.command = slow
    owner.show()
    start_worker(controller)
    try:
        service.start_external_media()
        wait_for_phase(service, "presenting")
        popup = owner._external_popup
        QTest.mouseClick(popup.buttons["play"], Qt.LeftButton)
        wait_until(entered.is_set)
        assert not popup.buttons["play"].isEnabled() and popup.stop_button.isEnabled()
        QTest.mouseClick(popup.stop_button, Qt.LeftButton)
        assert not popup.stop_button.isEnabled()
        wait_for_phase(service, "returning")
        assert order == ["play", "stop"] and released.is_set()
        assert backend.current == backend.original and client.program == "Palco"
        zoom.status_changed.emit(True, "JWL visível")
        assert owner._external_popup is None
    finally:
        service.stop()
        controller.stop()
        owner.close()


def test_command_failure_is_visible_but_does_not_commit_false_playback_success(tmp_path):
    owner = make_window(tmp_path)
    service, controller, client, _, zoom = make_service(inline=False)
    connect_owner(owner, service)
    original = service.controls.command

    def command(window, action, cancel):
        if action == "play":
            raise ValueError("Vídeo não expôs controle acessível")
        return original(window, action, cancel)

    service.controls.command = command
    owner.show()
    start_worker(controller)
    try:
        service.start_external_media()
        wait_for_phase(service, "presenting")
        popup = owner._external_popup
        QTest.mouseClick(popup.buttons["play"], Qt.LeftButton)
        wait_until(lambda: "não expôs" in popup.status.text())
        assert service.phase == "presenting" and client.program == SCENE
        QTest.mouseClick(popup.stop_button, Qt.LeftButton)
        wait_for_phase(service, "returning")
        zoom.status_changed.emit(True, "JWL visível")
    finally:
        service.stop()
        controller.stop()
        owner.close()


def test_live_watchdog_restores_program_and_does_not_resume_before_verified_jwl():
    service, controller, client, backend, zoom = make_service(inline=False)
    original = backend.confirm_presentation
    checks = []

    def confirm(*args):
        checks.append(threading.get_ident())
        if service.phase == "presenting":
            raise ValueError("Player perdeu a exibição no Salão")
        return original(*args)

    backend.confirm_presentation = confirm
    messages = []
    service.state_changed.connect(lambda _, text: messages.append(text))
    start_worker(controller)
    try:
        service.start_external_media()
        wait_for_phase(service, "presenting")
        wait_for_phase(service, "returning")  # Real QTimer triggers the monitoring worker.
        assert client.program == "Palco" and service.active
        assert len(checks) >= 2 and threading.get_ident() not in checks
        zoom.status_changed.emit(True, "JWL confirmado visível")
        assert not service.active and "perdeu a exibição" in messages[-1]
    finally:
        service.stop()
        controller.stop()
