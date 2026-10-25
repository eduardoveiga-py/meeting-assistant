"""Empirical Adversarial Stress Testing for Meeting Assistant AV Setup.

Challenger 2 Test Suite covering:
1. Adversarial Display Capture Infiltration:
   - Nested groups, nested scenes, deeply nested trees, cyclic references, obfuscated names.
   - Rigorous verification of enforce_no_display_captures() and assert_safe_media().
2. Audio Mix-Minus Infiltration & Echo Prevention:
   - Zoom process audio monitoring type strictly enforced as OBS_MONITORING_TYPE_NONE.
   - Track isolation (Tracks 1-6 False) preventing audio bleed into recording/stream.
   - JW Library process audio starts unmonitored (MONITOR_NONE) and muted.
3. OBS Provisioning Resilience & Failure Injection:
   - Socket timeouts, connection dropped mid-provisioning.
   - Unexpected OBSSDKRequestError codes (601, 700, 404, 500).
   - Missing profile paths, corrupted basic.ini, read-only basic.ini.
   - Invariant: SetCurrentProgramScene is NEVER invoked under any error conditions.
4. CLI and GUI Concurrency & Boundary Tests:
   - scripts/av_setup_tool.py invalid arguments, port boundaries, headless diagnostics concurrency.
   - MainWindow._open_av_setup rapid multi-clicks, reopen lifecycle, and background worker safety.
"""

from __future__ import annotations

import configparser
import json
import os
import stat
import sys
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from obsws_python.error import OBSSDKRequestError

import scripts.av_setup_tool as av_tool
from meeting_assistant.services.obs_av_provisioner import (
    JWL_AUDIO_SOURCE,
    MONITOR_NONE,
    PROCESS_AUDIO_KIND,
    ZOOM_AUDIO_SOURCE,
    enforce_no_display_captures,
    provision_jwl_hwnd_capture,
    provision_obs_av,
    provision_process_audio,
    provision_scenes,
    set_obs_monitoring_device,
)
from meeting_assistant.services.obs_capture_safety import assert_safe_media
from meeting_assistant.ui.av_setup_dialog import AVSetupWindow
from meeting_assistant.ui.main_window import MainWindow

# ===========================================================================
# Adversarial Mock OBS WebSocket Protocol Client
# ===========================================================================

