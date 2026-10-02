import json
import logging
import os
import subprocess
import threading
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from meeting_assistant import __version__

logger = logging.getLogger(__name__)


class UpdateService(QObject):
    """
    Serviço que verifica versões novas no GitHub e permite atualização e rollback.
    """

    update_available = Signal(str, str, str)  # versao, url_download, notas_lancamento

    def __init__(self, owner: str = "eduardoveiga-py", repo: str = "meeting-assistant"):
        super().__init__()
        self.owner = owner
        self.repo = repo
        self.api_url = f"https://api.github.com/repos/{owner}/{repo}/releases"
        
    def check_for_updates_async(self) -> None:
        """Verifica de forma assíncrona se existe uma versão mais recente."""
        threading.Thread(target=self._check_for_updates_worker, daemon=True).start()

    def _check_for_updates_worker(self) -> None:
        try:
            req = urllib.request.Request(self.api_url + "/latest", headers={'User-Agent': 'MeetingAssistant'})
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    data = json.loads(response.read())
                    latest_version = data.get("tag_name", "").lstrip("v")
                    
                    # Compara versão simples (ignora rc/dev pra simplificar ou assume diferente)
                    if latest_version and latest_version != __version__:
                        assets = data.get("assets", [])
                        download_url = next(
                            (a["browser_download_url"] for a in assets if a["name"].endswith(".exe")),
                            None
                        )
                        if download_url:
                            self.update_available.emit(latest_version, download_url, data.get("body", ""))
        except Exception as e:
            logger.error(f"Erro ao verificar atualizações: {e}")

    def get_releases_list(self) -> list[dict]:
        """Busca histórico de versões para rollback (de forma síncrona)."""
        try:
            req = urllib.request.Request(self.api_url, headers={'User-Agent': 'MeetingAssistant'})
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    data = json.loads(response.read())
                    releases = []
                    for r in data[:5]:  # Pega as últimas 5 releases
                        assets = r.get("assets", [])
                        exe_url = next(
                            (a["browser_download_url"] for a in assets if a["name"].endswith(".exe")),
                            None
                        )
                        if exe_url:
                            releases.append({
                                "version": r.get("tag_name", "").lstrip("v"),
                                "url": exe_url,
                                "name": r.get("name", "")
                            })
                    return releases
        except Exception as e:
            logger.error(f"Erro ao buscar histórico de atualizações: {e}")
        return []

    def download_and_install_async(self, download_url: str, version: str) -> None:
        """Baixa e instala em background."""
        threading.Thread(target=self._install_worker, args=(download_url, version), daemon=True).start()

    def _install_worker(self, download_url: str, version: str) -> None:
        try:
            download_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "MeetingAssistant" / "Updates"
            download_dir.mkdir(parents=True, exist_ok=True)
            
            installer_path = download_dir / f"MeetingAssistant-Setup-{version}.exe"
            
            logger.info(f"Baixando atualização para {installer_path}")
            urllib.request.urlretrieve(download_url, installer_path)
            
            logger.info("Iniciando instalador silencioso e encerrando aplicativo...")
            # Roda o instalador de forma totalmente silenciosa e manda ele reabrir o app
            subprocess.Popen([str(installer_path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
            
            # Encerrar o app atual
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                app.quit()
        except Exception as e:
            logger.error(f"Erro ao instalar atualização: {e}")
