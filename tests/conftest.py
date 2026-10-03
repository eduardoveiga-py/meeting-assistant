import gc

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    # Create QApplication before any service QObject and keep it alive for the suite.
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def collect_qt_objects_between_tests(qt_application):
    # Dispose cycles from signal callbacks before another widget is constructed.
    # Collection during a PySide widget constructor can destroy older Qt wrappers.
    gc.collect()
    yield
    gc.collect()


@pytest.fixture(autouse=True)
def isolate_operator_uia(monkeypatch):
    # UI unit tests never enumerate/control the runner's real Zoom UI. Direct
    # service regressions inject their own finder instead of this default.
    def unavailable(**_kwargs):
        raise ValueError("No Zoom controls in unit tests")

    monkeypatch.setattr("meeting_assistant.services.zoom_audio.find_control", unavailable)


@pytest.fixture
def audio_monitor_profile(tmp_path, monkeypatch):
    appdata = tmp_path / "profile-data"
    profile = appdata / "obs-studio/basic/profiles/unit"
    profile.mkdir(parents=True)
    (profile / "basic.ini").write_text(
        "[General]\nName=Unit audio\n[Audio]\nMonitoringDeviceId=cable\nMonitoringDeviceName=CABLE Input\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("APPDATA", str(appdata))
    return profile
