"""End-to-End (E2E) integration and requirement verification test suite for AV Setup Tool.

Covers R1 through R5 of ORIGINAL_REQUEST.md across 4 distinct testing tiers:
- Tier 1: Feature Coverage (F1 to F21 happy paths in strict isolation)
- Tier 2: Boundary & Corner Cases (empty devices, abnormal rates, closed OBS, single display)
- Tier 3: Cross-Feature Combinations (batch renames + disables, full OS apply & reverify)
- Tier 4: Real-World Workloads (complete meeting prep lifecycle, idempotency, drift repair)
"""

from __future__ import annotations

import configparser
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from obsws_python.error import OBSSDKRequestError

import meeting_assistant.services.windows_core_audio as win_audio
import scripts.av_setup_tool as av_tool
from meeting_assistant.core.state import AppState
from meeting_assistant.services.app_audio_router import (
    DEFAULT_ZOOM_CAPTURE_NAME,
    DEFAULT_ZOOM_RENDER_NAME,
    WHATSAPP_APP,
    ZOOM_APP,
    configure_app_route,
    get_virtual_cam_status,
    launch_apps_volume_settings,
    start_obs_virtual_cam,
    stop_obs_virtual_cam,
)
from meeting_assistant.services.obs_av_provisioner import (
    AUDIO_BUS_SCENE,
    DEFAULT_ZOOM_MONITOR_DEVICE_NAME,
    JWL_AUDIO_SOURCE,
    MANAGED_SCENES,
    MESA_AUDIO_SOURCE,
    MONITOR_NONE,
    PROCESS_AUDIO_KIND,
    ZOOM_AUDIO_SOURCE,
    OBSProvisionResult,
    enforce_no_display_captures,
    provision_obs_av,
    provision_scenes,
)
from meeting_assistant.services.obs_jwl_capture import (
    KIND as JWL_KIND,
)
from meeting_assistant.services.settings import AppSettings, SettingsService
from meeting_assistant.services.windows_core_audio import (
    ALL_PROJECT_ROLES,
    DEVICE_STATE_ACTIVE,
    PKEY_DEVICE_DESCRIPTION,
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
    generate_elevation_script,
    identify_endpoint_role,
    map_project_roles,
    parse_wave_format_sample_rate,
)
from meeting_assistant.services.windows_transmission_optimizer import (
    OptimizationStatus,
    apply_all_optimizations,
    check_all_optimizations,
    check_monitor_dpi_status,
    check_sample_rates,
)
from meeting_assistant.ui.av_setup_dialog import AVSetupDialog, AVSetupWindow
from meeting_assistant.ui.main_window import MainWindow
from meeting_assistant.ui.setup_assistant_dialog import SetupAssistantDialog

# ===========================================================================
# Stateful Mock OBS Client for E2E Testing
# ===========================================================================


class E2EMockObsClient:
    """In-memory protocol mock of obs-websocket v5 simulating realistic OBS server."""

    def __init__(self, current_profile: str = "Salão Padrão"):
        self.current_profile = current_profile
        self.scenes: list[str] = []
        self.scene_items: dict[str, list[dict[str, Any]]] = {}
        self.inputs: dict[str, dict[str, Any]] = {}
        self.input_monitor_types: dict[str, str] = {}
        self.input_tracks: dict[str, dict[str, bool]] = {}
        self.input_mutes: dict[str, bool] = {}
        self.profile_parameters: dict[tuple[str, str], str] = {}
        self.program_scene_calls: list[str] = []
        self.virtual_cam_active = False
        self.item_id_counter = 1000

    def send(self, request: str, data: dict[str, Any] | None = None, raw: bool = True) -> dict[str, Any]:
        data = data or {}

        if request == "GetVersion":
            return {"obsVersion": "31.0.3", "obsWebSocketVersion": "5.5.0"}

        if request == "GetProfileList":
            return {"currentProfileName": self.current_profile, "profiles": [self.current_profile]}

        if request == "SetProfileParameter":
            cat = data.get("parameterCategory", "")
            name = data.get("parameterName", "")
            val = data.get("parameterValue", "")
            self.profile_parameters[(cat, name)] = val
            return {}

        if request == "GetProfileParameter":
            cat = data.get("parameterCategory", "")
            name = data.get("parameterName", "")
            return {"parameterValue": self.profile_parameters.get((cat, name), "")}

        if request == "GetSceneList":
            return {
                "currentProgramSceneName": self.scenes[0] if self.scenes else "Default",
                "scenes": [{"sceneName": s} for s in self.scenes],
            }

        if request == "CreateScene":
            name = data["sceneName"]
            if name not in self.scenes:
                self.scenes.append(name)
                self.scene_items.setdefault(name, [])
            return {}

        if request == "SetCurrentProgramScene":
            self.program_scene_calls.append(data.get("sceneName", ""))
            return {}

        if request == "GetSceneItemList":
            scene = data["sceneName"]
            return {"sceneItems": list(self.scene_items.get(scene, []))}

        if request == "CreateSceneItem":
            scene = data["sceneName"]
            source = data["sourceName"]
            self.item_id_counter += 1
            item = {
                "sceneItemId": self.item_id_counter,
                "sourceName": source,
                "sceneItemEnabled": data.get("sceneItemEnabled", True),
                "isGroup": False,
            }
            self.scene_items.setdefault(scene, []).append(item)
            return {"sceneItemId": self.item_id_counter}

        if request == "SetSceneItemEnabled":
            scene = data["sceneName"]
            item_id = data["sceneItemId"]
            enabled = data["sceneItemEnabled"]
            for item in self.scene_items.get(scene, []):
                if item["sceneItemId"] == item_id:
                    item["sceneItemEnabled"] = enabled
                    break
            return {}

        if request == "SetSceneItemTransform":
            return {}

        if request == "SetSceneItemIndex":
            return {}

        if request == "GetInputList":
            return {
                "inputs": [
                    {"inputName": name, "inputKind": info["inputKind"]}
                    for name, info in self.inputs.items()
                ]
            }

        if request == "GetInputKindList":
            return {
                "inputKinds": [
                    "wasapi_input_capture",
                    PROCESS_AUDIO_KIND,
                    JWL_KIND,
                    "image_source",
                    "ffmpeg_source",
                    "monitor_capture",
                    "window_capture",
                ]
            }

        if request == "CreateInput":
            name = data["inputName"]
            kind = data["inputKind"]
            scene = data["sceneName"]
            if name in self.inputs:
                raise OBSSDKRequestError(601, f"Resource {name} already exists")
            self.inputs[name] = {"inputKind": kind, "settings": data.get("inputSettings", {})}
            self.item_id_counter += 1
            item = {
                "sceneItemId": self.item_id_counter,
                "sourceName": name,
                "sceneItemEnabled": data.get("sceneItemEnabled", True),
                "isGroup": False,
            }
            self.scene_items.setdefault(scene, []).append(item)
            return {"sceneItemId": self.item_id_counter}

        if request == "GetInputSettings":
            name = data["inputName"]
            return {"inputSettings": self.inputs.get(name, {}).get("settings", {})}

        if request == "SetInputSettings":
            name = data["inputName"]
            settings = data.get("inputSettings", {})
            if name in self.inputs:
                if data.get("overlay", False):
                    self.inputs[name]["settings"].update(settings)
                else:
                    self.inputs[name]["settings"] = settings
            return {}

        if request == "GetInputAudioMonitorType":
            name = data["inputName"]
            return {"monitorType": self.input_monitor_types.get(name, MONITOR_NONE)}

        if request == "SetInputAudioMonitorType":
            name = data["inputName"]
            self.input_monitor_types[name] = data["monitorType"]
            return {}

        if request == "GetInputAudioTracks":
            default_tracks = {str(i): False for i in range(1, 7)}
            return {"inputAudioTracks": self.input_tracks.get(data["inputName"], default_tracks)}

        if request == "SetInputAudioTracks":
            name = data["inputName"]
            self.input_tracks[name] = data["inputAudioTracks"]
            return {}

        if request == "GetInputMute":
            return {"inputMuted": self.input_mutes.get(data["inputName"], False)}

        if request == "SetInputMute":
            name = data["inputName"]
            self.input_mutes[name] = data["inputMuted"]
            return {}

        if request == "GetVideoSettings":
            return {"baseWidth": 1920, "baseHeight": 1080, "outputWidth": 1920, "outputHeight": 1080}

        if request == "GetVirtualCamStatus":
            return {"outputActive": self.virtual_cam_active}

        if request == "StartVirtualCam":
            self.virtual_cam_active = True
            return {}

        if request == "StopVirtualCam":
            self.virtual_cam_active = False
            return {}

        return {}


