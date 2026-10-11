"""Automated tests for Windows Core Audio service (Milestone 1).

Tests device enumeration, sample rate parsing, deterministic role identification,
elevation script generation, registry updates, and error handling.
"""

from __future__ import annotations

import struct
import sys
from unittest.mock import MagicMock, patch

import pytest

from meeting_assistant.services.windows_core_audio import (
    DEVICE_STATE_ACTIVE,
    DEVICE_STATE_DISABLED,
    DEVICE_STATE_DISABLED_COM,
    DEVICE_STATE_NOTPRESENT,
    DEVICE_STATE_UNPLUGGED,
    ROLE_BLACKMAGIC,
    ROLE_MESA_IN,
    ROLE_MESA_OUT_P2,
    ROLE_V_MIC_AUX,
    ROLE_V_MIC_WAPP,
    ROLE_V_MIC_ZOOM,
    ROLE_V_OUT_AUX,
    ROLE_V_OUT_WAPP,
    ROLE_V_OUT_ZOOM,
    ROLE_WEBCAM_MIC,
    AudioEndpoint,
    apply_device_modifications,
    enumerate_endpoints,
    generate_elevation_script,
    get_endpoint_flow_name,
    get_endpoint_guid,
    identify_endpoint_role,
    map_project_roles,
    modify_endpoints_in_registry,
    parse_wave_format_sample_rate,
)

# ---------------------------------------------------------------------------
# 1. AudioEndpoint Dataclass & Helper Properties
# ---------------------------------------------------------------------------


def test_audio_endpoint_properties():
    ep = AudioEndpoint(
        id="{0.0.0.00000000}.{11111111-2222-3333-4444-555555555555}",
        friendly_name="Test Speaker (Realtek)",
        desc="Speakers",
        interface_name="Realtek Audio",
        flow="eRender",
        state=DEVICE_STATE_ACTIVE,
        sample_rate_hz=48000,
    )
    assert ep.is_active is True
    assert ep.is_disabled is False
    assert ep.guid == "{11111111-2222-3333-4444-555555555555}"
    assert ep.flow_direction == "Render"

    disabled_ep = AudioEndpoint(
        id="{0.0.1.00000000}.{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}",
        friendly_name="Disabled Mic",
        desc="Mic",
        interface_name="USB Audio",
        flow="eCapture",
        state=DEVICE_STATE_DISABLED,
        sample_rate_hz=44100,
    )
    assert disabled_ep.is_active is False
    assert disabled_ep.is_disabled is True
    assert disabled_ep.guid == "{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}"
    assert disabled_ep.flow_direction == "Capture"


def test_get_endpoint_guid():
    assert get_endpoint_guid("{0.0.0.00000000}.{ABC-123}") == "{ABC-123}"
    assert get_endpoint_guid("{0.0.1.00000000}.{DEF-456}") == "{DEF-456}"
    assert get_endpoint_guid("{ALREADY-GUID}") == "{ALREADY-GUID}"


def test_get_endpoint_flow_name():
    assert get_endpoint_flow_name("{0.0.0.00000000}.{GUID}") == "Render"
    assert get_endpoint_flow_name("{0.0.1.00000000}.{GUID}") == "Capture"
    assert get_endpoint_flow_name("eRender") == "Render"
    assert get_endpoint_flow_name("eCapture") == "Capture"
    assert get_endpoint_flow_name("Render") == "Render"
    assert get_endpoint_flow_name("Capture") == "Capture"


# ---------------------------------------------------------------------------
# 2. Binary WAVEFORMATEXTENSIBLE Sample Rate Parsing
# ---------------------------------------------------------------------------


def test_parse_wave_format_sample_rate_valid():
    # Build a simulated Windows VT_BLOB with 48000 Hz at offset 12
    # Offset 0-7: VT_BLOB header (e.g. 0x0041, size)
    # Offset 8-9: wFormatTag = 0xFFFE
    # Offset 10-11: nChannels = 2
    # Offset 12-15: nSamplesPerSec = 48000 (0xBB80)
    blob_48k = bytearray(48)
    struct.pack_into("<I", blob_48k, 0, 0x00000041)
    struct.pack_into("<H", blob_48k, 8, 0xFFFE)
    struct.pack_into("<H", blob_48k, 10, 2)
    struct.pack_into("<I", blob_48k, 12, 48000)
    assert parse_wave_format_sample_rate(bytes(blob_48k)) == 48000

    blob_44k = bytearray(48)
    struct.pack_into("<I", blob_44k, 12, 44100)
    assert parse_wave_format_sample_rate(bytes(blob_44k)) == 44100


