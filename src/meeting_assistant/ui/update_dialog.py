"""Review release notes before installing or intentionally restoring a version."""

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QLabel, QPushButton, QTextBrowser, QVBoxLayout

from meeting_assistant.services.release_check import version_tuple
from meeting_assistant.ui.window_geometry import ScreenFitController


class UpdateDialog(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Atualizações e versões anteriores")
        self.resize(600, 560)
        layout = QVBoxLayout(self)
        self.status = QLabel("Consultando Releases…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.versions = QComboBox()
        layout.addWidget(self.versions)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        layout.addWidget(self.notes, 1)
        self.rollback = QCheckBox("Quero restaurar a versão anterior selecionada; fiz backup dos ajustes.")
        layout.addWidget(self.rollback)
        self.install = QPushButton("Instalar versão selecionada")
        layout.addWidget(self.install)
        self.retry = QPushButton("Atualizar lista")
        self.retry.clicked.connect(service.request_history)
        layout.addWidget(self.retry)
        close = QPushButton("Fechar")
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        self.install.clicked.connect(self._install)
        self.versions.currentIndexChanged.connect(self._selection)
        self.rollback.toggled.connect(self._selection)
        service.history_ready.connect(self._loaded)
        service.status_changed.connect(self._status)
        service.operation_finished.connect(self._finished)
        self.finished.connect(self._disconnect)
        self._fit = ScreenFitController(self)
        self.install.setEnabled(False)
        service.request_history()

    def _loaded(self, offers):
        self.versions.clear()
        for offer in offers:
            self.versions.addItem(f"v{offer['version']} — {offer['name']}", offer)
        self._selection()

    def _selection(self):
        offer = self.versions.currentData()
        if not offer:
            self.install.setEnabled(False)
            return
        self.notes.setMarkdown(offer["notes"])
        older = version_tuple(offer["version"]) <= version_tuple(self.service.installed_version)
        self.rollback.setVisible(older and self.service.frozen)
        if self.service.frozen:
            self.install.setText("Restaurar versão" if older else "Instalar atualização")
            self.install.setEnabled(
                bool(offer["url"]) and (not older or self.rollback.isChecked()) and not self.service.busy
            )
        else:
            self.install.setText("Ver instruções para atualizar pelo Git")
            self.install.setEnabled(True)

    def _install(self):
        offer = self.versions.currentData()
        if offer:
            self.service.download_and_install_async(
                offer["url"], offer["version"], allow_rollback=self.rollback.isChecked()
            )

    def _status(self, message, busy):
        self.status.setText(message)
        self.retry.setEnabled(not busy)
        self.install.setEnabled(False) if busy else self._selection()

    def _finished(self):
        self.retry.setEnabled(True)
        self._selection()

    def _disconnect(self):
        self.service.history_ready.disconnect(self._loaded)
        self.service.status_changed.disconnect(self._status)
        self.service.operation_finished.disconnect(self._finished)
