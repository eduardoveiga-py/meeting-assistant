"""Windows 11 OS transmission optimizations service for Meeting Assistant AV Setup.

Verifies and applies system-level transmission optimizations for Windows 11:
- Communications ducking (UserDuckingPreference = 3, 'Do nothing')
- System sound scheme (.None) and Windows startup sound (DisableStartupSound = 1)
- Power plan AC timeouts (monitor and standby timeouts = 0 / Never)
- Exclusive mode disabled across audio endpoints
- Audio signal enhancements / processing disabled across endpoints
- Sample rate diagnostic (48.000 Hz / 48 kHz across all endpoints)
- Monitor 2 DPI scale factor verification (100% / 1.0 / 96 DPI)
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any

from meeting_assistant.services.windows_core_audio import (
    PKEY_DEVICE_INTERFACE_NAME,
    REG_MMDEVICES_PATH,
    enumerate_endpoints,
    is_user_admin,
)

logger = logging.getLogger(__name__)

# Registry Paths & Values
REG_DUCKING_PATH = r"Software\Microsoft\Multimedia\Audio"
VAL_DUCKING = "UserDuckingPreference"
DUCKING_DO_NOTHING = 3

REG_SOUND_SCHEMES_PATH = r"AppEvents\Schemes"
SOUND_SCHEME_NONE = ".None"

REG_LOGON_BOOT_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\LogonUI\BootAnimation"
VAL_DISABLE_STARTUP_SOUND = "DisableStartupSound"

# MMDevice Audio Endpoint Properties
PKEY_EXCLUSIVE_MODE = "{b3f8fa53-0004-438e-9003-51a46e139bfc},3"
PKEY_EXCLUSIVE_MODE_EXT = "{b3f8fa53-0004-438e-9003-51a46e139bfc},4"
PKEY_DISABLE_SYS_FX = "{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},5"


@dataclass
class OptimizationStatus:
    """Status report for a single system transmission optimization."""

    name: str
    current_value: Any
    is_optimal: bool
    recommended_value: Any
    description: str


# -------------------------------------------------------------------------
# 1. Communications Ducking
# -------------------------------------------------------------------------


def check_ducking() -> OptimizationStatus:
    """Check Windows Communications Ducking preference."""
    current_val: int | None = None
    is_optimal = False

    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_DUCKING_PATH) as k:
                val, _ = winreg.QueryValueEx(k, VAL_DUCKING)
                current_val = int(val)
                is_optimal = current_val == DUCKING_DO_NOTHING
        except Exception:
            current_val = None

    desc = (
        "Impede que o Windows reduza automaticamente em 80% o volume de outras fontes "
        "quando chamadas (Zoom/WhatsApp) estão ativas."
    )
    return OptimizationStatus(
        name="Ducking de Comunicações",
        current_value=current_val,
        is_optimal=is_optimal,
        recommended_value=DUCKING_DO_NOTHING,
        description=desc,
    )


def apply_ducking() -> bool:
    """Set Communications Ducking to 'Do nothing' (3) in HKCU."""
    if sys.platform != "win32":
        return False

    import winreg

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_DUCKING_PATH) as k:
            winreg.SetValueEx(k, VAL_DUCKING, 0, winreg.REG_DWORD, DUCKING_DO_NOTHING)
        return True
    except Exception as exc:
        logger.error("Failed to apply ducking preference: %s", exc)
        return False


# -------------------------------------------------------------------------
# 2. System Sound Scheme & Startup Sound
# -------------------------------------------------------------------------


def check_sound_scheme() -> OptimizationStatus:
    """Check active Windows sound scheme (should be '.None')."""
    current_val: str | None = None
    is_optimal = False

    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_SOUND_SCHEMES_PATH) as k:
                val, _ = winreg.QueryValueEx(k, "")
                current_val = str(val)
                is_optimal = current_val.casefold() == SOUND_SCHEME_NONE.casefold()
        except Exception:
            current_val = None

    desc = "Esquema 'Sem som' desativa alertas sonoros acidentais do sistema operacional durante a reunião."
    return OptimizationStatus(
        name="Esquema de Sons do Sistema",
        current_value=current_val,
        is_optimal=is_optimal,
        recommended_value=SOUND_SCHEME_NONE,
        description=desc,
    )


def apply_sound_scheme() -> bool:
    """Set Windows sound scheme to '.None' (No Sounds) in HKCU."""
    if sys.platform != "win32":
        return False

    import winreg

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_SOUND_SCHEMES_PATH) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, SOUND_SCHEME_NONE)
        return True
    except Exception as exc:
        logger.error("Failed to set sound scheme: %s", exc)
        return False


def check_startup_sound() -> OptimizationStatus:
    """Check Windows startup sound status in HKLM."""
    current_val: int | None = None
    is_optimal = False

    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REG_LOGON_BOOT_PATH) as k:
                val, _ = winreg.QueryValueEx(k, VAL_DISABLE_STARTUP_SOUND)
                current_val = int(val)
                is_optimal = current_val == 1
        except Exception:
            current_val = 0

    desc = "Desativa o som de inicialização do Windows ao ligar ou reiniciar o computador."
    return OptimizationStatus(
        name="Som de Inicialização do Windows",
        current_value=current_val,
        is_optimal=is_optimal,
        recommended_value=1,
        description=desc,
    )


def apply_startup_sound() -> bool:
    """Disable Windows startup sound in HKLM if elevated."""
    if sys.platform != "win32":
        return False

    import winreg

    try:
        with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, REG_LOGON_BOOT_PATH) as k:
            winreg.SetValueEx(k, VAL_DISABLE_STARTUP_SOUND, 0, winreg.REG_DWORD, 1)
        return True
    except Exception as exc:
        logger.debug("Could not write DisableStartupSound directly (needs elevation): %s", exc)
        return False


# -------------------------------------------------------------------------
# 3. Power Plan AC Timeouts (Monitor & Standby)
# -------------------------------------------------------------------------


def _query_powercfg_ac_seconds(subgroup: str, setting: str) -> int | None:
    """Query current AC setting index in seconds from powercfg."""
    if sys.platform != "win32":
        return None

    try:
        proc = subprocess.run(
            ["powercfg", "/query", "SCHEME_CURRENT", subgroup, setting],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if proc.returncode != 0:
            return None

        # Matches English ('Current AC Power Setting Index') or Portuguese ('Correntes Alternadas')
        pattern = r"(?:Correntes Alternadas|Current AC|AC Power Setting Index)[^\n\r]*:\s*0x([0-9a-fA-F]+)"
        match = re.search(pattern, proc.stdout, re.IGNORECASE)
        if match:
            return int(match.group(1), 16)
    except Exception as exc:
        logger.debug("Error querying powercfg: %s", exc)

    return None


def check_power_ac_monitor() -> OptimizationStatus:
    """Check display timeout on AC power (should be 0 / Never)."""
    seconds = _query_powercfg_ac_seconds("SUB_VIDEO", "VIDEOIDLE")
    is_optimal = seconds == 0

    desc = "Impede que o monitor ou telão desligue por inatividade durante a reunião."
    return OptimizationStatus(
        name="Desligamento de Tela (Modo AC)",
        current_value=f"{seconds}s" if seconds is not None else "Desconhecido",
        is_optimal=is_optimal,
        recommended_value="0s (Nunca)",
        description=desc,
    )


def apply_power_ac_monitor() -> bool:
    """Set AC display timeout to 0 (Never) via powercfg."""
    if sys.platform != "win32":
        return False

    try:
        proc = subprocess.run(
            ["powercfg", "/change", "monitor-timeout-ac", "0"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        return proc.returncode == 0
    except Exception as exc:
        logger.error("Failed to set monitor timeout: %s", exc)
        return False


def check_power_ac_standby() -> OptimizationStatus:
    """Check system sleep/standby timeout on AC power (should be 0 / Never)."""
    seconds = _query_powercfg_ac_seconds("SUB_SLEEP", "STANDBYIDLE")
    is_optimal = seconds == 0

    desc = "Impede que o computador entre em suspensão durante a transmissão da reunião."
    return OptimizationStatus(
        name="Suspensão do Sistema (Modo AC)",
        current_value=f"{seconds}s" if seconds is not None else "Desconhecido",
        is_optimal=is_optimal,
        recommended_value="0s (Nunca)",
        description=desc,
    )


def apply_power_ac_standby() -> bool:
    """Set AC sleep timeout to 0 (Never) via powercfg."""
    if sys.platform != "win32":
        return False

    try:
        proc = subprocess.run(
            ["powercfg", "/change", "standby-timeout-ac", "0"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        return proc.returncode == 0
    except Exception as exc:
        logger.error("Failed to set standby timeout: %s", exc)
        return False


# -------------------------------------------------------------------------
# 4. Exclusive Mode & Signal Enhancements
# -------------------------------------------------------------------------


def check_exclusive_mode() -> OptimizationStatus:
    """Check if Exclusive Mode is disabled across MMDevices endpoints."""
    if sys.platform != "win32":
        return OptimizationStatus("Modo Exclusivo de Áudio", None, True, 0, "")

    import winreg

    total_checked = 0
    enabled_count = 0

    for direction in ("Render", "Capture"):
        path = rf"{REG_MMDEVICES_PATH}\{direction}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
                num_subkeys = winreg.QueryInfoKey(k)[0]
                for i in range(num_subkeys):
                    guid = winreg.EnumKey(k, i)
                    prop_path = rf"{path}\{guid}\Properties"
                    try:
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, prop_path) as pk:
                            num_vals = winreg.QueryInfoKey(pk)[1]
                            vals = dict(winreg.EnumValue(pk, j)[:2] for j in range(num_vals))
                            # Exclude endpoints without interface name (unconfigured/system stubs)
                            if PKEY_DEVICE_INTERFACE_NAME.casefold() in {k.casefold() for k in vals}:
                                total_checked += 1
                                excl = vals.get(PKEY_EXCLUSIVE_MODE)
                                # In Windows, 0 means disabled; 1 or missing means enabled
                                if excl != 0:
                                    enabled_count += 1
                    except Exception:
                        pass
        except Exception:
            pass

    is_optimal = total_checked > 0 and enabled_count == 0
    current_display = (
        "Desativado em todos"
        if is_optimal
        else f"Ativo em {enabled_count} de {total_checked} dispositivo(s)"
    )

    desc = (
        "Evita que Zoom ou outros aplicativos travem acesso exclusivo aos microfones "
        "ou saídas, bloqueando o OBS e o Meeting Assistant."
    )
    return OptimizationStatus(
        name="Modo Exclusivo de Áudio",
        current_value=current_display,
        is_optimal=is_optimal,
        recommended_value="Desativado em todos (0)",
        description=desc,
    )


def apply_exclusive_mode() -> bool:
    """Disable Exclusive Mode across all MMDevices endpoints in registry."""
    if sys.platform != "win32":
        return False

    import winreg

    success = True
    for direction in ("Render", "Capture"):
        path = rf"{REG_MMDEVICES_PATH}\{direction}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
                num_subkeys = winreg.QueryInfoKey(k)[0]
                for i in range(num_subkeys):
                    guid = winreg.EnumKey(k, i)
                    prop_path = rf"{path}\{guid}\Properties"
                    try:
                        with winreg.OpenKey(
                            winreg.HKEY_LOCAL_MACHINE, prop_path, 0, winreg.KEY_SET_VALUE
                        ) as pk:
                            winreg.SetValueEx(pk, PKEY_EXCLUSIVE_MODE, 0, winreg.REG_DWORD, 0)
                            winreg.SetValueEx(pk, PKEY_EXCLUSIVE_MODE_EXT, 0, winreg.REG_DWORD, 0)
                    except Exception:
                        success = False
        except Exception:
            success = False

    return success


def check_signal_enhancements() -> OptimizationStatus:
    """Check if Audio Signal Enhancements (APO) are disabled across endpoints."""
    if sys.platform != "win32":
        return OptimizationStatus("Aprimoramentos de Sinal de Áudio", None, True, 1, "")

    import winreg

    total_checked = 0
    disabled_count = 0

    for direction in ("Render", "Capture"):
        path = rf"{REG_MMDEVICES_PATH}\{direction}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
                num_subkeys = winreg.QueryInfoKey(k)[0]
                for i in range(num_subkeys):
                    guid = winreg.EnumKey(k, i)
                    prop_path = rf"{path}\{guid}\Properties"
                    try:
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, prop_path) as pk:
                            num_vals = winreg.QueryInfoKey(pk)[1]
                            vals = dict(winreg.EnumValue(pk, j)[:2] for j in range(num_vals))
                            if PKEY_DEVICE_INTERFACE_NAME.casefold() in {k.casefold() for k in vals}:
                                total_checked += 1
                                fx = vals.get(PKEY_DISABLE_SYS_FX)
                                if fx == 1:
                                    disabled_count += 1
                    except Exception:
                        pass
        except Exception:
            pass

    is_optimal = total_checked > 0 and disabled_count == total_checked
    current_display = (
        "Desativado em todos"
        if is_optimal
        else f"Desativado em {disabled_count} de {total_checked} dispositivo(s)"
    )

    desc = (
        "Desativa cancelamentos de ruído e equalizações artificiais do Windows "
        "para garantir fidelidade às músicas e vozes do Salão."
    )
    return OptimizationStatus(
        name="Aprimoramentos de Sinal de Áudio",
        current_value=current_display,
        is_optimal=is_optimal,
        recommended_value="Desativado em todos (1)",
        description=desc,
    )


def apply_signal_enhancements() -> bool:
    """Disable Audio Signal Enhancements (set Disable_SysFx=1) across endpoints."""
    if sys.platform != "win32":
        return False

    import winreg

    success = True
    for direction in ("Render", "Capture"):
        path = rf"{REG_MMDEVICES_PATH}\{direction}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
                num_subkeys = winreg.QueryInfoKey(k)[0]
                for i in range(num_subkeys):
                    guid = winreg.EnumKey(k, i)
                    prop_path = rf"{path}\{guid}\Properties"
                    try:
                        with winreg.OpenKey(
                            winreg.HKEY_LOCAL_MACHINE, prop_path, 0, winreg.KEY_SET_VALUE
                        ) as pk:
                            winreg.SetValueEx(pk, PKEY_DISABLE_SYS_FX, 0, winreg.REG_DWORD, 1)
                    except Exception:
                        success = False
        except Exception:
            success = False

    return success


# -------------------------------------------------------------------------
# 5. Sample Rate Diagnostics (48.000 Hz)
# -------------------------------------------------------------------------


def check_sample_rates() -> OptimizationStatus:
    """Verify that all audio endpoints operate at 48.000 Hz (48 kHz)."""
    endpoints = enumerate_endpoints()
    discrepancies: list[str] = []

    for ep in endpoints:
        # Check active and relevant virtual/physical devices
        if ep.sample_rate_hz != 48000:
            discrepancies.append(f"{ep.desc} ({ep.sample_rate_hz} Hz)")

    is_optimal = len(discrepancies) == 0
    current_val = (
        "48.000 Hz em todos"
        if is_optimal
        else f"{len(discrepancies)} discrepância(s): {', '.join(discrepancies[:3])}"
    )

    desc = (
        "Todos os dispositivos devem operar em 48.000 Hz (48 kHz) para evitar "
        "reamostragem, estalos e dessincronização de áudio no OBS Studio."
    )
    return OptimizationStatus(
        name="Taxa de Amostragem (48 kHz)",
        current_value=current_val,
        is_optimal=is_optimal,
        recommended_value="48.000 Hz",
        description=desc,
    )


# -------------------------------------------------------------------------
# 6. Monitor 2 DPI Scale Check (100% / 96 DPI)
# -------------------------------------------------------------------------


def check_monitor_dpi(display_index: int = 1) -> tuple[bool, float, str]:
    """Query monitor scale factor / DPI.

    By default inspects display_index=1 (secondary monitor, Telão/TV).
    Returns (is_optimal, scale_factor, description).
    Target is 100% (1.0 / 96 DPI).
    """
    if sys.platform != "win32":
        return True, 1.0, "Escala padrão 100% (96 DPI)."

    import ctypes
    from ctypes import wintypes

    monitors: list[tuple[int, int]] = []

    def enum_callback(h_monitor: int, _hdc: int, _lprc: Any, _dw_data: int) -> bool:
        dpi_x = wintypes.UINT()
        dpi_y = wintypes.UINT()
        try:
            res = ctypes.windll.shcore.GetDpiForMonitor(
                h_monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)
            )
            if res == 0:
                monitors.append((dpi_x.value, dpi_y.value))
        except Exception:
            pass
        return True

    try:
        mon_proc = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            wintypes.HMONITOR,
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            wintypes.LPARAM,
        )
        ctypes.windll.user32.EnumDisplayMonitors(None, None, mon_proc(enum_callback), 0)
    except Exception as exc:
        logger.debug("EnumDisplayMonitors failed: %s", exc)

    if not monitors:
        # Fallback to Qt screens if available
        try:
            from PySide6.QtGui import QGuiApplication

            screens = QGuiApplication.screens()
            if screens:
                target_screen = screens[display_index] if len(screens) > display_index else screens[0]
                dpr = float(target_screen.devicePixelRatio())
                optimal = dpr == 1.0
                msg = f"Escala do monitor: {dpr * 100:.0f}% (devicePixelRatio: {dpr})."
                return optimal, dpr, msg
        except Exception:
            pass
        return True, 1.0, "Não foi possível consultar os monitores diretamente."

    if len(monitors) <= display_index:
        # Only 1 monitor connected
        primary_dpi = monitors[0][0]
        primary_scale = primary_dpi / 96.0
        return (
            False,
            0.0,
            f"Monitor secundário não detectado "
            f"(apenas 1 monitor conectado, escala {primary_scale * 100:.0f}%).",
        )

    target_dpi_x, _ = monitors[display_index]
    scale = target_dpi_x / 96.0
    is_optimal = target_dpi_x == 96

    if is_optimal:
        msg = f"Monitor {display_index + 1} em 100% de escala (96 DPI) — ideal para projeção 1:1."
    else:
        msg = (
            f"Monitor {display_index + 1} em {scale * 100:.0f}% de escala ({target_dpi_x} DPI). "
            f"Recomendado ajustar para 100% (96 DPI) nas configurações do Windows."
        )

    return is_optimal, scale, msg


def check_monitor_dpi_status() -> OptimizationStatus:
    """Return OptimizationStatus for secondary monitor DPI."""
    is_optimal, scale, msg = check_monitor_dpi(display_index=1)
    return OptimizationStatus(
        name="Escala do Monitor Secundário (DPI 100%)",
        current_value=f"{scale * 100:.0f}%" if scale > 0 else "Não conectado",
        is_optimal=is_optimal,
        recommended_value="100% (96 DPI)",
        description=msg,
    )


# -------------------------------------------------------------------------
# Master Checks & Elevation Script Generation
# -------------------------------------------------------------------------


def check_all_optimizations() -> list[OptimizationStatus]:
    """Execute all transmission optimization checks and return status list."""
    return [
        check_ducking(),
        check_sound_scheme(),
        check_startup_sound(),
        check_power_ac_monitor(),
        check_power_ac_standby(),
        check_exclusive_mode(),
        check_signal_enhancements(),
        check_sample_rates(),
        check_monitor_dpi_status(),
    ]


def generate_os_optimization_script() -> str:
    """Generate an elevated PowerShell script that applies all HKLM and system settings."""
    return (
        "# Meeting Assistant AV Setup - Elevated OS Optimizations Script\n"
        "$ErrorActionPreference = 'Continue'\n"
        "\n"
        "# 1. Communications Ducking (Do nothing)\n"
        "$duckingPath = 'HKCU:\\Software\\Microsoft\\Multimedia\\Audio'\n"
        "if (-not (Test-Path $duckingPath)) { New-Item -Path $duckingPath -Force | Out-Null }\n"
        "Set-ItemProperty -Path $duckingPath -Name 'UserDuckingPreference' -Value 3 -Type DWord -Force\n"
        "\n"
        "# 2. Sound Scheme (.None)\n"
        "$schemesPath = 'HKCU:\\AppEvents\\Schemes'\n"
        "Set-ItemProperty -Path $schemesPath -Name '(Default)' -Value '.None' -Type String -Force\n"
        "\n"
        "# 3. Disable Windows Startup Sound\n"
        "$bootPath = 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
        "Authentication\\LogonUI\\BootAnimation'\n"
        "if (-not (Test-Path $bootPath)) { New-Item -Path $bootPath -Force | Out-Null }\n"
        "Set-ItemProperty -Path $bootPath -Name 'DisableStartupSound' -Value 1 -Type DWord -Force\n"
        "\n"
        "# 4. Power Plan AC Timeouts (Monitor & Standby = 0)\n"
        "powercfg /change monitor-timeout-ac 0\n"
        "powercfg /change standby-timeout-ac 0\n"
        "\n"
        "# 5. Disable Exclusive Mode and Signal Enhancements across MMDevices\n"
        "foreach ($dir in @('Render', 'Capture')) {\n"
        "    $base = \"HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\MMDevices\\Audio\\$dir\"\n"
        "    if (Test-Path $base) {\n"
        "        Get-ChildItem -Path $base | ForEach-Object {\n"
        "            $prop = Join-Path $_.PSPath 'Properties'\n"
        "            if (Test-Path $prop) {\n"
        "                # Exclusive mode disabled (0)\n"
        "                Set-ItemProperty -Path $prop -Name '{b3f8fa53-0004-438e-9003-51a46e139bfc},3' "
        "-Value 0 -Type DWord -Force\n"
        "                Set-ItemProperty -Path $prop -Name '{b3f8fa53-0004-438e-9003-51a46e139bfc},4' "
        "-Value 0 -Type DWord -Force\n"
        "                # Signal enhancements disabled (1)\n"
        "                Set-ItemProperty -Path $prop -Name '{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},5' "
        "-Value 1 -Type DWord -Force\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
        "\n"
        "Write-Output 'OS Optimizations Applied Successfully'\n"
    )


def apply_elevated_os_optimizations() -> tuple[bool, str]:
    """Apply OS transmission optimizations with UAC elevation if required."""
    if sys.platform != "win32":
        return False, "Otimizações de sistema exclusivas para Windows 11."

    if is_user_admin():
        res = apply_all_optimizations()
        all_ok = all(res.values())
        return all_ok, f"Otimizações aplicadas diretamente: {res}"

    script_content = generate_os_optimization_script()
    temp_script = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".ps1",
            delete=False,
            encoding="utf-8-sig",
        ) as f:
            f.write(script_content)
            temp_script = f.name

        cmd = (
            f"Start-Process powershell.exe -ArgumentList "
            f"'-NoProfile -ExecutionPolicy Bypass -File \"{temp_script}\"' -Verb RunAs -Wait"
        )
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode == 0:
            return True, "Otimizações do Windows 11 aplicadas com elevação UAC com sucesso."
        return False, f"Falha na elevação ou cancelamento pelo usuário (código {proc.returncode})."

    except Exception as exc:
        return False, f"Erro ao aplicar otimizações elevadas: {exc}"
    finally:
        if temp_script and os.path.exists(temp_script):
            with contextlib.suppress(Exception):
                os.remove(temp_script)


def apply_all_optimizations() -> dict[str, bool]:
    """Apply all standard transmission optimizations directly.

    Non-admin optimizations (ducking, sounds, powercfg) always apply.
    HKLM optimizations apply if permissions allow or return False if unprivileged.
    """
    results: dict[str, bool] = {
        "ducking": apply_ducking(),
        "sound_scheme": apply_sound_scheme(),
        "power_monitor": apply_power_ac_monitor(),
        "power_standby": apply_power_ac_standby(),
        "startup_sound": apply_startup_sound(),
        "exclusive_mode": apply_exclusive_mode(),
        "signal_enhancements": apply_signal_enhancements(),
    }
    return results
