
with open("src/meeting_assistant/services/obs_controller.py", encoding="utf-8") as f:
    c = f.read()

c = c.replace("screenshot_preview: bool = True", "screenshot_preview: bool = False")
c = c.replace("self._preview_stream.start()", "pass  # self._preview_stream.start()")
c = c.replace("self._preview_delivery.start()", "pass  # self._preview_delivery.start()")

with open("src/meeting_assistant/services/obs_controller.py", "w", encoding="utf-8") as f:
    f.write(c)


with open("src/meeting_assistant/ui/main_window.py", encoding="utf-8") as f:
    c = f.read()

helper = """
def _is_local_host(host: str) -> bool:
    if host.lower() in {"localhost", "127.0.0.1", "::1"}:
        return True
    import socket
    try:
        return socket.gethostbyname(host) == socket.gethostbyname(socket.gethostname())
    except Exception:
        return False
"""
c = c.replace("from __future__ import annotations", "from __future__ import annotations\n" + helper)
c = c.replace(
    """                and self.settings.obs_host.lower()
                in {
                    "127.0.0.1",
                    "localhost",
                    "::1",
                }""",
    "                and _is_local_host(self.settings.obs_host)",
)

with open("src/meeting_assistant/ui/main_window.py", "w", encoding="utf-8") as f:
    f.write(c)