def test_parse_wave_format_sample_rate_fallback():
    # Simulated blob where 48000 is embedded further in buffer
    blob = b"\x00" * 20 + struct.pack("<I", 48000) + b"\x00" * 10
    assert parse_wave_format_sample_rate(blob) == 48000


def test_parse_wave_format_sample_rate_invalid():
    assert parse_wave_format_sample_rate(b"") is None
    assert parse_wave_format_sample_rate(b"\x00" * 10) is None
    assert parse_wave_format_sample_rate(b"\x00" * 40) is None


# ---------------------------------------------------------------------------
# 3. Deterministic Role Identification
# ---------------------------------------------------------------------------


def test_identify_endpoint_role_virtual_cable_a():
    # Cable A Render -> V-OUT Zoom
    ep_render = AudioEndpoint(
        id="{0.0.0.00000000}.{1}",
        friendly_name="CABLE-A Input (VB-Audio Virtual Cable A)",
        desc="CABLE-A Input",
        interface_name="VB-Audio Virtual Cable A",
        flow="eRender",
        state=1,
        sample_rate_hz=48000,
    )
    assert identify_endpoint_role(ep_render) == ROLE_V_OUT_ZOOM

    # Cable A Capture -> V-MIC Zoom
    ep_capture = AudioEndpoint(
        id="{0.0.1.00000000}.{2}",
        friendly_name="CABLE-A Output (VB-Audio Virtual Cable A)",
        desc="CABLE-A Output",
        interface_name="VB-Audio Virtual Cable A",
        flow="eCapture",
        state=1,
        sample_rate_hz=48000,
    )
    assert identify_endpoint_role(ep_capture) == ROLE_V_MIC_ZOOM


def test_identify_endpoint_role_virtual_cable_b():
    # Cable B Render -> V-OUT Wapp
    ep_render = AudioEndpoint(
        id="{0.0.0.00000000}.{3}",
        friendly_name="CABLE-B Input (VB-Audio Virtual Cable B)",
        desc="CABLE-B Input",
        interface_name="VB-Audio Virtual Cable B",
        flow="eRender",
        state=1,
        sample_rate_hz=48000,
    )
    assert identify_endpoint_role(ep_render) == ROLE_V_OUT_WAPP

    # Cable B Capture -> V-MIC Wapp
    ep_capture = AudioEndpoint(
        id="{0.0.1.00000000}.{4}",
        friendly_name="CABLE-B Output (VB-Audio Virtual Cable B)",
        desc="CABLE-B Output",
        interface_name="VB-Audio Virtual Cable B",
        flow="eCapture",
        state=1,
        sample_rate_hz=48000,
    )
    assert identify_endpoint_role(ep_capture) == ROLE_V_MIC_WAPP


def test_identify_endpoint_role_standard_virtual_cable():
    # Standard Cable Render -> V-OUT Aux
    ep_render = AudioEndpoint(
        id="{0.0.0.00000000}.{5}",
        friendly_name="CABLE Input (VB-Audio Virtual Cable)",
        desc="CABLE Input",
        interface_name="VB-Audio Virtual Cable",
        flow="eRender",
        state=1,
        sample_rate_hz=48000,
    )
    assert identify_endpoint_role(ep_render) == ROLE_V_OUT_AUX

    # Standard Cable Capture -> V-MIC Aux
    ep_capture = AudioEndpoint(
        id="{0.0.1.00000000}.{6}",
        friendly_name="CABLE Output (VB-Audio Virtual Cable)",
        desc="CABLE Output",
        interface_name="VB-Audio Virtual Cable",
        flow="eCapture",
        state=1,
        sample_rate_hz=48000,
    )
    assert identify_endpoint_role(ep_capture) == ROLE_V_MIC_AUX


