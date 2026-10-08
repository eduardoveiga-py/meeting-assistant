"""Exercise presentation, OBS commands and verified return as one lifecycle."""

from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox
from test_review_capture_external import VisualObs, Zoom
from test_review_ui import make_window
from test_review_windows import window

from meeting_assistant.services.display_service import DisplayInfo
from meeting_assistant.services.external_media_service import ExternalMediaService
from meeting_assistant.services.hall_capture import obs_window_key
from meeting_assistant.services.hall_policy import hall_runtime_flags
from meeting_assistant.services.obs_controller import ObsController
from meeting_assistant.services.obs_external_media import (
    SCENE,
    SOURCE,
    begin_external,
    prepare_external,
    select_external_window,
    show_external,
)
from meeting_assistant.ui.external_media_dialog import ExternalMediaDialog


class PlayerBackend:
    def __init__(self, *, minimized=True):
        self.original = replace(window(41, process="vlc.exe", title="Player"), minimized=minimized)
        self.current = self.original
        self.placements = []
        self.restores = []

    def windows(self):
        return [self.current] if self.current else []

    def monitors(self):
        return [{"primary": False, "rect": (1920, 0, 3840, 1080)}]

    def same_window(self, candidate):
        return bool(self.current and candidate.hwnd == self.current.hwnd
                    and candidate.pid == self.current.pid and candidate.created == self.current.created)

    def present(self, candidate, rect):
        self.placements.append(candidate)
        # Opening a movie changes VLC's title while it is restored.
        self.current = replace(candidate, minimized=False, rect=rect, title="Clip: 1 # demo.mp4")
        return True

    def restore_presentation(self, candidate):
        self.restores.append(candidate)
        self.current = candidate

    def confirm_presentation(self, candidate, rect):
        assert self.same_window(candidate) and self.current.rect == rect
        return {"ready": True}


class PlayerObs(VisualObs):
    def __init__(self, backend):
        super().__init__()
        self.backend = backend

    def send(self, request, data=None, **kwargs):
        if request == "GetInputPropertiesListPropertyItems" and data.get("propertyName") == "window":
            self.calls.append((request, data))
            current = self.backend.current
            options = [] if not current or current.minimized else [{
                "itemValue": obs_window_key(current.title, current.class_name, current.process),
                "itemEnabled": True,
            }]
            return {"propertyItems": options}
        return super().send(request, data, **kwargs)


def make_service(*, inline=True):
    backend = PlayerBackend()
    client = PlayerObs(backend)
    controller = ObsController()
    controller._client = client
    controller.local_connection = True
    zoom = Zoom()
    display = DisplayInfo("hall", "hall", "", "", "", 1920, 0, 1920, 1080, False, 1)
    service = ExternalMediaService(lambda: display, controller, zoom, backend=backend)
    if inline:
        service._work = lambda action, callback: service._native_result(action, True, callback())
    service.candidates_ready.connect(lambda candidates: service.select(candidates[0]))
    return service, controller, client, backend, zoom


def drain(controller):
    # Bound the number of transitions so a regression cannot loop forever.
    for _ in range(12):
        if controller._commands.empty():
            return
        command, payload = controller._commands.get_nowait()
        assert command == "external_task"
        controller._handle_external_task(*payload)
    raise AssertionError("External presentation did not settle")


def test_minimized_player_is_restored_before_obs_selection_and_title_is_refreshed():
    service, controller, client, backend, zoom = make_service()
    policy = []
    service.state_changed.connect(
        lambda active, _: policy.append(hall_runtime_flags(True, False, False, external_active=active))
    )
    assert service.start_external_media()
    assert client.program == "Palco"
    drain(controller)
    assert service.phase == "presenting"
    assert len(backend.placements) == 1
    assert client.program == SCENE
    current = backend.current
    assert client.inputs[SOURCE]["settings"]["window"] == obs_window_key(
        current.title, current.class_name, current.process
    )
    assert policy and all(flags == (False, False) for flags in policy)
    service.stop_external_media()
    drain(controller)
    assert client.program == "Palco" and backend.restores == [backend.original]
    assert service.phase == "returning"
    zoom.status_changed.emit(True, "JWL visível")
    assert not service.active and policy[-1] == (True, True)


class PendingController(QObject):
    external_task_finished = Signal(str, bool, object)

    def __init__(self):
        super().__init__()
        self.external_task = Mock()


