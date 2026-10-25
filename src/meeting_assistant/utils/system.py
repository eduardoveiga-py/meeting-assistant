"""System utilities: DPI awareness, rotating logs, and global exception handling."""

from __future__ import annotations

import ctypes
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from meeting_assistant.utils.paths import get_appdata_dir


def configure_dpi_awareness() -> bool:
    """Configure Per-Monitor DPI Awareness (v2) on Windows before QApplication startup."""
    if sys.platform != "win32":
        return False
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4 (Windows 10 1703+)
        # Usar SetProcessDpiAwarenessContext primeiro alinha com o Qt 6 e evita aviso de acesso negado
        if hasattr(ctypes.windll.user32, "SetProcessDpiAwarenessContext"):
            context = ctypes.c_void_p(-4)
            if ctypes.windll.user32.SetProcessDpiAwarenessContext(context):
                return True
    except Exception:
        pass
    try:
        # 2 = PROCESS_PER_MONITOR_DPI_AWARE
        res = ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return res == 0
    except Exception:
        try:
            return bool(ctypes.windll.user32.SetProcessDPIAware())
        except Exception:
            return False


def setup_rotating_logger(
    log_dir: Path | None = None,
    max_bytes: int = 2_000_000,
    backup_count: int = 5,
) -> Path:
    """Configure a rotating file handler logging to meeting_assistant.log."""
    target_dir = log_dir or (get_appdata_dir() / "logs")
    target_dir.mkdir(parents=True, exist_ok=True)
    log_file = target_dir / "meeting_assistant.log"

    handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    if not any(
        isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None) == str(log_file)
        for h in root_logger.handlers
    ):
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

    return log_file


def install_global_excepthook() -> None:
    """Install a global excepthook that writes unhandled exceptions to disk."""
    def _hook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logging.critical(
            "Exceção não tratada capturada globalmente:",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance():
                QMessageBox.critical(
                    None,
                    "Erro Inesperado — Meeting Assistant",
                    f"Ocorreu um erro inesperado no aplicativo:\n\n{exc_value}\n\n"
                    "O detalhe técnico foi gravado no arquivo de log do Meeting Assistant.",
                )
        except Exception:
            pass

    sys.excepthook = _hook
