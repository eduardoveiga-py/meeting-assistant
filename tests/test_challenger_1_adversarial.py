"""Empirical Adversarial Stress Tests for Windows Core Audio & Transmission Optimizer.

Author: Challenger 1 (critic, specialist)
Covers:
1. Binary WAVEFORMATEXTENSIBLE blob parsing fuzzing (boundary conditions, corrupt data, rates).
2. Device role recognition & mapping edge cases (unicode, case, priority, collisions, ambiguous).
3. PowerShell UAC elevation script generation (AST parser syntax validity, injection safety).
4. OS transmission optimizer idempotency, missing registry branches, and monitor DPI edge cases.
"""

from __future__ import annotations

import os
import random
import struct
import subprocess
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from meeting_assistant.services.windows_core_audio import (
    DEVICE_STATE_ACTIVE,
    DEVICE_STATE_DISABLED,
    ROLE_MESA_OUT_P2,
    ROLE_SLUG_MAP,
    ROLE_V_MIC_AUX,
    ROLE_V_MIC_WAPP,
    ROLE_V_MIC_ZOOM,
    ROLE_V_OUT_ZOOM,
    ROLE_WEBCAM_MIC,
    AudioEndpoint,
    generate_elevation_script,
    identify_endpoint_role,
    map_project_roles,
    parse_wave_format_sample_rate,
)
from meeting_assistant.services.windows_transmission_optimizer import (
    OptimizationStatus,
    apply_ducking,
    apply_sound_scheme,
    check_all_optimizations,
    check_ducking,
    check_monitor_dpi,
    check_sound_scheme,
    check_startup_sound,
    generate_os_optimization_script,
)

# ===========================================================================
# 1. FUZZING & STRESS TESTING: parse_wave_format_sample_rate
# ===========================================================================


class TestSampleRateBinaryFuzzing:
    """Fuzzing and boundary tests for parse_wave_format_sample_rate."""

    @pytest.mark.parametrize(
        "invalid_input",
        [
            b"",
            None,
            b"\x00" * 1,
            b"\x00" * 4,
            b"\x00" * 8,
            b"\x00" * 15,  # Exactly one byte short of minimum 16
        ],
    )
    def test_truncated_and_empty_inputs(self, invalid_input):
        """Verify that inputs shorter than 16 bytes return None without throwing."""
        assert parse_wave_format_sample_rate(invalid_input) is None

    @pytest.mark.parametrize(
        "rate",
        [
            8000,
            11025,
            16000,
            22050,
            32000,
            44100,
            48000,
            88200,
            96000,
            176400,
            192000,
        ],
    )
    def test_valid_standard_sample_rates_at_offset_12(self, rate):
        """Verify standard rates unpack cleanly from offset 12."""
        blob = b"\x00" * 12 + struct.pack("<I", rate) + b"\x00" * 16
        assert parse_wave_format_sample_rate(blob) == rate

    @pytest.mark.parametrize(
        "extreme_rate",
        [
            0,
            1,
            7999,  # Just below 8000 minimum
            192001,  # Just above 192000 maximum
            384000,  # Pro-audio 384kHz
            768000,  # Extreme pro-audio DAC 768kHz
            0x7FFFFFFF,  # Max 32-bit signed int
            0xFFFFFFFF,  # 32-bit unsigned max / -1
        ],
    )
    def test_extreme_and_out_of_bounds_sample_rates(self, extreme_rate):
        """Rates outside 8000..192000 should be rejected unless valid fallback is present."""
        blob = b"\x00" * 12 + struct.pack("<I", extreme_rate) + b"\x00" * 16
        assert parse_wave_format_sample_rate(blob) is None

    def test_fallback_scan_with_offset_shifts(self):
        """Test fallback scan when header has different length (offset >= 4)."""
        for offset in (4, 8, 16, 24):
            blob = b"\xff" * offset + struct.pack("<I", 48000) + b"\x00" * 16
            result = parse_wave_format_sample_rate(blob)
            assert result in (48000, None)

    def test_random_fuzzing_1000_iterations(self):
        """Fuzz with 1,000 completely random byte sequences of varying lengths.

        Must never raise an unhandled exception (crash resilience).
        """
        random.seed(42)
        for _ in range(1000):
            length = random.randint(0, 512)
            blob = os.urandom(length)
            res = parse_wave_format_sample_rate(blob)
            if res is not None:
                assert isinstance(res, int)
                assert 8000 <= res <= 192000


