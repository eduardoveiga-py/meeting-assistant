import re

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

c = c.replace(helper, "")
c = c.replace(helper.lstrip(), "")

# find imports end
imports_end = c.rfind("from meeting_assistant.ui.window_geometry import ScreenFitController")
end_line = c.find("\n", imports_end)

c = c[: end_line + 1] + "\n" + helper.strip() + "\n" + c[end_line + 1 :]

c = re.sub(r"        visible = self\.isVisible\(\) and not self\.isMinimized\(\)\n", "", c)

with open("src/meeting_assistant/ui/main_window.py", "w", encoding="utf-8") as f:
    f.write(c)