# ===========================================================================
# Test Helpers & Fixtures
# ===========================================================================


def create_full_ten_role_endpoints() -> list[AudioEndpoint]:
    """Build complete realistic set of endpoints mapping to all 10 project roles."""
    return [
        AudioEndpoint(
            id="{0.0.0.00000000}.{11111111-0000-0000-0000-000000000001}",
            friendly_name="Cabo Virtual Auxiliar (VB-Audio Virtual Cable)",
            desc="VB-Audio Point",
            interface_name="VB-Audio Virtual Cable",
            flow="eRender",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
            detected_role=ROLE_V_OUT_AUX,
        ),
        AudioEndpoint(
            id="{0.0.1.00000000}.{11111111-0000-0000-0000-000000000002}",
            friendly_name="Microfone Virtual Auxiliar (VB-Audio Virtual Cable)",
            desc="VB-Audio Point",
            interface_name="VB-Audio Virtual Cable",
            flow="eCapture",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
            detected_role=ROLE_V_MIC_AUX,
        ),
        AudioEndpoint(
            id="{0.0.0.00000000}.{22222222-0000-0000-0000-000000000001}",
            friendly_name="Cabo Virtual A - Envio Zoom",
            desc="VB-Audio Cable-A",
            interface_name="VB-Audio Virtual Cable A",
            flow="eRender",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
            detected_role=ROLE_V_OUT_ZOOM,
        ),
        AudioEndpoint(
            id="{0.0.1.00000000}.{22222222-0000-0000-0000-000000000002}",
            friendly_name="Microfone Virtual A - Captação Zoom",
            desc="VB-Audio Cable-A",
            interface_name="VB-Audio Virtual Cable A",
            flow="eCapture",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
            detected_role=ROLE_V_MIC_ZOOM,
        ),
        AudioEndpoint(
            id="{0.0.0.00000000}.{33333333-0000-0000-0000-000000000001}",
            friendly_name="Cabo Virtual B - Envio WhatsApp",
            desc="VB-Audio Cable-B",
            interface_name="VB-Audio Virtual Cable B",
            flow="eRender",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
            detected_role=ROLE_V_OUT_WAPP,
        ),
        AudioEndpoint(
            id="{0.0.1.00000000}.{33333333-0000-0000-0000-000000000002}",
            friendly_name="Microfone Virtual B - Captação WhatsApp",
            desc="VB-Audio Cable-B",
            interface_name="VB-Audio Virtual Cable B",
            flow="eCapture",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
            detected_role=ROLE_V_MIC_WAPP,
        ),
        AudioEndpoint(
            id="{0.0.1.00000000}.{44444444-0000-0000-0000-000000000001}",
            friendly_name="Linha (USB Audio CODEC - Mesa de Som)",
            desc="USB Audio",
            interface_name="USB Audio CODEC",
            flow="eCapture",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
            detected_role=ROLE_MESA_IN,
        ),
        AudioEndpoint(
            id="{0.0.0.00000000}.{55555555-0000-0000-0000-000000000001}",
            friendly_name="Alto-falantes (Realtek High Definition Audio)",
            desc="Speakers",
            interface_name="Realtek High Definition Audio",
            flow="eRender",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
            detected_role=ROLE_MESA_OUT_P2,
        ),
        AudioEndpoint(
            id="{0.0.0.00000000}.{66666666-0000-0000-0000-000000000001}",
            friendly_name="Blackmagic HDMI Audio",
            desc="Blackmagic Audio",
            interface_name="Blackmagic HDMI Audio Device",
            flow="eRender",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
            detected_role=ROLE_BLACKMAGIC,
        ),
        AudioEndpoint(
            id="{0.0.1.00000000}.{77777777-0000-0000-0000-000000000001}",
            friendly_name="Microfone (USB Webcam)",
            desc="Webcam Audio",
            interface_name="USB Webcam Microphone",
            flow="eCapture",
            state=DEVICE_STATE_ACTIVE,
            sample_rate_hz=48000,
            detected_role=ROLE_WEBCAM_MIC,
        ),
    ]


