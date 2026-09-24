from __future__ import annotations

import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

try:
    import mss
    import mss.tools
except ImportError:  # pragma: no cover - dependency is installed in production
    mss = None


_SENSITIVE_KEY = re.compile(
    r"(password|passwd|pwd|secret|token|authorization|cookie|api[_-]?key)",
    re.IGNORECASE,
)
_ZOOM_PWD = re.compile(r"([?&]pwd=)[^&#\s]+", re.IGNORECASE)
_ZOOM_MEETING = re.compile(r"(/j/|confno=)\d{6,}", re.IGNORECASE)
_URL_CREDENTIALS = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^\s/@]+@", re.IGNORECASE)
_TEXT_SECRET = re.compile(
    r"((?:password|passwd|pwd|secret|token|api[_-]?key)\s*[=:]\s*)[^\s&,;]+", re.IGNORECASE
)
_BEARER = re.compile(r"\bBearer\s+[^\s,;]+", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_session_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"MA-{stamp}-{uuid.uuid4().hex[:4].upper()}"


def sanitize_text(value: str) -> str:
    text = value
    user_profile = os.environ.get("USERPROFILE", "")
    if user_profile:
        text = text.replace(user_profile, "%USERPROFILE%")
        text = text.replace(user_profile.replace("\\", "/"), "%USERPROFILE%")
    text = _ZOOM_PWD.sub(r"\1[REDACTED]", text)
    text = _ZOOM_MEETING.sub(r"\1[REDACTED]", text)
    text = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", text)
    text = _TEXT_SECRET.sub(r"\1[REDACTED]", text)
    text = _BEARER.sub("Bearer [REDACTED]", text)
    return text


def sanitize_value(value: Any, *, key: str = "") -> Any:
    if _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if is_dataclass(value) and not isinstance(value, type):
        return sanitize_value(asdict(value))
    if isinstance(value, dict):
        return {
            str(item_key): sanitize_value(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_value(item) for item in value]
    if isinstance(value, Path):
        return sanitize_text(str(value))
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return sanitize_text(repr(value))


def _app_version() -> str:
    try:
        return version("meeting-assistant")
    except PackageNotFoundError:
        return "dev"


def _git_candidates() -> list[Path]:
    candidates: list[Path] = []
    from_path = shutil.which("git")
    if from_path:
        candidates.append(Path(from_path))

    local = Path(os.environ.get("LOCALAPPDATA", ""))
    desktop_root = local / "GitHubDesktop"
    if desktop_root.exists():
        for app_dir in sorted(desktop_root.glob("app-*"), reverse=True):
            candidates.extend(
                [
                    app_dir / "resources" / "app" / "git" / "cmd" / "git.exe",
                    app_dir / "resources" / "app" / "git" / "mingw64" / "bin" / "git.exe",
                ]
            )
    return candidates


def find_git() -> Path | None:
    for candidate in _git_candidates():
        if candidate.exists():
            return candidate
    return None


class TelemetryService(QObject):
    """Best-effort structured telemetry that can never gate application behavior."""

    sync_status_changed = Signal(bool, str)

    def __init__(
        self,
        *,
        enabled: bool,
        repo_url: str = "",
        sync_enabled: bool = False,
        screenshots_enabled: bool = False,
        sync_interval_seconds: float = 15.0,
        root: Path | None = None,
    ) -> None:
        super().__init__()
        local = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        self.root = root or local / "MeetingAssistant" / "telemetry"
        self.sessions_root = self.root / "sessions"
        self.repo_path = self.root / "sync-repo"
        self.session_id = new_session_id()
        self.session_path = self.sessions_root / self.session_id
        self.events_path = self.session_path / "events.jsonl"
        self.summary_path = self.session_path / "summary.json"
        self.system_path = self.session_path / "system.json"
        self.screenshots_path = self.session_path / "screenshots"

        self.enabled = bool(enabled)
        self.repo_url = repo_url.strip()
        self.sync_enabled = bool(sync_enabled and self.repo_url)
        self.screenshots_enabled = bool(screenshots_enabled)
        self.status_message = "Diagnóstico local ativo; envio automático desativado."
        if self.sync_enabled:
            self.status_message = "Diagnóstico local ativo; aguardando sincronização opcional."
        if not self.enabled:
            self.status_message = "Diagnóstico desativado."
        self.sync_interval = max(8.0, sync_interval_seconds)

        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=2048)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._dirty = False
        self._started_at = utc_now()
        self._event_count = 0
        self._last_sync_error: str | None = None
        self._old_excepthook = None
        self._old_threading_excepthook = None

    def start(self) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        try:
            self._start()
        except Exception:
            self._disable_after_failure()
            self.restore_exception_hooks()

    def _disable_after_failure(self) -> None:
        self.enabled = False
        self.status_message = "Diagnóstico indisponível nesta sessão; a operação pode continuar."
        self.sync_status_changed.emit(False, self.status_message)

    def _start(self) -> None:
        self.session_path.mkdir(parents=True, exist_ok=True)
        self.screenshots_path.mkdir(parents=True, exist_ok=True)
        self._write_json(
            self.system_path,
            {
                "session_id": self.session_id,
                "app_version": _app_version(),
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "windows_release": platform.release(),
                "machine": platform.machine(),
            },
        )
        self._write_summary("running")
        self.install_exception_hooks()
        self._thread = threading.Thread(
            target=self._worker_guarded,
            name="MeetingAssistant-Telemetry",
            daemon=True,
        )
        self._thread.start()
        self.event("app_started", app_version=_app_version())

    def stop(self) -> None:
        if self.enabled:
            self.event("app_stopping")
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.restore_exception_hooks()

    def _enqueue(self, command: str, payload: Any = None) -> None:
        if not self.enabled or self._stop.is_set():
            return
        try:
            self._queue.put_nowait((command, payload))
        except queue.Full:
            # Diagnostics must never block the operator or grow without bound.
            pass

    def event(self, name: str, *, severity: str = "info", **data: Any) -> None:
        if not self.enabled:
            return
        payload = {
            "ts_utc": utc_now(),
            "monotonic_ms": round(time.monotonic() * 1000),
            "event": str(name),
            "severity": str(severity),
            "data": sanitize_value(data),
        }
        self._enqueue("event", payload)

    def request_sync(self) -> None:
        if self.sync_enabled:
            self._enqueue("sync")

    def capture_screenshot(self, reason: str) -> None:
        if self.enabled and self.screenshots_enabled:
            self._enqueue("screenshot", sanitize_text(reason))

    def install_exception_hooks(self) -> None:
        if not self.enabled:
            return
        self._old_excepthook = sys.excepthook
        self._old_threading_excepthook = threading.excepthook

        def sys_hook(exc_type, exc_value, exc_traceback) -> None:
            self.event(
                "unhandled_exception",
                severity="error",
                exception_type=getattr(exc_type, "__name__", str(exc_type)),
                message=str(exc_value),
                traceback="".join(
                    traceback.format_exception(exc_type, exc_value, exc_traceback)
                ),
            )
            self.request_sync()
            if self._old_excepthook is not None:
                self._old_excepthook(exc_type, exc_value, exc_traceback)

        def thread_hook(args) -> None:
            self.event(
                "thread_unhandled_exception",
                severity="error",
                thread=getattr(args.thread, "name", ""),
                exception_type=getattr(args.exc_type, "__name__", str(args.exc_type)),
                message=str(args.exc_value),
                traceback="".join(
                    traceback.format_exception(
                        args.exc_type,
                        args.exc_value,
                        args.exc_traceback,
                    )
                ),
            )
            self.request_sync()
            if self._old_threading_excepthook is not None:
                self._old_threading_excepthook(args)

        sys.excepthook = sys_hook
        threading.excepthook = thread_hook

    def restore_exception_hooks(self) -> None:
        if self._old_excepthook is not None:
            sys.excepthook = self._old_excepthook
        if self._old_threading_excepthook is not None:
            threading.excepthook = self._old_threading_excepthook

    def _worker_guarded(self) -> None:
        try:
            self._worker()
        except Exception:
            self._disable_after_failure()

    def _worker(self) -> None:
        next_sync = time.monotonic() + self.sync_interval
        finalizing = False

        while True:
            timeout = max(0.1, min(1.0, next_sync - time.monotonic()))
            try:
                command, payload = self._queue.get(timeout=timeout)
            except queue.Empty:
                command, payload = "", None

            if command == "event" and isinstance(payload, dict):
                self._append_event(payload)
            elif command == "screenshot" and isinstance(payload, str):
                self._capture_screenshot_sync(payload)
            elif command == "sync":
                self._sync_best_effort()
                next_sync = time.monotonic() + self.sync_interval
            elif command == "finalize":
                finalizing = True

            if time.monotonic() >= next_sync:
                if self._dirty:
                    self._sync_best_effort()
                next_sync = time.monotonic() + self.sync_interval

            if finalizing and self._queue.empty():
                self._write_summary("completed")
                self._sync_best_effort()
                break

            if self._stop.is_set() and self._queue.empty() and not finalizing:
                self._write_summary("completed")
                self._sync_best_effort()
                break

    def _append_event(self, payload: dict[str, Any]) -> None:
        self.session_path.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
        self._event_count += 1
        self._dirty = True
        self._write_summary("running")

    def _write_summary(self, status: str) -> None:
        self._write_json(
            self.summary_path,
            {
                "session_id": self.session_id,
                "started_at_utc": self._started_at,
                "updated_at_utc": utc_now(),
                "status": status,
                "event_count": self._event_count,
                "screenshots_enabled": self.screenshots_enabled,
                "last_sync_error": sanitize_text(self._last_sync_error or ""),
            },
        )
        self._dirty = True

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(
            json.dumps(sanitize_value(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)

    def _capture_screenshot_sync(self, reason: str) -> None:
        if mss is None:
            self._append_event(
                {
                    "ts_utc": utc_now(),
                    "monotonic_ms": round(time.monotonic() * 1000),
                    "event": "screenshot_failed",
                    "severity": "warning",
                    "data": {"reason": reason, "error": "mss unavailable"},
                }
            )
            return
        safe_reason = (
            re.sub(r"[^A-Za-z0-9_-]+", "-", reason).strip("-")[:50] or "event"
        )
        filename = f"{datetime.now().strftime('%H%M%S-%f')[:-3]}-{safe_reason}.png"
        target = self.screenshots_path / filename
        try:
            with mss.mss() as capture:
                monitor = capture.monitors[0]
                shot = capture.grab(monitor)
                mss.tools.to_png(shot.rgb, shot.size, output=str(target))
            self._append_event(
                {
                    "ts_utc": utc_now(),
                    "monotonic_ms": round(time.monotonic() * 1000),
                    "event": "screenshot_captured",
                    "severity": "info",
                    "data": {"reason": reason, "file": f"screenshots/{filename}"},
                }
            )
        except Exception as exc:  # noqa: BLE001 - telemetry must never crash app
            self._append_event(
                {
                    "ts_utc": utc_now(),
                    "monotonic_ms": round(time.monotonic() * 1000),
                    "event": "screenshot_failed",
                    "severity": "warning",
                    "data": {"reason": reason, "error": sanitize_text(repr(exc))},
                }
            )

    def _sync_best_effort(self) -> None:
        if not self.sync_enabled or not self._dirty:
            return
        try:
            git = find_git()
            if git is None:
                raise RuntimeError("git executable not found")
            self._ensure_repo(git)
            self._copy_session_to_repo()
            self._git_commit_and_push(git)
            self._last_sync_error = None
            self._dirty = False
            self.status_message = f"Telemetria sincronizada • {self.session_id}"
            self.sync_status_changed.emit(True, self.status_message)
        except Exception as exc:  # noqa: BLE001 - sync failure is non-fatal by design
            self._last_sync_error = sanitize_text(repr(exc))
            self.status_message = "Diagnóstico mantido localmente; envio não concluído."
            self.sync_status_changed.emit(False, self.status_message)

    def _ensure_repo(self, git: Path) -> None:
        git_dir = self.repo_path / ".git"
        if not git_dir.exists():
            if self.repo_path.exists():
                shutil.rmtree(self.repo_path, ignore_errors=True)
            self.repo_path.parent.mkdir(parents=True, exist_ok=True)

            self._run_git(
                git,
                ["clone", self.repo_url, str(self.repo_path)],
                cwd=self.repo_path.parent,
                timeout=25,
            )
            self._run_git(git, ["checkout", "-B", "main"], cwd=self.repo_path)

        # Keep identity/configuration local to the diagnostics clone. Re-applying
        # these values is cheap and also repairs a partially initialized clone.
        origin = self._run_git(git, ["remote", "get-url", "origin"], cwd=self.repo_path, capture=True).strip()
        if origin != self.repo_url:
            raise RuntimeError("Destino alterado; clone anterior preservado. Use a exportação local.")
        self._run_git(
            git,
            ["config", "user.name", "Meeting Assistant Diagnostics"],
            cwd=self.repo_path,
        )
        self._run_git(
            git,
            ["config", "user.email", "meeting-assistant@local.invalid"],
            cwd=self.repo_path,
        )

        readme = self.repo_path / "README.md"
        if not readme.exists():
            readme.write_text(
                "# Meeting Assistant Diagnostics\n\n"
                "Repositorio privado preenchido automaticamente pelo Meeting Assistant.\n\n"
                "Cada pasta em sessions/ contem telemetria sanitizada de uma execucao.\n"
                "Falhas de sincronizacao nunca bloqueiam o aplicativo.\n",
                encoding="utf-8",
            )

        schema = self.repo_path / "SCHEMA.md"
        if not schema.exists():
            schema.write_text(
                "# Telemetry schema\n\n"
                "- latest.json: ponteiro para a sessao mais recente.\n"
                "- sessions/<id>/summary.json: estado e contadores da sessao.\n"
                "- sessions/<id>/system.json: ambiente sanitizado.\n"
                "- sessions/<id>/events.jsonl: eventos estruturados em ordem temporal.\n"
                "- sessions/<id>/screenshots/: opcional e desativado por padrao.\n",
                encoding="utf-8",
            )

    def _copy_session_to_repo(self) -> None:
        target = self.repo_path / "sessions" / self.session_id
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(self.session_path, target)
        self._write_json(
            self.repo_path / "latest.json",
            {
                "schema_version": 1,
                "session_id": self.session_id,
                "updated_at_utc": utc_now(),
                "path": f"sessions/{self.session_id}",
            },
        )

    def _git_commit_and_push(self, git: Path) -> None:
        self._run_git(
            git,
            [
                "add",
                "README.md",
                "SCHEMA.md",
                "latest.json",
                f"sessions/{self.session_id}",
            ],
            cwd=self.repo_path,
        )
        status = self._run_git(
            git,
            ["status", "--porcelain"],
            cwd=self.repo_path,
            capture=True,
        )
        if not status.strip():
            return

        self._run_git(
            git,
            ["commit", "-m", f"telemetry: {self.session_id} update"],
            cwd=self.repo_path,
            timeout=15,
        )

        remote_has_main = bool(
            self._run_git(
                git,
                ["ls-remote", "--heads", "origin", "main"],
                cwd=self.repo_path,
                capture=True,
                timeout=15,
                check=False,
            ).strip()
        )
        if remote_has_main:
            self._run_git(
                git,
                ["pull", "--rebase", "origin", "main"],
                cwd=self.repo_path,
                timeout=20,
            )
        self._run_git(
            git,
            ["push", "-u", "origin", "main"],
            cwd=self.repo_path,
            timeout=25,
        )

    @staticmethod
    def _run_git(
        git: Path,
        args: list[str],
        *,
        cwd: Path,
        timeout: int = 12,
        capture: bool = False,
        check: bool = True,
    ) -> str:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GCM_INTERACTIVE"] = "Never"
        completed = subprocess.run(
            [str(git), *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
            check=False,
            env=env,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        if check and completed.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args[:2])} failed ({completed.returncode}): "
                f"{sanitize_text(output.strip())[:600]}"
            )
        return output if capture else output
