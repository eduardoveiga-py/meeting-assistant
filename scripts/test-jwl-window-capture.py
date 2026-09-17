from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QPixmap
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
from meeting_assistant.services.jwl_service import JwlService
from meeting_assistant.services.jwl_window_capture import (
    JwlWindowCapture,
    select_jwl_capture_target,
)
from meeting_assistant.services.settings import SettingsService


class CapturePreviewDialog(QDialog):
    def __init__(
        self,
        capture: JwlWindowCapture,
        *,
        source_description: str,
    ) -> None:
        super().__init__()
        self.capture = capture
        self.setWindowTitle("Meeting Assistant — teste de captura direta do JW Library")
        self.resize(1050, 690)
        self.setMinimumSize(720, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QLabel("CAPTURA DIRETA — JW LIBRARY")
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
            "Teste principal: com o vídeo/foto rodando, arraste esta janela e cubra a janela "
            "do JW Library na Tela 2. O preview deve continuar atualizando. "
            "Não minimize nem feche a janela-fonte neste teste."
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
        self.source_label.setText(message)
        if not ok:
            self.preview.clear()
            self.preview.setText(message)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        self.capture.stop()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Meeting Assistant Capture Test")

    settings = SettingsService().load()
    displays = DisplayService(app).snapshot()
    hall_display = resolve_hall_display(displays, settings.hall_display_key)

    jwl_service = JwlService()
    windows = jwl_service.scan(include_hidden=False)
    target = select_jwl_capture_target(windows, hall_display)

    if target is None:
        hall_text = hall_display.label if hall_display else "nenhuma Tela do Salão resolvida"
        QMessageBox.critical(
            None,
            "Saída do JW Library não encontrada",
            "Não encontrei uma janela visível do JW Library na Tela do Salão.\n\n"
            f"Tela resolvida: {hall_text}\n\n"
            "Abra a saída do JW Library na segunda tela e execute este teste novamente.",
        )
        return 2

    window = target.window
    hall_text = hall_display.label if hall_display else "fallback de diagnóstico"
    source_description = (
        f"Alvo: HWND {window.hwnd} • {window.size} • {window.title or window.process_name}\n"
        f"Tela do Salão: {hall_text}"
    )

    capture = JwlWindowCapture(ui_interval_ms=33)
    dialog = CapturePreviewDialog(capture, source_description=source_description)
    dialog.show()

    if not capture.start(window.hwnd):
        return app.exec()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