def test_identify_endpoint_role_soundboard_and_hardware():
    # USB Soundboard input
    ep_mesa_in = AudioEndpoint(
        id="{0.0.1.00000000}.{7}",
        friendly_name="Microfone USB (Mesa de Som)",
        desc="Entrada USB (Mesa de Som)",
        interface_name="USB Audio CODEC",
        flow="eCapture",
        state=1,
        sample_rate_hz=48000,
    )
    assert identify_endpoint_role(ep_mesa_in) == ROLE_MESA_IN

    # P2 Return (Speakers / Onboard)
    ep_mesa_out = AudioEndpoint(
        id="{0.0.0.00000000}.{8}",
        friendly_name="Saída P2 (Mesa de Som) (Realtek Audio)",
        desc="Saída P2 (Mesa de Som)",
        interface_name="Realtek Audio",
        flow="eRender",
        state=1,
        sample_rate_hz=48000,
    )
    assert identify_endpoint_role(ep_mesa_out) == ROLE_MESA_OUT_P2

    # Blackmagic HDMI Audio
    ep_bm = AudioEndpoint(
        id="{0.0.0.00000000}.{9}",
        friendly_name="Blackmagic HDMI (DeckLink Mini)",
        desc="Blackmagic HDMI Audio",
        interface_name="Blackmagic Audio",
        flow="eRender",
        state=1,
        sample_rate_hz=48000,
    )
    assert identify_endpoint_role(ep_bm) == ROLE_BLACKMAGIC

    # Webcam Mic
    ep_webcam = AudioEndpoint(
        id="{0.0.1.00000000}.{10}",
        friendly_name="HD Pro Webcam C920",
        desc="Microfone Webcam C920",
        interface_name="USB Audio Device",
        flow="eCapture",
        state=1,
        sample_rate_hz=48000,
    )
    assert identify_endpoint_role(ep_webcam) == ROLE_WEBCAM_MIC


def test_identify_endpoint_role_already_renamed():
    ep = AudioEndpoint(
        id="{0.0.0.00000000}.{11}",
        friendly_name="V-OUT Zoom (Envio)",
        desc="V-OUT Zoom (Envio)",
        interface_name="VB-Audio Virtual Cable A",
        flow="eRender",
        state=1,
        sample_rate_hz=48000,
    )
    assert identify_endpoint_role(ep) == ROLE_V_OUT_ZOOM


def test_identify_endpoint_role_unrelated_device():
    ep = AudioEndpoint(
        id="{0.0.0.00000000}.{12}",
        friendly_name="TV da Sala (Intel Display Audio)",
        desc="TV-monitor",
        interface_name="Áudio Intel(R) para telas",
        flow="eRender",
        state=4,
        sample_rate_hz=48000,
    )
    assert identify_endpoint_role(ep) is None


# ---------------------------------------------------------------------------
# 4. map_project_roles
# ---------------------------------------------------------------------------


def test_map_project_roles_priority_and_slugs():
    # When an active and a disabled Cable A exist, active is chosen
    ep_active = AudioEndpoint(
        id="{0.0.0.00000000}.{active-zoom}",
        friendly_name="Cabo Virtual A - Entrada Zoom",
        desc="Cabo Virtual A - Entrada Zoom",
        interface_name="VB-Audio Virtual Cable A",
        flow="eRender",
        state=DEVICE_STATE_ACTIVE,
        sample_rate_hz=48000,
    )
    ep_disabled = AudioEndpoint(
        id="{0.0.0.00000000}.{disabled-zoom}",
        friendly_name="CABLE-A In 16ch",
        desc="CABLE-A In 16ch",
        interface_name="VB-Audio Virtual Cable A",
        flow="eRender",
        state=DEVICE_STATE_DISABLED,
        sample_rate_hz=48000,
    )

    mapping = map_project_roles([ep_disabled, ep_active])

    # Should map to the active endpoint
    assert mapping[ROLE_V_OUT_ZOOM].id == ep_active.id
    # Slug access should also work
    assert mapping["v_out_zoom"].id == ep_active.id


# ---------------------------------------------------------------------------
# 5. PowerShell Elevation Script Generation
# ---------------------------------------------------------------------------


def test_generate_elevation_script():
    renames = {
        "{0.0.0.00000000}.{GUID-1}": "V-OUT Zoom (Envio)",
        "{0.0.1.00000000}.{GUID-2}": "V-MIC Zoom (Captação)",
    }
    disables = [
        "{0.0.0.00000000}.{GUID-BM}",
        "{0.0.1.00000000}.{GUID-CAM}",
    ]

    script = generate_elevation_script(renames, disables, restart_audiosrv=True)

    assert "$ErrorActionPreference = 'Stop'" in script
    assert "{a45c254e-df1c-4efd-8020-67d146a850e0},2" in script
    assert "V-OUT Zoom (Envio)" in script
    assert "V-MIC Zoom (Captação)" in script
    assert "DeviceState" in script
    assert "268435457" in script
    assert "Restart-Service Audiosrv -Force" in script
    assert "SUCCESS:" in script


def test_generate_elevation_script_no_restart():
    script = generate_elevation_script({}, ["{0.0.0.00000000}.{GUID-1}"], restart_audiosrv=False)
    assert "Restart-Service Audiosrv" not in script
    assert "DeviceState" in script


# ---------------------------------------------------------------------------
# 6. Direct Registry Modifications & UAC Handling
# ---------------------------------------------------------------------------


