"""Unit tests for OBS reconnection, Pre-Flight check of the 5 critical items, and Watchdog recovery."""

from unittest.mock import MagicMock, patch

from meeting_assistant.services.obs_service import ObsService
from meeting_assistant.services.preflight import Check, PreFlightChecker
from meeting_assistant.services.watchdog_service import WatchdogService


def test_obs_service_reconnect_loop_and_scene_switch():
    obs = ObsService(host="127.0.0.1", port=4455, password="secret")
    assert not obs.is_connected

    # Mock ReqClient
    mock_client = MagicMock()
    mock_client.send.return_value = {"version": "30.0.0"}

    with patch("meeting_assistant.services.obs_service.obs.ReqClient", return_value=mock_client), \
         patch("meeting_assistant.services.obs_service.obs.EventClient"):
        connected = obs._try_connect()
        assert connected is True
        assert obs.is_connected is True

        # Test scene switch
        switched = obs.switch_scene("Palco")
        assert switched is True
        mock_client.send.assert_called_with(
            "SetCurrentProgramScene",
            {"sceneName": "Palco"},
            raw=True,
        )

        # Test mute
        muted = obs.set_input_mute("Meeting Assistant - Mesa", True)
        assert muted is True
        mock_client.send.assert_called_with(
            "SetInputMute",
            {"inputName": "Meeting Assistant - Mesa", "inputMuted": True},
            raw=True,
        )

        # Disconnect
        obs.stop()
        assert obs.is_connected is False


def test_preflight_checker_5_items():
    mock_obs = MagicMock()
    mock_obs.is_connected = True
    mock_obs.is_virtual_cam_active.return_value = False
    mock_obs.start_virtual_cam.return_value = True

    checker = PreFlightChecker(obs_service=mock_obs)

    with patch("psutil.process_iter") as mock_procs, \
         patch("meeting_assistant.services.window_manager.WindowManager.get_monitors_info") as mock_mons:

        # Processes: obs64.exe and zoom.exe running
        p1 = MagicMock()
        p1.info = {"name": "obs64.exe"}
        p2 = MagicMock()
        p2.info = {"name": "Zoom.exe"}
        mock_procs.return_value = [p1, p2]

        # Monitors: 2 monitors connected
        mock_mons.return_value = [
            {"primary": True, "rect": (0, 0, 1920, 1080)},
            {"primary": False, "rect": (1920, 0, 3840, 1080)},
        ]

        checks = checker.check_all()
        assert len(checks) == 5

        # 1. OBS
        c_obs = next(c for c in checks if c.category == "OBS")
        assert c_obs.passed is True

        # 2. CÂMERA (initially inactive)
        c_cam = next(c for c in checks if c.category == "CÂMERA")
        assert c_cam.passed is False

        # Auto-fix camera
        fixed = checker.auto_fix_virtual_cam()
        assert fixed is True
        mock_obs.start_virtual_cam.assert_called_once()

        # 4. MONITOR
        c_mon = next(c for c in checks if c.category == "MONITOR")
        assert c_mon.passed is True

        # 5. ZOOM
        c_zoom = next(c for c in checks if c.category == "ZOOM")
        assert c_zoom.passed is True


def test_watchdog_service_detects_reconnection():
    mock_obs = MagicMock()
    mock_obs.is_connected = True
    mock_obs.is_virtual_cam_active.return_value = True

    watchdog = WatchdogService(obs_service=mock_obs)

    patch_mons = patch("meeting_assistant.services.window_manager.WindowManager.get_monitors_info")
    patch_protect = patch(
        "meeting_assistant.services.window_manager.WindowManager.enforce_secondary_screen_protection"
    )
    with patch_mons as mock_mons, patch_protect as mock_protect:

        # Initially only 1 monitor
        mock_mons.return_value = [{"primary": True, "rect": (0, 0, 1920, 1080)}]
        status1 = watchdog.check_health()
        assert status1["secondary_monitor"] is False

        watchdog._last_state = status1

        # Now secondary monitor connected (e.g. HDMI plugged in)
        mock_mons.return_value = [
            {"primary": True, "rect": (0, 0, 1920, 1080)},
            {"primary": False, "rect": (1920, 0, 3840, 1080)},
        ]
        status2 = watchdog.check_health()
        assert status2["secondary_monitor"] is True

        # Trigger recovery
        recovery_events = []
        watchdog.recovery_triggered.connect(recovery_events.append)
        watchdog._handle_reconnect_triggers(status2)

        assert "secondary_monitor_reconnected" in recovery_events
        mock_protect.assert_called_once()


