with open("src/meeting_assistant/ui/main_window.py", encoding="utf-8") as f:
    lines = f.read().split("\n")

out = []
skip = False
for line in lines:
    if "self.obs.preview_age.connect(self._preview_age)" in line:
        continue
    if "def _preview_age(self, age):" in line:
        skip = True
        continue
    if skip and line.startswith("    def _manual_select"):
        skip = False
    if skip:
        continue

    if 'if hasattr(self.obs, "_preview_stream"):' in line:
        skip = True
        continue
    if skip and line.startswith("        if time.monotonic()"):
        skip = False
    if skip:
        continue

    if "self.obs.refresh_preview()" in line:
        continue

    if "def _start_preview_fade(self) -> None:" in line:
        skip = True
        continue
    if skip and line.startswith("    def _on_displays_changed"):
        skip = False
    if skip:
        continue

    out.append(line)

with open("src/meeting_assistant/ui/main_window.py", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
