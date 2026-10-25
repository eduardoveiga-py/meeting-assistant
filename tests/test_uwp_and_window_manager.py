"""Unit tests verifying UWP window resolution, process unwrapping, and secondary screen protection."""

from unittest.mock import MagicMock, patch

from meeting_assistant.services.window_manager import WindowManager


def test_get_real_window_process_win32():
    with patch("meeting_assistant.services.window_manager.win32process") as mock_proc, \
         patch("meeting_assistant.services.window_manager.psutil.Process") as mock_psutil, \
         patch("meeting_assistant.services.window_manager.win32gui"):

        mock_proc.GetWindowThreadProcessId.return_value = (1, 1234)
        mock_proc_instance = MagicMock()
        mock_proc_instance.name.return_value = "Zoom.exe"
        mock_psutil.return_value = mock_proc_instance

        pid, exe = WindowManager.get_real_window_process(9999)
        assert pid == 1234
        assert exe == "Zoom.exe"


def test_get_real_window_process_uwp_unwrapping():
    with patch("meeting_assistant.services.window_manager.win32process") as mock_proc, \
         patch("meeting_assistant.services.window_manager.psutil.Process") as mock_psutil, \
         patch("meeting_assistant.services.window_manager.win32gui") as mock_gui:

        mock_proc.GetWindowThreadProcessId.side_effect = lambda hwnd: (1, 5000 if hwnd == 9999 else 6000)

        def mock_psutil_factory(pid):
            p = MagicMock()
            if pid == 5000:
                p.name.return_value = "ApplicationFrameHost.exe"
            elif pid == 6000:
                p.name.return_value = "JWLibrary.exe"
            return p

        mock_psutil.side_effect = mock_psutil_factory

        # EnumChildWindows discovers child with CoreWindow or child PID
        def fake_enum_child(hwnd, callback, _lparam):
            callback(10001, None)
            return True

        mock_gui.EnumChildWindows.side_effect = fake_enum_child
        mock_gui.GetClassName.return_value = "Windows.UI.Core.CoreWindow"

        pid, exe = WindowManager.get_real_window_process(9999)
        assert pid == 6000
        assert exe == "JWLibrary.exe"


def test_find_windows_by_executable():
    with patch.object(WindowManager, "get_real_window_process") as mock_get_proc, \
         patch("meeting_assistant.services.window_manager.win32gui") as mock_gui:

        mock_gui.IsWindowVisible.return_value = True

        def fake_enum_windows(callback, _lparam):
            callback(101, None)
            callback(102, None)
            callback(103, None)
            return True

        mock_gui.EnumWindows.side_effect = fake_enum_windows

        def fake_proc(hwnd):
            if hwnd == 101:
                return 1001, "Zoom.exe"
            elif hwnd == 102:
                return 1002, "JWLibrary.exe"
            return 1003, "explorer.exe"

        mock_get_proc.side_effect = fake_proc

        hwnds = WindowManager.find_windows_by_executable("Zoom.exe")
        assert hwnds == [101]

        jwl_hwnds = WindowManager.find_windows_by_executable("jwlibrary.exe")
        assert jwl_hwnds == [102]


def test_enforce_secondary_screen_protection():
    with patch("meeting_assistant.services.window_manager.win32gui") as mock_gui, \
         patch("meeting_assistant.services.window_manager.win32con") as mock_con:

        mock_gui.IsWindow.return_value = True
        mock_con.SWP_NOACTIVATE = 0x0010
        mock_con.SWP_SHOWWINDOW = 0x0040
        mock_con.HWND_TOP = 0

        sec_rect = (1920, 0, 3840, 1080)
        res = WindowManager.enforce_secondary_screen_protection(
            media_hwnd=5555, secondary_monitor_rect=sec_rect
        )
        assert res is True

        # Assert SetWindowPos was called with SWP_NOACTIVATE flag
        mock_gui.SetWindowPos.assert_called_once()
        args = mock_gui.SetWindowPos.call_args[0]
        # (hwnd, insertAfter, x, y, cx, cy, uFlags)
        assert args[0] == 5555
        assert args[2] == 1920
        assert args[3] == 0
        assert args[4] == 1920
        assert args[5] == 1080
        assert (args[6] & mock_con.SWP_NOACTIVATE) != 0, "SWP_NOACTIVATE must be present to not steal focus"