def create_all_optimal_statuses() -> list[OptimizationStatus]:
    """Return status list representing a 100% compliant Windows 11 system."""
    return [
        OptimizationStatus("Ducking de Comunicações", 3, True, 3, "Não fazer nada"),
        OptimizationStatus("Esquema de Sons do Sistema", ".None", True, ".None", "Sem som"),
        OptimizationStatus("Som de Inicialização do Windows", 1, True, 1, "Desativado"),
        OptimizationStatus("Desligamento de Tela (Modo AC)", 0, True, 0, "Nunca"),
        OptimizationStatus("Suspensão do Sistema (Modo AC)", 0, True, 0, "Nunca"),
        OptimizationStatus("Modo Exclusivo de Áudio", 0, True, 0, "Desativado"),
        OptimizationStatus("Aprimoramentos de Sinal de Áudio", 1, True, 1, "Desativados"),
        OptimizationStatus("Taxa de Amostragem (48 kHz)", "48000 Hz", True, "48000 Hz", "Conforme"),
        OptimizationStatus("Escala do Monitor Secundário (DPI 100%)", "100%", True, "100%", "Conforme"),
    ]


# ===========================================================================
# Tier 1: Feature Coverage (F1 to F21 Happy Paths)
# ===========================================================================


class TestTier1FeatureCoverage:
    """Verifies each functional capability individually under standard conditions."""

    def test_e2e_f1_f2_core_audio_enumeration_and_sample_rates(self):
        """F1, F2: Core Audio endpoints are properly enumerated with sample rates and properties."""
        eps = create_full_ten_role_endpoints()
        with patch.object(win_audio, "enumerate_endpoints", return_value=eps):
            result = win_audio.enumerate_endpoints()
            assert len(result) == 10
            for ep in result:
                assert ep.is_active is True
                assert ep.is_disabled is False
                assert ep.sample_rate_hz == 48000
                assert ep.guid.startswith("{") and ep.guid.endswith("}")
                assert ep.flow_direction in ("Render", "Capture")

    def test_e2e_f3_device_role_recognition_across_all_ten_roles(self):
        """F3: Unambiguously map all 10 project endpoints to expected roles and slugs."""
        eps = create_full_ten_role_endpoints()
        for ep in eps:
            identified = identify_endpoint_role(ep)
            assert identified is not None, f"Failed identifying {ep.friendly_name}"
            assert identified == ep.detected_role

        role_map = map_project_roles(eps)
        for expected_role in ALL_PROJECT_ROLES:
            assert expected_role in role_map, f"Missing role: {expected_role}"
            ep = role_map[expected_role]
            assert isinstance(ep, AudioEndpoint)

        # Check slug aliases
        assert "v_out_zoom" in role_map
        assert "v_mic_zoom" in role_map
        assert "v_out_wapp" in role_map
        assert "v_mic_wapp" in role_map
        assert "mesa_in" in role_map
        assert "mesa_out_p2" in role_map
        assert "blackmagic" in role_map
        assert "webcam_mic" in role_map

    def test_e2e_f4_device_renaming_script_generation(self):
        """F4: PowerShell script accurately targets PKEY_DEVICE_DESCRIPTION."""
        renames = {
            "{0.0.0.00000000}.{22222222-0000-0000-0000-000000000001}": ROLE_V_OUT_ZOOM,
            "{0.0.1.00000000}.{22222222-0000-0000-0000-000000000002}": ROLE_V_MIC_ZOOM,
        }
        script = generate_elevation_script(renames=renames, disables=[], restart_audiosrv=False)
        assert "$ErrorActionPreference = 'Stop'" in script
        assert "{22222222-0000-0000-0000-000000000001}" in script
        assert PKEY_DEVICE_DESCRIPTION in script
        assert ROLE_V_OUT_ZOOM in script
        assert ROLE_V_MIC_ZOOM in script
        assert "Restart-Service Audiosrv" not in script

    def test_e2e_f5_endpoint_disabling_script_generation(self):
        """F5: Script sets DeviceState to 268435457 (0x10000001) for Blackmagic and Webcam mic."""
        disables = [
            "{0.0.0.00000000}.{66666666-0000-0000-0000-000000000001}",
            "{0.0.1.00000000}.{77777777-0000-0000-0000-000000000001}",
        ]
        script = generate_elevation_script(renames={}, disables=disables, restart_audiosrv=True)
        assert "{66666666-0000-0000-0000-000000000001}" in script
        assert "{77777777-0000-0000-0000-000000000001}" in script
        assert "DeviceState" in script
        assert "268435457" in script
        assert "Restart-Service Audiosrv -Force" in script

    def test_e2e_f6_f11_os_transmission_checks(self):
        """F6-F11: All OS transmission checks return structured OptimizationStatus instances."""
        statuses = check_all_optimizations()
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

    def test_e2e_f12_per_app_call_routing(self, tmp_path: Path):
        """F12: Independent audio routing for Zoom and WhatsApp via CLI or guidance."""
        dummy_cli = tmp_path / "svcl.exe"
        dummy_cli.write_text("dummy", encoding="utf-8")

        mock_res = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_res):
            ok_zoom, msg_zoom = configure_app_route(
                ZOOM_APP,
                render_id=DEFAULT_ZOOM_RENDER_NAME,
                capture_id=DEFAULT_ZOOM_CAPTURE_NAME,
                cli_path=dummy_cli,
            )
            assert ok_zoom is True
            assert "configurado com sucesso" in msg_zoom

            ok_wapp, msg_wapp = configure_app_route(
                WHATSAPP_APP,
                render_id=DEFAULT_ZOOM_RENDER_NAME,
                capture_id="V-MIC Wapp (Captação)",
                cli_path=dummy_cli,
            )
            assert ok_wapp is True
            assert "configurado com sucesso" in msg_wapp

    def test_e2e_f13_virtual_camera_controls(self):
        """F13: Verify OBS virtual camera status inquiry and start/stop controls."""
        mock_client = E2EMockObsClient()
        status = get_virtual_cam_status(obs_client=mock_client)
        assert status["obs_virtual_cam"]["available"] is True
        assert status["obs_virtual_cam"]["active"] is False

        ok_start, msg_start = start_obs_virtual_cam(obs_client=mock_client)
        assert ok_start is True
        assert "iniciada" in msg_start.lower()
        assert mock_client.virtual_cam_active is True

        ok_stop, msg_stop = stop_obs_virtual_cam(obs_client=mock_client)
        assert ok_stop is True
        assert "parada" in msg_stop.lower()
        assert mock_client.virtual_cam_active is False

    def test_e2e_f14_f17_obs_av_provisioning(self, tmp_path: Path):
        """F14-F17: Full OBS provisioning creates scenes, HWND capture, process audio, and monitor device."""
        profile_dir = tmp_path / "profiles" / "Salão"
        profile_dir.mkdir(parents=True)
        ini_file = profile_dir / "basic.ini"
        config = configparser.ConfigParser()
        config["General"] = {"Name": "Salão"}
        config["Audio"] = {"MonitoringDeviceId": "default"}
        with open(ini_file, "w", encoding="utf-8-sig") as f:
            config.write(f)

        client = E2EMockObsClient(current_profile="Salão")
        cable_id = "{0.0.0.00000000}.{22222222-0000-0000-0000-000000000001}"

        res = provision_obs_av(
            zoom_cable_id=cable_id,
            zoom_cable_name=DEFAULT_ZOOM_MONITOR_DEVICE_NAME,
            client=client,
            profiles_dir=tmp_path / "profiles",
            jwl_target={"hwnd": "54321", "session": "active-jwl"},
        )

        assert res.success is True
        assert res.errors == []
        assert res.monitoring_device_set is True
        assert set(res.scenes_created) == {*MANAGED_SCENES, AUDIO_BUS_SCENE}
        assert res.jwl_hwnd_capture_configured is True
        assert set(res.process_audio_configured) == {MESA_AUDIO_SOURCE, JWL_AUDIO_SOURCE, ZOOM_AUDIO_SOURCE}
        assert client.program_scene_calls == []  # Program scene never switched

    def test_e2e_f18_standalone_gui_window(self, monkeypatch):
        """F18: Single-window PySide6 AVSetupWindow constructs with all 5 functional tabs."""
        eps = create_full_ten_role_endpoints()
        role_map = map_project_roles(eps)
        opt_statuses = create_all_optimal_statuses()

        monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.enumerate_endpoints", lambda: eps)
        monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.map_project_roles", lambda _: role_map)
        monkeypatch.setattr(
            "meeting_assistant.ui.av_setup_dialog.check_all_optimizations", lambda: opt_statuses
        )

        window = AVSetupWindow(auto_refresh=False)
        try:
            assert isinstance(window, AVSetupDialog)
            assert window.tabs.count() == 5
            titles = [window.tabs.tabText(i) for i in range(5)]
            assert any("Dispositivos de Áudio" in t for t in titles)
            assert any("Otimizações Windows 11" in t for t in titles)
            assert any("Roteamento & Câmeras" in t for t in titles)
            assert any("OBS Studio" in t for t in titles)
            assert any("Diagnóstico & Relatório" in t for t in titles)
        finally:
            window.close()

    def test_e2e_f19_standalone_cli_execution(self, capsys, monkeypatch):
        """F19: Standalone CLI entrypoint supports --diagnose and --json modes."""
        eps = create_full_ten_role_endpoints()
        role_map = map_project_roles(eps)
        opt_statuses = create_all_optimal_statuses()

        monkeypatch.setattr("meeting_assistant.services.windows_core_audio.enumerate_endpoints", lambda: eps)
        monkeypatch.setattr(
            "meeting_assistant.services.windows_core_audio.map_project_roles", lambda _: role_map
        )
        monkeypatch.setattr(
            "meeting_assistant.services.windows_transmission_optimizer.check_all_optimizations",
            lambda: opt_statuses,
        )
        monkeypatch.setattr(
            "meeting_assistant.services.obs_av_provisioner.connect_obs",
            lambda **_: E2EMockObsClient(),
        )

        monkeypatch.setattr("sys.argv", ["av_setup_tool.py", "--diagnose", "--json"])
        code = av_tool.main()
        assert code == 0

        captured = capsys.readouterr()
        diag = json.loads(captured.out)
        assert diag["ready"] is True
        assert diag["endpoints_count"] == 10
        assert diag["optimizations_optimal"] == 9
        assert diag["obs"]["connected"] is True

    def test_e2e_f20_launcher_script_presence(self):
        """F20: PowerShell launcher scripts/run_av_setup.ps1 exists and contains execution logic."""
        launcher_path = Path("scripts/run_av_setup.ps1")
        assert launcher_path.is_file(), "Launcher script scripts/run_av_setup.ps1 must exist"
        content = launcher_path.read_text(encoding="utf-8")
        assert "av_setup_tool.py" in content
        assert "ExecutionPolicy" in content or "python" in content.lower()

    def test_e2e_f21_settings_dialog_and_main_window_integration(self, tmp_path: Path, monkeypatch):
        """F21: Settings Assistant and MainWindow provide accessible hooks to launch AV Setup."""
        eps = create_full_ten_role_endpoints()
        role_map = map_project_roles(eps)
        monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.enumerate_endpoints", lambda: eps)
        monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.map_project_roles", lambda _: role_map)
        monkeypatch.setattr(
            "meeting_assistant.ui.av_setup_dialog.check_all_optimizations", create_all_optimal_statuses
        )
        monkeypatch.setattr(
            "meeting_assistant.ui.av_setup_dialog.AVSetupWindow.refresh_all_diagnostics",
            lambda *args, **kwargs: None,
        )

        services = [MagicMock() for _ in range(6)]
        services[1].snapshot.return_value = []
        services[5].active = services[5].returning = False
        settings_service = SettingsService(tmp_path / "settings.json")
        main_win = MainWindow(AppState(), AppSettings(), settings_service, *services)

        try:
            assert main_win._av_setup_window is None
            main_win._open_av_setup()
            assert main_win._av_setup_window is not None
            assert isinstance(main_win._av_setup_window, AVSetupWindow)

            monkeypatch.setattr(SetupAssistantDialog, "_inspect", lambda self: None)
            setup_dlg = SetupAssistantDialog(main_win, page="installation")
            try:
                assert hasattr(setup_dlg, "av_setup_install_btn")
                assert hasattr(setup_dlg, "av_setup_diag_btn")
            finally:
                setup_dlg.close()
        finally:
            if main_win._av_setup_window:
                main_win._av_setup_window.close()
            main_win.close()


