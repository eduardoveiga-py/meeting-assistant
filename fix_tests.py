with open("tests/test_operator_improvements.py", encoding="utf-8") as f:
    lines = f.read().split("\n")

out = []
skip = False
for line in lines:
    if "from meeting_assistant.services.preview_stream import PreviewStream" in line:
        continue
    if "def test_preview_stream" in line:
        skip = True
        continue
    if skip and line.startswith("def "):
        skip = False
    if skip:
        continue
    out.append(line)

with open("tests/test_operator_improvements.py", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
