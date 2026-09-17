from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from meeting_assistant.services.display_service import (
    DisplayService,
    resolve_hall_display,
)
from meeting_assistant.services.jwl_window_capture import (
    JwlWindowCapture,
    monitor_index_for_display,
)
from meeting_assistant.services.settings import SettingsService

WDA_EXCLUDEFROMCAPTURE = 0x00000011


def _exclude_window_from_capture(hwnd: int) -> bool:
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.SetWindowDisplayAffinity.restype = ctypes.c_bool
        return bool(
            user32.SetWindowDisplayAffinity(
                ctypes.c_void_p(hwnd),
                WDA_EXCLUDEFROMCAPTURE,
            )
        )
    except (AttributeError, OSError):
        return False


class CapturePreviewDialog(QDialog):
    def __init__(
        self,
        capture: JwlWindowCapture,
        *,
        source_description: str,
    ) -> None:
        super().__init__()
        self.capture = capture
        self._affinity_applied = False
        self.setWindowTitle("Meeting Assistant — prova de captura da Tela do Salão")
        self.resize(1050, 690)
        self.setMinimumSize(720, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QLabel("CAPTURA DIRETA — TELA DO SALÃO")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        self.source_label = QLabel(source_description)
        self.source_label.setWordWrap(True)
        root.addWidget(self.source_label)

        self.stats_label = QLabel("Aguardando primeiro frame…")
        root.addWidget(self.stats_label)

        self.preview = QLabel("Iniciando Windows Graphics Capture…")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(640, 360)
        self.preview.setStyleSheet(
            "background: #000; color: #ddd; border: 1px solid #444; font-size: 14px;"
        )
        root.addWidget(self.preview, 1)

        help_text = QLabel(
            "Este teste captura diretamente a Tela do Salão, sem depender de descobrir a "
            "janela fullscreen do JW Library. Primeiro confirme imagem e vídeo fluidos. "
            "Depois arraste esta janela de teste para cima da Tela do Salão: ela está marcada "
            "para ser excluída da captura e, portanto, o preview deve continuar mostrando o "
            "conteúdo do JW Library por baixo, sem efeito espelho/recursão."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #aaa;")
        root.addWidget(help_text)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close_button = QPushButton("Fechar teste")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

        self.capture.frame_ready.connect(self._on_frame)
        self.capture.status_changed.connect(self._on_status)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        if not self._affinity_applied:
            self._affinity_applied = _exclude_window_from_capture(int(self.winId()))
            suffix = (
                " • janela de teste excluída da captura"
                if self._affinity_applied
                else " • aviso: exclusão da janela de teste não pôde ser ativada"
            )
            self.source_label.setText(self.source_label.text() + suffix)

    def _on_frame(self, image: object, fps: float, width: int, height: int) -> None:
        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(scaled)
        self.stats_label.setText(
            f"Fonte: {width}×{height} • captura {fps:.1f} fps • preview ao vivo"
        )

    def _on_status(self, ok: bool, message: str) -> None:
        if ok:
            self.source_label.setText(self.source_label.text() + f"\n{message}")
        else:
            self.preview.clear()
            self.preview.setText(message)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        self.capture.stop()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Meeting Assistant Hall Capture Test")

    settings = SettingsService().load()
    displays = DisplayService(app).snapshot()
    hall_display = resolve_hall_display(displays, settings.hall_display_key)

    if hall_display is None:
        QMessageBox.critical(
            None,
            "Tela do Salão não encontrada",
            "Não foi possível resolver a Tela do Salão configurada.\n\n"
            "Abra Ajustes no Meeting Assistant e selecione a segunda tela física.",
        )
        return 2

    monitor_index = monitor_index_for_display(displays, hall_display)
    if monitor_index is None:
        QMessageBox.critical(
            None,
            "Índice da Tela do Salão não encontrado",
            f"Tela resolvida: {hall_display.label}\n\n"
            "A tela existe, mas não foi possível mapear o índice de captura.",
        )
        return 3

    source_description = (
        f"Tela do Salão: {hall_display.label}\n"
        f"Windows Graphics Capture: monitor {monitor_index}"
    )

    capture = JwlWindowCapture(ui_interval_ms=33)
    dialog = CapturePreviewDialog(capture, source_description=source_description)
    dialog.show()

    if not capture.start_monitor(monitor_index):
        return app.exec()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