class AdversarialMockObsClient:
    """Stateful mock of obs-websocket v5 with failure injection hooks."""

    def __init__(self, current_profile: str = "Salão Padrão"):
        self.current_profile = current_profile
        self.scenes: list[str] = []
        self.scene_items: dict[str, list[dict[str, Any]]] = {}  # container -> list of items
        self.inputs: dict[str, dict[str, Any]] = {}
        self.input_monitor_types: dict[str, str] = {}
        self.input_tracks: dict[str, dict[str, bool]] = {}
        self.input_mutes: dict[str, bool] = {}
        self.profile_parameters: dict[tuple[str, str], str] = {}
        self.program_scene_calls: list[str] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.item_id_counter = 1000

        # Failure injection triggers: request_name -> Exception or callable
        self.fault_injections: dict[str, Any] = {}

    def inject_fault(self, request_name: str, exc_or_callable: Any) -> None:
        self.fault_injections[request_name] = exc_or_callable

    def clear_faults(self) -> None:
        self.fault_injections.clear()

    def send(self, request: str, data: dict[str, Any] | None = None, raw: bool = True) -> dict[str, Any]:
        data = data or {}
        self.calls.append((request, dict(data)))

        # Trigger faults if injected
        if request in self.fault_injections:
            fault = self.fault_injections[request]
            if isinstance(fault, Exception):
                raise fault
            elif callable(fault):
                fault(request, data)

        if request == "GetVersion":
            return {"obsVersion": "31.0.3", "obsWebSocketVersion": "5.5.0"}

        elif request == "GetProfileList":
            return {"currentProfileName": self.current_profile, "profiles": [self.current_profile]}

        elif request == "SetProfileParameter":
            cat = data.get("parameterCategory", "")
            name = data.get("parameterName", "")
            val = data.get("parameterValue", "")
            self.profile_parameters[(cat, name)] = val
            return {}

        elif request == "GetProfileParameter":
            cat = data.get("parameterCategory", "")
            name = data.get("parameterName", "")
            return {"parameterValue": self.profile_parameters.get((cat, name), "")}

        elif request == "GetSceneList":
            return {
                "currentProgramSceneName": self.scenes[0] if self.scenes else "",
                "scenes": [{"sceneName": s} for s in self.scenes],
            }

        elif request == "CreateScene":
            name = data["sceneName"]
            if name not in self.scenes:
                self.scenes.append(name)
                self.scene_items.setdefault(name, [])
            return {}

        elif request == "SetCurrentProgramScene":
            self.program_scene_calls.append(data.get("sceneName", ""))
            return {}

        elif request in ("GetSceneItemList", "GetGroupSceneItemList"):
            scene = data["sceneName"]
            return {"sceneItems": list(self.scene_items.get(scene, []))}

        elif request == "CreateSceneItem":
            scene = data["sceneName"]
            source = data["sourceName"]
            self.item_id_counter += 1
            item = {
                "sceneItemId": self.item_id_counter,
                "sourceName": source,
                "sceneItemEnabled": data.get("sceneItemEnabled", True),
                "isGroup": data.get("isGroup", False),
            }
            self.scene_items.setdefault(scene, []).append(item)
            return {"sceneItemId": self.item_id_counter}

        elif request == "SetSceneItemEnabled":
            scene = data["sceneName"]
            item_id = data["sceneItemId"]
            enabled = data["sceneItemEnabled"]
            for item in self.scene_items.get(scene, []):
                if item["sceneItemId"] == item_id:
                    item["sceneItemEnabled"] = enabled
                    break
            return {}

        elif request == "GetInputList":
            return {
                "inputs": [
                    {"inputName": name, "inputKind": info["inputKind"]}
                    for name, info in self.inputs.items()
                ]
            }

        elif request == "CreateInput":
            name = data["inputName"]
            kind = data["inputKind"]
            scene = data["sceneName"]
            if name in self.inputs:
                raise OBSSDKRequestError("CreateInput", 601, f"Resource '{name}' already exists")
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

        elif request == "SetInputSettings":
            name = data["inputName"]
            settings = data.get("inputSettings", {})
            if name in self.inputs:
                if data.get("overlay", False):
                    self.inputs[name]["settings"].update(settings)
                else:
                    self.inputs[name]["settings"] = settings
            return {}

        elif request == "GetInputAudioMonitorType":
            name = data["inputName"]
            return {"monitorType": self.input_monitor_types.get(name, MONITOR_NONE)}

        elif request == "SetInputAudioMonitorType":
            name = data["inputName"]
            self.input_monitor_types[name] = data["monitorType"]
            return {}

        elif request == "GetInputAudioTracks":
            name = data["inputName"]
            return {"inputAudioTracks": self.input_tracks.get(name, {str(i): False for i in range(1, 7)})}

        elif request == "SetInputAudioTracks":
            name = data["inputName"]
            self.input_tracks[name] = data["inputAudioTracks"]
            return {}

        elif request == "GetInputMute":
            name = data["inputName"]
            return {"inputMuted": self.input_mutes.get(name, False)}

        elif request == "SetInputMute":
            name = data["inputName"]
            self.input_mutes[name] = data["inputMuted"]
            return {}

        elif request == "GetVirtualCamStatus":
            return {"outputActive": False}

        elif request == "StartVirtualCam":
            return {}

        elif request == "StopVirtualCam":
            return {}

        return {}


# ===========================================================================
# 1. ADVERSARIAL DISPLAY CAPTURE INFILTRATION TESTS
# ===========================================================================