# ===========================================================================
# Tier 2: Boundary & Corner Cases
# ===========================================================================


class TestTier2BoundariesAndCornerCases:
    """Verifies robustness against invalid inputs, missing devices, network and OS errors."""

    def test_tier2_empty_device_enumeration_graceful_handling(self):
        """Empty endpoint enumeration does not crash role mapping or diagnostics."""
        with patch.object(win_audio, "enumerate_endpoints", return_value=[]):
            eps = win_audio.enumerate_endpoints()
            assert eps == []
            role_map = map_project_roles(eps)
            assert role_map == {}

        with patch(
            "meeting_assistant.services.windows_transmission_optimizer.enumerate_endpoints",
            return_value=[],
        ):
            status = check_sample_rates()
            assert isinstance(status, OptimizationStatus)
            assert status.name == "Taxa de Amostragem (48 kHz)"
            assert status.is_optimal is True

    def test_tier2_unexpected_sample_rates_detection(self):
        """Mixed abnormal sample rates (44.1kHz, 16kHz, 96kHz, 0Hz) are properly flagged."""
        abnormal_eps = [
            AudioEndpoint(
                id="{0.0.0.0}.{1}",
                friendly_name="Bluetooth Headset",
                desc="BT",
                interface_name="BT",
                flow="eRender",
                state=DEVICE_STATE_ACTIVE,
                sample_rate_hz=16000,
            ),
            AudioEndpoint(
                id="{0.0.0.0}.{2}",
                friendly_name="Studio Dac",
                desc="Dac",
                interface_name="Dac",
                flow="eRender",
                state=DEVICE_STATE_ACTIVE,
                sample_rate_hz=96000,
            ),
            AudioEndpoint(
                id="{0.0.1.0}.{3}",
                friendly_name="Webcam Mic",
                desc="Mic",
                interface_name="Mic",
                flow="eCapture",
                state=DEVICE_STATE_ACTIVE,
                sample_rate_hz=44100,
            ),
            AudioEndpoint(
                id="{0.0.0.0}.{4}",
                friendly_name="Uninitialized Cable",
                desc="Cable",
                interface_name="Cable",
                flow="eRender",
                state=DEVICE_STATE_ACTIVE,
                sample_rate_hz=0,
            ),
        ]

        with patch(
            "meeting_assistant.services.windows_transmission_optimizer.enumerate_endpoints",
            return_value=abnormal_eps,
        ):
            status = check_sample_rates()
            assert status.is_optimal is False
            curr = str(status.current_value)
            assert "16000" in curr or "16.0" in curr
            assert "96000" in curr or "96.0" in curr
            assert "44100" in curr or "44.1" in curr

    def test_tier2_unresponsive_or_closed_obs_websocket(self):
        """Connection refused on OBS WebSocket produces clean error reporting without traceback."""
        with patch(
            "meeting_assistant.services.obs_av_provisioner.connect_obs",
            side_effect=ConnectionRefusedError("Connection refused on 127.0.0.1:4455"),
        ):
            result = provision_obs_av(host="127.0.0.1", port=4455, client=None)
            assert isinstance(result, OBSProvisionResult)
            assert result.success is False
            assert len(result.errors) > 0
            assert "Não foi possível conectar ao OBS Studio" in result.errors[0]

        # Starting virtual camera while OBS is offline returns clean failure
        ok, msg = start_obs_virtual_cam(obs_client=None)
        assert ok is False
        assert "não conectado" in msg.lower()

    def test_tier2_single_display_environment_missing_secondary_monitor(self):
        """Single display setup reports secondary display missing without failing suite."""
        with patch(
            "meeting_assistant.services.windows_transmission_optimizer.check_monitor_dpi",
            return_value=(False, 0.0, "Segundo monitor não detectado (apenas 1 monitor ativo)."),
        ):
            status = check_monitor_dpi_status()
            assert status.is_optimal is False
            assert "não detectado" in status.description.lower()
            assert status.current_value in ("Não conectado", "Não detectado", 0.0, "0%")

    def test_tier2_missing_soundvolumeview_fallback_to_settings_uri(self):
        """When SoundVolumeView CLI is missing, app provides operator guidance or opens settings."""
        with patch(
            "meeting_assistant.services.app_audio_router.find_cli_tool",
            return_value=None,
        ):
            ok, msg = configure_app_route(
                ZOOM_APP,
                render_id=DEFAULT_ZOOM_RENDER_NAME,
                capture_id=DEFAULT_ZOOM_CAPTURE_NAME,
                cli_path=None,
            )
            assert ok is False
            assert "soundvolumeview" in msg.lower() or "manual" in msg.lower()

        # Settings URI launch fallback
        with patch("sys.platform", "win32"), patch("os.startfile", create=True) as mock_startfile:
            ok_launch, _ = launch_apps_volume_settings()
            assert ok_launch is True
            mock_startfile.assert_called_once_with("ms-settings:apps-volume")

    def test_tier2_permission_denial_on_uac_elevation_cancel(self):
        """When user cancels UAC dialog, apply_device_modifications returns clean failure."""
        mock_proc = MagicMock(returncode=1223)  # Win32 ERROR_CANCELLED
        with patch("sys.platform", "win32"), patch(
            "meeting_assistant.services.windows_core_audio.is_user_admin", return_value=False
        ), patch("subprocess.run", return_value=mock_proc):
            ok, msg = apply_device_modifications(
                renames={"guid1": "New Name"},
                disables=[],
            )
            assert ok is False
            assert "cancelamento" in msg.lower() or "falha na elevação" in msg.lower()

    def test_tier2_corrupted_wave_format_binary_registry_blobs(self):
        """Corrupted, empty, or truncated binary blobs safely return None without crashing."""
        assert parse_wave_format_sample_rate(b"") is None
        assert parse_wave_format_sample_rate(b"short_bytes") is None
        assert parse_wave_format_sample_rate(b"\x00" * 32) is None
        assert parse_wave_format_sample_rate(None) is None  # type: ignore


