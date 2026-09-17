from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QImage
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from meeting_assistant.services.display_service import DisplayService, resolve_hall_display
from meeting_assistant.services.hall_idle_reference import HallIdleReferenceStore
from meeting_assistant.services.jwl_window_capture import JwlWindowCapture, monitor_index_for_display
from meeting_assistant.services.settings import SettingsService
from meeting_assistant.ui.hall_output_window import HallOutputWindow


class HallOutputTestDialog(QDialog):
    def __init__(
        self,
        *,
        capture: JwlWindowCapture,
        hall_output: HallOutputWindow,
        idle_store: HallIdleReferenceStore,
        hall_description: str,
    ) -> None:
        super().__init__()
        self.capture = capture
        self.hall_output = hall_output
        self.idle_store = idle_store
        self.latest_frame = QImage()

        self.setWindowTitle("Meeting Assistant — teste da Saída do Salão")
        self.resize(620, 330)
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("SAÍDA DO SALÃO — FASE 2")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        description = QLabel(hall_description)
        description.setWordWrap(True)
        root.addWidget(description)

        self.capture_status = QLabel("Iniciando captura…")
        self.capture_status.setWordWrap(True)
        root.addWidget(self.capture_status)

        self.output_status = QLabel("Abrindo HallOutputWindow…")
        self.output_status.setWordWrap(True)
        root.addWidget(self.output_status)

        explanation = QLabel(
            "A segunda tela agora está coberta por uma janela do Meeting Assistant. "
            "Mesmo assim, a captura continua lendo o JW Library que está por baixo. "
            "Com o Texto do Ano visível no JW Library, use 'Salvar repouso'. Depois teste "
            "os dois fades enquanto troca entre Texto do Ano, foto e vídeo no JW Library."
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet("color: #666;")
        root.addWidget(explanation)

        buttons = QHBoxLayout()
        self.save_idle_button = QPushButton("Salvar repouso atual")
        self.show_idle_button = QPushButton("Fade → repouso")
        self.show_media_button = QPushButton("Fade → mídia")
        close_button = QPushButton("Fechar teste")

        self.save_idle_button.clicked.connect(self._save_idle)
        self.show_idle_button.clicked.connect(lambda _checked=False: self._show_idle())
        self.show_media_button.clicked.connect(lambda _checked=False: self._show_media())
        close_button.clicked.connect(self.close)

        buttons.addWidget(self.save_idle_button)
        buttons.addWidget(self.show_idle_button)
        buttons.addWidget(self.show_media_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        root.addLayout(buttons)

        self.capture.frame_ready.connect(self._on_frame)
        self.capture.status_changed.connect(self._on_capture_status)
        self.hall_output.capture_exclusion_changed.connect(self._on_exclusion_changed)

        idle = self.idle_store.load()
        if idle is not None:
            self.hall_output.set_idle_image(idle)
            self.show_idle_button.setEnabled(True)
            self.output_status.setText(
                f"Referência de repouso carregada: {idle.width()}×{idle.height()}."
            )
        else:
            self.show_idle_button.setEnabled(False)
            self.output_status.setText(
                "Nenhuma referência de repouso salva ainda. Mostre o Texto do Ano e salve."
            )

    def _on_frame(self, image: object, fps: float, width: int, height: int) -> None:
        if not isinstance(image, QImage):
            return
        self.latest_frame = image.copy()
        self.hall_output.update_media_frame(image)
        self.capture_status.setText(
            f"Captura: {width}×{height} • {fps:.1f} fps • frames ao vivo chegando normalmente"
        )

    def _on_capture_status(self, ok: bool, message: str) -> None:
        prefix = "Captura OK" if ok else "Falha de captura"
        self.capture_status.setText(f"{prefix}: {message}")

    def _on_exclusion_changed(self, excluded: bool) -> None:
        if excluded:
            self.output_status.setText(
                "HallOutputWindow fullscreen • excluída da captura • sem recursão"
            )
        else:
            self.output_status.setText(
                "ATENÇÃO: o Windows não confirmou a exclusão da HallOutputWindow da captura."
            )

    def _save_idle(self) -> None:
        if self.latest_frame.isNull():
            QMessageBox.warning(self, "Sem frame", "Ainda não chegou nenhum frame da Tela do Salão.")
            return
        if not self.idle_store.save(self.latest_frame):
            QMessageBox.warning(self, "Falha", "Não foi possível salvar a referência de repouso.")
            return
        self.hall_output.set_idle_image(self.latest_frame)
        self.show_idle_button.setEnabled(True)
        self.output_status.setText(
            "Referência de repouso salva. Agora os fades usam exatamente este quadro."
        )

    def _show_idle(self) -> None:
        if self.idle_store.load() is None:
            return
        self.hall_output.show_idle(animated=True)
        self.output_status.setText("Fade para repouso em execução.")

    def _show_media(self) -> None:
        self.hall_output.show_media(animated=True)
        self.output_status.setText("Fade para mídia ao vivo em execução.")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        self.capture.stop()
        self.hall_output.close()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Meeting Assistant Hall Output Test")

    settings = SettingsService().load()
    display_service = DisplayService(app)
    displays = display_service.snapshot()
    hall_display = resolve_hall_display(displays, settings.hall_display_key)

    if hall_display is None:
        QMessageBox.critical(
            None,
            "Tela do Salão não encontrada",
            "Selecione uma segunda tela física em Ajustes antes deste teste.",
        )
        return 2

    monitor_index = monitor_index_for_display(displays, hall_display)
    if monitor_index is None:
        QMessageBox.critical(
            None,
            "Captura não resolvida",
            f"Não foi possível mapear {hall_display.label} para Windows Graphics Capture.",
        )
        return 3

    hall_screen_index = next(
        (
            index
            for index, display in enumerate(displays)
            if display.key == hall_display.key
        ),
        None,
    )
    screens = app.screens()
    if hall_screen_index is None or hall_screen_index >= len(screens):
        QMessageBox.critical(None, "Tela não encontrada", "QScreen da Tela do Salão não foi resolvido.")
        return 4

    capture = JwlWindowCapture(ui_interval_ms=33)
    hall_output = HallOutputWindow(fade_duration_ms=320)
    idle_store = HallIdleReferenceStore()

    controller = HallOutputTestDialog(
        capture=capture,
        hall_output=hall_output,
        idle_store=idle_store,
        hall_description=(
            f"Tela do Salão: {hall_display.label}\n"
            f"Captura: monitor {monitor_index} • HallOutputWindow: fullscreen/excluída da captura"
        ),
    )
    controller.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    controller.show()

    hall_output.show_on_screen(screens[hall_screen_index])
    hall_output.show_media(animated=False)

    if not capture.start_monitor(monitor_index):
        controller.capture_status.setText("Falha ao iniciar a captura da Tela do Salão.")

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