class TestDisplayCaptureInfiltration:
    """Stress tests attempting to sneak monitor_capture into managed scenes."""

    def test_infiltrate_monitor_capture_via_nested_group(self):
        """Sneak a monitor_capture inside a group within Mídias; verify enforcement disables group."""
        client = AdversarialMockObsClient()
        provision_scenes(client)

        # Create a group item in Mídias
        group_name = "Innocent Group"
        client.scene_items["Mídias"].append({
            "sceneItemId": 2001,
            "sourceName": group_name,
            "sceneItemEnabled": True,
            "isGroup": True,
        })
        # Put monitor_capture inside the group
        client.inputs["Hidden Display"] = {"inputKind": "monitor_capture", "settings": {}}
        client.scene_items[group_name] = [{
            "sceneItemId": 2002,
            "sourceName": "Hidden Display",
            "sceneItemEnabled": True,
            "isGroup": False,
        }]

        # Run enforce_no_display_captures
        disabled, errors = enforce_no_display_captures(client)
        assert not errors
        assert any("Mídias: Innocent Group" in d for d in disabled)

        # The group item in Mídias must now be disabled
        group_in_midias = next(i for i in client.scene_items["Mídias"] if i["sourceName"] == group_name)
        assert group_in_midias["sceneItemEnabled"] is False

        # Invariant: source was NOT deleted from inputs
        assert "Hidden Display" in client.inputs

    def test_infiltrate_monitor_capture_via_nested_scene(self):
        """Embed a subscene containing monitor_capture inside Palco."""
        client = AdversarialMockObsClient()
        provision_scenes(client)

        subscene_name = "Sub Scene Palco"
        client.scenes.append(subscene_name)
        client.scene_items[subscene_name] = []

        # Nest subscene in Palco
        client.scene_items["Palco"].append({
            "sceneItemId": 2010,
            "sourceName": subscene_name,
            "sceneItemEnabled": True,
            "isGroup": False,
        })
        # Put monitor_capture in subscene
        client.inputs["Sneaky Screen"] = {"inputKind": "monitor_capture", "settings": {}}
        client.scene_items[subscene_name].append({
            "sceneItemId": 2011,
            "sourceName": "Sneaky Screen",
            "sceneItemEnabled": True,
            "isGroup": False,
        })

        disabled, errors = enforce_no_display_captures(client)
        assert not errors
        assert any("Palco: Sub Scene Palco" in d for d in disabled)
        subscene_in_palco = next(i for i in client.scene_items["Palco"] if i["sourceName"] == subscene_name)
        assert subscene_in_palco["sceneItemEnabled"] is False

    def test_infiltrate_monitor_capture_deeply_nested_three_levels(self):
        """Scene -> Nested Scene -> Group -> monitor_capture (3 levels deep)."""
        client = AdversarialMockObsClient()
        provision_scenes(client)

        client.scenes.append("Level1_Scene")
        client.scene_items["Level1_Scene"] = []

        client.scene_items["Texto do Ano"].append({
            "sceneItemId": 3001,
            "sourceName": "Level1_Scene",
            "sceneItemEnabled": True,
            "isGroup": False,
        })
        client.scene_items["Level1_Scene"].append({
            "sceneItemId": 3002,
            "sourceName": "Level2_Group",
            "sceneItemEnabled": True,
            "isGroup": True,
        })
        client.inputs["Deep Screen"] = {"inputKind": "monitor_capture", "settings": {}}
        client.scene_items["Level2_Group"] = [{
            "sceneItemId": 3003,
            "sourceName": "Deep Screen",
            "sceneItemEnabled": True,
            "isGroup": False,
        }]

        disabled, errors = enforce_no_display_captures(client)
        assert not errors
        assert any("Texto do Ano: Level1_Scene" in d for d in disabled)
        assert client.scene_items["Texto do Ano"][-1]["sceneItemEnabled"] is False

    @pytest.mark.parametrize("obfuscated_name", [
        "Webcam 1",
        "Camera Canon",
        "Microfone USB",
        "Texto do Ano Fundo",
        "jwlibrary.exe",
        "Zoom Meeting Video",
        "   ",
        "Screen\u200bZeroWidth",
        "127.0.0.1",
    ])
    def test_infiltrate_obfuscated_source_names(self, obfuscated_name):
        """Obfuscated names with inputKind == monitor_capture must always be detected and disabled."""
        client = AdversarialMockObsClient()
        provision_scenes(client)

        client.inputs[obfuscated_name] = {"inputKind": "monitor_capture", "settings": {}}
        client.scene_items["Mídias"].append({
            "sceneItemId": 4001,
            "sourceName": obfuscated_name,
            "sceneItemEnabled": True,
            "isGroup": False,
        })

        disabled, errors = enforce_no_display_captures(client)
        assert not errors
        assert any(f"Mídias: {obfuscated_name}" in d for d in disabled)
        assert client.scene_items["Mídias"][-1]["sceneItemEnabled"] is False

    def test_circular_scene_references_terminates_gracefully(self):
        """Cyclic scene embedding (Scene A -> Scene B -> Scene A) must terminate without recursion error."""
        client = AdversarialMockObsClient()
        provision_scenes(client)

        client.scenes.extend(["CycleA", "CycleB"])
        client.scene_items["CycleA"] = [{
            "sceneItemId": 5001,
            "sourceName": "CycleB",
            "sceneItemEnabled": True,
            "isGroup": False,
        }]
        client.scene_items["CycleB"] = [{
            "sceneItemId": 5002,
            "sourceName": "CycleA",
            "sceneItemEnabled": True,
            "isGroup": False,
        }]

        # Add monitor_capture into CycleB
        client.inputs["CycleMonitor"] = {"inputKind": "monitor_capture", "settings": {}}
        client.scene_items["CycleB"].append({
            "sceneItemId": 5003,
            "sourceName": "CycleMonitor",
            "sceneItemEnabled": True,
            "isGroup": False,
        })

        # Add CycleA into Mídias
        client.scene_items["Mídias"].append({
            "sceneItemId": 5004,
            "sourceName": "CycleA",
            "sceneItemEnabled": True,
            "isGroup": False,
        })

        # Should complete without RecursionError and disable CycleA in Mídias
        disabled, errors = enforce_no_display_captures(client)
        assert not errors
        assert any("Mídias: CycleA" in d for d in disabled)
        assert client.scene_items["Mídias"][-1]["sceneItemEnabled"] is False

    def test_assert_safe_media_blocks_active_display_capture(self):
        """assert_safe_media raises ValueError if a display_capture remains active in Mídias."""
        client = AdversarialMockObsClient()
        provision_scenes(client)
        provision_jwl_hwnd_capture(client, scene="Mídias")

        # Infiltrate active monitor_capture
        client.inputs["Desktop Rogue"] = {"inputKind": "monitor_capture", "settings": {}}
        client.scene_items["Mídias"].append({
            "sceneItemId": 6001,
            "sourceName": "Desktop Rogue",
            "sceneItemEnabled": True,
            "isGroup": False,
        })

        with pytest.raises(ValueError, match="Captura de monitor ativa em Mídias"):
            assert_safe_media(client, "Mídias")

    def test_assert_safe_media_blocks_rogue_window_capture(self):
        """assert_safe_media raises ValueError if an unauthorized window_capture is enabled in Mídias."""
        client = AdversarialMockObsClient()
        provision_scenes(client)
        provision_jwl_hwnd_capture(client, scene="Mídias")

        # Infiltrate active window_capture
        client.inputs["Rogue Window"] = {"inputKind": "window_capture", "settings": {}}
        client.scene_items["Mídias"].append({
            "sceneItemId": 6002,
            "sourceName": "Rogue Window",
            "sceneItemEnabled": True,
            "isGroup": False,
        })

        with pytest.raises(ValueError, match="Outra captura de janela/jogo permanece ativa em Mídias"):
            assert_safe_media(client, "Mídias")