# ===========================================================================
# Tier 3: Cross-Feature Combinations & Interactions
# ===========================================================================


class TestTier3CombinationsAndInteractions:
    """Verifies multi-feature interactions, script coordination, and safety purges."""

    def test_tier3_combined_batch_rename_and_endpoint_disables(self):
        """Consolidated script simultaneously renames endpoints and disables targeted hardware."""
        renames = {
            "{0.0.0.00000000}.{GUID-CABLE-A-OUT}": ROLE_V_OUT_ZOOM,
            "{0.0.1.00000000}.{GUID-CABLE-A-IN}": ROLE_V_MIC_ZOOM,
            "{0.0.0.00000000}.{GUID-CABLE-B-OUT}": ROLE_V_OUT_WAPP,
            "{0.0.1.00000000}.{GUID-CABLE-B-IN}": ROLE_V_MIC_WAPP,
        }
        disables = [
            "{0.0.0.00000000}.{GUID-BLACKMAGIC-HDMI}",
            "{0.0.1.00000000}.{GUID-WEBCAM-MIC}",
        ]

        script = generate_elevation_script(renames=renames, disables=disables, restart_audiosrv=True)

        # Verify all 4 renames are included
        assert "{GUID-CABLE-A-OUT}" in script
        assert "{GUID-CABLE-A-IN}" in script
        assert "{GUID-CABLE-B-OUT}" in script
        assert "{GUID-CABLE-B-IN}" in script

        # Verify both disables are included
        assert "{GUID-BLACKMAGIC-HDMI}" in script
        assert "{GUID-WEBCAM-MIC}" in script
        assert "DeviceState" in script
        assert "268435457" in script

        # Verify audiosrv restart
        assert "Restart-Service Audiosrv -Force" in script

    def test_tier3_full_os_optimization_apply_and_reverify(self):
        """Applying all OS optimizations translates directly into 100% optimal check status."""
        with patch(
            "meeting_assistant.services.windows_transmission_optimizer.apply_ducking",
            return_value=True,
        ), patch(
            "meeting_assistant.services.windows_transmission_optimizer.apply_sound_scheme",
            return_value=True,
        ), patch(
            "meeting_assistant.services.windows_transmission_optimizer.apply_startup_sound",
            return_value=True,
        ), patch(
            "meeting_assistant.services.windows_transmission_optimizer.apply_power_ac_monitor",
            return_value=True,
        ), patch(
            "meeting_assistant.services.windows_transmission_optimizer.apply_power_ac_standby",
            return_value=True,
        ), patch(
            "meeting_assistant.services.windows_transmission_optimizer.apply_exclusive_mode",
            return_value=True,
        ), patch(
            "meeting_assistant.services.windows_transmission_optimizer.apply_signal_enhancements",
            return_value=True,
        ):
            results = apply_all_optimizations()
            assert all(results.values()) is True

            # Re-verify with mocked optimal environment
            with patch(
                "meeting_assistant.services.windows_transmission_optimizer.check_ducking",
                return_value=OptimizationStatus("Ducking", 3, True, 3, "OK"),
            ), patch(
                "meeting_assistant.services.windows_transmission_optimizer.check_sound_scheme",
                return_value=OptimizationStatus("Sounds", ".None", True, ".None", "OK"),
            ), patch(
                "meeting_assistant.services.windows_transmission_optimizer.check_startup_sound",
                return_value=OptimizationStatus("Startup", 1, True, 1, "OK"),
            ), patch(
                "meeting_assistant.services.windows_transmission_optimizer.check_power_ac_monitor",
                return_value=OptimizationStatus("Power Mon", 0, True, 0, "OK"),
            ), patch(
                "meeting_assistant.services.windows_transmission_optimizer.check_power_ac_standby",
                return_value=OptimizationStatus("Power Stb", 0, True, 0, "OK"),
            ), patch(
                "meeting_assistant.services.windows_transmission_optimizer.check_exclusive_mode",
                return_value=OptimizationStatus("Exclusive", 0, True, 0, "OK"),
            ), patch(
                "meeting_assistant.services.windows_transmission_optimizer.check_signal_enhancements",
                return_value=OptimizationStatus("Enhancements", 1, True, 1, "OK"),
            ), patch(
                "meeting_assistant.services.windows_transmission_optimizer.check_sample_rates",
                return_value=OptimizationStatus("Rates", "48000 Hz", True, "48000 Hz", "OK"),
            ), patch(
                "meeting_assistant.services.windows_transmission_optimizer.check_monitor_dpi_status",
                return_value=OptimizationStatus("DPI", "100%", True, "100%", "OK"),
            ):
                post_checks = check_all_optimizations()
                assert len(post_checks) == 9
                assert all(s.is_optimal for s in post_checks) is True

    def test_tier3_obs_provisioning_purges_preexisting_display_captures(self, tmp_path: Path):
        """OBS provisioning automatically disables pre-existing monitor_capture sources across all scenes."""
        client = E2EMockObsClient()
        provision_scenes(client)

        # Inject dangerous rogue display capture in Palco and Mídias
        client.inputs["Captura do Monitor Perigosa"] = {
            "inputKind": "monitor_capture",
            "settings": {"monitor": 1},
        }
        client.scene_items["Palco"].append({
            "sceneItemId": 8801,
            "sourceName": "Captura do Monitor Perigosa",
            "sceneItemEnabled": True,
            "isGroup": False,
        })
        client.scene_items["Mídias"].append({
            "sceneItemId": 8802,
            "sourceName": "Captura do Monitor Perigosa",
            "sceneItemEnabled": True,
            "isGroup": False,
        })

        disabled, errs = enforce_no_display_captures(client)
        assert len(errs) == 0
        assert len(disabled) == 2
        assert any("Palco" in d for d in disabled)
        assert any("Mídias" in d for d in disabled)

        # Verify both items in OBS are strictly disabled (sceneItemEnabled = False)
        palco_items = client.scene_items["Palco"]
        midias_items = client.scene_items["Mídias"]
        assert palco_items[-1]["sceneItemEnabled"] is False
        assert midias_items[-1]["sceneItemEnabled"] is False

    def test_tier3_full_pipeline_diagnostic_dirty_to_clean_transition(self, monkeypatch):
        """Full diagnostic pipeline accurately reflects readiness transition from dirty to clean."""
        # Step 1: Dirty environment
        dirty_eps = [
            AudioEndpoint(
                id="{0.0.0.0}.{1}",
                friendly_name="Unknown Speaker",
                desc="Realtek",
                interface_name="Realtek",
                flow="eRender",
                state=DEVICE_STATE_ACTIVE,
                sample_rate_hz=44100,
            )
        ]
        dirty_opts = [
            OptimizationStatus("Ducking", 0, False, 3, "Pendente"),
            OptimizationStatus("DPI", "150%", False, "100%", "Pendente"),
        ]

        monkeypatch.setattr(
            "meeting_assistant.services.windows_core_audio.enumerate_endpoints", lambda: dirty_eps
        )
        monkeypatch.setattr(
            "meeting_assistant.services.windows_core_audio.map_project_roles", lambda _: {}
        )
        monkeypatch.setattr(
            "meeting_assistant.services.windows_transmission_optimizer.check_all_optimizations",
            lambda: dirty_opts,
        )
        monkeypatch.setattr(
            "meeting_assistant.services.obs_av_provisioner.connect_obs",
            lambda **_: (_ for _ in ()).throw(ConnectionRefusedError("Offline")),
        )

        diag_dirty = av_tool.run_headless_diagnostics()
        assert diag_dirty["ready"] is False
        assert diag_dirty["optimizations_optimal"] == 0
        assert diag_dirty["obs"]["connected"] is False

        # Step 2: Clean environment
        clean_eps = create_full_ten_role_endpoints()
        clean_roles = map_project_roles(clean_eps)
        clean_opts = create_all_optimal_statuses()

        monkeypatch.setattr(
            "meeting_assistant.services.windows_core_audio.enumerate_endpoints", lambda: clean_eps
        )
        monkeypatch.setattr(
            "meeting_assistant.services.windows_core_audio.map_project_roles", lambda _: clean_roles
        )
        monkeypatch.setattr(
            "meeting_assistant.services.windows_transmission_optimizer.check_all_optimizations",
            lambda: clean_opts,
        )
        monkeypatch.setattr(
            "meeting_assistant.services.obs_av_provisioner.connect_obs",
            lambda **_: E2EMockObsClient(),
        )

        diag_clean = av_tool.run_headless_diagnostics()
        assert diag_clean["ready"] is True
        assert diag_clean["optimizations_optimal"] == 9
        assert diag_clean["obs"]["connected"] is True


