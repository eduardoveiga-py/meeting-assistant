from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import psutil
from PySide6.QtCore import QObject, Signal

try:
    import win32gui
except ImportError:  # pragma: no cover - Windows-only
    win32gui = None


_JWL_FALLBACK_AUMID = "WatchtowerBibleandTractSo.45909CDBADF3C_5rz59y55nfz3e!App"
_ZOOM_MEETING_CLASS = "ConfMultiTabContentWndClass"


@dataclass(frozen=True, slots=True)
class LaunchSummary:
    obs_running: bool
    jwl_running: bool
    zoom_running: bool
    zoom_meeting_active: bool
    notes: tuple[str, ...]
    jwl_exited_during_startup: bool = False


def zoom_join_uri(value: str) -> str:
    """Convert a normal Zoom invite URL into the native desktop join URI."""

    raw = value.strip()
    if not raw:
        return ""
    if raw.casefold().startswith("zoommtg://"):
        return raw

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return raw

    parts = [part for part in parsed.path.split("/") if part]
    meeting_id = ""
    if "j" in parts:
        index = parts.index("j")
        if index + 1 < len(parts):
            meeting_id = re.sub(r"\D", "", parts[index + 1])

    if not meeting_id:
        return raw

    query = parse_qs(parsed.query)
    params: dict[str, str] = {
        "action": "join",
        "confno": meeting_id,
    }
    pwd = query.get("pwd", [""])[0]
    if pwd:
        params["pwd"] = pwd

    return "zoommtg://zoom.us/join?" + urlencode(params)


def looks_like_obs_process(name: str) -> bool:
    normalized = name.casefold()
    return normalized in {"obs64.exe", "obs32.exe", "obs.exe"}


def looks_like_zoom_process(name: str) -> bool:
    return name.casefold() == "zoom.exe"


def looks_like_jwl_process(name: str) -> bool:
    compact = name.casefold().replace(" ", "").replace("_", "").replace("-", "")
    return "jwlibrary" in compact and "signlanguage" not in compact