# ===========================================================================
# 2. AUDIO MIX-MINUS INFILTRATION & ECHO PREVENTION TESTS
# ===========================================================================

class TestAudioMixMinusInfiltration:
    """Adversarial testing of audio mix-minus and monitoring type constraints."""

    def test_zoom_audio_monitor_type_overwrites_any_adversarial_setting(self):
        """Pre-set Zoom process audio to MONITOR_AND_OUTPUT; verify provisioning forces MONITOR_NONE."""
        client = AdversarialMockObsClient()
        provision_scenes(client)

        # Adversarially configure Zoom audio to echo
        client.inputs[ZOOM_AUDIO_SOURCE] = {
            "inputKind": PROCESS_AUDIO_KIND,
            "settings": {"window": "Qualquer:Qualquer:zoom.exe"},
        }
        client.input_monitor_types[ZOOM_AUDIO_SOURCE] = "OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT"
        client.input_tracks[ZOOM_AUDIO_SOURCE] = {
            "1": True,
            "2": True,
            "3": True,
            "4": True,
            "5": True,
            "6": True,
        }

        configured, errors = provision_process_audio(client)
        assert not errors
        assert ZOOM_AUDIO_SOURCE in configured

        # Invariant: Zoom monitor type MUST be strictly OBS_MONITORING_TYPE_NONE
        assert client.input_monitor_types[ZOOM_AUDIO_SOURCE] == MONITOR_NONE

    def test_zoom_audio_track_isolation_enforced(self):
        """Zoom audio must have tracks 1-6 set to False to prevent recording bleed."""
        client = AdversarialMockObsClient()
        provision_scenes(client)

        provision_process_audio(client)

        tracks = client.input_tracks[ZOOM_AUDIO_SOURCE]
        for trk in ("1", "2", "3", "4", "5", "6"):
            assert tracks[trk] is False, f"Track {trk} must be False to prevent audio bleed!"

    def test_jwl_audio_monitor_starts_unmonitored_and_isolated(self):
        """JW Library audio newly created must start MONITOR_NONE, muted, and tracks 1-6 False."""
        client = AdversarialMockObsClient()
        provision_scenes(client)

        provision_process_audio(client)

        assert client.input_monitor_types[JWL_AUDIO_SOURCE] == MONITOR_NONE
        assert client.input_mutes[JWL_AUDIO_SOURCE] is True
        tracks = client.input_tracks[JWL_AUDIO_SOURCE]
        for trk in ("1", "2", "3", "4", "5", "6"):
            assert tracks[trk] is False

    def test_repeated_provisioning_preserves_mix_minus_invariants(self):
        """Run provision_process_audio repeatedly 10 times; invariants must never drift."""
        client = AdversarialMockObsClient()
        provision_scenes(client)

        for _ in range(10):
            configured, errors = provision_process_audio(client)
            assert not errors
            assert client.input_monitor_types[ZOOM_AUDIO_SOURCE] == MONITOR_NONE
            assert client.input_monitor_types[JWL_AUDIO_SOURCE] == MONITOR_NONE
            assert client.input_tracks[ZOOM_AUDIO_SOURCE]["6"] is False
            assert client.input_tracks[ZOOM_AUDIO_SOURCE]["1"] is False


