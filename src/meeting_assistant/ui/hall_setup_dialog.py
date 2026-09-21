from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from meeting_assistant.services.hall_capture import capture_png
from meeting_assistant.ui.window_geometry import ScreenFitController


class HallSetupDialog(QDialog):
    def __init__(self, store, target_provider, obs, settings, parent=None, embedded=False):
        super().__init__(parent)
        self.store, self.target_provider, self.obs, self.settings = store, target_provider, obs, settings
        self.pending_png = None
        self.setWindowTitle("Texto do Ano e fontes do OBS")
        self.resize(610, 700)
        self.setMinimumSize(340, 240)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        root = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        hint = QLabel(
            "Usa os ajustes já salvos. Deixe somente o Texto do Ano no JWL, sem mídia, "
            "Zoom ou outras janelas na Tela do Salão. A foto não altera a calibração do sensor."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.photo_status = QLabel()
        self.photo_status.setWordWrap(True)
        root.addWidget(self.photo_status)
        self.preview = QLabel("Nenhuma foto salva")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.preview.setMinimumHeight(150)
        self.preview.installEventFilter(self)
        root.addWidget(self.preview)
        self.year = QSpinBox()
        self.year.setRange(2000, datetime.now().year + 1)
        self.year.setValue(datetime.now().year)
        self.year.setPrefix("Ano do texto: ")
        root.addWidget(self.year)
        self.confirm = QCheckBox("Conferi a foto do Texto do Ano e o ano.")
        outer.addWidget(self.confirm)
        self.capture_button = QPushButton("Capturar foto da Tela do Salão")
        self.capture_button.clicked.connect(self._capture)
        root.addWidget(self.capture_button)
        self.save_button = QPushButton("Salvar foto e aplicar no OBS")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)
        self.confirm.toggled.connect(self._update_save_state)
        self.year.valueChanged.connect(lambda _: self.confirm.setChecked(False))
        outer.addWidget(self.save_button)
        self.apply_button = QPushButton("Aplicar foto já salva no OBS")
        self.apply_button.clicked.connect(self._apply)
        root.addWidget(self.apply_button)
        media = QPushButton("Preparar janela JWL em Mídias")
        media.clicked.connect(self._media)
        root.addWidget(media)
        virtual = QPushButton("Ligar e verificar câmera virtual")
        virtual.clicked.connect(self.obs.ensure_virtual_camera)
        root.addWidget(virtual)
        inspect = QPushButton("Verificar fontes e câmera virtual")
        inspect.clicked.connect(
            lambda: self.obs.hall_task(
                "inspect",
                {
                    "background": self.settings.scene_background,
                    "media": self.settings.scene_media,
                },
            )
        )
        root.addWidget(inspect)
        self.result = QLabel("Nenhuma operação solicitada.")
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.result)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("Fechar")
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.obs.hall_task_finished.connect(self._finished)
        self._refresh_photo()
        if embedded:
            self.setWindowFlags(Qt.Widget)
            buttons.hide()
            self.setMinimumSize(0, 0)
        else:
            self._fit = ScreenFitController(self)

    def _local_obs(self) -> bool:
        if self.settings.obs_host.lower() not in {"localhost", "127.0.0.1", "::1"}:
            self.result.setText("Aplicação de arquivo/janela requer OBS neste mesmo computador.")
            return False
        return True

    def _refresh_photo(self):
        current = self.store.current()
        message = self.store.status()
        if current:
            message += f"\nCapturada em {current['captured_at']}."
            message += " Aplicação OBS pendente." if current.get("obs_pending") else " Aplicada ao OBS."
            if self.pending_png is None:
                self._preview(QImage(current["path"]))
        elif self.pending_png is None:
            if hasattr(self, "_preview_image"):
                del self._preview_image
            self.preview.clear()
            self.preview.setText("Nenhuma foto salva")
        if self.pending_png is not None:
            message = "Nova prévia — ainda NÃO salva.\n" + message
        self.photo_status.setText(message)
        self.apply_button.setEnabled(current is not None)
        self.capture_button.setText(
            "Atualizar foto — capturar JWL" if current else "Criar foto — capturar JWL"
        )

    def _preview(self, image, width=None):
        self._preview_image = image
        width = min(520, max(1, (width or self.preview.width()) - 4))
        self.preview.setPixmap(
            QPixmap.fromImage(image).scaled(width, 292, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def eventFilter(self, watched, event):
        if watched is self.preview and event.type() == QEvent.Resize and hasattr(self, "_preview_image"):
            self._preview(self._preview_image, event.size().width())
        return super().eventFilter(watched, event)

    def _update_save_state(self):
        self.save_button.setEnabled(self.pending_png is not None and self.confirm.isChecked())

    def _capture(self):
        # A failed recapture must never leave an older pending image saveable.
        self.pending_png = None
        self.confirm.setChecked(False)
        self._update_save_state()
        self._refresh_photo()
        try:
            before = self.target_provider()
            png = capture_png(before)
            after = self.target_provider()
            if before["hwnd"] != after["hwnd"] or before["rect"] != after["rect"]:
                raise ValueError("A janela mudou durante a captura. Tente novamente.")
            self.pending_png = png
            self.confirm.setChecked(False)
            self._update_save_state()
            self._refresh_photo()
            self._preview(QImage.fromData(png))
            self.result.setText("Prévia capturada. Confira o ano e marque a confirmação antes de salvar.")
        except Exception as exc:
            self.result.setText(
                str(exc) if isinstance(exc, ValueError) else "Não foi possível capturar o JWL."
            )

    def _save(self):
        if self.pending_png is None or not self.confirm.isChecked():
            self.result.setText("Confira a prévia e confirme que ela contém o Texto do Ano informado.")
            return
        try:
            self.store.save(self.pending_png, self.year.value())
        except (ValueError, OSError) as exc:
            self.result.setText(str(exc))
            return
        self.pending_png = None
        self.save_button.setEnabled(False)
        self._refresh_photo()
        self.result.setText("Foto salva localmente. Aguardando aplicação no OBS.")
        self._apply()

    def _apply(self):
        if self._local_obs():
            self.obs.hall_task(
                "yeartext",
                {
                    "directory": str(self.store.directory),
                    "scene": self.settings.scene_background,
                },
            )

    def _media(self):
        if not self._local_obs():
            return
        try:
            target = self.target_provider()
        except Exception as exc:
            self.result.setText(str(exc) if isinstance(exc, ValueError) else "JWL indisponível.")
            return
        answer = QMessageBox.question(
            self,
            "Preparar Mídias",
            "Criar/atualizar a fonte gerenciada JWL na cena Mídias? "
            "Fontes existentes serão preservadas. Confira o resultado no OBS.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.obs.hall_task(
                "media", {"scene": self.settings.scene_media, "selectors": target["selectors"]}
            )

    def _finished(self, action, ok, message):
        if self.pending_png is not None and action == "yeartext":
            message += " A nova prévia ainda não foi salva; confira e confirme para salvar."
        self.result.setText(message)
        if action == "yeartext":
            self._refresh_photo()
