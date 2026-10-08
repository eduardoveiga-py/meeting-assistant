from __future__ import annotations

from dataclasses import replace
from threading import Thread

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from meeting_assistant.services import setup_assistant as service
from meeting_assistant.services.display_service import resolve_hall_display
from meeting_assistant.services.obs_setup import STANDARD_SCENES
from meeting_assistant.services.preflight import Check
from meeting_assistant.ui.audio_setup_dialog import AudioSetupDialog
from meeting_assistant.ui.hall_setup_dialog import HallSetupDialog
from meeting_assistant.ui.obs_maintenance_panel import ObsMaintenancePanel
from meeting_assistant.ui.settings_dialog import SettingsDialog
from meeting_assistant.ui.virtual_camera_dialog import VirtualCameraDialog
from meeting_assistant.ui.window_geometry import ScreenFitController, fit_window


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
    def __init__(self, owner, *, page="installation"):
        super().__init__(owner)
        self.owner = owner
        self.worker = None
        self._completion = None
        self._close_pending = False
        self.deferred_action = None
        self._views_disconnected = False
        self.setWindowTitle("Ajustes — Meeting Assistant")
        # The native Windows style gives QTextEdit a white viewport even when
        # the parent has a dark QWidget rule. Specify both colors for reports.
        self.setStyleSheet(
            "QTextEdit { background: #0e141c; color: #f2f4f8; border: 1px solid #46546a; }"
        )
        self.resize(620, 700)
        self.setMinimumSize(360, 280)
        # Video children can create native handles before Show; bound the size
        # before constructing them, then fit again after the form is complete.
        fit_window(self)
        root = QVBoxLayout(self)
        self.navigation = QComboBox()
        self.navigation.setAccessibleName("Categoria dos ajustes")
        root.addWidget(self.navigation)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        root.addWidget(self.hint)
        self.pages = QStackedWidget()
        # QStackedLayout includes hidden pages in height-for-width constraints.
        # Windows can then enlarge the dialog beyond fit_window's work area.
        # A viewport bounds the stack without propagating that preferred height.
        # Existing pages own their scrolling; navigation and Save/Close stay fixed.
        self.page_viewport = QAbstractScrollArea()
        self.page_viewport.setObjectName("SettingsPagesViewport")
        self.page_viewport.setFrameShape(QFrame.NoFrame)
        self.page_viewport.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.page_viewport.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.page_viewport.setViewport(self.pages)
        root.addWidget(self.page_viewport, 1)
        self.editor = SettingsDialog(owner.settings, owner.obs_scenes, self, embedded=True)
        self.editor.hide()
        self.actions = []
        self.manual_checks = []
        self._check_rows = []
        self.status = QLabel("Alterações de configuração só são salvas ao clicar em Salvar ajustes.")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        meeting = self.editor.sections["meeting"]
        self._page(
            "meeting",
            "Reunião e janelas",
            meeting,
            "Link da reunião, aplicativos, monitor do Salão e disposição das janelas.",
        )
        meeting_layout = meeting.widget().layout()
        layouts = QGroupBox("Disposição das janelas")
        layouts_body = QVBoxLayout(layouts)
        self._button(layouts_body, "Salvar disposição atual", lambda: owner._persist_layout(capture=True))
        self._button(layouts_body, "Aplicar disposição salva", owner._restore_layout)
        meeting_layout.insertWidget(meeting_layout.count() - 1, layouts)

        self.video_tabs = QTabWidget()
        self._page(
            "video",
            "OBS e vídeo",
            self.video_tabs,
            "Conecte o OBS, complete as fontes e confira o Texto do Ano. O Program não muda ao preparar.",
        )
        connection = self.editor.sections["video"]
        self.video_tabs.addTab(connection, "Conexão")
        connection_body = connection.widget().layout()
        self._button(connection_body, "Aplicar câmera IP em Palco", self._camera)
        self.maintenance = ObsMaintenancePanel(owner, self._save, self._can_prepare, self)
        self.maintenance.plugins_requested.connect(lambda: self.select_page("installation"))
        self.video_tabs.addTab(self.maintenance, "Fontes")
        self.hall = HallSetupDialog(
            owner.yeartext_store,
            owner._hall_capture_target,
            owner.obs,
            owner.settings,
            self,
            embedded=True,
            photo_only=True,
            before_apply=self._save,
        )
        self.video_tabs.addTab(self.hall, "Texto do Ano")
        self.camera = VirtualCameraDialog(self, owner.camera_session, embedded=True)
        self.video_tabs.addTab(self.camera, "WhatsApp")
        self.audio = AudioSetupDialog(
            owner.obs, owner.settings, self, settings_service=owner.settings_service,
            embedded=True, before_route=self._save,
        )
        self.audio.tabs.setCurrentIndex(1)
        self._page(
            "audio",
            "Áudio",
            self.audio,
            "Volumes não alteram o som do Salão.",
        )
        # The same checkbox is saved by the editor, with no duplicate audio setting.
        self.audio.volume_body.insertWidget(2, self.editor.auto_mute_mic_for_jwl_media)

        self.installation_scroll = QScrollArea()
        self.installation_scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        self.installation_scroll.setWidget(body)
        self._page(
            "installation",
            "Instalação e plugins",
            self.installation_scroll,
            "Use na instalação ou manutenção. Instalações requerem autorização; "
            "feche OBS antes de trocar plugins.",
        )
        self.checks = QTextEdit()
        self.checks.setReadOnly(True)
        self.checks.setMinimumHeight(120)
        layout.addWidget(self.checks)
        self._button(layout, "Verificar ambiente", self._inspect)
        for label in (
            "Áudio e câmera IP testados",
            "Zoom e retorno JWL testados",
        ):
            checkbox = QCheckBox(label)
            checkbox.setToolTip("Confirmação do operador nesta sessão; não é um teste automático.")
            checkbox.toggled.connect(self._render_checks)
            self.manual_checks.append(checkbox)
            layout.addWidget(checkbox)
        self._button(layout, "Registrar revisão desta versão", self._review)
        self.allow = QCheckBox("Autorizo a instalação e seus termos.")
        layout.addWidget(self.allow)
        apps = QGroupBox("Aplicativos")
        apps_body = QVBoxLayout(apps)
        for app in ("OBS", "Zoom"):
            self._button(apps_body, f"Instalar {app} (WinGet)", lambda _=False, app=app: self._install(app))
        self._button(apps_body, "Obter JW Library (Store)", self._store)
        self._button(apps_body, "Instalar cabos virtuais (ZIP)", self._install_virtual_cables)
        self._button(apps_body, "Abrir OBS", self._open_obs)
        layout.addWidget(apps)
        plugins = QGroupBox("OBS fechado: conexão e plugins")
        plugins_body = QVBoxLayout(plugins)
        self._button(plugins_body, "Configurar WebSocket local", self._websocket)
        self._button(plugins_body, "Instalar/reparar captura JWL", self._jwl_plugin)
        self._button(plugins_body, "Instalar Audio Monitor", self._audio_monitor)
        self._button(plugins_body, "Câmera e ponte nativas", self._native)
        layout.addWidget(plugins)
        guide = QLabel(
            "Depois da instalação, reabra o OBS e use OBS e vídeo → Fontes → Verificar. "
            "O Audio Monitor só é necessário no perfil com retorno do Zoom para o WhatsApp. "
            "No Zoom, habilite dois monitores antes de entrar e selecione OBS Virtual Camera."
        )
        guide.setWordWrap(True)
        guide.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(guide)
        layout.addStretch()

        diagnostics = self.editor.sections["diagnostics"]
        self._page(
            "diagnostics",
            "Diagnóstico",
            diagnostics,
            "Telemetria, exportação, atualizações e calibração. Verificações técnicas ficam aqui.",
        )
        diagnostic_body = diagnostics.widget().layout()
        tools = QGroupBox("Ferramentas")
        tools_body = QVBoxLayout(tools)
        self._button(tools_body, "Observar mídia no JWL (20 s)", lambda: self._defer(owner._start_jwl_probe))
        self._button(
            tools_body, "Calibrar Texto do Ano", lambda: self._defer(owner._calibrate_idle_reference)
        )
        self._button(
            tools_body, "Histórico de atualizações", lambda: self._defer(owner._trigger_update)
        )
        diagnostic_body.insertWidget(0, tools)
        root.addWidget(self.status)
        row = QHBoxLayout()
        self.save_button = QPushButton("Salvar ajustes")
        self.save_button.clicked.connect(self._save)
        row.addWidget(self.save_button)
        self.actions.append(self.save_button)
        close = QPushButton("Fechar")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        root.addLayout(row)
        self._fit = ScreenFitController(self)
        owner.obs.setup_finished.connect(self._obs_finished)
        self.audio.controller.audio_task_finished.connect(self._audio_idle)
        self.maintenance.idle.connect(self._maybe_close)
        self.maintenance.activity_changed.connect(self._maintenance_activity)
        self.finished.connect(self._disconnect_views)
        self.navigation.currentIndexChanged.connect(self._page_changed)
        self.select_page(page)
        # Bound the requested size before Windows creates the native dialog.
        # Fitting only after Show can race queued native resize events at high DPI.
        fit_window(self)
        if page == "installation":
            self._inspect()

    def _page(self, key, title, widget, hint):
        self.navigation.addItem(title, (key, self.pages.addWidget(widget), hint))

    def select_page(self, key):
        for index in range(self.navigation.count()):
            if self.navigation.itemData(index)[0] == key:
                self.navigation.setCurrentIndex(index)
                self._page_changed(index)
                return

    def _page_changed(self, index):
        key, page, hint = self.navigation.itemData(index)
        self.pages.setCurrentIndex(page)
        self.hint.setText(hint)
        self.save_button.setVisible(key != "audio")
        self.status.setVisible(key != "audio")

    def _can_prepare(self):
        if self._busy():
            self.status.setText("Aguarde a operação atual antes de preparar ou instalar.")
            return False
        if (
            self.owner.state.automation_enabled
            or self.owner.zoom_hall.active
            or self.owner.zoom_hall.returning
        ):
            self.status.setText("Pause a automação e retorne ao JWL antes de preparar fontes ou instalar.")
            return False
        if self.owner.external_media and self.owner.external_media.active:
            self.status.setText("Encerre a mídia externa antes de preparar o ambiente.")
            return False
        return True

    def _defer(self, action):
        if not self._save():
            return
        self.deferred_action = action
        self.reject()

    def _audio_idle(self, *_args):
        self._maybe_close()

    def _maintenance_activity(self, busy):
        for action in self.actions:
            action.setEnabled(not busy)
        for page in self.editor.sections.values():
            page.setEnabled(not busy)
        self.audio.setEnabled(not busy)
        self.hall.setEnabled(not busy)

    def _maybe_close(self):
        if self._close_pending and not self._busy():
            self.reject()

    def _busy(self):
        return bool(
            self.worker is not None and self.worker.isRunning() or self.audio.busy or self.maintenance.busy
        )

    def _disconnect_views(self, *_args):
        if self._views_disconnected:
            return
        self._views_disconnected = True
        self.audio.disconnect_results()
        self.audio.controller.audio_task_finished.disconnect(self._audio_idle)
        self.hall.disconnect_results()
        self.camera.disconnect_results()
        self.maintenance.disconnect_results()
        self.owner.obs.setup_finished.disconnect(self._obs_finished)

    def _jwl_plugin(self):
        if self._authorized():
            from meeting_assistant.services.obs_plugins import install_jwl_plugin

            settings = replace(self.owner.settings)
            self._run(lambda: install_jwl_plugin(settings))

    def _audio_monitor(self):
        if self._authorized():
            from meeting_assistant.services.obs_plugins import install_audio_monitor

            settings = replace(self.owner.settings)
            self._run(lambda: install_audio_monitor(settings))

    def _button(self, layout, text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        layout.addWidget(button)
        self.actions.append(button)

    def _save(self):
        pending = replace(self.owner.settings)
        self.editor.apply_to(pending)
        try:
            service.validate_settings(pending)
            if pending != self.owner.settings:
                self.owner._apply_assistant_settings(pending)
        except Exception as exc:
            self.status.setText(str(exc) if isinstance(exc, ValueError) else "Falha ao salvar ajustes.")
            self.status.show()
            return False
        self.status.setText("Ajustes salvos.")
        return True

    def _authorized(self):
        if not self._can_prepare():
            return False
        if not self.allow.isChecked():
            self.status.setText("Marque a autorização antes de executar a ação escolhida.")
            return False
        return self._save()

    def _run(self, operation, completion=None):
        if self._busy():
            self.status.setText("Aguarde a operação atual antes de continuar.")
            return
        self._completion = completion
        self.status.setText("Operação em andamento… aguarde. Instalações podem levar vários minutos.")
        for action in self.actions:
            action.setEnabled(False)
        for page in self.editor.sections.values():
            page.setEnabled(False)
        self.audio.setEnabled(False)
        self.maintenance.setEnabled(False)
        self.hall.setEnabled(False)
        self.camera.setEnabled(False)
        worker = SetupWorker(operation, self)
        self.worker = worker
        worker.result.connect(self._result)
        worker.finished.connect(self._unbusy)
        worker.start()

    def _unbusy(self):
        self.worker = None
        for action in self.actions:
            action.setEnabled(True)
        for page in self.editor.sections.values():
            page.setEnabled(True)
        self.audio.setEnabled(True)
        self.maintenance.setEnabled(True)
        self.hall.setEnabled(True)
        self.camera.setEnabled(True)
        self.allow.setChecked(False)
        if self._close_pending:
            self._maybe_close()

    def _result(self, ok, value):
        if isinstance(value, list):
            display = resolve_hall_display(
                self.owner.displays.snapshot(), self.owner.settings.hall_display_key
            )
            self._check_rows = value + [
                Check("CONEXÃO", "Tela do Salão conectada", display is not None),
                Check(
                    "CONFIGURAÇÃO",
                    "Foto do Texto do Ano salva",
                    self.owner.yeartext_store.current() is not None,
                ),
            ]
            self._render_checks()
            self.status.setText("Verificação concluída. Pendências aparecem em Instalação e plugins.")
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
        # Probe what is currently displayed in the embedded editor. Previously
        # this used only owner.settings, so a freshly typed host/port/password
        # was ignored until the operator discovered the separate Save button.
        settings = replace(self.owner.settings)
        self.editor.apply_to(settings)
        if settings != self.owner.settings:
            try:
                service.validate_settings(settings)
                self.owner._apply_assistant_settings(settings)
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            except Exception:
                self.status.setText("Falha ao aplicar os ajustes antes da verificação.")
                return
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

    def _install_virtual_cables(self):
        if not self._authorized():
            return
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "Selecione o arquivo ZIP do VB-CABLE A+B", "", "ZIP Files (*.zip)"
        )
        if not path:
            return

        def work():
            import subprocess
            import tempfile
            import zipfile
            from pathlib import Path

            try:
                with tempfile.TemporaryDirectory() as td:
                    target = Path(td)
                    with zipfile.ZipFile(path, "r") as zip_ref:
                        zip_ref.extractall(target)

                    setups = list(target.rglob("*Setup_x64.exe"))
                    if not setups:
                        return "Erro: Nenhum instalador Setup_x64.exe encontrado no ZIP."

                    results = []
                    for setup in setups:
                        sig_check = subprocess.run(
                            [
                                "powershell",
                                "-NoProfile",
                                "-Command",
                                f"(Get-AuthenticodeSignature '{setup}').Status -eq 'Valid'",
                            ],
                            capture_output=True,
                            text=True,
                        )
                        if "True" not in sig_check.stdout:
                            results.append(f"Segurança: {setup.name} não possui assinatura válida.")
                            continue
                        cmd = (
                            f"$p = Start-Process -FilePath '{setup}' -Wait "
                            f"-PassThru -Verb RunAs; exit $p.ExitCode"
                        )
                        res = subprocess.run(
                            ["powershell", "-NoProfile", "-Command", cmd], capture_output=True
                        )
                        if res.returncode != 0:
                            results.append(f"Falha na instalação de {setup.name}.")
                        else:
                            results.append(f"{setup.name} instalado.")

                    return " ".join(results) + " Reinicie o computador."
            except Exception as e:
                return f"Erro ao extrair ou instalar: {e}"

        self._run(work)

    def _websocket(self):
        if self._authorized():
            settings = replace(self.owner.settings)
            self._run(lambda: service.configure_websocket(settings))

    def _native(self):
        if self._authorized():
            from meeting_assistant.services.obs_plugins import install_camera_bridge

            settings = replace(self.owner.settings)
            self._run(lambda: install_camera_bridge(settings))

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
        self.maintenance.request("camera")

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
        if self._busy():
            self._close_pending = True
            self.status.setText("Fechamento solicitado; aguardando a operação terminar.")
            return
        pending = replace(self.owner.settings)
        self.editor.apply_to(pending)
        if pending != self.owner.settings:
            answer = QMessageBox.question(
                self,
                "Alterações pendentes",
                "Salvar os ajustes editados antes de fechar?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if answer == QMessageBox.Cancel or answer == QMessageBox.Save and not self._save():
                self._close_pending = False
                self.deferred_action = None
                return
        if self.audio.has_pending_changes() or self.hall.pending_png is not None:
            answer = QMessageBox.question(
                self, "Alterações ainda não aplicadas",
                "Há áudio editado ou uma foto capturada ainda não salvos/aplicados. "
                "Volte à categoria correspondente para concluir ou descarte estas edições.",
                QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel,
            )
            if answer != QMessageBox.Discard:
                self._close_pending = False
                self.deferred_action = None
                return
        self.done(QDialog.Rejected)

    def closeEvent(self, event):
        event.ignore()
        self.reject()