# ===========================================================================
# 2. ADVERSARIAL STRESS TESTING: Role Recognition & Priority Ordering
# ===========================================================================


class TestRoleRecognitionAdversarial:
    """Stress tests for identify_endpoint_role and map_project_roles."""

    def test_case_insensitivity_and_diacritics(self):
        """Verify casing and Portuguese diacritics handled consistently."""
        ep_camera = AudioEndpoint(
            id="1",
            friendly_name="CÂMERA USB HD",
            desc="Dispositivo de Vídeo",
            interface_name="USB Video Device",
            flow="eCapture",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
        )
        assert identify_endpoint_role(ep_camera) == ROLE_WEBCAM_MIC

        ep_retorno = AudioEndpoint(
            id="2",
            friendly_name="Alto-falantes (Realtek Audio)",
            desc="SAÍDA P2 (MESA DE SOM)",
            interface_name="Realtek High Definition Audio",
            flow="eRender",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
        )
        assert identify_endpoint_role(ep_retorno) == ROLE_MESA_OUT_P2

    def test_cable_disambiguation_zoom_vs_wapp_vs_aux(self):
        """Ensure Cable A, Cable B, and standard Cable do not cross-contaminate."""
        cable_a = AudioEndpoint(
            id="a",
            friendly_name="CABLE-A Output (VB-Audio Cable A)",
            desc="CABLE-A Output",
            interface_name="VB-Audio Virtual Cable A",
            flow="eCapture",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
        )
        cable_b = AudioEndpoint(
            id="b",
            friendly_name="CABLE-B Output (VB-Audio Cable B)",
            desc="CABLE-B Output",
            interface_name="VB-Audio Virtual Cable B",
            flow="eCapture",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
        )
        cable_std = AudioEndpoint(
            id="c",
            friendly_name="CABLE Output (VB-Audio Virtual Cable)",
            desc="CABLE Output",
            interface_name="VB-Audio Virtual Cable",
            flow="eCapture",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
        )

        assert identify_endpoint_role(cable_a) == ROLE_V_MIC_ZOOM
        assert identify_endpoint_role(cable_b) == ROLE_V_MIC_WAPP
        assert identify_endpoint_role(cable_std) == ROLE_V_MIC_AUX

    def test_blocked_keywords_for_mesa_out_p2(self):
        """Verify that HDMI, Blackmagic, or Virtual devices on Realtek don't match Mesa Out."""
        blocked_ep = AudioEndpoint(
            id="x",
            friendly_name="Realtek HDMI Display Audio",
            desc="Display Audio",
            interface_name="Realtek Audio",
            flow="eRender",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
        )
        assert identify_endpoint_role(blocked_ep) != ROLE_MESA_OUT_P2

    def test_map_project_roles_active_precedence_over_disabled(self):
        """Active endpoints must take priority over disabled ones."""
        disabled_cable_a = AudioEndpoint(
            id="1",
            friendly_name="CABLE-A Output",
            desc="VB-Audio Cable A",
            interface_name="VB-Audio Virtual Cable A",
            flow="eRender",
            state=DEVICE_STATE_DISABLED,
            sample_rate_hz=48000,
        )
        active_cable_a = AudioEndpoint(
            id="2",
            friendly_name="CABLE-A Output",
            desc="VB-Audio Cable A",
            interface_name="VB-Audio Virtual Cable A",
            flow="eRender",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
        )

        role_map = map_project_roles([disabled_cable_a, active_cable_a])
        assert role_map[ROLE_V_OUT_ZOOM].id == "2"

    def test_all_slug_aliases_populated(self):
        """Verify that all ROLE_SLUG_MAP keys exist when official roles are mapped."""
        endpoints = [
            AudioEndpoint("1", "V-OUT Zoom", "CABLE-A", "VB-Audio Virtual Cable A", "eRender", 1, 48000),
            AudioEndpoint("2", "V-MIC Zoom", "CABLE-A", "VB-Audio Virtual Cable A", "eCapture", 1, 48000),
            AudioEndpoint("3", "V-OUT Wapp", "CABLE-B", "VB-Audio Virtual Cable B", "eRender", 1, 48000),
            AudioEndpoint("4", "V-MIC Wapp", "CABLE-B", "VB-Audio Virtual Cable B", "eCapture", 1, 48000),
            AudioEndpoint("5", "V-OUT Aux", "CABLE", "VB-Audio Virtual Cable", "eRender", 1, 48000),
            AudioEndpoint("6", "V-MIC Aux", "CABLE", "VB-Audio Virtual Cable", "eCapture", 1, 48000),
            AudioEndpoint("7", "Mesa IN", "USB Audio", "USB Audio CODEC", "eCapture", 1, 48000),
            AudioEndpoint("8", "Mesa OUT", "P2", "Realtek Audio", "eRender", 1, 48000),
            AudioEndpoint("9", "Blackmagic", "DeckLink", "Blackmagic Audio", "eRender", 1, 48000),
            AudioEndpoint("10", "Webcam", "C920", "Webcam Mic", "eCapture", 1, 48000),
        ]
        role_map = map_project_roles(endpoints)
        for slug in ROLE_SLUG_MAP:
            assert slug in role_map, f"Slug alias '{slug}' missing from role_map"

    def test_adversarial_name_collision_realtek_vs_explicit_retorno_p2(self):
        """Adversarial scenario: Two active endpoints match ROLE_MESA_OUT_P2.

        Endpoint A: 'Alto-falantes (Realtek Audio)' (generic default onboard)
        Endpoint B: 'Mesa de Som (Retorno P2) (Realtek Audio)' (explicitly renamed / configured)
        Currently, map_project_roles sorts by friendly_name ascending.
        Because 'Alto-falantes' < 'Mesa de Som', 'Alto-falantes' is chosen first,
        causing Endpoint B to be ignored.
        This test documents this algorithmic behavior.
        """
        generic_p2 = AudioEndpoint(
            id="p2_generic",
            friendly_name="Alto-falantes (Realtek Audio)",
            desc="Alto-falantes",
            interface_name="Realtek Audio",
            flow="eRender",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
        )
        explicit_p2 = AudioEndpoint(
            id="p2_explicit",
            friendly_name="Mesa de Som (Retorno P2) (Realtek Audio)",
            desc="Mesa de Som (Retorno P2)",
            interface_name="Realtek Audio",
            flow="eRender",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
        )
        role_map = map_project_roles([generic_p2, explicit_p2])
        # Confirms that explicit_p2 is prioritized over generic_p2
        assert role_map[ROLE_MESA_OUT_P2].id == "p2_explicit"


