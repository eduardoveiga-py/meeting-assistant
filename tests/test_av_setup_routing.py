"""Unit and integration tests for app_audio_router (Milestone 3, R3).

Tests per-app audio routing for Zoom and WhatsApp, multi-tier strategy
(CLI, Settings launch, session query), and virtual camera management.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from meeting_assistant.services.app_audio_router import (
    DEFAULT_ZOOM_CAPTURE_NAME,
    DEFAULT_ZOOM_RENDER_NAME,
    WHATSAPP_APP,
    ZOOM_APP,
    check_app_routes,
    configure_all_routes,
    configure_app_route,
    find_cli_tool,
    get_active_sessions_for_app,
    get_virtual_cam_status,
    is_virtual_camera_supported,
    launch_apps_volume_settings,
    read_policy_config_routes,
    start_obs_virtual_cam,
    stop_obs_virtual_cam,
)


def test_find_cli_tool_when_present(tmp_path: Path):
    dummy_svcl = tmp_path / "svcl.exe"
    dummy_svcl.write_text("dummy", encoding="utf-8")

    with patch("shutil.which", return_value=str(dummy_svcl)):
        found = find_cli_tool("svcl.exe")
        assert found == dummy_svcl


def test_find_cli_tool_when_missing():
    with patch("shutil.which", return_value=None), patch.object(Path, "is_file", return_value=False):
        found = find_cli_tool("nonexistent_tool_12345.exe")
        assert found is None


def test_launch_apps_volume_settings_success():
    with patch("sys.platform", "win32"), patch("os.startfile", create=True) as mock_startfile:
        ok, msg = launch_apps_volume_settings()
        assert ok is True
        assert "ms-settings:apps-volume" in msg or "aberto" in msg
        mock_startfile.assert_called_once_with("ms-settings:apps-volume")


def test_launch_apps_volume_settings_fallback_subprocess():
    with patch("sys.platform", "win32"), patch(
        "os.startfile", side_effect=OSError("Access denied"), create=True
    ), patch("subprocess.Popen") as mock_popen:
        ok, msg = launch_apps_volume_settings()
        assert ok is True
        assert mock_popen.called
        assert "enviado" in msg


def test_launch_apps_volume_settings_non_windows():
    with patch("sys.platform", "linux"):
        ok, msg = launch_apps_volume_settings()
        assert ok is False
        assert "requer Windows" in msg


def test_read_policy_config_routes_mocked():
    with patch("sys.platform", "win32"):
        # Mock winreg keys
        mock_winreg = MagicMock()
        mock_winreg.HKEY_CURRENT_USER = 1
        mock_winreg.OpenKey.return_value.__enter__.return_value = MagicMock()

        # Simulate 1 subkey
        mock_winreg.QueryInfoKey.side_effect = [
            (1, 0, 0),  # main key: 1 subkey
            (0, 1, 0),  # subkey 0: 1 value
        ]
        mock_winreg.EnumKey.return_value = "Subkey1"
        mock_winreg.EnumValue.return_value = (
            "Val1",
            r"{2}.\\device_guid|\Device\HarddiskVolume3\Program Files\Zoom\bin\Zoom.exe",
            1,
        )

        with patch.dict(sys.modules, {"winreg": mock_winreg}):
            routes = read_policy_config_routes()
            assert ZOOM_APP in routes
            assert any("Subkey1" in k for k in routes[ZOOM_APP])


def test_get_active_sessions_for_app_matching():
    with patch("sys.platform", "win32"):
        mock_session_zoom = MagicMock()
        mock_session_zoom.Process.name.return_value = "Zoom.exe"
        mock_session_zoom.Process.pid = 1234
        mock_session_zoom.DisplayName = "Zoom Meeting"
        mock_session_zoom.Identifier = "zoom_session_1"
        mock_session_zoom.State = 1
        mock_session_zoom.SimpleAudioVolume.GetMute.return_value = 0
        mock_session_zoom.SimpleAudioVolume.GetMasterVolume.return_value = 0.85

        mock_session_other = MagicMock()
        mock_session_other.Process.name.return_value = "notepad.exe"
        mock_session_other.Process.pid = 5678
        mock_session_other.DisplayName = ""
        mock_session_other.Identifier = ""

        mock_pycaw = MagicMock()
        mock_pycaw.AudioUtilities.GetAllSessions.return_value = [
            mock_session_zoom,
            mock_session_other,
        ]

        with patch.dict(sys.modules, {"pycaw.pycaw": mock_pycaw}):
            matches = get_active_sessions_for_app("Zoom")
            assert len(matches) == 1
            assert matches[0]["process_name"] == "Zoom.exe"
            assert matches[0]["pid"] == 1234
            assert matches[0]["muted"] is False
            assert matches[0]["volume"] == 0.85


def test_check_app_routes_classifications():
    # Test case: Zoom is active & routed, WhatsApp is unconfigured
    mock_policy = {ZOOM_APP: {"k1": "path/Zoom.exe"}}

    def mock_sessions(app):
        if "zoom" in app.lower():
            return [{"process_name": "Zoom.exe", "pid": 100}]
        return []

    with patch(
        "meeting_assistant.services.app_audio_router.read_policy_config_routes",
        return_value=mock_policy,
    ), patch(
        "meeting_assistant.services.app_audio_router.get_active_sessions_for_app",
        side_effect=mock_sessions,
    ):
        report = check_app_routes()
        assert ZOOM_APP in report
        assert WHATSAPP_APP in report

        zoom_info = report[ZOOM_APP]
        assert zoom_info["status"] == "active_and_routed"
        assert zoom_info["is_running"] is True
        assert zoom_info["configured_render"] == DEFAULT_ZOOM_RENDER_NAME

        wapp_info = report[WHATSAPP_APP]
        assert wapp_info["status"] == "unconfigured"
        assert wapp_info["is_running"] is False


def test_configure_app_route_empty_devices():
    ok, msg = configure_app_route(ZOOM_APP, None, None)
    assert ok is False
    assert "Nenhum dispositivo" in msg


def test_configure_app_route_cli_success(tmp_path: Path):
    dummy_cli = tmp_path / "svcl.exe"
    dummy_cli.write_text("echo", encoding="utf-8")

    mock_run_result = MagicMock()
    mock_run_result.returncode = 0
    mock_run_result.stdout = ""
    mock_run_result.stderr = ""

    with patch("subprocess.run", return_value=mock_run_result) as mock_run:
        ok, msg = configure_app_route(
            ZOOM_APP,
            render_id=DEFAULT_ZOOM_RENDER_NAME,
            capture_id=DEFAULT_ZOOM_CAPTURE_NAME,
            cli_path=dummy_cli,
        )
        assert ok is True
        assert "configurado com sucesso" in msg
        assert mock_run.call_count == 2

        # Check render command: Type '1'
        call_render = mock_run.call_args_list[0][0][0]
        assert call_render == [str(dummy_cli), "/SetAppDefault", DEFAULT_ZOOM_RENDER_NAME, "1", ZOOM_APP]

        # Check capture command: Type '2'
        call_capture = mock_run.call_args_list[1][0][0]
        assert call_capture == [str(dummy_cli), "/SetAppDefault", DEFAULT_ZOOM_CAPTURE_NAME, "2", ZOOM_APP]


def test_configure_app_route_cli_failure(tmp_path: Path):
    dummy_cli = tmp_path / "svcl.exe"
    dummy_cli.write_text("echo", encoding="utf-8")

    mock_run_result = MagicMock()
    mock_run_result.returncode = 1
    mock_run_result.stderr = "Access denied"
    mock_run_result.stdout = ""

    with patch("subprocess.run", return_value=mock_run_result):
        ok, msg = configure_app_route(
            ZOOM_APP,
            render_id=DEFAULT_ZOOM_RENDER_NAME,
            cli_path=dummy_cli,
        )
        assert ok is False
        assert "Falha na configuração CLI" in msg or "Erro ao definir saída" in msg


def test_configure_app_route_cli_missing_fallback_guidance():
    with patch(
        "meeting_assistant.services.app_audio_router.find_cli_tool",
        return_value=None,
    ):
        ok, msg = configure_app_route(
            ZOOM_APP,
            render_id=DEFAULT_ZOOM_RENDER_NAME,
            capture_id=DEFAULT_ZOOM_CAPTURE_NAME,
        )
        assert ok is False
        assert "svcl/SoundVolumeView" in msg
        assert "ms-settings:apps-volume" in msg
        assert DEFAULT_ZOOM_RENDER_NAME in msg
        assert DEFAULT_ZOOM_CAPTURE_NAME in msg


def test_configure_all_routes_batch():
    with patch(
        "meeting_assistant.services.app_audio_router.configure_app_route",
        side_effect=[(True, "Zoom OK"), (True, "Wapp OK")],
    ) as mock_cfg:
        results = configure_all_routes()
        assert ZOOM_APP in results
        assert WHATSAPP_APP in results
        assert results[ZOOM_APP][0] is True
        assert results[WHATSAPP_APP][0] is True
        assert mock_cfg.call_count == 2


def test_is_virtual_camera_supported():
    with patch(
        "meeting_assistant.services.app_audio_router.camera_support",
        return_value=(True, "OK"),
    ):
        supported, reason = is_virtual_camera_supported()
        assert supported is True
        assert reason == "OK"


def test_get_virtual_cam_status_with_client():
    mock_obs = MagicMock()
    mock_obs.send.return_value = {"outputActive": True}

    with patch(
        "meeting_assistant.services.app_audio_router.camera_support",
        return_value=(True, "Windows 11 OK"),
    ):
        status = get_virtual_cam_status(mock_obs)
        assert status["obs_virtual_cam"]["active"] is True
        assert status["obs_virtual_cam"]["available"] is True
        assert status["obs_virtual_cam"]["error"] is None
        assert status["native_virtual_cam"]["supported"] is True


def test_get_virtual_cam_status_without_client():
    status = get_virtual_cam_status(None)
    assert status["obs_virtual_cam"]["active"] is False
    assert status["obs_virtual_cam"]["available"] is False
    assert "Cliente OBS não conectado" in status["obs_virtual_cam"]["error"]


def test_start_obs_virtual_cam_lifecycle():
    # 1. Without client
    ok, msg = start_obs_virtual_cam(None)
    assert ok is False
    assert "OBS não conectado" in msg

    # 2. Already active
    mock_obs = MagicMock()
    mock_obs.send.side_effect = [{"outputActive": True}]
    ok, msg = start_obs_virtual_cam(mock_obs)
    assert ok is True
    assert "já está em execução" in msg

    # 3. Transitions from inactive to active
    mock_obs.reset_mock()
    mock_obs.send.side_effect = [
        {"outputActive": False},  # first check
        {},  # StartVirtualCam
        {"outputActive": True},  # second check
    ]
    ok, msg = start_obs_virtual_cam(mock_obs)
    assert ok is True
    assert "iniciada com sucesso" in msg
    mock_obs.send.assert_any_call("StartVirtualCam", raw=True)


def test_stop_obs_virtual_cam_lifecycle():
    # 1. Without client
    ok, msg = stop_obs_virtual_cam(None)
    assert ok is False
    assert "OBS não conectado" in msg

    # 2. Already stopped
    mock_obs = MagicMock()
    mock_obs.send.side_effect = [{"outputActive": False}]
    ok, msg = stop_obs_virtual_cam(mock_obs)
    assert ok is True
    assert "já está parada" in msg

    # 3. Transitions from active to stopped
    mock_obs.reset_mock()
    mock_obs.send.side_effect = [
        {"outputActive": True},  # first check
        {},  # StopVirtualCam
        {"outputActive": False},  # second check
    ]
    ok, msg = stop_obs_virtual_cam(mock_obs)
    assert ok is True
    assert "parada com sucesso" in msg
    mock_obs.send.assert_any_call("StopVirtualCam", raw=True)