def test_cancel_during_preparation_waits_for_the_prior_scene_before_restoring():
    controller, zoom = PendingController(), Zoom()
    service = ExternalMediaService(lambda: None, controller, zoom, backend=Mock())
    service.phase = "preparing"
    service._pending_obs = "prepare"
    service.window = window(1, process="vlc.exe")
    service.stop_external_media()
    assert service.active and service.phase == "preparing"
    controller.external_task.assert_not_called()
    controller.external_task_finished.emit("prepare", True, {"prior": "Palco"})
    assert service.phase == "stopping"
    assert controller.external_task.call_args.args == ("restore", {"prior": "Palco"})


def test_failed_obs_preparation_restores_the_player_and_retains_the_failure():
    service, controller, client, backend, zoom = make_service()
    original_send = client.send

    def reject_capture(request, data=None, **kwargs):
        if request == "GetInputPropertiesListPropertyItems" and data.get("propertyName") == "window":
            return {"propertyItems": []}
        return original_send(request, data, **kwargs)

    client.send = reject_capture
    messages = []
    service.state_changed.connect(lambda _, message: messages.append(message))
    service.start_external_media()
    drain(controller)
    assert backend.restores == [backend.original]
    assert client.program == "Palco" and service.phase == "returning"
    zoom.status_changed.emit(True, "JWL visível")
    assert not service.active
    assert "OBS" in messages[-1] and "JWL visível" in messages[-1]


def test_obs_is_checked_before_any_window_move_and_names_are_not_replaced():
    service, controller, client, backend, _ = make_service()
    client.inputs[SOURCE] = {"kind": "image_source", "settings": {"file": "operator.png"}}
    before = deepcopy(client.inputs), deepcopy(client.scenes)
    service.start_external_media()
    drain(controller)
    assert not service.active and not backend.placements
    assert (client.inputs, client.scenes) == before and client.program == "Palco"
    assert all(request.startswith("Get") for request, _ in client.calls)


def test_disconnected_obs_does_not_move_a_minimized_player():
    service, controller, client, backend, _ = make_service()
    controller._client = None
    service.start_external_media()
    drain(controller)
    assert not service.active and not backend.placements and client.program == "Palco"


def test_manual_program_change_during_preparation_is_preserved_on_return():
    service, controller, client, backend, zoom = make_service()
    service.start_external_media()
    command, payload = controller._commands.get_nowait()
    assert command == "external_task" and payload[0] == "begin"
    controller._handle_external_task(*payload)
    assert service.phase == "preparing" and backend.placements
    client.program = "Cena escolhida pelo operador"
    drain(controller)
    assert backend.restores == [backend.original]
    assert client.program == "Cena escolhida pelo operador"
    zoom.status_changed.emit(True, "JWL visível")
    assert not service.active


def test_cancel_while_begin_is_pending_does_not_move_the_player():
    service, controller, client, backend, _ = make_service()
    service.start_external_media()
    assert service.phase == "checking"
    service.stop_external_media()
    drain(controller)
    assert not service.active and not backend.placements and client.program == "Palco"


def test_cancel_while_show_is_pending_returns_with_the_confirmed_prior_scene():
    service, controller, client, backend, zoom = make_service()
    service.start_external_media()
    for _ in range(2):
        _, payload = controller._commands.get_nowait()
        controller._handle_external_task(*payload)
    assert service.phase == "showing"
    service.stop_external_media()
    assert service.phase == "showing" and service.active
    drain(controller)
    assert service.phase == "returning" and client.program == "Palco"
    assert backend.restores == [backend.original]
    zoom.status_changed.emit(True, "JWL visível")
    assert not service.active


def test_old_native_and_obs_replies_cannot_resume_a_new_cycle():
    service, controller, client, _, _ = make_service()
    service.start_external_media()
    old_token = service._token
    service.stop_external_media()
    drain(controller)
    service.start_external_media()
    assert service._token != old_token and service.phase == "checking"
    queued = controller._commands.qsize()
    service._native_event(old_token, "discover", True, [window(99, process="chrome.exe")])
    service._obs_result("begin", True, {"prior": "Old scene", "token": old_token})
    assert service.phase == "checking" and controller._commands.qsize() == queued
    assert not service._prior and client.program == "Palco"
    service.stop_external_media()
    drain(controller)


def test_queued_sensor_scene_is_discarded_even_after_external_return():
    controller = ObsController()
    client = VisualObs()
    controller._client = client
    controller.set_program_scene("Palco")
    _, stale = controller._commands.get_nowait()
    controller.set_external_media_active(True)
    controller.set_program_scene("Mídias")
    assert controller._commands.empty()
    controller.set_external_media_active(False)
    controller._handle_scene_request(stale)
    assert not client.calls
    controller.set_program_scene("Palco")
    _, current = controller._commands.get_nowait()
    controller._handle_scene_request(current)
    assert ("SetCurrentProgramScene", {"sceneName": "Palco"}) in client.calls