# ===========================================================================
# 3. ADVERSARIAL STRESS TESTING: PowerShell UAC Elevation Scripts
# ===========================================================================


class TestElevationScriptSecurityAndSyntax:
    """Stress testing PowerShell script generation for syntax, quoting, and injection."""

    def test_empty_renames_and_disables_generates_valid_powershell(self):
        """Script with empty collections must still contain valid structure."""
        script = generate_elevation_script({}, [], restart_audiosrv=False)
        assert "$ErrorActionPreference = 'Stop'" in script
        assert '$successCount operations completed' in script

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell required for AST check")
    def test_powershell_ast_parser_validates_generated_script_file(self):
        """Pass generated script file through PowerShell AST parser to confirm 0 syntax errors."""
        renames = {
            "{0.0.0.00000000}.{11111111-2222-3333-4444-555555555555}": "V-OUT Zoom (Envio)",
            "{0.0.1.00000000}.{22222222-3333-4444-5555-666666666666}": "Mesa de Som (Entrada USB)",
        }
        disables = ["{0.0.0.00000000}.{33333333-4444-5555-6666-777777777777}"]
        script = generate_elevation_script(renames, disables, restart_audiosrv=True)

        with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as f:
            f.write(script)
            tmp_path = f.name

        try:
            # Use PowerShell to check file syntax via ParseFile
            ps_code = (
                f"& {{ $errs = $null; "
                f"$parser = [System.Management.Automation.Language.Parser]; "
                f"$parser::ParseFile('{tmp_path}', [ref]$null, [ref]$errs) | Out-Null; "
                f"if ($errs.Count -gt 0) {{ exit 1 }} else {{ exit 0 }} }}"
            )
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", ps_code],
                capture_output=True,
                text=True,
                check=False,
            )
            assert proc.returncode == 0, f"PowerShell syntax errors in generated script:\n{proc.stderr}"
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_single_quote_escaping_in_friendly_names(self):
        """Verify that single quotes in friendly names are escaped (e.g. O'Connor -> O''Connor)."""
        renames = {
            "{0.0.0.00000000}.{11111111-2222-3333-4444-555555555555}": "Sound's Great (Retorno P2)",
        }
        script = generate_elevation_script(renames, [])
        assert "$newName = 'Sound''s Great (Retorno P2)'" in script

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell required for AST check")
    def test_os_optimization_script_ast_syntax_file(self):
        """Verify that generate_os_optimization_script() has 0 syntax errors."""
        script = generate_os_optimization_script()
        with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as f:
            f.write(script)
            tmp_path = f.name

        try:
            ps_code = (
                f"& {{ $errs = $null; "
                f"$parser = [System.Management.Automation.Language.Parser]; "
                f"$parser::ParseFile('{tmp_path}', [ref]$null, [ref]$errs) | Out-Null; "
                f"if ($errs.Count -gt 0) {{ exit 1 }} else {{ exit 0 }} }}"
            )
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", ps_code],
                capture_output=True,
                text=True,
                check=False,
            )
            assert proc.returncode == 0, f"PowerShell syntax errors in OS script:\n{proc.stderr}"
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_vulnerability_injection_in_endpoint_id(self):
        """Verify that single quotes and malicious characters in endpoint ID are sanitized.

        An adversarial ep_id containing single quotes or injected commands must have its GUID
        sanitized to only valid hex characters and hyphens, preventing string breakout.
        """
        malicious_id = "{0.0.0.00000000}.{evil'; Write-Output 'INJECTION'; #'}"
        script = generate_elevation_script({malicious_id: "Harmless Name"}, [])
        assert "INJECTION" not in script
        assert "Write-Output 'INJECTION'" not in script
        assert "evil'" not in script

    def test_vulnerability_newline_injection_in_rename(self):
        """Verify that newlines in new_name are stripped/sanitized so no arbitrary commands execute.

        Newline characters must be converted to spaces, ensuring no injected command becomes an
        uncommented top-level executable line.
        """
        malicious_name = "TestName\nStart-Process calc.exe\n# "
        script = generate_elevation_script(
            {"{0.0.0.00000000}.{11111111-2222-3333-4444-555555555555}": malicious_name},
            [],
        )
        lines = script.splitlines()
        # Find lines: none of them starts directly with 'Start-Process calc.exe' (uncommented!)
        assert not any(line.strip() == "Start-Process calc.exe" for line in lines)
        assert not any(line.startswith("Start-Process") for line in lines)
        assert "$newName = 'TestName Start-Process calc.exe #'" in script