def test_obs_controller_virtual_cam_and_is_connected():
    from meeting_assistant.services.obs_controller import ObsConnectionConfig, ObsController

    controller = ObsController()
    assert controller.is_connected is False
    assert controller.is_virtual_cam_active() is False

    mock_client = MagicMock()
    controller._client = mock_client
    controller._last_connected = True
    assert controller.is_connected is True

    # 1. Dict response with outputActive
    mock_client.send.return_value = {"outputActive": True}
    assert controller.is_virtual_cam_active() is True
    mock_client.send.assert_called_with("GetVirtualCamStatus", raw=True)

    # 2. Dict response with output_active
    mock_client.send.return_value = {"output_active": False}
    assert controller.is_virtual_cam_active() is False

    # 3. Object response with output_active
    class ObjResp:
        output_active = True
    mock_client.send.return_value = ObjResp()
    assert controller.is_virtual_cam_active() is True

    # 4. Fallback via _config when _client is None
    controller._client = None
    controller._last_connected = False
    controller._config = ObsConnectionConfig(host="127.0.0.1", port=4455, password="test")

    with patch("obsws_python.ReqClient") as mock_req_cls:
        temp_inst = MagicMock()
        temp_inst.send.return_value = {"outputActive": True}
        mock_req_cls.return_value = temp_inst

        assert controller.is_virtual_cam_active() is True
        mock_req_cls.assert_called_with(host="127.0.0.1", port=4455, password="test", timeout=2)
        temp_inst.send.assert_called_with("GetVirtualCamStatus", raw=True)


def test_preflight_checker_virtual_cam_active_and_settings_fallback():
    from meeting_assistant.services.obs_controller import ObsController
    from meeting_assistant.services.settings import AppSettings

    # Case 1: obs controller returns active
    controller = ObsController()
    controller._client = MagicMock()
    controller._client.send.return_value = {"outputActive": True}
    controller._last_connected = True

    checker = PreFlightChecker(obs_service=controller)
    check = checker.check_virtual_cam()
    assert check.passed is True
    assert check.category == "CÂMERA"

    # Case 2: obs controller is disconnected, but settings fallback detects active
    settings = AppSettings(obs_host="127.0.0.1", obs_port=4455, obs_password="pw")
    checker_fallback = PreFlightChecker(obs_service=None, settings=settings)

    with patch("obsws_python.ReqClient") as mock_req_cls:
        temp_inst = MagicMock()
        temp_inst.send.return_value = {"outputActive": True}
        mock_req_cls.return_value = temp_inst

        check2 = checker_fallback.check_virtual_cam()
        assert check2.passed is True
        temp_inst.send.assert_called_with("GetVirtualCamStatus", raw=True)

    # Case 3: auto_fix_virtual_cam fallback via settings
    vcam_step_path = "meeting_assistant.services.obs_hall_setup.virtual_camera_step"
    with patch("obsws_python.ReqClient") as mock_req_cls, \
         patch(vcam_step_path, return_value=True) as mock_step:
        fixed = checker_fallback.auto_fix_virtual_cam()
        assert fixed is True
        mock_step.assert_called_once()


def test_main_window_run_preflight_and_report_success(tmp_path):
    from test_review_ui import make_window

    window = make_window(tmp_path)
    mock_checker = MagicMock()
    mock_checker.check_all.return_value = [
        Check("OBS", "OBS Studio rodando", True),
        Check("CÂMERA", "Câmera virtual ativa", True),
    ]
    window.preflight_checker = mock_checker

    with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
        window._run_preflight_and_report()
        mock_info.assert_called_once()
        assert "Ambiente verificado e pronto" in mock_info.call_args[0][2]
        assert window.btn_preflight.isEnabled() is True
        assert window.btn_preflight.text() == "🔍 Checar Ambiente"
    window.close()


