"""Automated tests for Windows 11 OS transmission optimizer (Milestone 2).

Tests ducking preferences, sound scheme configuration, power plan AC settings,
exclusive mode, signal enhancements, sample rate diagnostics, and DPI scaling.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from meeting_assistant.services.windows_core_audio import AudioEndpoint
from meeting_assistant.services.windows_transmission_optimizer import (
    DUCKING_DO_NOTHING,
    PKEY_DISABLE_SYS_FX,
    PKEY_EXCLUSIVE_MODE,
    SOUND_SCHEME_NONE,
    VAL_DISABLE_STARTUP_SOUND,
    VAL_DUCKING,
    OptimizationStatus,
    _query_powercfg_ac_seconds,
    apply_all_optimizations,
    apply_ducking,
    apply_elevated_os_optimizations,
    apply_exclusive_mode,
    apply_power_ac_monitor,
    apply_power_ac_standby,
    apply_signal_enhancements,
    apply_sound_scheme,
    apply_startup_sound,
    check_all_optimizations,
    check_ducking,
    check_exclusive_mode,
    check_monitor_dpi,
    check_monitor_dpi_status,
    check_power_ac_monitor,
    check_power_ac_standby,
    check_sample_rates,
    check_signal_enhancements,
    check_sound_scheme,
    check_startup_sound,
    generate_os_optimization_script,
)

# ---------------------------------------------------------------------------
# 1. OptimizationStatus Dataclass
# ---------------------------------------------------------------------------


def test_optimization_status_dataclass():
    status = OptimizationStatus(
        name="Test Opt",
        current_value=3,
        is_optimal=True,
        recommended_value=3,
        description="Test description",
    )
    assert status.name == "Test Opt"
    assert status.current_value == 3
    assert status.is_optimal is True
    assert status.recommended_value == 3
    assert status.description == "Test description"


# ---------------------------------------------------------------------------
# 2. Communications Ducking
# ---------------------------------------------------------------------------


def test_check_ducking_optimal():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    with patch("winreg.OpenKey") as mock_open, patch("winreg.QueryValueEx", return_value=(3, 4)):
        mock_open.return_value.__enter__.return_value = MagicMock()
        status = check_ducking()
        assert status.is_optimal is True
        assert status.current_value == DUCKING_DO_NOTHING


def test_check_ducking_suboptimal():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    with patch("winreg.OpenKey") as mock_open, patch("winreg.QueryValueEx", return_value=(1, 4)):
        mock_open.return_value.__enter__.return_value = MagicMock()
        status = check_ducking()
        assert status.is_optimal is False
        assert status.current_value == 1


def test_apply_ducking_success():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    with patch("winreg.CreateKey") as mock_create, patch("winreg.SetValueEx") as mock_set:
        mock_create.return_value.__enter__.return_value = MagicMock()
        assert apply_ducking() is True
        mock_set.assert_called_once()
        args = mock_set.call_args[0]
        assert args[1] == VAL_DUCKING
        assert args[4] == DUCKING_DO_NOTHING


# ---------------------------------------------------------------------------
# 3. Sound Scheme & Startup Sound
# ---------------------------------------------------------------------------


def test_check_sound_scheme():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    with patch("winreg.OpenKey") as mock_open, patch("winreg.QueryValueEx", return_value=(".None", 1)):
        mock_open.return_value.__enter__.return_value = MagicMock()
        status = check_sound_scheme()
        assert status.is_optimal is True
        assert status.current_value == SOUND_SCHEME_NONE

    with patch("winreg.OpenKey") as mock_open, patch("winreg.QueryValueEx", return_value=(".Default", 1)):
        mock_open.return_value.__enter__.return_value = MagicMock()
        status = check_sound_scheme()
        assert status.is_optimal is False
        assert status.current_value == ".Default"


def test_apply_sound_scheme():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    with patch("winreg.CreateKey") as mock_create, patch("winreg.SetValueEx") as mock_set:
        mock_create.return_value.__enter__.return_value = MagicMock()
        assert apply_sound_scheme() is True
        mock_set.assert_called_once()
        args = mock_set.call_args[0]
        assert args[1] == ""
        assert args[4] == SOUND_SCHEME_NONE


def test_check_startup_sound():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    with patch("winreg.OpenKey") as mock_open, patch("winreg.QueryValueEx", return_value=(1, 4)):
        mock_open.return_value.__enter__.return_value = MagicMock()
        status = check_startup_sound()
        assert status.is_optimal is True
        assert status.current_value == 1

    with patch("winreg.OpenKey") as mock_open, patch("winreg.QueryValueEx", return_value=(0, 4)):
        mock_open.return_value.__enter__.return_value = MagicMock()
        status = check_startup_sound()
        assert status.is_optimal is False


def test_apply_startup_sound():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    with patch("winreg.CreateKey") as mock_create, patch("winreg.SetValueEx") as mock_set:
        mock_create.return_value.__enter__.return_value = MagicMock()
        assert apply_startup_sound() is True
        mock_set.assert_called_once()
        args = mock_set.call_args[0]
        assert args[1] == VAL_DISABLE_STARTUP_SOUND
        assert args[4] == 1


# ---------------------------------------------------------------------------
# 4. Power Plan AC Timeouts (powercfg)
# ---------------------------------------------------------------------------


def test_query_powercfg_ac_seconds_portuguese():
    sample_pt = """
    Alias GUID: VIDEOIDLE
    Índice de Configurações de Correntes Alternadas Atuais: 0x00000000
    Índice de Configurações de Correntes Contínuas Atuais: 0x00000258
    """
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=sample_pt)
        val = _query_powercfg_ac_seconds("SUB_VIDEO", "VIDEOIDLE")
        assert val == 0


def test_query_powercfg_ac_seconds_english():
    sample_en = """
    Power Setting GUID: 3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e
    Current AC Power Setting Index: 0x0000012c
    Current DC Power Setting Index: 0x0000012c
    """
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=sample_en)
        val = _query_powercfg_ac_seconds("SUB_VIDEO", "VIDEOIDLE")
        assert val == 300  # 0x12c = 300 seconds


def test_check_and_apply_power_ac():
    with patch(
        "meeting_assistant.services.windows_transmission_optimizer._query_powercfg_ac_seconds",
        return_value=0,
    ):
        mon_status = check_power_ac_monitor()
        assert mon_status.is_optimal is True

        sb_status = check_power_ac_standby()
        assert sb_status.is_optimal is True

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert apply_power_ac_monitor() is True
        assert apply_power_ac_standby() is True


# ---------------------------------------------------------------------------
# 5. Exclusive Mode & Signal Enhancements
# ---------------------------------------------------------------------------


def test_check_exclusive_mode():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    # Mock winreg returning endpoints with exclusive mode = 0
    with patch("winreg.OpenKey") as mock_open, patch("winreg.QueryInfoKey") as mock_info, patch(
        "winreg.EnumKey", return_value="{GUID}"
    ), patch(
        "winreg.EnumValue",
        side_effect=[
            ("{b3f8fa53-0004-438e-9003-51a46e139bfc},6", "Driver", 1),
            (PKEY_EXCLUSIVE_MODE, 0, 4),
        ],
    ):
        mock_open.return_value.__enter__.return_value = MagicMock()
        mock_info.side_effect = [(1, 0, 0), (2, 2, 0), (0, 0, 0), (0, 0, 0)]
        status = check_exclusive_mode()
        assert isinstance(status, OptimizationStatus)
        assert status.name == "Modo Exclusivo de Áudio"


def test_apply_exclusive_mode():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    with patch("winreg.OpenKey") as mock_open, patch("winreg.QueryInfoKey", return_value=(1, 0, 0)), patch(
        "winreg.EnumKey", return_value="{GUID}"
    ), patch("winreg.SetValueEx") as mock_set:
        mock_open.return_value.__enter__.return_value = MagicMock()
        success = apply_exclusive_mode()
        assert success is True
        assert mock_set.call_count >= 2


def test_check_signal_enhancements():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    with patch("winreg.OpenKey") as mock_open, patch("winreg.QueryInfoKey") as mock_info, patch(
        "winreg.EnumKey", return_value="{GUID}"
    ), patch(
        "winreg.EnumValue",
        side_effect=[
            ("{b3f8fa53-0004-438e-9003-51a46e139bfc},6", "Driver", 1),
            (PKEY_DISABLE_SYS_FX, 1, 4),
        ],
    ):
        mock_open.return_value.__enter__.return_value = MagicMock()
        mock_info.side_effect = [(1, 0, 0), (2, 2, 0), (0, 0, 0), (0, 0, 0)]
        status = check_signal_enhancements()
        assert isinstance(status, OptimizationStatus)
        assert status.name == "Aprimoramentos de Sinal de Áudio"


def test_apply_signal_enhancements():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    with patch("winreg.OpenKey") as mock_open, patch("winreg.QueryInfoKey", return_value=(1, 0, 0)), patch(
        "winreg.EnumKey", return_value="{GUID}"
    ), patch("winreg.SetValueEx") as mock_set:
        mock_open.return_value.__enter__.return_value = MagicMock()
        success = apply_signal_enhancements()
        assert success is True
        assert mock_set.call_count >= 1


# ---------------------------------------------------------------------------
# 6. Sample Rate Diagnostics
# ---------------------------------------------------------------------------


def test_check_sample_rates_all_48k():
    mock_eps = [
        AudioEndpoint("id1", "Speaker", "Desc", "Intf", "eRender", 1, 48000),
        AudioEndpoint("id2", "Mic", "Desc", "Intf", "eCapture", 1, 48000),
    ]
    with patch(
        "meeting_assistant.services.windows_transmission_optimizer.enumerate_endpoints",
        return_value=mock_eps,
    ):
        status = check_sample_rates()
        assert status.is_optimal is True
        assert status.current_value == "48.000 Hz em todos"


def test_check_sample_rates_flag_44k():
    mock_eps = [
        AudioEndpoint("id1", "Speaker", "Desc", "Intf", "eRender", 1, 48000),
        AudioEndpoint("id2", "Mic 44k", "USB Mic", "Intf", "eCapture", 1, 44100),
    ]
    with patch(
        "meeting_assistant.services.windows_transmission_optimizer.enumerate_endpoints",
        return_value=mock_eps,
    ):
        status = check_sample_rates()
        assert status.is_optimal is False
        assert "44100 Hz" in status.current_value


# ---------------------------------------------------------------------------
# 7. Monitor DPI Checks
# ---------------------------------------------------------------------------


def test_check_monitor_dpi_optimal():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    def mock_enum(h_mon, hdc, lprc, dw_data):
        return True

    # Mock EnumDisplayMonitors calling callback with 2 monitors (primary 96 DPI, secondary 96 DPI)
    def fake_enum(_a, _b, proc, _c):
        proc(1001, 0, None, 0)
        proc(1002, 0, None, 0)
        return True

    with patch("ctypes.windll.user32.EnumDisplayMonitors", side_effect=fake_enum), patch(
        "ctypes.windll.shcore.GetDpiForMonitor"
    ) as mock_get_dpi:
        mock_get_dpi.return_value = 0
        # Configure GetDpiForMonitor to write 96 into dpi_x
        def fake_get_dpi(_mon, _type, dpi_x, dpi_y):
            dpi_x._obj.value = 96
            dpi_y._obj.value = 96
            return 0

        mock_get_dpi.side_effect = fake_get_dpi

        is_optimal, scale, msg = check_monitor_dpi(display_index=1)
        assert is_optimal is True
        assert scale == 1.0
        assert "100%" in msg


def test_check_monitor_dpi_single_monitor():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    def fake_enum(_a, _b, proc, _c):
        proc(1001, 0, None, 0)
        return True

    with patch("ctypes.windll.user32.EnumDisplayMonitors", side_effect=fake_enum), patch(
        "ctypes.windll.shcore.GetDpiForMonitor"
    ) as mock_get_dpi:
        def fake_get_dpi(_mon, _type, dpi_x, dpi_y):
            dpi_x._obj.value = 96
            dpi_y._obj.value = 96
            return 0

        mock_get_dpi.side_effect = fake_get_dpi

        is_optimal, scale, msg = check_monitor_dpi(display_index=1)
        assert is_optimal is False
        assert scale == 0.0
        assert "não detectado" in msg


def test_check_monitor_dpi_status():
    with patch(
        "meeting_assistant.services.windows_transmission_optimizer.check_monitor_dpi",
        return_value=(True, 1.0, "Ideal"),
    ):
        status = check_monitor_dpi_status()
        assert status.is_optimal is True
        assert status.current_value == "100%"


# ---------------------------------------------------------------------------
# 8. Master Checks & Script Generation
# ---------------------------------------------------------------------------


def test_check_all_optimizations():
    statuses = check_all_optimizations()
    assert isinstance(statuses, list)
    assert len(statuses) == 9

    names = [s.name for s in statuses]
    assert "Ducking de Comunicações" in names
    assert "Esquema de Sons do Sistema" in names
    assert "Som de Inicialização do Windows" in names
    assert "Desligamento de Tela (Modo AC)" in names
    assert "Suspensão do Sistema (Modo AC)" in names
    assert "Modo Exclusivo de Áudio" in names
    assert "Aprimoramentos de Sinal de Áudio" in names
    assert "Taxa de Amostragem (48 kHz)" in names
    assert "Escala do Monitor Secundário (DPI 100%)" in names


def test_generate_os_optimization_script():
    script = generate_os_optimization_script()
    assert "UserDuckingPreference" in script
    assert "DisableStartupSound" in script
    assert "powercfg /change monitor-timeout-ac 0" in script
    assert "powercfg /change standby-timeout-ac 0" in script
    assert "{b3f8fa53-0004-438e-9003-51a46e139bfc},3" in script
    assert "{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},5" in script
    assert "SUCCESS" in script.upper()


def test_apply_all_optimizations():
    with patch(
        "meeting_assistant.services.windows_transmission_optimizer.apply_ducking",
        return_value=True,
    ), patch(
        "meeting_assistant.services.windows_transmission_optimizer.apply_sound_scheme",
        return_value=True,
    ), patch(
        "meeting_assistant.services.windows_transmission_optimizer.apply_power_ac_monitor",
        return_value=True,
    ), patch(
        "meeting_assistant.services.windows_transmission_optimizer.apply_power_ac_standby",
        return_value=True,
    ), patch(
        "meeting_assistant.services.windows_transmission_optimizer.apply_startup_sound",
        return_value=True,
    ), patch(
        "meeting_assistant.services.windows_transmission_optimizer.apply_exclusive_mode",
        return_value=True,
    ), patch(
        "meeting_assistant.services.windows_transmission_optimizer.apply_signal_enhancements",
        return_value=True,
    ):
        res = apply_all_optimizations()
        assert res["ducking"] is True
        assert res["sound_scheme"] is True
        assert res["power_monitor"] is True
        assert res["power_standby"] is True
        assert res["startup_sound"] is True
        assert res["exclusive_mode"] is True
        assert res["signal_enhancements"] is True


def test_apply_elevated_os_optimizations_admin():
    with patch(
        "meeting_assistant.services.windows_transmission_optimizer.is_user_admin",
        return_value=True,
    ), patch(
        "meeting_assistant.services.windows_transmission_optimizer.apply_all_optimizations",
        return_value={"ducking": True},
    ):
        success, msg = apply_elevated_os_optimizations()
        assert success is True
        assert "diretamente" in msg


def test_apply_elevated_os_optimizations_non_admin():
    with patch(
        "meeting_assistant.services.windows_transmission_optimizer.is_user_admin",
        return_value=False,
    ), patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        success, msg = apply_elevated_os_optimizations()
        assert success is True
        assert "sucesso" in msg.casefold()
