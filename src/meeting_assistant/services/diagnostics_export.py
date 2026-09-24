"""Explicit local export. Never include screenshots, settings or a Git checkout."""
from __future__ import annotations

import json
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from meeting_assistant.services.telemetry_service import sanitize_value


def export_latest_session(destination: Path, root: Path | None = None) -> Path:
    root = root or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MeetingAssistant" / "telemetry"
    sessions = root / "sessions"
    candidates = sorted(
        (p for p in sessions.glob("MA-*") if p.is_dir() and not p.is_symlink()), reverse=True
    )
    if not candidates:
        raise ValueError("Nenhuma sessão de diagnóstico local disponível.")
    session = candidates[0]
    payloads = {}
    for name in ("system.json", "summary.json", "events.jsonl"):
        source = session / name
        if not source.is_file() or source.is_symlink():
            continue
        with source.open(encoding="utf-8") as handle:
            # A fixed snapshot avoids chasing a file still being appended by telemetry.
            content = handle.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            raise ValueError("Sessão grande demais para exportação automática; revise os arquivos locais.")
        if name.endswith(".jsonl"):
            rows = []
            for line in content.splitlines():
                try:
                    rows.append(json.dumps(sanitize_value(json.loads(line)), ensure_ascii=False))
                except json.JSONDecodeError:
                    # The writer may still be finishing its last line.
                    continue
            payloads[name] = "\n".join(rows) + "\n"
        else:
            payloads[name] = json.dumps(sanitize_value(json.loads(content)), ensure_ascii=False, indent=2)
    if not payloads:
        raise ValueError("Nenhum diagnóstico disponível nesta sessão.")
    # Build the complete archive before replacing the selected output file.
    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile(dir=destination.parent, suffix=".zip", delete=False) as temp:
        temporary = Path(temp.name)
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
            for name, content in payloads.items():
                archive.writestr(f"{session.name}/{name}", content)
            archive.writestr(
                "LEIA-ME.txt",
                "Diagnóstico local. Revise os textos antes de compartilhar. "
                "Screenshots, configurações e histórico Git não foram incluídos.\n",
            )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
