"""Window-local controls: use the existing actions, never intercept other apps."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMessageBox

LABELS = (
    "Ajuda de atalhos",
    "Texto do Ano",
    "Palco",
    "Mídia",
    "Zoom → Salão / voltar ao JWL",
    "Ativar / pausar automação",
    "Contingência → Palco ou Texto do Ano",
    "Iniciar reunião",
    "Operação: preparar / resolver",
    "Ajustes",
)


class MainWindowShortcuts:
    def __init__(self, owner, callbacks):
        self.owner = owner
        self.shortcuts = []
        actions = [self.show_help, *callbacks]
        if len(actions) != 10:
            raise ValueError("São necessárias nove ações além da ajuda.")
        for number, action in enumerate(actions, 1):
            shortcut = QShortcut(QKeySequence(f"F{number}"), owner)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(lambda fn=action: self.dispatch(fn))
            self.shortcuts.append(shortcut)
        owner.setToolTip("F1: atalhos. Ativos somente nesta tela, com o app em foco.")

    def dispatch(self, action):
        if (
            QApplication.activeWindow() is self.owner
            and QApplication.activeModalWidget() is None
            and QApplication.activePopupWidget() is None
        ):
            action()

    def show_help(self):
        QMessageBox.information(
            self.owner,
            "Atalhos da tela principal",
            "\n".join(f"F{i} — {label}" for i, label in enumerate(LABELS, 1))
            + "\n\nFuncionam somente com esta tela em foco. "
            "No notebook, pode ser necessário Fn + F1…F10.",
        )