def test_main_window_run_preflight_and_report_warning_and_autofix(tmp_path):
    from test_review_ui import make_window

    window = make_window(tmp_path)
    mock_checker = MagicMock()
    mock_checker.check_all.side_effect = [
        [Check("CÂMERA", "Câmera virtual ativa", False)],
        [Check("CÂMERA", "Câmera virtual ativa", False)],
    ]
    mock_checker.auto_fix_virtual_cam.return_value = True
    window.preflight_checker = mock_checker

    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        window._run_preflight_and_report()
        mock_warn.assert_called_once()
        assert "Alguns itens requerem atenção" in mock_warn.call_args[0][2]
        mock_checker.auto_fix_virtual_cam.assert_called_once()
        assert window.btn_preflight.isEnabled() is True
        assert window.btn_preflight.text() == "🔍 Checar Ambiente"
    window.close()


def test_main_window_run_preflight_and_report_handles_exception(tmp_path):
    from test_review_ui import make_window

    window = make_window(tmp_path)
    mock_checker = MagicMock()
    mock_checker.check_all.side_effect = RuntimeError("Falha simulada de teste")
    window.preflight_checker = mock_checker

    with patch("PySide6.QtWidgets.QMessageBox.critical") as mock_crit:
        window._run_preflight_and_report()
        mock_crit.assert_called_once()
        assert "Falha simulada de teste" in mock_crit.call_args[0][2]
        assert window.btn_preflight.isEnabled() is True
        assert window.btn_preflight.text() == "🔍 Checar Ambiente"
    window.close()


def test_extract_vcam_status_all_variants():
    from meeting_assistant.services.preflight import _extract_vcam_status

    assert _extract_vcam_status({"outputActive": True}) is True
    assert _extract_vcam_status({"outputActive": False}) is False
    assert _extract_vcam_status({"output_active": True}) is True
    assert _extract_vcam_status({"output_active": False}) is False
    assert _extract_vcam_status(True) is True
    assert _extract_vcam_status(False) is False

    class ObjCamel:
        outputActive = True

    class ObjSnake:
        output_active = True

    class ObjFalse:
        output_active = False

    assert _extract_vcam_status(ObjCamel()) is True
    assert _extract_vcam_status(ObjSnake()) is True
    assert _extract_vcam_status(ObjFalse()) is False
    assert _extract_vcam_status(None) is False
    assert _extract_vcam_status({}) is False


def test_preflight_checker_recovers_with_detected_password_when_settings_password_wrong():
    from meeting_assistant.services.settings import AppSettings

    settings = AppSettings(obs_host="127.0.0.1", obs_port=4455, obs_password="wrong_password")
    checker = PreFlightChecker(obs_service=None, settings=settings)

    call_args_list = []

    def mock_req_constructor(host, port, password, timeout):
        call_args_list.append(password)
        if password == "wrong_password":
            raise RuntimeError("Authentication failed")
        if password == "correct_detected_pw":
            mock_inst = MagicMock()
            mock_inst.send.return_value = {"outputActive": True}
            return mock_inst
        raise RuntimeError("Unknown password")

    with (
        patch(
            "meeting_assistant.services.settings.detect_obs_websocket_password",
            return_value="correct_detected_pw",
        ),
        patch("obsws_python.ReqClient", side_effect=mock_req_constructor),
    ):
        check = checker.check_virtual_cam()
        assert check.passed is True
        assert call_args_list == ["wrong_password", "correct_detected_pw"]


def test_obs_controller_thread_safe_poll_and_vcam_status():
    from meeting_assistant.services.obs_controller import ObsController

    controller = ObsController()
    mock_client = MagicMock()
    mock_client.send.return_value = {"outputActive": True}
    controller._client = mock_client
    controller._last_connected = True

    # Call poll to refresh virtual cam status
    controller._poll()
    assert controller._virtual_cam_active is True

    # Active status returned and cached
    assert controller.is_virtual_cam_active() is True



