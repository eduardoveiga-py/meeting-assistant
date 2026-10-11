"""Unit and integration tests for AV Setup Window, CLI tool, and app integration."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication

import scripts.av_setup_tool as av_tool
from meeting_assistant.core.state import AppState
from meeting_assistant.services.obs_av_provisioner import OBSProvisionResult
from meeting_assistant.services.settings import AppSettings, SettingsService
from meeting_assistant.services.windows_core_audio import (
    ROLE_BLACKMAGIC,
    ROLE_MESA_OUT_P2,
    ROLE_V_MIC_WAPP,
    ROLE_V_MIC_ZOOM,
    ROLE_V_OUT_WAPP,
    ROLE_V_OUT_ZOOM,
    ROLE_WEBCAM_MIC,
    AudioEndpoint,
)
from meeting_assistant.services.windows_transmission_optimizer import OptimizationStatus
from meeting_assistant.ui.av_setup_dialog import AVSetupDialog, AVSetupWindow
from meeting_assistant.ui.main_window import MainWindow
from meeting_assistant.ui.setup_assistant_dialog import SetupAssistantDialog


def _make_sample_endpoints() -> tuple[list[AudioEndpoint], dict[str, AudioEndpoint]]:
    eps = [
        AudioEndpoint(
            id="{0.0.0.00000000}.{cable_a_render}",
            friendly_name="Cabo Virtual A - Entrada Zoom",
            desc="VB-Audio Cable A",
            interface_name="VB-Audio Cable A",
            flow="eRender",
            state=1,
            sample_rate_hz=48000,
            detected_role=ROLE_V_OUT_ZOOM,
        ),
        AudioEndpoint(
            id="{0.0.1.00000000}.{cable_a_capture}",
            friendly_name="Cabo Virtual A - Saída Zoom",
            desc="VB-Audio Cable A",
            interface_name="VB-Audio Cable A",
            flow="eCapture",
            state=1,
            sample_rate_hz=48000,
            detected_role=ROLE_V_MIC_ZOOM,
        ),
        AudioEndpoint(
            id="{0.0.0.00000000}.{cable_b_render}",
            friendly_name="Cabo Virtual B - Entrada WhatsApp",
            desc="VB-Audio Cable B",
            interface_name="VB-Audio Cable B",
            flow="eRender",
            state=1,
            sample_rate_hz=48000,
            detected_role=ROLE_V_OUT_WAPP,
        ),
        AudioEndpoint(
            id="{0.0.1.00000000}.{cable_b_capture}",
            friendly_name="Cabo Virtual B - Saída WhatsApp",
            desc="VB-Audio Cable B",
            interface_name="VB-Audio Cable B",
            flow="eCapture",
            state=1,
            sample_rate_hz=48000,
            detected_role=ROLE_V_MIC_WAPP,
        ),
        AudioEndpoint(
            id="{0.0.0.00000000}.{speakers_p2}",
            friendly_name="Alto-falantes (Realtek High Definition Audio)",
            desc="Speakers",
            interface_name="Realtek Audio",
            flow="eRender",
            state=1,
            sample_rate_hz=48000,
            detected_role=ROLE_MESA_OUT_P2,
        ),
        AudioEndpoint(
            id="{0.0.0.00000000}.{bm_hdmi}",
            friendly_name="Blackmagic Audio",
            desc="Blackmagic",
            interface_name="Blackmagic HDMI",
            flow="eRender",
            state=1,
            sample_rate_hz=48000,
            detected_role=ROLE_BLACKMAGIC,
        ),
        AudioEndpoint(
            id="{0.0.1.00000000}.{webcam_mic}",
            friendly_name="Microfone (USB Webcam)",
            desc="Webcam",
            interface_name="USB Webcam",
            flow="eCapture",
            state=1,
            sample_rate_hz=44100,
            detected_role=ROLE_WEBCAM_MIC,
        ),
    ]
    roles = {ep.detected_role: ep for ep in eps if ep.detected_role}
    return eps, roles


def _make_sample_optimizations() -> list[OptimizationStatus]:
    return [
        OptimizationStatus("Ducking de Comunicações", 3, True, 3, "Não fazer nada"),
        OptimizationStatus("Esquema de Sons do Sistema", ".None", True, ".None", "Sem som"),
        OptimizationStatus("Som de Inicialização do Windows", 1, True, 1, "Desativado"),
        OptimizationStatus("Plano de Energia (Tela AC)", 0, True, 0, "Nunca desligar tela"),
        OptimizationStatus("Plano de Energia (Suspensão AC)", 0, True, 0, "Nunca suspender"),
        OptimizationStatus("Modo Exclusivo de Áudio", 0, True, 0, "Desativado nos endpoints"),
        OptimizationStatus("Aprimoramentos de Sinal (APO)", 1, True, 1, "Desativados"),
        OptimizationStatus("Taxa de Amostragem (48 kHz)", "48000 Hz", True, "48000 Hz", "Conforme"),
        OptimizationStatus("Escala DPI do Monitor 2", "100%", True, "100%", "Conforme"),
    ]


# ---------------------------------------------------------------------------
# Test AVSetupDialog Initialization & UI Structure
# ---------------------------------------------------------------------------


def test_av_setup_window_initialization(monkeypatch):
    """Verify AVSetupDialog / AVSetupWindow constructs with 5 tabs and correct titles."""
    eps, roles = _make_sample_endpoints()
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.enumerate_endpoints", lambda: eps)
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.map_project_roles", lambda _: roles)
    monkeypatch.setattr(
        "meeting_assistant.ui.av_setup_dialog.check_all_optimizations", _make_sample_optimizations
    )

    window = AVSetupWindow(auto_refresh=False)
    try:
        assert window.tabs.count() == 5
        tab_titles = [window.tabs.tabText(i) for i in range(5)]
        assert any("Dispositivos de Áudio" in t for t in tab_titles)
        assert any("Otimizações Windows 11" in t for t in tab_titles)
        assert any("Roteamento & Câmeras" in t for t in tab_titles)
        assert any("OBS Studio" in t for t in tab_titles)
        assert any("Diagnóstico & Relatório" in t for t in tab_titles)
        assert isinstance(window, AVSetupDialog)
    finally:
        window.close()


def test_audio_tab_population(monkeypatch):
    """Verify table population with sample endpoints, rates and roles."""
    eps, roles = _make_sample_endpoints()
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.enumerate_endpoints", lambda: eps)
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.map_project_roles", lambda _: roles)

    window = AVSetupWindow(auto_refresh=False)
    try:
        window.refresh_audio_devices(blocking=True)
        assert window.audio_table.rowCount() == len(eps)

        # Check first row (Cable A render)
        tipo = window.audio_table.item(0, 0).text()
        assert "Reprodução" in tipo
        name = window.audio_table.item(0, 1).text()
        assert "Cabo Virtual A - Entrada Zoom" in name
        std_name = window.audio_table.item(0, 2).text()
        assert ROLE_V_OUT_ZOOM in std_name
        rate = window.audio_table.item(0, 3).text()
        assert "48000 Hz" in rate

        # Check webcam row rate
        webcam_row = len(eps) - 1
        wc_rate = window.audio_table.item(webcam_row, 3).text()
        assert "44100 Hz" in wc_rate
    finally:
        window.close()


def test_os_tab_population(monkeypatch):
    """Verify OS transmission optimization checklist cards populate."""
    opts = _make_sample_optimizations()
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.check_all_optimizations", lambda: opts)

    window = AVSetupWindow(auto_refresh=False)
    try:
        window.refresh_os_optimizations(blocking=True)
        # checklist layout has N cards + 1 stretch
        assert window.os_checklist_layout.count() >= len(opts)
    finally:
        window.close()


def test_routing_tab_population(monkeypatch):
    """Verify routing and camera labels update properly."""
    routes = {
        "Zoom.exe": {"status": "configured", "details": "Correto", "active_sessions": [{"pid": 1234}]},
        "WhatsApp.exe": {"status": "active", "details": "Conforme", "active_sessions": [{"pid": 5678}]},
    }
    cams = {
        "obs_virtual_cam": {"active": True, "available": True, "error": None},
        "native_virtual_cam": {"supported": True, "reason": "OK", "installed": True},
    }
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.check_app_routes", lambda: routes)
    monkeypatch.setattr(
        "meeting_assistant.ui.av_setup_dialog.get_virtual_cam_status",
        lambda obs_client=None: cams,
    )

    window = AVSetupWindow(auto_refresh=False)
    try:
        window.refresh_routing_and_cameras(blocking=True)
        assert "CONFIGURED" in window.zoom_status_label.text()
        assert "ACTIVE" in window.wapp_status_label.text()
        assert "EM EXECUÇÃO" in window.obs_cam_status_label.text()
        assert "SUPORTADA" in window.native_cam_status_label.text()
    finally:
        window.close()


def test_obs_tab_test_connection_and_provision(monkeypatch):
    """Verify OBS connection testing and provisioning callbacks."""
    mock_client = MagicMock()
    mock_client.send.return_value = {"obsVersion": "30.2.0"}
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.connect_obs", lambda **kwargs: mock_client)

    prov_res = OBSProvisionResult(
        monitoring_device_set=True,
        scenes_created=["Palco", "Mídias"],
        jwl_hwnd_capture_configured=True,
        display_captures_disabled=[],
        process_audio_configured=["JW Library", "Zoom"],
    )
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.provision_obs_av", lambda **kwargs: prov_res)
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.QMessageBox.information", lambda *args: None)

    window = AVSetupWindow(auto_refresh=False)
    try:
        window._on_test_obs_connection_clicked(blocking=True)
        QApplication.processEvents()

        window._on_provision_obs_clicked(blocking=True)
        QApplication.processEvents()
        assert "SUCESSO" in window.obs_log_text.toPlainText()
        assert "Palco, Mídias" in window.obs_log_text.toPlainText()
    finally:
        window.close()


def test_full_diagnostic_run(monkeypatch):
    """Verify running full diagnostic populates report and assesses readiness."""
    eps, roles = _make_sample_endpoints()
    opts = _make_sample_optimizations()
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.enumerate_endpoints", lambda: eps)
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.map_project_roles", lambda _: roles)
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.check_all_optimizations", lambda: opts)
    monkeypatch.setattr(
        "meeting_assistant.ui.av_setup_dialog.check_app_routes",
        lambda: {"Zoom.exe": {"status": "ok"}, "WhatsApp.exe": {"status": "ok"}},
    )
    monkeypatch.setattr(
        "meeting_assistant.ui.av_setup_dialog.get_virtual_cam_status",
        lambda obs_client=None: {
            "obs_virtual_cam": {"active": False},
            "native_virtual_cam": {"supported": True},
        },
    )

    window = AVSetupWindow(auto_refresh=False)
    try:
        window.run_full_diagnostic(blocking=True)
        report = window.diag_text_box.toPlainText()
        assert "RELATÓRIO DE DIAGNÓSTICO AV" in report
        assert "1. DISPOSITIVOS DE ÁUDIO" in report
        assert "2. OTIMIZAÇÕES DO WINDOWS 11" in report
        assert "PRONTO PARA TRANSMISSÃO" in window.readiness_banner.text()
    finally:
        window.close()


def test_rename_and_disable_device_actions(monkeypatch):
    """Verify clicking rename and disable triggers apply_device_modifications."""
    applied_calls = []

    def _mock_apply(renames, disables, restart_audiosrv=False):
        applied_calls.append({"renames": renames, "disables": disables, "restart": restart_audiosrv})
        return True, "Modificações simuladas aplicadas"

    eps, roles = _make_sample_endpoints()
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.enumerate_endpoints", lambda: eps)
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.map_project_roles", lambda _: roles)
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.apply_device_modifications", _mock_apply)
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.QMessageBox.information", lambda *args: None)

    window = AVSetupWindow(auto_refresh=False)
    try:
        window.refresh_audio_devices(blocking=True)
        window._on_disable_endpoints_clicked(blocking=True)
        QApplication.processEvents()

        assert len(applied_calls) >= 1
        last = applied_calls[-1]
        assert len(last["disables"]) >= 1  # Blackmagic and/or Webcam disabled
    finally:
        window.close()


# ---------------------------------------------------------------------------
# Test Standalone CLI Tool (scripts/av_setup_tool.py)
# ---------------------------------------------------------------------------


def test_cli_diagnose_text(monkeypatch, capsys):
    """Test av_setup_tool.py --diagnose outputs structured text."""
    eps, roles = _make_sample_endpoints()
    opts = _make_sample_optimizations()
    monkeypatch.setattr("meeting_assistant.services.windows_core_audio.enumerate_endpoints", lambda: eps)
    monkeypatch.setattr("meeting_assistant.services.windows_core_audio.map_project_roles", lambda _: roles)
    monkeypatch.setattr(
        "meeting_assistant.services.windows_transmission_optimizer.check_all_optimizations",
        lambda: opts,
    )
    monkeypatch.setattr(
        "meeting_assistant.services.app_audio_router.check_app_routes",
        lambda: {"Zoom.exe": {"status": "ok"}},
    )
    monkeypatch.setattr(
        "meeting_assistant.services.app_audio_router.get_virtual_cam_status",
        lambda obs_client=None: {
            "obs_virtual_cam": {"active": False},
            "native_virtual_cam": {"supported": True},
        },
    )

    monkeypatch.setattr("sys.argv", ["av_setup_tool.py", "--diagnose"])
    code = av_tool.main()
    assert code == 0
    captured = capsys.readouterr()
    assert "RELATÓRIO DE DIAGNÓSTICO AV" in captured.out
    assert "1. DISPOSITIVOS DE ÁUDIO" in captured.out


def test_cli_diagnose_json(monkeypatch, capsys):
    """Test av_setup_tool.py --diagnose --json outputs valid parseable JSON."""
    eps, roles = _make_sample_endpoints()
    opts = _make_sample_optimizations()
    monkeypatch.setattr("meeting_assistant.services.windows_core_audio.enumerate_endpoints", lambda: eps)
    monkeypatch.setattr("meeting_assistant.services.windows_core_audio.map_project_roles", lambda _: roles)
    monkeypatch.setattr(
        "meeting_assistant.services.windows_transmission_optimizer.check_all_optimizations",
        lambda: opts,
    )
    monkeypatch.setattr(
        "meeting_assistant.services.app_audio_router.check_app_routes",
        lambda: {"Zoom.exe": {"status": "ok"}},
    )
    monkeypatch.setattr(
        "meeting_assistant.services.app_audio_router.get_virtual_cam_status",
        lambda obs_client=None: {
            "obs_virtual_cam": {"active": False},
            "native_virtual_cam": {"supported": True},
        },
    )

    monkeypatch.setattr("sys.argv", ["av_setup_tool.py", "--diagnose", "--json"])
    code = av_tool.main()
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "ready" in data
    assert "endpoints" in data
    assert "optimizations" in data
    assert len(data["endpoints"]) == len(eps)


def test_cli_apply_os_json(monkeypatch, capsys):
    """Test av_setup_tool.py --apply-os --json outputs valid JSON."""
    monkeypatch.setattr(
        "meeting_assistant.services.windows_transmission_optimizer.apply_all_optimizations",
        lambda: {"ducking": True, "power_monitor": True},
    )
    monkeypatch.setattr(
        "meeting_assistant.services.windows_transmission_optimizer.is_user_admin", lambda: False
    )

    monkeypatch.setattr("sys.argv", ["av_setup_tool.py", "--apply-os", "--json"])
    code = av_tool.main()
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["elevated"] is False
    assert data["results"]["ducking"] is True


# ---------------------------------------------------------------------------
# Test Integration into MainWindow and SetupAssistantDialog
# ---------------------------------------------------------------------------


def test_main_window_open_av_setup_reuse(tmp_path, monkeypatch):
    """Verify MainWindow._open_av_setup instantiates and reuses window."""
    eps, roles = _make_sample_endpoints()
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.enumerate_endpoints", lambda: eps)
    monkeypatch.setattr("meeting_assistant.ui.av_setup_dialog.map_project_roles", lambda _: roles)
    monkeypatch.setattr(
        "meeting_assistant.ui.av_setup_dialog.check_all_optimizations", _make_sample_optimizations
    )
    monkeypatch.setattr(
        "meeting_assistant.ui.av_setup_dialog.AVSetupWindow.refresh_all_diagnostics",
        lambda *args, **kwargs: None,
    )

    services = [MagicMock() for _ in range(6)]
    services[1].snapshot.return_value = []
    services[5].active = services[5].returning = False
    owner = MainWindow(AppState(), AppSettings(), SettingsService(tmp_path / "settings.json"), *services)

    try:
        assert owner._av_setup_window is None
        owner._open_av_setup()
        first_instance = owner._av_setup_window
        assert first_instance is not None
        assert isinstance(first_instance, AVSetupWindow)

        # Calling again should reuse instance
        owner._open_av_setup()
        assert owner._av_setup_window is first_instance
    finally:
        if owner._av_setup_window:
            owner._av_setup_window.close()
        owner.close()


def test_setup_assistant_dialog_contains_av_setup_buttons(tmp_path, monkeypatch):
    """Verify SetupAssistantDialog has AV setup buttons on installation and diagnostics pages."""
    services = [MagicMock() for _ in range(6)]
    services[1].snapshot.return_value = []
    services[5].active = services[5].returning = False
    owner = MainWindow(AppState(), AppSettings(), SettingsService(tmp_path / "settings.json"), *services)
    monkeypatch.setattr(SetupAssistantDialog, "_inspect", lambda self: None)

    dialog = SetupAssistantDialog(owner, page="installation")
    try:
        assert hasattr(dialog, "av_setup_install_btn")
        assert hasattr(dialog, "av_setup_diag_btn")
        assert "Preparação AV" in dialog.av_setup_install_btn.text()
        assert "Preparação AV" in dialog.av_setup_diag_btn.text()

        # Test trigger sets deferred_action
        dialog.av_setup_install_btn.click()
        assert dialog.deferred_action == owner._open_av_setup
    finally:
        dialog.close()
        owner.close()