# ===========================================================================
# 4. ADVERSARIAL STRESS TESTING: OS Optimizations & Edge Cases
# ===========================================================================


class TestOSOptimizationsAdversarial:
    """Stress testing OS optimization functions, idempotency, and registry edge cases."""

    def test_check_monitor_dpi_boundary_indices(self):
        """Test check_monitor_dpi with various display index inputs."""
        opt0, scale0, desc0 = check_monitor_dpi(display_index=0)
        assert isinstance(opt0, bool)
        assert isinstance(scale0, float)
        assert isinstance(desc0, str)

        opt1, scale1, desc1 = check_monitor_dpi(display_index=1)
        assert isinstance(opt1, bool)
        assert isinstance(scale1, float)
        assert isinstance(desc1, str)

        opt99, scale99, desc99 = check_monitor_dpi(display_index=99)
        assert isinstance(opt99, bool)
        assert isinstance(scale99, float)
        assert isinstance(desc99, str)

    def test_check_monitor_dpi_negative_index_resilience(self):
        """Test negative display indices: check_monitor_dpi(-1).

        Documents behavior when negative display indices are passed.
        """
        # When 1 monitor is connected: len(monitors) = 1.
        # len(monitors) <= -1 is False.
        # monitors[-1] selects monitors[0].
        # scale is calculated for primary monitor.
        opt_neg, scale_neg, desc_neg = check_monitor_dpi(display_index=-1)
        assert isinstance(opt_neg, bool)
        assert isinstance(scale_neg, float)
        assert isinstance(desc_neg, str)

    def test_apply_ducking_idempotency(self):
        """Applying ducking repeatedly must be idempotent."""
        if sys.platform != "win32":
            pytest.skip("Windows only")

        with patch("winreg.CreateKey") as mock_create, patch("winreg.SetValueEx") as mock_set:
            mock_create.return_value.__enter__.return_value = MagicMock()
            assert apply_ducking() is True
            assert apply_ducking() is True
            assert mock_set.call_count == 2

    def test_apply_sound_scheme_idempotency(self):
        """Applying sound scheme repeatedly must be idempotent."""
        if sys.platform != "win32":
            pytest.skip("Windows only")

        with patch("winreg.CreateKey") as mock_create, patch("winreg.SetValueEx") as mock_set:
            mock_create.return_value.__enter__.return_value = MagicMock()
            assert apply_sound_scheme() is True
            assert apply_sound_scheme() is True
            assert mock_set.call_count == 2

    def test_check_ducking_when_registry_missing(self):
        """Missing registry key must result in is_optimal=False without raising."""
        if sys.platform != "win32":
            pytest.skip("Windows only")

        with patch("winreg.OpenKey", side_effect=FileNotFoundError):
            status = check_ducking()
            assert status.is_optimal is False
            assert status.current_value is None

    def test_check_sound_scheme_when_registry_missing(self):
        """Missing sound scheme key must result in is_optimal=False without raising."""
        if sys.platform != "win32":
            pytest.skip("Windows only")

        with patch("winreg.OpenKey", side_effect=FileNotFoundError):
            status = check_sound_scheme()
            assert status.is_optimal is False
            assert status.current_value is None

    def test_check_startup_sound_when_registry_missing(self):
        """Missing startup sound key defaults to current_value=0, is_optimal=False."""
        if sys.platform != "win32":
            pytest.skip("Windows only")

        with patch("winreg.OpenKey", side_effect=FileNotFoundError):
            status = check_startup_sound()
            assert status.is_optimal is False
            assert status.current_value == 0

    def test_check_all_optimizations_returns_9_items(self):
        """Verify check_all_optimizations contract: exactly 9 OptimizationStatus items."""
        statuses = check_all_optimizations()
        assert len(statuses) == 9
        for s in statuses:
            assert isinstance(s, OptimizationStatus)
            assert isinstance(s.name, str)
            assert isinstance(s.is_optimal, bool)
            assert isinstance(s.description, str)
