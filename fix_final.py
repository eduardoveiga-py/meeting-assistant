import re

with open("src/meeting_assistant/ui/main_window.py", encoding="utf-8") as f:
    c = f.read()

# remove everything between from __future__ import annotations and import time
c = re.sub(
    r"from __future__ import annotations.*?(?=import time)",
    "from __future__ import annotations\n\n",
    c,
    flags=re.DOTALL,
)

with open("src/meeting_assistant/ui/main_window.py", "w", encoding="utf-8") as f:
    f.write(c)