def test_modify_endpoints_in_registry_success():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    with patch("winreg.OpenKey") as mock_open, patch("winreg.SetValueEx") as mock_set:
        mock_open.return_value.__enter__.return_value = MagicMock()
        success, msg = modify_endpoints_in_registry(
            renames={"{0.0.0.00000000}.{GUID-1}": "New Name"},
            disables=["{0.0.0.00000000}.{GUID-2}"],
        )
        assert success is True
        assert "2 modificações aplicadas" in msg
        assert mock_set.call_count == 2


def test_modify_endpoints_in_registry_permission_error():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    with patch("winreg.OpenKey", side_effect=PermissionError("Access denied")):
        success, msg = modify_endpoints_in_registry(
            renames={"{0.0.0.00000000}.{GUID-1}": "New Name"},
            disables=[],
        )
        assert success is False
        assert "Acesso negado" in msg


def test_apply_device_modifications_empty():
    success, msg = apply_device_modifications({}, [])
    assert success is True
    assert "Nenhuma modificação" in msg


def test_apply_device_modifications_elevated():
    with patch("meeting_assistant.services.windows_core_audio.is_user_admin", return_value=True), patch(
        "meeting_assistant.services.windows_core_audio.modify_endpoints_in_registry",
        return_value=(True, "OK"),
    ):
        success, msg = apply_device_modifications({"{0.0.0.00000000}.{G}": "Name"}, [])
        assert success is True
        assert "OK" in msg


def test_apply_device_modifications_subprocess():
    with patch("meeting_assistant.services.windows_core_audio.is_user_admin", return_value=False), patch(
        "subprocess.run"
    ) as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0)
        success, msg = apply_device_modifications({"{0.0.0.00000000}.{G}": "Name"}, [])
        assert success is True
        assert "sucesso" in msg.casefold()


# ---------------------------------------------------------------------------
# 7. Real Windows Core Audio Enumeration
# ---------------------------------------------------------------------------


def test_enumerate_endpoints_real_system():
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    endpoints = enumerate_endpoints()
    assert isinstance(endpoints, list)
    assert len(endpoints) > 0, "Expected at least 1 audio endpoint on Windows host"

    for ep in endpoints:
        assert ep.flow in ("eRender", "eCapture")
        valid_states = (
            DEVICE_STATE_ACTIVE,
            DEVICE_STATE_DISABLED,
            DEVICE_STATE_DISABLED_COM,
            DEVICE_STATE_NOTPRESENT,
            DEVICE_STATE_UNPLUGGED,
        )
        assert ep.state in valid_states
        assert ep.sample_rate_hz > 0
        assert len(ep.guid) > 0


# ---------------------------------------------------------------------------
# 8. Elevation Script Sanitization & Role Priority Specificity
# ---------------------------------------------------------------------------


def test_generate_elevation_script_sanitization():
    """Verify that generate_elevation_script sanitizes names and GUIDs against injection."""
    renames = {
        "{0.0.0.00000000}.{11111111-2222-3333-4444-555555555555}": "Line1\r\nLine2's Name\n",
        "{0.0.1.00000000}.{evil'; Write-Output 'INJECTION'; #'}'": "Clean Name",
    }
    disables = [
        "{0.0.0.00000000}.{bad'; Remove-Item C:\\ -Recurse; #'}",
    ]

    script = generate_elevation_script(renames, disables)

    # Newlines stripped from rename
    assert "\r" not in script
    assert "$newName = 'Line1 Line2''s Name'" in script

    # Malicious injection strings sanitized out of GUIDs
    assert "INJECTION" not in script
    assert "Remove-Item" not in script
    assert "evil'" not in script
    assert "bad'" not in script


def test_map_project_roles_explicit_role_priority():
    """Verify that explicit role names in friendly_name take precedence over generic ones."""
    generic_out = AudioEndpoint(
        id="gen_out",
        friendly_name="Alto-falantes (Realtek Audio)",
        desc="Speakers",
        interface_name="Realtek Audio",
        flow="eRender",
        state=DEVICE_STATE_ACTIVE,
        sample_rate_hz=48000,
    )
    explicit_out = AudioEndpoint(
        id="exp_out",
        friendly_name="Mesa de Som (Retorno P2) (Realtek Audio)",
        desc="Mesa de Som (Retorno P2)",
        interface_name="Realtek Audio",
        flow="eRender",
        state=DEVICE_STATE_ACTIVE,
        sample_rate_hz=48000,
    )

    role_map = map_project_roles([generic_out, explicit_out])
    assert role_map[ROLE_MESA_OUT_P2].id == "exp_out"
    assert role_map["mesa_out_p2"].id == "exp_out"