class MeetingLauncherService(QObject):
    progress_changed = Signal(str)
    finished = Signal(object)

    def __init__(self, settings_provider) -> None:
        super().__init__()
        self._settings_provider = settings_provider
        self._thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start_meeting(self) -> bool:
        if self.busy:
            return False
        self._thread = threading.Thread(
            target=self._run,
            name="MeetingAssistant-Launcher",
            daemon=True,
        )
        self._thread.start()
        return True

    def _run(self) -> None:
        settings = self._settings_provider()
        notes: list[str] = []

        snapshot = self._process_snapshot()
        jwl_requested = False

        if not any(looks_like_obs_process(name) for name in snapshot.values()):
            self.progress_changed.emit("Abrindo OBS…")
            if self._launch_obs(getattr(settings, "obs_executable", "")):
                notes.append("OBS solicitado")
            else:
                notes.append("OBS não pôde ser localizado")
        else:
            notes.append("OBS já estava aberto")

        if not any(looks_like_jwl_process(name) for name in snapshot.values()):
            self.progress_changed.emit("Abrindo JW Library…")
            if self._launch_jwl():
                jwl_requested = True
                notes.append("JW Library solicitado")
            else:
                notes.append("JW Library não pôde ser iniciado")
        else:
            notes.append("JW Library já estava aberto")

        zoom_meeting = self._zoom_meeting_active()
        zoom_running = any(looks_like_zoom_process(name) for name in snapshot.values())
        join_url = str(getattr(settings, "zoom_join_url", "") or "").strip()

        if not zoom_meeting:
            if join_url:
                self.progress_changed.emit("Abrindo Zoom diretamente na reunião…")
                if self._open_uri(zoom_join_uri(join_url)):
                    notes.append("Entrada na reunião do Zoom solicitada")
                else:
                    notes.append("Não foi possível abrir o link da reunião do Zoom")
            elif not zoom_running:
                self.progress_changed.emit("Abrindo Zoom…")
                if self._launch_zoom(getattr(settings, "zoom_executable", "")):
                    notes.append("Zoom solicitado; configure o link da reunião em Ajustes")
                else:
                    notes.append("Zoom não pôde ser localizado")
            else:
                notes.append("Zoom aberto; link da reunião ainda não configurado")
        else:
            notes.append("Zoom já está em uma reunião")

        # A process appearing once is not a completed startup. In the reported
        # session JWL disappeared 28 seconds after the old success summary.
        # Observe only launches requested here; never reopen an app automatically
        # because its disappearance may also be an intentional user action.
        deadline = time.monotonic() + (45.0 if jwl_requested else 14.0)
        jwl_seen = False
        jwl_exited = False
        if jwl_requested:
            self.progress_changed.emit("Verificando se o JW Library permanece aberto (até 45 s)…")
        obs_running = False
        jwl_running = False
        zoom_running = False
        while time.monotonic() < deadline:
            snapshot = self._process_snapshot()
            obs_running = any(looks_like_obs_process(name) for name in snapshot.values())
            jwl_running = any(looks_like_jwl_process(name) for name in snapshot.values())
            zoom_running = any(looks_like_zoom_process(name) for name in snapshot.values())
            if jwl_requested and jwl_seen and not jwl_running:
                jwl_exited = True
                break
            jwl_seen = jwl_seen or jwl_running
            if not jwl_requested and obs_running and jwl_running and zoom_running:
                break
            time.sleep(0.45)

        zoom_meeting = self._zoom_meeting_active()
        if jwl_exited:
            notes.append("JW Library abriu e fechou durante a inicialização; tente abri-lo novamente")
        elif not jwl_running:
            notes.append("JW Library não foi detectado ao terminar a verificação")
        elif jwl_requested:
            notes.append(
                "JW Library permaneceu aberto durante a verificação; confirme o carregamento na tela"
            )
        if not obs_running:
            notes.append("OBS não foi detectado ao terminar a verificação")
        if not zoom_running:
            notes.append("Zoom não foi detectado ao terminar a verificação")
        elif not zoom_meeting:
            notes.append("Zoom aberto; entrada na reunião ainda não confirmada")
        summary = LaunchSummary(
            obs_running=obs_running,
            jwl_running=jwl_running,
            zoom_running=zoom_running,
            zoom_meeting_active=zoom_meeting,
            notes=tuple(notes),
            jwl_exited_during_startup=jwl_exited,
        )
        self.progress_changed.emit(
            "Verificação concluída; há pendências na abertura dos programas."
            if jwl_exited or not all((obs_running, jwl_running, zoom_running))
            else "Programas detectados; confira o OBS conectado e a entrada no Zoom."
        )
        self.finished.emit(summary)

    @staticmethod
    def _process_snapshot() -> dict[int, str]:
        result: dict[int, str] = {}
        try:
            for process in psutil.process_iter(["pid", "name"]):
                pid = process.info.get("pid")
                if isinstance(pid, int):
                    result[pid] = str(process.info.get("name") or "")
        except (psutil.Error, OSError):
            pass
        return result

    @staticmethod
    def _candidate_executable(configured: str, candidates: list[Path], names: list[str]) -> Path | None:
        if configured:
            path = Path(os.path.expandvars(configured)).expanduser()
            if path.exists():
                return path

        for name in names:
            found = shutil.which(name)
            if found:
                return Path(found)

        for path in candidates:
            if path.exists():
                return path
        return None

    def _launch_obs(self, configured: str) -> bool:
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        executable = self._candidate_executable(
            configured,
            [
                program_files / "obs-studio" / "bin" / "64bit" / "obs64.exe",
                local / "Programs" / "obs-studio" / "bin" / "64bit" / "obs64.exe",
            ],
            ["obs64.exe", "obs32.exe"],
        )
        if executable is None:
            return False
        try:
            subprocess.Popen(
                [str(executable), "--minimize-to-tray", "--startvirtualcam"],
                cwd=str(executable.parent),
                close_fds=True,
            )
            return True
        except OSError:
            return False

    def _launch_zoom(self, configured: str) -> bool:
        appdata = Path(os.environ.get("APPDATA", ""))
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        executable = self._candidate_executable(
            configured,
            [
                appdata / "Zoom" / "bin" / "Zoom.exe",
                local / "Zoom" / "bin" / "Zoom.exe",
                local / "Programs" / "Zoom" / "bin" / "Zoom.exe",
                program_files / "Zoom" / "bin" / "Zoom.exe",
            ],
            ["Zoom.exe"],
        )
        if executable is None:
            return False
        try:
            subprocess.Popen(
                [str(executable)],
                cwd=str(executable.parent),
                close_fds=True,
            )
            return True
        except OSError:
            return False

    def _launch_jwl(self) -> bool:
        aumid = self._discover_jwl_aumid() or _JWL_FALLBACK_AUMID
        if sys.platform != "win32":
            return False
        try:
            subprocess.Popen(
                ["explorer.exe", rf"shell:AppsFolder\{aumid}"],
                close_fds=True,
            )
            return True
        except OSError:
            return False

    @staticmethod
    def _discover_jwl_aumid() -> str:
        if sys.platform != "win32":
            return ""
        command = (
            "$apps=(New-Object -ComObject Shell.Application)."
            "NameSpace('shell:::{4234d49b-0245-4df3-b780-3893943456e1}').Items();"
            "$item=$apps|Where-Object {$_.Name -eq 'JW Library'}|Select-Object -First 1;"
            "if($item){$item.Path}"
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=creationflags,
                check=False,
            )
            return completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else ""
        except (OSError, subprocess.SubprocessError, IndexError):
            return ""

    @staticmethod
    def _open_uri(uri: str) -> bool:
        if not uri:
            return False
        try:
            if sys.platform == "win32":
                os.startfile(uri)  # type: ignore[attr-defined]
                return True
            return False
        except OSError:
            return False

    @staticmethod
    def _zoom_meeting_active() -> bool:
        if win32gui is None:
            return False
        active = False

        def callback(hwnd: int, _: object) -> bool:
            nonlocal active
            try:
                if (
                    win32gui.GetClassName(hwnd) == _ZOOM_MEETING_CLASS
                    and win32gui.GetWindowText(hwnd).strip() == "Zoom Meeting"
                ):
                    active = True
                    return False
            except (OSError, RuntimeError):
                pass
            return not active

        try:
            win32gui.EnumWindows(callback, None)
        except (OSError, RuntimeError):
            return False
        return active