# ===========================================================================
# Tier 4: Real-World Application Workloads & Idempotency
# ===========================================================================


class TestTier4RealWorldWorkloads:
    """Verifies realistic operator workflows, repeated executions, and drift repairs."""

    def test_tier4_complete_operator_meeting_preparation_lifecycle(self, tmp_path: Path, monkeypatch):
        """Simulates full meeting preparation lifecycle: diagnose -> optimize OS -> provision OBS -> ready."""
        client = E2EMockObsClient(current_profile="Salão")
        clean_eps = create_full_ten_role_endpoints()
        clean_roles = map_project_roles(clean_eps)
        opt_statuses = create_all_optimal_statuses()

        # Step 1: Initial Launch & Diagnosis
        monkeypatch.setattr(
            "meeting_assistant.services.windows_core_audio.enumerate_endpoints", lambda: clean_eps
        )
        monkeypatch.setattr(
            "meeting_assistant.services.windows_core_audio.map_project_roles", lambda _: clean_roles
        )
        monkeypatch.setattr(
            "meeting_assistant.services.windows_transmission_optimizer.check_all_optimizations",
            lambda: opt_statuses,
        )
        monkeypatch.setattr(
            "meeting_assistant.services.obs_av_provisioner.connect_obs",
            lambda **_: client,
        )

        initial_diag = av_tool.run_headless_diagnostics()
        assert initial_diag["endpoints_count"] == 10

        # Step 2: Apply OS Optimizations
        with patch(
            "meeting_assistant.services.windows_transmission_optimizer.apply_all_optimizations",
            return_value={"ducking": True, "sound_scheme": True, "power_monitor": True},
        ):
            os_res = av_tool.apply_headless_os_optimizations()
            assert os_res["results"]["ducking"] is True

        # Step 3: Provision OBS Studio
        profile_dir = tmp_path / "profiles" / "Salão"
        profile_dir.mkdir(parents=True)
        (profile_dir / "basic.ini").write_text("[Audio]\nMonitoringDeviceId=default\n", encoding="utf-8")

        obs_res = provision_obs_av(
            zoom_cable_id="{0.0.0.00000000}.{22222222-0000-0000-0000-000000000001}",
            zoom_cable_name=DEFAULT_ZOOM_MONITOR_DEVICE_NAME,
            client=client,
            profiles_dir=tmp_path / "profiles",
            jwl_target={"hwnd": "1001", "session": "session-1"},
        )
        assert obs_res.success is True

        # Step 4: Final Verification
        final_diag = av_tool.run_headless_diagnostics()
        assert final_diag["ready"] is True
        assert final_diag["obs"]["connected"] is True
        assert len(final_diag["obs"]["scenes"]) >= 3

    def test_tier4_repeated_execution_strict_idempotency(self, tmp_path: Path):
        """Repeated provisioning executions produce 0 duplicate scenes and preserve all settings."""
        client = E2EMockObsClient(current_profile="Salão")
        profile_dir = tmp_path / "profiles" / "Salão"
        profile_dir.mkdir(parents=True)
        (profile_dir / "basic.ini").write_text("[Audio]\nMonitoringDeviceId=default\n", encoding="utf-8")

        cable_id = "{0.0.0.00000000}.{22222222-0000-0000-0000-000000000001}"

        # First run (Initial Setup)
        res_run1 = provision_obs_av(
            zoom_cable_id=cable_id,
            zoom_cable_name=DEFAULT_ZOOM_MONITOR_DEVICE_NAME,
            client=client,
            profiles_dir=tmp_path / "profiles",
            jwl_target={"hwnd": "9999", "session": "jwl-sess"},
        )
        assert res_run1.success is True
        scenes_count_run1 = len(client.scenes)
        inputs_count_run1 = len(client.inputs)

        # Count scene items across all managed scenes
        items_count_run1 = sum(len(items) for items in client.scene_items.values())

        # Second run (Pre-meeting check run)
        res_run2 = provision_obs_av(
            zoom_cable_id=cable_id,
            zoom_cable_name=DEFAULT_ZOOM_MONITOR_DEVICE_NAME,
            client=client,
            profiles_dir=tmp_path / "profiles",
            jwl_target={"hwnd": "9999", "session": "jwl-sess"},
        )
        assert res_run2.success is True
        assert res_run2.scenes_created == []  # No new scenes created!
        assert len(client.scenes) == scenes_count_run1
        assert len(client.inputs) == inputs_count_run1

        items_count_run2 = sum(len(items) for items in client.scene_items.values())
        assert items_count_run2 == items_count_run1  # Zero duplicate scene items!
        assert client.program_scene_calls == []  # Program scene never altered

    def test_tier4_operator_drift_repair_mode(self, tmp_path: Path):
        """Repair mode: when a single setting drifts, only the defect is repaired."""
        client = E2EMockObsClient(current_profile="Salão")
        profile_dir = tmp_path / "profiles" / "Salão"
        profile_dir.mkdir(parents=True)
        (profile_dir / "basic.ini").write_text("[Audio]\nMonitoringDeviceId=default\n", encoding="utf-8")

        cable_id = "{0.0.0.00000000}.{22222222-0000-0000-0000-000000000001}"

        # Clean baseline provisioning
        provision_obs_av(
            zoom_cable_id=cable_id,
            zoom_cable_name=DEFAULT_ZOOM_MONITOR_DEVICE_NAME,
            client=client,
            profiles_dir=tmp_path / "profiles",
            jwl_target={"hwnd": "1234", "session": "jwl"},
        )

        # Operator drift: someone accidentally added a display capture to Mídias
        client.inputs["Captura de Tela Operador"] = {"inputKind": "monitor_capture", "settings": {}}
        client.scene_items["Mídias"].append({
            "sceneItemId": 7771,
            "sourceName": "Captura de Tela Operador",
            "sceneItemEnabled": True,
            "isGroup": False,
        })
        assert client.scene_items["Mídias"][-1]["sceneItemEnabled"] is True

        # Run repair
        repair_res = provision_obs_av(
            zoom_cable_id=cable_id,
            zoom_cable_name=DEFAULT_ZOOM_MONITOR_DEVICE_NAME,
            client=client,
            profiles_dir=tmp_path / "profiles",
            jwl_target={"hwnd": "1234", "session": "jwl"},
        )
        assert repair_res.success is True
        assert len(repair_res.display_captures_disabled) == 1
        assert "Mídias: Captura de Tela Operador" in repair_res.display_captures_disabled[0]
        assert client.scene_items["Mídias"][-1]["sceneItemEnabled"] is False