# ===========================================================================
# 3. OBS PROVISIONING RESILIENCE & FAILURE INJECTION TESTS
# ===========================================================================

class TestOBSProvisioningResilience:
    """Stress tests covering unexpected errors, network timeouts, and disk failures."""

    def test_socket_timeout_on_connection(self):
        """Simulate socket timeout during initial connection."""
        with patch(
            "meeting_assistant.services.obs_av_provisioner.connect_obs",
            side_effect=TimeoutError("Connection timed out after 3.0s"),
        ):
            result = provision_obs_av(host="10.255.255.1", port=4455, client=None)
            assert result.success is False
            assert any("timed out" in err or "Não foi possível conectar" in err for err in result.errors)

    def test_connection_dropped_mid_provisioning(self):
        """Simulate connection drop after scenes are created."""
        client = AdversarialMockObsClient()

        # Inject failure on SetInputAudioTracks
        client.inject_fault("SetInputAudioTracks", ConnectionResetError("Connection reset by peer"))

        result = provision_obs_av(
            zoom_cable_id="{CABLE-GUID}",
            client=client,
        )
        assert result.success is False
        assert any("Connection reset" in err or "áudio de processo" in err for err in result.errors)

    def test_unexpected_obs_sdk_request_error_codes(self):
        """Inject unexpected OBS SDK error code (e.g. 700 internal error)."""
        client = AdversarialMockObsClient()
        err = OBSSDKRequestError("CreateScene", 700, "Internal Server Error in OBS")
        client.inject_fault("CreateScene", err)

        result = provision_obs_av(client=client)
        assert result.success is False
        assert any("700" in err or "Internal Server Error" in err for err in result.errors)

    def test_missing_and_nonexistent_profiles_dir(self, tmp_path: Path):
        """Profiles dir pointing to non-existent folder should gracefully fall back without crash."""
        client = AdversarialMockObsClient()
        nonexistent = tmp_path / "does_not_exist_profiles"

        ok, msg = set_obs_monitoring_device(
            client=client,
            device_id="{TEST-GUID}",
            device_name="V-OUT Zoom (Envio)",
            profiles_dir=nonexistent,
        )
        # Succeeded via WebSocket even if disk path doesn't exist
        assert ok is True
        assert "V-OUT Zoom (Envio)" in msg

    def test_corrupted_basic_ini_handling(self, tmp_path: Path):
        """basic.ini contains invalid non-INI binary data."""
        profile_dir = tmp_path / "profiles" / "Salão"
        profile_dir.mkdir(parents=True)
        ini_file = profile_dir / "basic.ini"
        ini_file.write_bytes(b"\x00\xff\xfe\x00INVALID_HEADER_GARBAGE\x01\x02")

        client = AdversarialMockObsClient(current_profile="Salão")
        ok, _ = set_obs_monitoring_device(
            client=client,
            device_id="{TEST-GUID}",
            device_name="V-OUT Zoom (Envio)",
            profiles_dir=tmp_path / "profiles",
        )
        # Should catch configparser error and return success via WebSocket
        assert ok is True

    def test_read_only_basic_ini_file(self, tmp_path: Path):
        """basic.ini is read-only (PermissionError on open)."""
        profile_dir = tmp_path / "profiles" / "Salão"
        profile_dir.mkdir(parents=True)
        ini_file = profile_dir / "basic.ini"

        config = configparser.ConfigParser()
        config["General"] = {"Name": "Salão"}
        with open(ini_file, "w", encoding="utf-8-sig") as f:
            config.write(f)

        # Mark read-only
        os.chmod(ini_file, stat.S_IREAD)

        try:
            client = AdversarialMockObsClient(current_profile="Salão")
            ok, _ = set_obs_monitoring_device(
                client=client,
                device_id="{TEST-GUID}",
                device_name="V-OUT Zoom (Envio)",
                profiles_dir=tmp_path / "profiles",
            )
            assert ok is True  # Succeeded via WebSocket
        finally:
            # Restore write permission for cleanup
            os.chmod(ini_file, stat.S_IWRITE)

    def test_program_scene_is_never_changed_under_any_failure(self):
        """Rigorous invariant check: SetCurrentProgramScene is NEVER invoked."""
        client = AdversarialMockObsClient()
        client.inject_fault("CreateInput", OBSSDKRequestError("CreateInput", 500, "Simulated fatal error"))

        _ = provision_obs_av(client=client)
        assert client.program_scene_calls == [], "SetCurrentProgramScene was violated!"


