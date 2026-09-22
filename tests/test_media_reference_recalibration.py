from unittest.mock import MagicMock

import pytest

from meeting_assistant.services import media_automation_service as module
from meeting_assistant.services.jwl_idle_reference import JwlIdleReference, JwlIdleReferenceStore
from meeting_assistant.services.jwl_screen_sensor import CaptureRegion
from meeting_assistant.services.obs_controller import ObsConnectionConfig


def make_service(tmp_path):
    config = module.MediaAutomationConfig(
        obs=ObsConnectionConfig(host="localhost", port=4455, password=""),
        sensor_source="hall",
        media_scene="Mídias",
        eligible_return_scenes=("Palco",),
        preferred_return_scene="Palco",
    )
    store = JwlIdleReferenceStore(tmp_path / "reference.json")
    store.save(JwlIdleReference(bytes(100), 10, 10))
    service = module.MediaAutomationService(
        lambda: config,
        capture_region_provider=lambda: CaptureRegion(0, 0, 0, 320, 180),
        reference_store=store,
    )
    service.set_enabled(True)
    return service, store


def test_recalibration_replaces_reference_already_loaded_by_worker(tmp_path, monkeypatch):
    service, store = make_service(tmp_path)
    frame = bytes([220] * 5 + [0] * 95)
    replacement = JwlIdleReference(frame, 10, 10)
    sensor = MagicMock()

    def capture(_region):
        service.reset_idle_reference()
        # The old persisted reference remains available until calibration succeeds.
        assert store.load().pixels == bytes(100)
        return frame

    sensor.capture.side_effect = capture
    monkeypatch.setattr(module, "JwlScreenSensor", lambda: sensor)
    monkeypatch.setattr(service, "_calibrate_first_reference", lambda *_: replacement)
    events = []
    service.media_started.connect(lambda scene: events.append(scene))

    def finished(scene):
        events.append(scene)
        service._stop_event.set()

    service.media_ended.connect(finished)
    service._run()
    assert events == ["Palco"]
    assert store.load().pixels == replacement.pixels
    assert store.load().alternate_pixels == (bytes(100),)
    sensor.close.assert_called_once()


@pytest.mark.parametrize("media,expected", [(False, "Palco"), (True, "Mídias")])
def test_worker_routes_startup_using_saved_reference(tmp_path, monkeypatch, media, expected):
    service, _store = make_service(tmp_path)
    sensor = MagicMock()
    sensor.capture.return_value = bytes([220 if media else 0] * 100)
    monkeypatch.setattr(module, "JwlScreenSensor", lambda: sensor)
    events = []

    def finished(scene):
        events.append(scene)
        service._stop_event.set()

    service.media_started.connect(finished)
    service.media_ended.connect(finished)
    service._run()
    assert events == [expected]