def test_external_selector_accepts_obs_case_and_escaped_title_but_not_ambiguity():
    options = [{"itemValue": "Clip#3A 1 #22 demo.mp4:Qt:VLC.EXE", "itemEnabled": True}]
    assert select_external_window(options, "Clip#3A 1 #22 demo.mp4:Qt:vlc.exe") == options[0]["itemValue"]
    options.append({"itemValue": "CLIP#3A 1 #22 DEMO.MP4:Other:chrome.exe", "itemEnabled": True})
    with pytest.raises(ValueError, match="mesmo título"):
        select_external_window(options, options[0]["itemValue"])
    with pytest.raises(ValueError, match="janela externa"):
        select_external_window([], options[0]["itemValue"])


def test_monitor_capture_in_external_scene_is_rejected_without_deleting_it():
    client = VisualObs()
    client.inputs["Desktop"] = {"kind": "monitor_capture", "settings": {}}
    client.scenes[SCENE] = [{"sourceName": "Desktop", "sceneItemId": 1, "sceneItemEnabled": True}]
    before = deepcopy(client.inputs), deepcopy(client.scenes)
    with pytest.raises(ValueError, match="captura de monitor"):
        begin_external(client)
    assert (client.inputs, client.scenes) == before
    assert client.program == "Palco"


def test_title_change_after_preparation_aborts_without_changing_program():
    backend = PlayerBackend(minimized=False)
    client = PlayerObs(backend)
    selector = obs_window_key(backend.current.title, backend.current.class_name, backend.current.process)
    result = prepare_external(client, selector)
    backend.current = replace(backend.current, title="Different movie")
    with pytest.raises(ValueError, match="janela externa"):
        show_external(client, result["prior"], selector)
    assert client.program == "Palco"


def test_existing_audio_and_jwl_inputs_are_preserved_in_a_complete_cycle():
    service, controller, client, _, zoom = make_service()
    client.inputs["Meeting Assistant - Mesa"] = {"kind": "wasapi_input_capture", "settings": {
        "device_id": "operator-device", "gain_db": 7, "monitor": "OBS_MONITORING_TYPE_MONITOR_ONLY"
    }}
    client.inputs["Meeting Assistant - JWL (HWND)"] = {"kind": "meeting_assistant_jwl_capture",
                                                   "settings": {"hwnd": "123"}}
    before = deepcopy(client.inputs)
    service.start_external_media()
    drain(controller)
    service.stop_external_media()
    drain(controller)
    zoom.status_changed.emit(True, "JWL visível")
    assert {name: client.inputs[name] for name in before} == before
    assert all(data["inputName"] == SOURCE for request, data in client.calls if request == "SetInputMute")


def test_operator_button_and_actual_dialog_select_the_second_duplicate_label(tmp_path):
    owner = make_window(tmp_path)
    service, controller, _, backend, _ = make_service()
    service.candidates_ready.disconnect()
    candidates = [backend.original, replace(backend.original, hwnd=42, pid=142)]
    backend.windows = lambda: candidates
    owner.external_media = service
    service.state_changed.connect(owner._external_state)
    service.candidates_ready.connect(owner._choose_external_media)
    observed = []

    def select_second():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, ExternalMediaDialog)
        dialog.windows.setCurrentRow(1)
        observed.append(dialog.selected_window())
        QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.LeftButton)

    owner.show()
    QTimer.singleShot(0, select_second)
    QTest.mouseClick(owner.ext_media_button, Qt.LeftButton)
    assert observed == [candidates[1]] and service.window == candidates[1]
    assert owner.ext_media_button.isChecked() and service.phase == "checking"
    service.stop_external_media()
    drain(controller)
    owner.close()


def test_selection_dialog_cancel_leaves_obs_and_player_untouched(tmp_path):
    owner = make_window(tmp_path)
    service, controller, client, backend, _ = make_service()
    service.candidates_ready.disconnect()
    owner.external_media = service
    service.state_changed.connect(owner._external_state)
    service.candidates_ready.connect(owner._choose_external_media)
    observed = []

    def cancel():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, ExternalMediaDialog)
        observed.append(True)
        QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel), Qt.LeftButton)

    owner.show()
    QTimer.singleShot(0, cancel)
    QTest.mouseClick(owner.ext_media_button, Qt.LeftButton)
    assert observed and not service.active and not owner.ext_media_button.isChecked()
    assert controller._commands.empty() and not client.calls and not backend.placements
    owner.close()