# ===========================================================================
# 4. CLI AND GUI CONCURRENCY & BOUNDARY TESTS
# ===========================================================================

class TestCLIAndGUIBoundaryAndConcurrency:
    """Stress tests on CLI tool scripts and GUI dialog lifecycle."""

    def test_cli_invalid_arguments_exit_code(self):
        """Invoking av_setup_tool with invalid flags exits cleanly with code 2."""
        with patch.object(sys, "argv", ["av_setup_tool.py", "--completely-invalid-flag"]):
            with pytest.raises(SystemExit) as excinfo:
                av_tool.main()
            assert excinfo.value.code == 2

    def test_cli_diagnose_json_output_with_offline_obs(self, capsys):
        """--diagnose --json produces valid JSON even when OBS is completely offline."""
        with patch.object(
            sys, "argv", ["av_setup_tool.py", "--diagnose", "--json", "--port", "65432"]
        ):
            with patch("meeting_assistant.services.windows_core_audio.enumerate_endpoints", return_value=[]):
                code = av_tool.main()
                assert code == 0

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, dict)
        assert data["obs"]["connected"] is False
        assert data["ready"] is False
        assert "optimizations" in data

    def test_run_headless_diagnostics_thread_concurrency(self):
        """Simultaneous calls to run_headless_diagnostics across 10 threads must not race."""
        results = []
        errors = []

        def worker():
            try:
                diag = av_tool.run_headless_diagnostics(obs_port=65432)
                results.append(diag)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=35)

        assert not errors
        assert len(results) == 10
        for r in results:
            assert isinstance(r, dict)
            assert "ready" in r

    def test_main_window_open_av_setup_rapid_clicks(self, monkeypatch):
        """Rapidly clicking _open_av_setup 20 times creates exactly 1 AVSetupWindow instance."""
        from PySide6.QtWidgets import QApplication

        _ = QApplication.instance() or QApplication([])

        created_instances = []

        class MockAVSetupDialog:
            def __init__(self, parent=None, settings=None):
                created_instances.append(self)
                self.destroyed = MagicMock()

            def show(self): pass
            def raise_(self): pass
            def activateWindow(self): pass

        monkeypatch.setattr(
            "meeting_assistant.ui.av_setup_dialog.AVSetupWindow", MockAVSetupDialog
        )

        mock_main = MagicMock(spec=MainWindow)
        mock_main._av_setup_window = None
        mock_main.settings = MagicMock()

        # Bind the real method logic to mock_main
        bound_open = MainWindow._open_av_setup.__get__(mock_main, MainWindow)

        # 20 rapid invocations
        for _ in range(20):
            bound_open()

        assert len(created_instances) == 1
        assert mock_main._av_setup_window is created_instances[0]

    def test_main_window_open_av_setup_reopen_after_destroyed(self, monkeypatch):
        """After dialog is destroyed, clicking _open_av_setup creates a fresh new instance."""
        created_instances = []

        class MockAVSetupDialog:
            def __init__(self, parent=None, settings=None):
                created_instances.append(self)
                self._destroyed_callback = None
                self.destroyed = MagicMock()
                self.destroyed.connect = lambda cb: setattr(self, "_destroyed_callback", cb)

            def show(self): pass
            def raise_(self): pass
            def activateWindow(self): pass

            def trigger_destroy(self):
                if self._destroyed_callback:
                    self._destroyed_callback()

        monkeypatch.setattr(
            "meeting_assistant.ui.av_setup_dialog.AVSetupWindow", MockAVSetupDialog
        )

        mock_main = MagicMock(spec=MainWindow)
        mock_main._av_setup_window = None
        mock_main.settings = MagicMock()

        bound_open = MainWindow._open_av_setup.__get__(mock_main, MainWindow)

        # Open 1
        bound_open()
        assert len(created_instances) == 1
        first_instance = created_instances[0]

        # Destroy
        first_instance.trigger_destroy()
        assert mock_main._av_setup_window is None

        # Open 2
        bound_open()
        assert len(created_instances) == 2
        assert mock_main._av_setup_window is created_instances[1]

    def test_av_setup_dialog_close_event_worker_graceful_cleanup(self):
        """AVSetupDialog.closeEvent cancels running workers without hang or crash."""
        from PySide6.QtCore import QThread
        from PySide6.QtGui import QCloseEvent
        from PySide6.QtWidgets import QApplication

        _ = QApplication.instance() or QApplication([])

        dialog = AVSetupWindow(auto_refresh=False)
        try:
            # Simulate an active background worker
            mock_worker = MagicMock(spec=QThread)
            mock_worker.isRunning.return_value = True
            dialog._active_workers.append(mock_worker)

            event = QCloseEvent()
            dialog.closeEvent(event)

            mock_worker.requestInterruption.assert_called_once()
            mock_worker.wait.assert_called_once_with(400)
            assert event.isAccepted()
        finally:
            dialog.close()
