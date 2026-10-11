#!/usr/bin/env python3
"""Standalone executable AV Setup and Windows 11 Optimization Tool.

Supports both interactive GUI mode (PySide6) and headless CLI diagnostic
and optimization modes for automation and scripting.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

# Ensure 'src' directory is in Python module search path
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("av_setup_tool")


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if is_dataclass(o):
            return asdict(o)
        if isinstance(o, Path):
            return str(o)
        return super().default(o)


def run_headless_diagnostics(
    obs_host: str = "127.0.0.1",
    obs_port: int = 4455,
    obs_password: str = "",
) -> dict[str, Any]:
    """Execute all AV and OS transmission diagnostics headlessly."""
    from meeting_assistant.services.app_audio_router import check_app_routes, get_virtual_cam_status
    from meeting_assistant.services.obs_av_provisioner import connect_obs
    from meeting_assistant.services.windows_core_audio import (
        ROLE_V_OUT_WAPP,
        ROLE_V_OUT_ZOOM,
        enumerate_endpoints,
        map_project_roles,
    )
    from meeting_assistant.services.windows_transmission_optimizer import check_all_optimizations

    eps = enumerate_endpoints()
    roles = map_project_roles(eps)
    optimizations = check_all_optimizations()
    routes = check_app_routes()
    cams = get_virtual_cam_status(obs_client=None)

    obs_connected = False
    obs_scenes: list[str] = []
    try:
        client = connect_obs(host=obs_host, port=obs_port, password=obs_password, timeout=1.5)
        res = client.send("GetSceneList", raw=True)
        obs_scenes = [s["sceneName"] for s in res.get("scenes", [])]
        obs_connected = True
        if hasattr(client, "disconnect"):
            client.disconnect()
    except Exception:
        obs_connected = False

    opts_optimal = sum(1 for o in optimizations if o.is_optimal)
    all_opts_ok = opts_optimal == len(optimizations)
    cable_a = bool(roles.get(ROLE_V_OUT_ZOOM))
    cable_b = bool(roles.get(ROLE_V_OUT_WAPP))

    ready = all_opts_ok and cable_a and cable_b

    return {
        "ready": ready,
        "endpoints_count": len(eps),
        "endpoints": [asdict(e) for e in eps],
        "roles": {k: asdict(v) for k, v in roles.items()},
        "optimizations_count": len(optimizations),
        "optimizations_optimal": opts_optimal,
        "optimizations": [asdict(o) for o in optimizations],
        "routes": routes,
        "cameras": cams,
        "obs": {
            "connected": obs_connected,
            "scenes": obs_scenes,
        },
    }


def print_text_diagnostics(diag: dict[str, Any]) -> None:
    """Print readable text diagnostic to standard output."""
    ready_status = "PRONTO PARA TRANSMISSÃO" if diag["ready"] else "AÇÕES PENDENTES"
    print("\n" + "=" * 70)
    print(f" RELATÓRIO DE DIAGNÓSTICO AV — STATUS: {ready_status}")
    print("=" * 70)

    print(f"\n1. DISPOSITIVOS DE ÁUDIO ({diag['endpoints_count']} detectados):")
    for role_name, ep in diag["roles"].items():
        state = "Ativo" if ep["state"] == 1 else "Desativado"
        print(f"   • [{role_name}]: {ep['friendly_name']} ({ep['sample_rate_hz']} Hz, {state})")

    opts_opt = diag["optimizations_optimal"]
    opts_cnt = diag["optimizations_count"]
    print(f"\n2. OTIMIZAÇÕES DO WINDOWS 11 ({opts_opt}/{opts_cnt} conformes):")
    for opt in diag["optimizations"]:
        tag = "OK" if opt["is_optimal"] else "PENDENTE"
        c_val = opt["current_value"]
        r_val = opt["recommended_value"]
        print(f"   [{tag:8s}] {opt['name']}: atual={c_val} (recomendado={r_val})")

    print("\n3. ROTEAMENTO DE APLICATIVOS & CÂMERAS:")
    for app, info in diag["routes"].items():
        print(f"   • {app}: status={info.get('status')} ({info.get('details')})")
    obs_cam_act = "Ativa" if diag["cameras"].get("obs_virtual_cam", {}).get("active") else "Inativa"
    print(f"   • Câmera OBS: {obs_cam_act}")
    nat_cam_sup = (
        "Suportada" if diag["cameras"].get("native_virtual_cam", {}).get("supported") else "Não suportada"
    )
    print(f"   • Câmera Nativa: {nat_cam_sup}")

    print("\n4. OBS STUDIO:")
    obs_info = diag["obs"]
    print(f"   • Conexão: {'Conectado' if obs_info['connected'] else 'Desconectado / Indisponível'}")
    if obs_info["scenes"]:
        print(f"   • Cenas: {', '.join(obs_info['scenes'])}")

    print("\n" + "=" * 70 + "\n")


def apply_headless_os_optimizations() -> dict[str, Any]:
    """Apply OS transmission optimizations directly."""
    from meeting_assistant.services.windows_transmission_optimizer import (
        apply_all_optimizations,
        apply_elevated_os_optimizations,
        is_user_admin,
    )

    if is_user_admin():
        ok, msg = apply_elevated_os_optimizations()
        return {"elevated": True, "success": ok, "message": msg}
    results = apply_all_optimizations()
    return {"elevated": False, "results": results}


def start_gui() -> int:
    """Launch the PySide6 single-window AV setup application."""
    from PySide6.QtWidgets import QApplication

    from meeting_assistant.ui.av_setup_dialog import AVSetupWindow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    window = AVSetupWindow()
    window.show()
    return app.exec()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Meeting Assistant AV Setup & Windows 11 Optimization Tool"
    )
    parser.add_argument("--gui", action="store_true", help="Launch interactive graphical interface")
    parser.add_argument("--diagnose", action="store_true", help="Run full diagnostic suite headlessly")
    parser.add_argument(
        "--apply-os", action="store_true", help="Apply OS transmission optimizations headlessly"
    )
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("--host", default="127.0.0.1", help="OBS WebSocket host")
    parser.add_argument("--port", type=int, default=4455, help="OBS WebSocket port")
    parser.add_argument("--password", default="", help="OBS WebSocket password")

    args = parser.parse_args()

    # If --apply-os requested
    if args.apply_os:
        results = apply_headless_os_optimizations()
        if args.json:
            print(json.dumps(results, indent=2, cls=EnhancedJSONEncoder))
        else:
            print("Otimizações do Sistema Operacional aplicadas:")
            for k, v in results.items():
                print(f"  {k}: {v}")
        return 0

    # If --diagnose requested
    if args.diagnose:
        need_com = sys.platform == "win32"
        if need_com:
            try:
                import pythoncom

                pythoncom.CoInitialize()
            except Exception:
                need_com = False

        try:
            diag = run_headless_diagnostics(
                obs_host=args.host,
                obs_port=args.port,
                obs_password=args.password,
            )
            if args.json:
                print(json.dumps(diag, indent=2, cls=EnhancedJSONEncoder))
            else:
                print_text_diagnostics(diag)
            return 0
        finally:
            if need_com:
                try:
                    import pythoncom

                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    # If explicit --gui or default without command flags
    return start_gui()


if __name__ == "__main__":
    sys.exit(main())