def test_duplicate_labels_and_long_titles_fit_the_selection_window():
    candidates = [window(index, process="chrome.exe", title="A long browser title " * 40)
                  for index in (1, 2)]
    dialog = ExternalMediaDialog(candidates)
    dialog.resize(330, 270)
    dialog.show()
    QApplication.processEvents()
    assert dialog.windows.horizontalScrollBar().maximum() == 0
    assert dialog.windows.item(0).text() != dialog.windows.item(1).text()
    for button in dialog.buttons.buttons():
        assert button.isVisible() and button.sizeHint().width() <= button.width()
        assert dialog.rect().contains(button.mapTo(dialog, button.rect().bottomRight()))
    dialog.close()


def wait_for_phase(service, phase):
    import time
    deadline = time.monotonic() + 3
    while service.phase != phase and time.monotonic() < deadline:
        QTest.qWait(5)
    assert service.phase == phase


def start_worker(controller):
    import threading
    controller._poll = Mock()
    controller._sync_jwl_capture = Mock()
    controller._disconnect = Mock()
    controller._thread = threading.Thread(target=controller._run, daemon=True)
    controller._thread.start()


def test_real_native_and_obs_workers_complete_two_cycles_without_gui_native_calls():
    import threading
    service, controller, client, backend, zoom = make_service(inline=False)
    threads = []
    original_present = backend.present
    original_restore = backend.restore_presentation

    def present(*args):
        threads.append(threading.get_ident())
        return original_present(*args)

    def restore(*args):
        threads.append(threading.get_ident())
        return original_restore(*args)

    backend.present, backend.restore_presentation = present, restore
    start_worker(controller)
    try:
        for _ in range(2):
            assert service.start_external_media()
            wait_for_phase(service, "presenting")
            assert client.program == SCENE
            service.stop_external_media()
            wait_for_phase(service, "returning")
            assert client.program == "Palco"
            zoom.status_changed.emit(True, "JWL visível")
            assert not service.active
        assert len(threads) == 4 and threading.get_ident() not in threads
    finally:
        service.stop()
        controller.stop()


def test_partial_native_placement_failure_restores_the_fresh_snapshot():
    service, controller, client, backend, zoom = make_service(inline=False)
    original = backend.present

    def fail_after_placement(*args):
        original(*args)
        raise RuntimeError("Native failure")

    backend.present = fail_after_placement
    messages = []
    service.state_changed.connect(lambda _, message: messages.append(message))
    start_worker(controller)
    try:
        service.start_external_media()
        wait_for_phase(service, "returning")
        assert backend.restores == [backend.original] and client.program == "Palco"
        zoom.status_changed.emit(True, "JWL visível")
        assert not service.active and "Posicionamento" in messages[-1]
    finally:
        service.stop()
        controller.stop()


def test_cancel_during_native_placement_does_not_overlap_restore_or_commit_program():
    import threading
    service, controller, client, backend, zoom = make_service(inline=False)
    entered, release = threading.Event(), threading.Event()
    original = backend.present

    def wait_then_place(*args):
        entered.set()
        assert release.wait(2)
        return original(*args)

    backend.present = wait_then_place
    start_worker(controller)
    try:
        service.start_external_media()
        wait_for_phase(service, "placing")
        # Native worker can begin just after Qt published the placing phase.
        assert entered.wait(1)
        service.stop_external_media()
        assert not backend.restores and client.program == "Palco"
        release.set()
        wait_for_phase(service, "returning")
        assert backend.restores == [backend.original] and client.program == "Palco"
        zoom.status_changed.emit(True, "JWL visível")
        assert not service.active
    finally:
        release.set()
        service.stop()
        controller.stop()


