from __future__ import annotations

from dataclasses import replace
from threading import Thread

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from meeting_assistant.services import setup_assistant as service
from meeting_assistant.services.display_service import resolve_hall_display
from meeting_assistant.services.obs_setup import STANDARD_SCENES, camera_url
from meeting_assistant.services.preflight import Check
from meeting_assistant.ui.hall_setup_dialog import HallSetupDialog
from meeting_assistant.ui.settings_dialog import SettingsDialog
from meeting_assistant.ui.window_geometry import ScreenFitController


class SetupWorker(QObject):
    result = Signal(bool, object)
    finished = Signal()

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.thread = None

    def isRunning(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        self.thread = Thread(target=self.run, daemon=True, name="Setup operation")
        self.thread.start()

    def run(self):
        try:
            self.result.emit(True, self.operation())
        except ValueError as exc:
            self.result.emit(False, str(exc))
        except Exception:
            # Never render connection errors that may include secrets.
            self.result.emit(
                False, "Não foi possível concluir. Verifique conexão, permissões e tente novamente."
            )
        finally:
            self.finished.emit()


class SetupAssistantDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.worker = None
        self._completion = None
        self._close_pending = False
        self.setWindowTitle("Assistente de instalação e configuração")
        self.resize(660, 700)
        self.setMinimumSize(360, 280)
        root = QVBoxLayout(self)
        hint = QLabel(
            "Configure por etapas. Nada é instalado ou alterado sem selecionar uma ação. "
            "Você pode continuar depois; as pendências serão verificadas novamente."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.editor = SettingsDialog(owner.settings, owner.obs_scenes, self, embedded=True)
        self.tabs.addTab(self.editor, "1 · Ajustes")
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.tabs.addTab(scroll, "2 · Preparar")
        self.checks = QTextEdit()
        self.checks.setReadOnly(True)
        self.checks.setMinimumHeight(100)
        layout.addWidget(self.checks)
        self.manual_checks = []
        for label in (
            "Áudio e câmera IP conferidos no equipamento atual",
            "Duas janelas Zoom e retorno ao JWL conferidos",
        ):
            checkbox = QCheckBox(label)
            checkbox.setToolTip("Confirmação do operador nesta sessão; não é um teste automático.")
            checkbox.toggled.connect(self._render_checks)
            self.manual_checks.append(checkbox)
            layout.addWidget(checkbox)
        self._check_rows = []
        self.allow = QCheckBox("Autorizo a ação e os termos de instalação.")
        self.allow.setToolTip(
            "WinGet mantém a verificação de integridade. UAC/instalador podem abrir janelas do Windows."
        )
        layout.addWidget(self.allow)
        self.actions = []
        self._button(layout, "Verificar ambiente novamente", self._inspect)
        for app in ("OBS", "Zoom"):
            self._button(
                layout, f"Baixar e instalar {app} (WinGet)", lambda _=False, app=app: self._install(app)
            )
        self._button(layout, "Obter JW Library — Microsoft Store", self._store)
        self._button(layout, "Configurar WebSocket local (OBS fechado)", self._websocket)
        self._button(layout, "Abrir OBS", self._open_obs)
        self._button(layout, "Criar cenas padrão, preservando as existentes", self._scenes)
        self._button(layout, "Preparar câmera IP em Palco", self._camera)
        guide = QLabel(
            "OBS portátil: configure WebSocket em Ferramentas → Configurações do servidor WebSocket. "
            "Use a mesma porta e senha dos Ajustes. No Zoom, habilite dois monitores antes de entrar "
            "na reunião e selecione OBS Virtual Camera. Esses ajustes do Zoom exigem confirmação manual."
        )
        guide.setWordWrap(True)
        layout.addWidget(guide)
        self.hall = HallSetupDialog(
            owner.yeartext_store, owner._hall_capture_target, owner.obs, owner.settings, self, embedded=True
        )
        self.tabs.addTab(self.hall, "3 · Foto e fontes")
        self.status = QLabel("Salve os ajustes antes de preparar o ambiente.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        row = QHBoxLayout()
        save = QPushButton("Salvar ajustes")
        save.clicked.connect(self._save)
        row.addWidget(save)
        self.actions.append(save)
        finish = QPushButton("Registrar revisão desta versão")
        finish.clicked.connect(self._review)
        row.addWidget(finish)
        self.actions.append(finish)
        close = QPushButton("Continuar depois")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        root.addLayout(row)
        self._fit = ScreenFitController(self)
        owner.obs.setup_finished.connect(self._obs_finished)
        self._inspect()

    def _button(self, layout, text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        self.actions.append(button)

    def _save(self):
        pending = replace(self.owner.settings)
        self.editor.apply_to(pending)
        try:
            service.validate_settings(pending)
            self.owner._apply_assistant_settings(pending)
        except Exception as exc:
            self.status.setText(str(exc) if isinstance(exc, ValueError) else "Falha ao salvar ajustes.")
            return False
        self.status.setText("Ajustes salvos. Use Verificar ambiente novamente.")
        return True

    def _authorized(self):
        if not self.allow.isChecked():
            self.status.setText("Marque a autorização antes de executar a ação escolhida.")
            return False
        return self._save()

    def _run(self, operation, completion=None):
        if self.worker is not None and self.worker.isRunning():
            return
        self._completion = completion
        self.status.setText("Operação em andamento… aguarde. Instalações podem levar vários minutos.")
        for action in self.actions:
            action.setEnabled(False)
        self.editor.setEnabled(False)
        worker = SetupWorker(operation, self)
        self.worker = worker
        worker.result.connect(self._result)
        worker.finished.connect(self._unbusy)
        worker.start()

    def _unbusy(self):
        for action in self.actions:
            action.setEnabled(True)
        self.editor.setEnabled(True)
        self.allow.setChecked(False)
        if self._close_pending:
            self.done(QDialog.Rejected)

    def _result(self, ok, value):
        if isinstance(value, list):
            display = resolve_hall_display(
                self.owner.displays.snapshot(), self.owner.settings.hall_display_key
            )
            self._check_rows = value + [
                Check("CONEXÃO", "Tela do Salão conectada", display is not None),
                Check(
                    "CONFIGURAÇÃO", "Foto do Texto do Ano salva",
                    self.owner.yeartext_store.current() is not None,
                ),
            ]
            self._render_checks()
            self.status.setText("Verificação concluída. Pendências aparecem na aba Preparar.")
        else:
            self.status.setText(str(value))
        if ok and self._completion:
            self._completion()
        self._completion = None

    def _render_checks(self):
        manual = [
            "OPERADOR · " + ("CONFIRMADO" if check.isChecked() else "NÃO CONFIRMADO") + " · " + check.text()
            for check in self.manual_checks
        ]
        self.checks.setPlainText("\n".join([row.render() for row in self._check_rows] + manual))

    def _inspect(self):
        settings = replace(self.owner.settings)
        self._run(lambda: service.inspect_environment(settings))

    def _install(self, app):
        if self._authorized():
            self._run(lambda: service.install_application(app))

    def _store(self):
        if self._authorized():
            QDesktopServices.openUrl(QUrl("https://www.jw.org/pt/ajuda-online/jw-library/windows/"))
            self.status.setText(
                "Conclua a instalação oficial e use Verificar ambiente novamente. "
                "O assistente permanece aberto."
            )

    def _websocket(self):
        if self._authorized():
            settings = replace(self.owner.settings)
            self._run(lambda: service.configure_websocket(settings))

    def _open_obs(self):
        if self._authorized():
            configured = self.owner.settings.obs_executable

            def launch():
                if service.process_running("obs64.exe") or service.process_running("obs32.exe"):
                    return "OBS já está aberto. Use Verificar ambiente novamente."
                if not self.owner.launcher._launch_obs(configured):
                    raise ValueError("OBS não localizado. Instale ou informe o executável.")
                return "Abertura solicitada. Aguarde e use Verificar ambiente novamente."

            self._run(launch)

    def _scenes(self):
        if self._authorized():
            settings = replace(self.owner.settings)
            self._run(lambda: service.create_standard_scenes(settings), self._standard_mapping)

    def _standard_mapping(self):
        for combo, name in zip(
            (self.editor.background_combo, self.editor.speaker_combo, self.editor.media_combo),
            STANDARD_SCENES,
            strict=True,
        ):
            combo.setCurrentText(name)
        self._save()
        self.status.setText("Cenas padrão criadas e mapeadas. Prepare as fontes na aba Foto e fontes.")

    def _camera(self):
        if self._authorized():
            settings = self.owner.settings
            try:
                camera_url(
                    settings.camera_ip,
                    settings.camera_username,
                    settings.camera_password,
                    settings.camera_rtsp_port,
                )
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            self.status.setText("Preparação da câmera solicitada; aguardando OBS.")
            self.owner.obs.prepare_stage(settings)
            self.allow.setChecked(False)

    def _obs_finished(self, ok, message):
        if ok:
            self._standard_mapping()
        self.status.setText(message)

    def _review(self):
        # Acknowledging a review is not a claim that physical tests passed.
        if self._save():
            self.owner.settings.setup_review_version = service.review_key()
            self.owner.settings_service.save(self.owner.settings)
            self.status.setText("Revisão registrada. Os testes físicos pendentes continuam necessários.")

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            self._close_pending = True
            self.status.setText("Fechamento solicitado; aguardando a operação terminar.")
            return
        self.done(QDialog.Rejected)

    def closeEvent(self, event):
        event.ignore()
        self.reject()
