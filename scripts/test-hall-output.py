from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QImage, QScreen
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


def _screen_for_display(screens: list[QScreen], display: object) -> QScreen | None:
    """Resolve QScreen by exact geometry instead of relying on list indexes."""

    for screen in screens:
        geometry = screen.geometry()
        if (
            geometry.x(),
            geometry.y(),
            geometry.width(),
            geometry.height(),
        ) == (
            display.x,
            display.y,
            display.width,
            display.height,
        ):
            return screen
    return None


class HallOutputTestDialog(QDialog):
    def __init__(
        self,
        *,
        capture: JwlWindowCapture,
        hall_output: HallOutputWindow,
        hall_screen: QScreen,
        idle_store: HallIdleReferenceStore,
        hall_description: str,
    ) -> None:
        super().__init__()
        self.capture = capture
        self.hall_output = hall_output
        self.hall_screen = hall_screen
        self.idle_store = idle_store
        self.latest_frame = QImage()
        self._output_started = False

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

        self.capture_status = QLabel("Iniciando captura antes de abrir a saída fullscreen…")
        self.capture_status.setWordWrap(True)
        root.addWidget(self.capture_status)

        self.output_status = QLabel(
            "A HallOutputWindow só será mostrada depois que chegar o primeiro frame válido."
        )
        self.output_status.setWordWrap(True)
        root.addWidget(self.output_status)

        explanation = QLabel(
            "A janela do Salão nunca é aberta antes da captura funcionar. Quando o primeiro "
            "frame chegar, ela cobre somente a Tela do Salão e fica excluída da própria "
            "captura. Com o Texto do Ano visível no JW Library, use 'Salvar repouso'. Depois "
            "teste os dois fades enquanto troca entre Texto do Ano, foto e vídeo."
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
                f"Referência de repouso carregada: {idle.width()}×{idle.height()}. "
                "Aguardando captura para abrir a Tela do Salão."
            )
        else:
            self.show_idle_button.setEnabled(False)

        self.save_idle_button.setEnabled(False)
        self.show_media_button.setEnabled(False)

    def _on_frame(self, image: object, fps: float, width: int, height: int) -> None:
        if not isinstance(image, QImage):
            return

        self.latest_frame = image.copy()
        self.hall_output.update_media_frame(image)
        self.capture_status.setText(
            f"Captura: {width}×{height} • {fps:.1f} fps • frames ao vivo chegando normalmente"
        )

        if not self._output_started:
            self.hall_output.show_media(animated=False)
            self.hall_output.show_on_screen(self.hall_screen)
            self._output_started = True
            self.save_idle_button.setEnabled(True)
            self.show_media_button.setEnabled(True)
            self.output_status.setText(
                "Primeiro frame recebido. HallOutputWindow aberta somente na Tela do Salão."
            )

    def _on_capture_status(self, ok: bool, message: str) -> None:
        prefix = "Captura OK" if ok else "Falha de captura"
        self.capture_status.setText(f"{prefix}: {message}")
        if not ok and not self._output_started:
            self.output_status.setText(
                "A saída fullscreen NÃO foi aberta porque a captura falhou. "
                "A tela principal permanece intacta."
            )

    def _on_exclusion_changed(self, excluded: bool) -> None:
        if excluded:
            self.output_status.setText(
                "HallOutputWindow na Tela do Salão • excluída da captura • sem recursão"
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

    hall_screen = _screen_for_display(app.screens(), hall_display)
    if hall_screen is None:
        QMessageBox.critical(
            None,
            "Tela não encontrada",
            f"A Tela do Salão foi detectada, mas seu QScreen não corresponde à geometria "
            f"{hall_display.x},{hall_display.y} {hall_display.width}×{hall_display.height}.",
        )
        return 4

    capture = JwlWindowCapture(ui_interval_ms=33)
    hall_output = HallOutputWindow(fade_duration_ms=320)
    idle_store = HallIdleReferenceStore()

    controller = HallOutputTestDialog(
        capture=capture,
        hall_output=hall_output,
        hall_screen=hall_screen,
        idle_store=idle_store,
        hall_description=(
            f"Tela do Salão: {hall_display.label}\n"
            f"Captura: monitor {monitor_index} • saída só abre após o primeiro frame válido"
        ),
    )
    controller.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    controller.show()

    capture.start_monitor(monitor_index)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