@pytest.mark.parametrize("automation", [False, True])
def test_actual_stop_button_returns_two_cycles_even_with_a_stale_checked_flag(tmp_path, automation):
    owner = make_window(tmp_path)
    service, controller, client, backend, zoom = make_service()
    owner.external_media = service
    owner.state.automation_enabled = automation
    service.state_changed.connect(owner._external_state)
    policies = []
    service.state_changed.connect(lambda active, _: policies.append(
        hall_runtime_flags(automation, False, zoom.returning, external_active=active)
    ))
    owner.show()
    try:
        for _ in range(2):
            QTest.mouseClick(owner.ext_media_button, Qt.LeftButton)
            drain(controller)
            assert service.phase == "presenting" and client.program == SCENE
            assert "Parar" in owner.ext_media_button.text()
            assert all(flags == (False, False) for flags in policies)
            # A UI repaint/state update must not decide which operation runs.
            owner.ext_media_button.blockSignals(True)
            owner.ext_media_button.setChecked(False)
            owner.ext_media_button.blockSignals(False)
            QTest.mouseClick(owner.ext_media_button, Qt.LeftButton)
            assert service.phase == "stopping" and not owner.ext_media_button.isEnabled()
            assert owner.ext_media_button.text() == "Retornando…"
            drain(controller)
            assert client.program == "Palco" and backend.current == backend.original
            assert service.phase == "returning" and service.active
            assert owner.state.automation_enabled is automation
            zoom.status_changed.emit(True, "JWL confirmado visível")
            assert not service.active and owner.ext_media_button.isEnabled()
            assert not owner.ext_media_button.isChecked()
            assert owner.ext_media_button.text() == "🎬 Mídia Externa"
            assert policies.pop() == (automation, automation)
        assert len(backend.restores) == 2 and len(backend.placements) == 2
    finally:
        service.stop()
        owner.close()


def test_program_is_not_committed_if_player_is_covered_after_obs_preparation():
    service, controller, client, backend, zoom = make_service(inline=False)
    backend.confirm_presentation = Mock(side_effect=ValueError("Player coberto pelo JWL"))
    messages = []
    service.state_changed.connect(lambda _, message: messages.append(message))
    start_worker(controller)
    try:
        service.start_external_media()
        wait_for_phase(service, "returning")
        assert client.program == "Palco" and backend.restores == [backend.original]
        assert not any(request == "SetCurrentProgramScene" and data["sceneName"] == SCENE
                       for request, data in client.calls)
        zoom.status_changed.emit(True, "JWL confirmado visível")
        assert not service.active and "Player coberto" in messages[-1]
    finally:
        service.stop()
        controller.stop()


def test_cancel_during_exposure_confirmation_waits_and_restores_once():
    import threading
    service, controller, client, backend, zoom = make_service(inline=False)
    entered, release = threading.Event(), threading.Event()
    original = backend.confirm_presentation

    def wait_then_confirm(*args):
        entered.set()
        assert release.wait(2)
        return original(*args)

    backend.confirm_presentation = wait_then_confirm
    start_worker(controller)
    try:
        service.start_external_media()
        wait_for_phase(service, "confirming")
        assert entered.wait(1)
        service.stop_external_media()
        assert not backend.restores and client.program == "Palco"
        release.set()
        wait_for_phase(service, "returning")
        assert backend.restores == [backend.original] and client.program == "Palco"
        zoom.status_changed.emit(True, "JWL confirmado visível")
        assert not service.active
    finally:
        release.set()
        service.stop()
        controller.stop()


def test_return_failure_keeps_diagnostics_and_button_retries_instead_of_starting(tmp_path):
    owner = make_window(tmp_path)
    service, controller, client, backend, zoom = make_service()
    owner.external_media = service
    service.state_changed.connect(owner._external_state)
    owner.show()
    try:
        QTest.mouseClick(owner.ext_media_button, Qt.LeftButton)
        drain(controller)
        QTest.mouseClick(owner.ext_media_button, Qt.LeftButton)
        drain(controller)
        zoom.status_changed.emit(False, "JWL não confirmou retorno em 5 s")
        assert service.phase == "return_failed" and service.active
        assert owner.ext_media_button.isEnabled() and owner.ext_media_button.text() == "Repetir retorno"
        QTest.mouseClick(owner.ext_media_button, Qt.LeftButton)
        drain(controller)
        assert service.phase == "returning" and client.program == "Palco"
        zoom.status_changed.emit(True, "JWL confirmado visível")
        assert not service.active and backend.current == backend.original
        assert len(backend.placements) == 1
    finally:
        service.stop()
        owner.close()


def test_completed_worker_emission_does_not_block_an_immediate_next_cycle():
    service, controller, client, backend, _ = make_service()
    service._thread = Mock()
    service._thread.is_alive.return_value = True
    service._native_busy = False
    assert service.start_external_media()
    assert service.phase == "checking" and not backend.placements and client.program == "Palco"
    service.stop_external_media()
    drain(controller)


def test_cancelled_inventory_must_finish_before_a_new_cycle_can_start():
    service, controller, client, backend, _ = make_service()
    service._native_busy = True
    assert not service.start_external_media()
    assert not service.active and controller._commands.empty()
    assert not backend.placements and client.program == "Palco"

