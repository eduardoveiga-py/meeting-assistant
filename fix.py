with open("src/meeting_assistant/services/obs_controller.py", encoding="utf-8") as f:
    lines = f.read().split("\n")

out = []
skip = False
for line in lines:
    if "preview_changed = Signal(bytes)" in line:
        continue
    if "preview_error = Signal(str)" in line:
        continue
    if "preview_age = Signal(float)" in line:
        continue
    if "screenshot_preview: bool = True" in line:
        out.append(line.replace(", *, screenshot_preview: bool = True", ""))
        continue
    if "self._screenshot_preview = screenshot_preview" in line:
        continue
    if "self._preview_interval =" in line:
        continue
    if "self._last_preview_error =" in line:
        continue
    if "from meeting_assistant.services.preview_stream import PreviewStream" in line:
        continue
    if "self._preview_stream = PreviewStream()" in line:
        continue
    if "self._preview_last = 0.0" in line:
        continue
    if "self._preview_delivery = QTimer(self)" in line:
        continue
    if "self._preview_delivery.setInterval(50)" in line:
        continue
    if "self._preview_delivery.timeout.connect(self._deliver_preview)" in line:
        continue
    if "self._preview_stream.config = config" in line:
        continue
    if "self._preview_stream.start()" in line:
        continue
    if "self._preview_delivery.start()" in line:
        continue
    if "def refresh_preview(self) -> None:" in line:
        skip = True
        continue
    if skip and line.startswith("    def stop(self) -> None:"):
        skip = False
    if skip:
        continue

    if "self._preview_delivery.stop()" in line:
        continue
    if "self._preview_stream.stop()" in line:
        continue
    if "next_preview = 0.0" in line:
        continue
    if "next_preview =" in line:
        continue
    if 'elif command == "preview":' in line:
        continue

    if "if self._client is not None and now >= next_preview:" in line:
        skip = True
        continue
    if skip and line.startswith("        self._disconnect()"):
        skip = False
    if skip:
        continue

    if "self._preview_stream.set_scene(scene)" in line:
        continue
    if "self._preview_stream.set_scene(None)" in line:
        continue

    if "def _refresh_preview(self) -> None:" in line:
        skip = True
        continue
    if skip and line.startswith("    def _handle_set_scene"):
        skip = False
    if skip:
        continue

    if "def _emit_preview_error(self, message: str) -> None:" in line:
        skip = True
        continue
    if skip and line.startswith("    def _set_connected"):
        skip = False
    if skip:
        continue

    out.append(line)

with open("src/meeting_assistant/services/obs_controller.py", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
