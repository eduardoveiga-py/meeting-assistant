from pathlib import Path


def resolve(path):
    p = Path(path)
    if not p.exists():
        return
    content = p.read_text(encoding="utf-8")

    lines = content.splitlines()
    out = []
    state = 0
    head_lines = []
    feature_lines = []

    for line in lines:
        if line.startswith("<<<<<<< HEAD"):
            state = 1
            head_lines = []
        elif line.startswith("======="):
            state = 2
            feature_lines = []
        elif line.startswith(">>>>>>>"):
            # Resolve!
            if (
                len(head_lines) > 0
                and len(feature_lines) > 0
                and "version" in head_lines[0]
                and "version" in feature_lines[0]
            ):
                out.extend(feature_lines)
            elif path.endswith("settings.py"):
                if "telemetry_repo_url" in "".join(head_lines):
                    # We have an overlap on telemetry_repo_url. Keep head's telemetry_sync_enabled but use feature's repo url and layouts.
                    out.append("    telemetry_sync_enabled: bool = False")
                    out.extend(feature_lines)
                else:
                    out.extend(head_lines)
                    out.extend(feature_lines)
            else:
                out.extend(head_lines)
                out.extend(feature_lines)
            state = 0
        else:
            if state == 1:
                head_lines.append(line)
            elif state == 2:
                feature_lines.append(line)
            else:
                out.append(line)

    p.write_text("\n".join(out) + "\n", encoding="utf-8")


for file in "pyproject.toml src/meeting_assistant/__init__.py src/meeting_assistant/services/obs_controller.py src/meeting_assistant/services/settings.py src/meeting_assistant/services/setup_assistant.py src/meeting_assistant/services/telemetry_service.py src/meeting_assistant/ui/main_window.py src/meeting_assistant/ui/settings_dialog.py .github/workflows/release.yml CHANGELOG.md docs/operator-guide.md packaging/MeetingAssistant.iss packaging/MeetingAssistant.spec packaging/README.md".split():
    resolve(file)
