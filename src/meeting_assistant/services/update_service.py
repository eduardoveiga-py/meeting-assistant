"""Stable release updates with verified artifacts and a GUI-owned shutdown.

Python development runs get Git instructions; no installer replaces their tree.
All network work is cancelable and bounded. The helper waits for process exit
before installing, then starts the installed executable only on success.
"""

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Signal

from meeting_assistant import __version__
from meeting_assistant.services.release_check import version_tuple


class UpdateService(QObject):
    update_available = Signal(str, str, str)
    status_changed = Signal(str, bool)  # message, busy
    history_ready = Signal(object)
    operation_finished = Signal()
    install_ready = Signal(str, str, str)  # path, version, verified sha256

    def __init__(
        self,
        owner="eduardoveiga-py",
        repo="meeting-assistant",
        *,
        installed_version=__version__,
        frozen=None,
        opener=None,
        activity_provider=None,
    ):
        super().__init__()
        self.owner, self.repo = owner, repo
        self.api_url = f"https://api.github.com/repos/{owner}/{repo}/releases"
        self.installed_version = installed_version
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        self._open = opener or urllib.request.urlopen
        self.activity_provider = activity_provider or (lambda: False)
        self._cancel = threading.Event()
        self._thread = None
        self._offers = {}
        self._busy = False
        self._verified_handoff = None

    @property
    def busy(self):
        return self._busy

    def _start(self, target, *args):
        if self.busy:
            self.status_changed.emit("Outra verificação está em andamento.", True)
            return False
        self._cancel.clear()
        self._busy = True
        self.status_changed.emit("Consultando ou baixando atualização…", True)

        def work():
            try:
                target(*args)
            finally:
                self._busy = False
                self.operation_finished.emit()

        self._thread = threading.Thread(target=work, daemon=True, name="Release updates")
        self._thread.start()
        return True

    def stop(self):
        self._cancel.set()

    def _read(self, url, limit=1_000_000):
        request = urllib.request.Request(
            url, headers={"User-Agent": "MeetingAssistant", "Accept": "application/vnd.github+json"}
        )
        with self._open(request, timeout=10) as response:
            data = response.read(limit + 1)
        if len(data) > limit or self._cancel.is_set():
            raise ValueError("Resposta de atualização inválida ou operação cancelada.")
        return data

    def _asset_url(self, url):
        parsed = urlparse(url)
        prefix = f"/{self.owner}/{self.repo}/releases/download/"
        return parsed.scheme == "https" and parsed.netloc == "github.com" and parsed.path.startswith(prefix)

    def _offer(self, release):
        version = str(release.get("tag_name", "")).removeprefix("v")
        if release.get("draft") or release.get("prerelease") or version_tuple(version) is None:
            return None
        assets = release.get("assets", [])
        installers = [
            a for a in assets if re.fullmatch(r"MeetingAssistant-Setup-[\w.-]+\.exe", str(a.get("name", "")))
        ]
        checksums = [a for a in assets if a.get("name") == "SHA256SUMS.txt"]
        offer = {
            "version": version,
            "notes": str(release.get("body", "")),
            "name": str(release.get("name", version)),
            "url": "",
            "checksum_url": "",
            "filename": "",
        }
        if len(installers) == 1 and len(checksums) == 1:
            exe, sums = installers[0], checksums[0]
            expected = f"MeetingAssistant-Setup-{version}.exe"
            tag_path = f"/{self.owner}/{self.repo}/releases/download/{release['tag_name']}/"
            if (
                exe["name"] == expected
                and urlparse(exe.get("browser_download_url", "")).path == tag_path + expected
                and urlparse(sums.get("browser_download_url", "")).path == tag_path + "SHA256SUMS.txt"
                and self._asset_url(exe.get("browser_download_url", ""))
                and self._asset_url(sums.get("browser_download_url", ""))
            ):
                offer.update(
                    url=exe["browser_download_url"],
                    checksum_url=sums["browser_download_url"],
                    filename=exe["name"],
                )
        self._offers[version] = offer
        return offer

    def check_for_updates_async(self):
        return self._start(self._check_for_updates_worker)

    def _check_for_updates_worker(self):
        try:
            offer = self._offer(json.loads(self._read(self.api_url + "/latest")))
            local = version_tuple(self.installed_version)
            if offer and local and version_tuple(offer["version"]) > local:
                self.update_available.emit(offer["version"], offer["url"], offer["notes"])
                message = "Nova versão estável disponível."
            else:
                message = "Nenhuma versão estável mais recente."
            self.status_changed.emit(message, False)
        except Exception:
            self.status_changed.emit("Não foi possível consultar Releases. Tente novamente.", False)

    def request_history(self):
        return self._start(self._history_worker)

    def _history_worker(self):
        try:
            releases = json.loads(self._read(self.api_url + "?per_page=20"))
            offers = [offer for release in releases if (offer := self._offer(release))]
            offers.sort(key=lambda offer: version_tuple(offer["version"]), reverse=True)
            self.history_ready.emit(offers)
            self.status_changed.emit("Histórico carregado. Leia as notas antes de atualizar.", False)
        except Exception:
            self.status_changed.emit("Falha ao consultar o histórico. Tente novamente.", False)

    def download_and_install_async(self, download_url, version, *, allow_rollback=False):
        if not self.frozen:
            self.status_changed.emit(
                "Execução Python: feche o app, rode git pull --ff-only e scripts/run.ps1.", False
            )
            return False
        if self.activity_provider():
            self.status_changed.emit("Encerre a reunião e pause as apresentações antes de atualizar.", False)
            return False
        return self._start(self._install_worker, download_url, version, allow_rollback)

    def _install_worker(self, download_url, version, allow_rollback=False):
        partial = None
        try:
            offer = self._offers.get(version)
            local, remote = version_tuple(self.installed_version), version_tuple(version)
            if (
                not offer
                or not offer["url"]
                or download_url != offer["url"]
                or not local
                or not remote
                or (remote <= local and not allow_rollback)
            ):
                raise ValueError("Selecione uma versão verificada no histórico de Releases.")
            matches = []
            for line in self._read(offer["checksum_url"]).decode("ascii").splitlines():
                match = re.fullmatch(r"([a-fA-F0-9]{64})\s+\*?([^/\\]+)", line.strip())
                if match and match[2] == offer["filename"]:
                    matches.append(match[1].lower())
            if len(matches) != 1:
                raise ValueError("Checksum da versão ausente ou ambíguo. Instalação bloqueada.")
            directory = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "MeetingAssistant" / "Updates"
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / offer["filename"]
            partial = destination.with_suffix(".exe.part")
            digest, size = hashlib.sha256(), 0
            request = urllib.request.Request(download_url, headers={"User-Agent": "MeetingAssistant"})
            with self._open(request, timeout=10) as response, partial.open("wb") as output:
                while block := response.read(256 * 1024):
                    if self._cancel.is_set():
                        raise ValueError("Atualização cancelada.")
                    size += len(block)
                    if size > 512 * 1024 * 1024:
                        raise ValueError("Instalador excede o tamanho permitido.")
                    digest.update(block)
                    output.write(block)
            if digest.hexdigest() != matches[0]:
                raise ValueError("Integridade do instalador não confirmada. Nenhum arquivo foi executado.")
            from meeting_assistant.services.window_inventory import WindowBackend

            if (
                self._cancel.is_set()
                or self.activity_provider()
                or any(
                    name in {"obs64.exe", "obs32.exe", "zoom.exe", "whatsapp.exe"}
                    for _pid, _created, name in WindowBackend().processes()
                )
            ):
                raise ValueError("Feche OBS, Zoom e WhatsApp antes de instalar; atualização adiada.")
            partial.replace(destination)
            self._verified_handoff = (str(destination), matches[0])
            self.install_ready.emit(str(destination), version, matches[0])
            self.status_changed.emit("Download verificado. Preparando encerramento para instalar.", False)
        except ValueError as exc:
            self.status_changed.emit(str(exc), False)
        except Exception:
            self.status_changed.emit(
                "Falha no download. Nenhum instalador foi executado. Tente novamente.", False
            )
        finally:
            if partial is not None:
                partial.unlink(missing_ok=True)

    def launch_after_exit(self, path, checksum):
        if not self.frozen or sys.platform != "win32" or self.activity_provider():
            raise ValueError("Instalação permitida apenas fora da reunião no app instalado.")
        if self._verified_handoff != (str(path), checksum) or not Path(path).is_file():
            raise ValueError("Instalador não corresponde ao download verificado.")

        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        script = (
            "$ErrorActionPreference='Stop';"
            f"$p=Get-Process -Id {os.getpid()} -ErrorAction SilentlyContinue;"
            "if($p -and -not $p.WaitForExit(120000)){exit 3};"
            "if(Get-Process -Name obs64,obs32,Zoom,WhatsApp -ErrorAction SilentlyContinue){exit 5};"
            f"$hash=(Get-FileHash -Algorithm SHA256 -LiteralPath {quote(path)}).Hash;"
            f"if($hash -ne {quote(checksum)}){{exit 4}};"
            f"$i=Start-Process -FilePath {quote(path)} -ArgumentList '/SILENT','/NORESTART' -Wait -PassThru;"
            f"if($i.ExitCode -eq 0){{Start-Process -FilePath {quote(sys.executable)}}}"
        )
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
