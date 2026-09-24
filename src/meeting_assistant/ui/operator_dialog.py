"""Daily preparation, handoff, recovery and maintenance in one operator surface."""

import json
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from meeting_assistant.services.preflight import Check
from meeting_assistant.services.setup_assistant import inspect_environment
from meeting_assistant.ui.setup_assistant_dialog import SetupWorker
from meeting_assistant.ui.window_geometry import ScreenFitController

RECOVERY = {
    "Sem áudio no Zoom": "1. Confira se seu microfone no Zoom está mudo.\n"
    "2. Confira o sinal das fontes no mixer OBS e o monitoramento para CABLE Input.\n"
    "3. No Zoom, confirme CABLE Output como microfone.\n"
    "4. Peça escuta remota. Não inclua o retorno Zoom na mistura enviada.",
    "Sem imagem": "1. Confira a entrada e a alimentação da TV.\n2. Confira área de trabalho estendida.\n"
    "3. Diferencie imagem local do Program OBS.\n4. No Zoom, confira OBS Virtual Camera.",
    "Zoom não aparece no Salão": "1. Confira a opção de dois monitores no Zoom.\n"
    "2. Confirme que entrou na reunião e as duas janelas existem.\n"
    "3. Use Zoom → Salão novamente somente após conferir o estado atual.",
    "JWL não voltou": "1. Confira o monitor físico.\n2. Use voltar ao JWL no controle Zoom → Salão.\n"
    "3. Se necessário, pause a automação e confira a segunda tela no JWL.\n"
    "4. Registre o horário da falha; não recalibre durante um vídeo.",
    "Câmera indisponível": "Use Palco / Texto do Ano para solicitar a contingência.\n"
    "Confira conexão, energia e fonte da câmera no OBS. Fontes sem informação de saúde usam Texto do Ano.\n"
    "A troca visual não silencia o áudio.",
}


class OperatorDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.worker = None
        self.close_pending = False
        self.obs_pending = False
        self.setWindowTitle("Preparar, acompanhar e resolver")
        self.resize(650, 650)
        self.setMinimumSize(360, 280)
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        daily = self.page("Reunião")
        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        daily.addWidget(self.summary)
        self.voice_meter = QProgressBar()
        self.media_meter = QProgressBar()
        for meter in (self.voice_meter, self.media_meter):
            meter.setRange(0, 60)
            daily.addWidget(meter)
        self.meter_timer = QTimer(self)
        self.meter_timer.setInterval(250)
        self.meter_timer.timeout.connect(self.meters)
        self.meter_timer.start()
        self.meters()
        self.remote = QCheckBox("Conferi imagem e escuta em outro dispositivo Zoom")
        daily.addWidget(self.remote)
        self.remote.toggled.connect(self.confirm_remote)
        self.button(daily, "Verificar ambiente e mudanças", self.inspect)
        self.button(daily, "Registrar configuração conferida", self.record)
        self.button(daily, "Preparação inicial / fontes…", self.open_setup)
        recovery = self.page("Resolver")
        self.symptom = QComboBox()
        self.symptom.addItems(RECOVERY)
        recovery.addWidget(self.symptom)
        self.advice = QLabel()
        self.advice.setWordWrap(True)
        recovery.addWidget(self.advice)
        self.symptom.currentTextChanged.connect(lambda name: self.advice.setText(RECOVERY[name]))
        self.advice.setText(RECOVERY[self.symptom.currentText()])
        self.button(recovery, "Pausar e solicitar Palco / Texto do Ano", owner._activate_safe_scene)
        self.button(recovery, "Solicitar câmera virtual", owner.obs.ensure_virtual_camera)
        self.button(recovery, "Abrir diagnóstico detalhado", owner._legacy_diagnostics)
        camera = self.page("Câmera")
        hint = QLabel(
            "Toda câmera é vinculada à cena Palco. Prepare fora da reunião. "
            "USB/captura: liste dispositivos antes de aplicar. NDI ou plugins: use fonte existente. "
            "A fonte IP já configurada continua disponível no assistente inicial."
        )
        hint.setWordWrap(True)
        camera.addWidget(hint)
        self.camera_mode = QComboBox()
        for label, key in [
            ("Fonte existente OBS", "existing"),
            ("USB / placa de captura", "usb"),
            ("URL de rede RTSP / SRT / HTTP", "network"),
        ]:
            self.camera_mode.addItem(label, key)
        camera.addWidget(self.camera_mode)
        self.camera_choices = QComboBox()
        camera.addWidget(self.camera_choices)
        self.camera_url = QLineEdit()
        self.camera_url.setEchoMode(QLineEdit.Password)
        self.camera_url.setPlaceholderText("URL completa da câmera de rede")
        camera.addWidget(self.camera_url)
        self.button(camera, "Listar fontes / dispositivos USB", self.list_cameras)
        self.button(camera, "Aplicar câmera em Palco", self.apply_camera)
        self.camera_notice = QLabel("Fontes existentes preservam seu áudio. Confira o mixer antes de usar.")
        self.camera_notice.setWordWrap(True)
        camera.addWidget(self.camera_notice)
        end = self.page("Encerrar / Suporte")
        self.button(end, "Pausar automação", self.pause)
        self.button(end, "Silenciar meu microfone Zoom", lambda: owner.zoom_audio.request("mute"))
        self.button(end, "Desligar câmera virtual OBS…", self.stop_camera)
        notice = QLabel(
            "Encerre a reunião pelo Zoom e confira os equipamentos. "
            "O app não fecha aplicativos externos automaticamente."
        )
        notice.setWordWrap(True)
        end.addWidget(notice)
        self.button(end, "Consultar versão e atualizações", self.updates)
        self.button(
            end,
            "Abrir downloads públicos",
            lambda: QDesktopServices.openUrl(
                QUrl("https://github.com/eduardoveiga-py/meeting-assistant/releases/latest")
            ),
        )
        self.button(end, "Exportar perfil sem credenciais…", self.export_profile)
        self.button(end, "Importar perfil…", self.import_profile)
        self.button(end, "Treinar controles sem comandar equipamentos…", self.training)
        self.button(root, "Fechar", self.reject)
        owner.obs.operator_finished.connect(self.obs_result)
        self._fit = ScreenFitController(self)
        self.inspect()

    def meters(self):
        values = getattr(getattr(self.owner.obs, "audio_levels", None), "latest", None)
        if not isinstance(values, tuple) or len(values) != 3:
            values = (0, None, None)
        at, voice, media = values
        for label, meter, value in (("Mesa", self.voice_meter, voice), ("Mídias", self.media_meter, media)):
            available = value is not None and time.monotonic() - at < 2
            meter.setValue(round(value + 60) if available else 0)
            meter.setFormat(
                f"{label} no OBS: {value:.0f} dBFS" if available else f"{label}: sinal não verificado"
            )
        self.voice_meter.setToolTip("Fontes gerenciadas pelo app. Sinal OBS não comprova escuta no Zoom.")

    def page(self, name):
        scroll = QScrollArea()
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        self.tabs.addTab(scroll, name)
        return layout

    @staticmethod
    def button(layout, text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)

    def maintenance(self):
        if (
            self.owner.state.automation_enabled
            or self.owner.zoom_hall.active
            or self.owner.zoom_hall.returning
        ):
            self.status.setText("Pause a automação e retorne ao JWL antes de alterar a instalação.")
            return False
        return True

    def inspect(self):
        if self.worker and self.worker.isRunning():
            return
        self.status.setText("Verificando em segundo plano…")
        settings = replace(self.owner.settings)
        self.worker = SetupWorker(lambda: inspect_environment(settings), self)
        self.worker.result.connect(self.inspected)
        self.worker.finished.connect(self.finished_work)
        self.worker.start()

    def inspected(self, ok, result):
        if not ok:
            self.status.setText(str(result))
            return
        from meeting_assistant.services.display_service import resolve_hall_display

        result.append(
            Check(
                "CONEXÃO",
                "Tela do Salão",
                resolve_hall_display(self.owner.displays.snapshot(), self.owner.settings.hall_display_key)
                is not None,
            )
        )
        state = "ativa" if self.owner.state.automation_enabled else "pausada / controle manual"
        local = "Zoom" if self.owner.zoom_hall.active else "JWL: conferir tela física"
        text = (
            f"Automação: {state}\nOBS: {self.owner.current_obs_scene or 'não confirmado'}\nSalão: {local}\n\n"
        )
        text += "\n".join(row.render() for row in result)
        old = self.baseline()
        changed = [
            key for key, value in self.snapshot().items() if old.get("equipment", {}).get(key) != value
        ]
        text += "\n\n" + (
            "Mudanças desde a conferência: " + ", ".join(changed)
            if changed
            else "Configuração igual à última conferência; isso não comprova recepção remota."
        )
        text += "\nConferência remota: " + getattr(self.owner, "remote_confirmation", "pendente nesta sessão")
        self.summary.setPlainText(text)
        self.status.setText("Verificação concluída. Itens não verificados exigem conferência.")

    def snapshot(self):
        s = self.owner.settings
        return {
            "monitor": s.hall_display_key,
            "câmera": s.camera_source_name,
            "cenas": [s.scene_background, s.scene_speaker, s.scene_media],
            "telas detectadas": [d.key for d in self.owner.displays.snapshot()],
        }

    def baseline(self):
        try:
            data = json.loads(self.record_path().read_text(encoding="utf-8"))
            return data if isinstance(data, dict) and isinstance(data.get("equipment"), dict) else {}
        except (OSError, ValueError):
            return {}

    def record_path(self):
        return self.owner.settings_service.path.parent / "operator-check.json"

    def record(self):
        if not self.remote.isChecked():
            self.status.setText("Confirme imagem e escuta remotas antes de registrar.")
            return
        try:
            path = self.record_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_text(
                json.dumps(
                    {"equipment": self.snapshot(), "at": datetime.now().isoformat()}, ensure_ascii=False
                ),
                encoding="utf-8",
            )
            temp.replace(path)
            self.status.setText("Conferência registrada neste equipamento; próxima sessão exige novo teste.")
        except OSError:
            self.status.setText("Não foi possível gravar a conferência.")

    def confirm_remote(self, checked):
        self.owner.remote_confirmation = datetime.now().strftime("%H:%M:%S") if checked else "pendente"

    def open_setup(self):
        if self.maintenance():
            self.owner._open_setup_assistant()

    def list_cameras(self):
        if self.maintenance() and not self.obs_pending:
            self.obs_pending = True
            if self.camera_mode.currentData() == "usb":
                self.owner.obs.operator_task("camera_prepare", {"mode": "usb", "value": ""})
            else:
                self.owner.obs.operator_task("camera_list")

    def apply_camera(self):
        if self.obs_pending or not self.maintenance():
            return
        mode = self.camera_mode.currentData()
        value = self.camera_url.text().strip() if mode == "network" else self.camera_choices.currentData()
        if not value:
            self.status.setText("Preencha a URL ou selecione uma fonte/dispositivo.")
            return
        if "Palco" in {self.owner.settings.scene_background, self.owner.settings.scene_media}:
            self.status.setText("Palco está mapeada a outro modo. Corrija os nomes nos ajustes primeiro.")
            return
        self.obs_pending = True
        self.owner.obs.operator_task("camera_prepare", {"mode": mode, "value": value})

    def obs_result(self, action, ok, result):
        if action in {"camera_prepare", "camera_list"}:
            self.obs_pending = False
        if not ok:
            self.status.setText(str(result))
        elif action == "camera_list":
            self.camera_choices.clear()
            for name in result:
                self.camera_choices.addItem(name, name)
        elif action == "camera_prepare":
            if "devices" in result:
                self.camera_choices.clear()
                for device in result["devices"]:
                    if device.get("itemEnabled", True):
                        self.camera_choices.addItem(device["itemName"], device["itemValue"])
                self.status.setText("Selecione o dispositivo e aplique. Fonte USB ainda não habilitada.")
            else:
                pending = replace(
                    self.owner.settings, camera_source_name=result["source"], scene_speaker="Palco"
                )
                try:
                    self.owner._apply_assistant_settings(pending)
                    self.status.setText(
                        "Câmera vinculada a Palco. Confira imagem e fontes pessoais sobrepostas no OBS."
                    )
                    self.remote.setChecked(False)
                except Exception:
                    self.status.setText(
                        "Fonte criada, mas ajustes não salvos. Confira o OBS e salve o mapeamento."
                    )
        else:
            self.status.setText(str(result))

        if self.close_pending and not self.obs_pending and not (self.worker and self.worker.isRunning()):
            self.done(QDialog.Rejected)

    def pause(self):
        if self.owner.state.automation_enabled:
            self.owner._toggle_automation()
        self.status.setText("Automação pausada. Áudio e reunião Zoom permanecem como estavam.")

    def stop_camera(self):
        if (
            QMessageBox.question(self, "Encerramento", "Desligar a câmera virtual enviada ao Zoom?")
            == QMessageBox.Yes
        ):
            self.pause()
            self.owner.obs.operator_task("stop_virtual")

    def updates(self):
        from meeting_assistant import __version__
        from meeting_assistant.services.release_check import check_release

        if not self.maintenance() or (self.worker and self.worker.isRunning()):
            return
        self.status.setText("Consultando a versão pública…")
        self.worker = SetupWorker(lambda: check_release(__version__), self)
        self.worker.result.connect(
            lambda ok, result: self.status.setText(
                str(result) if ok else "Sem consulta online; a operação continua disponível."
            )
        )
        self.worker.finished.connect(self.finished_work)
        self.worker.start()

    def export_profile(self):
        from meeting_assistant.services.operator_profile import export_profile

        path, _ = QFileDialog.getSaveFileName(self, "Exportar perfil", "perfil.json", "JSON (*.json)")
        if path:
            try:
                export_profile(self.owner.settings, Path(path))
                self.status.setText("Perfil exportado sem senhas, links de reunião ou endereço da câmera.")
            except OSError:
                self.status.setText("Não foi possível exportar.")

    def import_profile(self):
        from meeting_assistant.services.operator_profile import import_profile

        if not self.maintenance():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Importar perfil", "", "JSON (*.json)")
        if path:
            try:
                pending = import_profile(self.owner.settings, Path(path))
                if (
                    QMessageBox.question(
                        self,
                        "Perfil",
                        "Aplicar cenas e preferências do perfil? "
                        "Dispositivos e credenciais locais serão preservados.",
                    )
                    == QMessageBox.Yes
                ):
                    self.owner._apply_assistant_settings(pending)
                    self.remote.setChecked(False)
                    self.inspect()
            except (OSError, ValueError, TypeError):
                self.status.setText("Perfil inválido ou não foi possível salvar; confira os ajustes.")

    def training(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("TREINAMENTO — nenhum comando enviado")
        layout = QVBoxLayout(dialog)
        label = QLabel("Simulação isolada. Escolha uma ação para conhecer seu efeito.")
        label.setWordWrap(True)
        layout.addWidget(label)
        for name, message in {
            "Texto do Ano": "Solicita a cena Texto do Ano no OBS.",
            "Palco": "Solicita a cena da câmera no OBS.",
            "Zoom → Salão": "Alterna a janela local; não envia o retorno Zoom ao próprio Zoom.",
            "Contingência": "Pausa automação e solicita Palco ou Texto do Ano. Não silencia áudio.",
            "Microfone Zoom": "Consulta o estado e solicita silenciar ou ativar seu microfone.",
        }.items():
            self.button(layout, name, lambda _=False, text=message: label.setText(text))
        dialog.exec()

    def finished_work(self):
        if self.close_pending and not self.obs_pending:
            self.done(QDialog.Rejected)

    def reject(self):
        if self.obs_pending or (self.worker and self.worker.isRunning()):
            self.close_pending = True
            self.status.setText("Fechamento solicitado; aguardando a verificação terminar.")
            return
        self.done(QDialog.Rejected)

    def closeEvent(self, event):
        event.ignore()
        self.reject()
