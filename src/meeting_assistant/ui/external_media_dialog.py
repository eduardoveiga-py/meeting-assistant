"""Index-based window selection with bounded layout and no native calls."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
)

from meeting_assistant.ui.window_geometry import ScreenFitController, fit_window


class ExternalMediaDialog(QDialog):
    def __init__(self, candidates, parent=None):
        super().__init__(parent)
        self.candidates = tuple(candidates)
        self.setWindowTitle("Mídia externa")
        self.resize(520, 350)
        self.setMinimumSize(300, 220)
        fit_window(self)
        layout = QVBoxLayout(self)
        hint = QLabel("Escolha o player ou navegador para apresentar no Salão e nas chamadas.")
        hint.setWordWrap(True)
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(hint)
        self.windows = QListWidget()
        self.windows.setMinimumWidth(0)
        self.windows.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.windows.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.windows.setTextElideMode(Qt.TextElideMode.ElideRight)
        for index, candidate in enumerate(self.candidates, 1):
            text = f"{index}. {candidate.process} — {candidate.title}"
            item = QListWidgetItem(text, self.windows)
            item.setToolTip(text)
        layout.addWidget(self.windows, 1)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apresentar")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.windows.currentRowChanged.connect(self._selection_changed)
        self.windows.itemDoubleClicked.connect(lambda _: self.accept())
        layout.addWidget(self.buttons)
        self.windows.setCurrentRow(0 if self.candidates else -1)
        self._selection_changed(self.windows.currentRow())
        self._screen_fit = ScreenFitController(self)

    def _selection_changed(self, index):
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(0 <= index < len(self.candidates))

    def selected_window(self):
        index = self.windows.currentRow()
        return self.candidates[index] if 0 <= index < len(self.candidates) else None
