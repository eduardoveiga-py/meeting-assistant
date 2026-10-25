import gc
import os

os.environ.setdefault("MEETING_ASSISTANT_TESTING", "1")

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
    if hasattr(qt_application, "_program_video"):
        try:
            qt_application._program_video.stop()
        except Exception:
            pass
        try:
            delattr(qt_application, "_program_video")
        except AttributeError:
            pass
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


@pytest.fixture(autouse=True)
def isolate_app_settings(tmp_path_factory, monkeypatch):
    """Garante que nenhum teste sobrescreva o settings.json real de produção."""
    fake_appdata = tmp_path_factory.mktemp("fake_appdata") / "AppData" / "Roaming"
    fake_appdata.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("APPDATA", str(fake_appdata))


@pytest.fixture
def mock_win32(monkeypatch):
    """Provides mock primitives for win32gui, win32process, win32api, win32con."""
    from unittest.mock import MagicMock
    m_gui = MagicMock()
    m_proc = MagicMock()
    m_api = MagicMock()
    m_con = MagicMock()
    m_con.SWP_NOACTIVATE = 0x0010
    m_con.SWP_NOSIZE = 0x0001
    m_con.SWP_NOMOVE = 0x0002
    m_con.SWP_SHOWWINDOW = 0x0040
    m_con.HWND_TOP = 0
    m_con.HWND_TOPMOST = -1
    m_con.HWND_NOTOPMOST = -2
    return {"gui": m_gui, "proc": m_proc, "api": m_api, "con": m_con}


@pytest.fixture
def mock_obsws():
    """Provides mock clients for OBS WebSocket requests and events."""
    from unittest.mock import MagicMock
    req = MagicMock()
    event = MagicMock()
    return {"req": req, "event": event}


@pytest.fixture
def mock_wasapi():
    """Provides mock objects for pycaw and comtypes audio sessions."""
    from unittest.mock import MagicMock
    meter = MagicMock()
    meter.GetPeakValue.return_value = 0.0
    session = MagicMock()
    session.SimpleAudioVolume.GetMute.return_value = 0
    session.SimpleAudioVolume.GetMasterVolume.return_value = 1.0
    session._ctl.QueryInterface.return_value = meter
    return {"meter": meter, "session": session}


