"""Adapt pinned Microsoft SimpleMediaSource in an isolated build checkout."""

import sys
from pathlib import Path

CLSID = "C5C7589B-FF9A-4E96-B156-68479F4C75CA"
HARDWARE_ID = r"root\MeetingAssistantFrameServerPoC"


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Upstream changed: {old[:80]!r}")
    return text.replace(old, new)


def prepare(root):
    sample = root / "general/SimpleMediaSource"
    inf = sample / "SimpleMediaSourceDriver/SimpleMediaSourceDriver.inf"
    raw = inf.read_bytes()
    content = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    content = content.replace("\r\n", "\n")
    content = content.replace("Include=WUDFRD.inf\n", "")
    content = content.replace("Needs=WUDFRD.NT\n", "")
    content = content.replace("Needs=WUDFRD.NT.HW\n", "")
    content = replace_once(
        content,
        "Needs=WUDFRD.NT.Services",
        """AddService=WUDFRd,0x000001fa,WUDFRD_ServiceInstall

[WUDFRD_ServiceInstall]
DisplayName="Windows Driver Foundation - User-mode Driver Framework Reflector"
ServiceType=1
StartType=3
ErrorControl=1
ServiceBinary=%12%\\WUDFRd.sys""",
    )
    content = content.replace("...17134", "...19041")
    content = replace_once(content, r"root\SimpleMediaSource", HARDWARE_ID)
    content = replace_once(content, "{9812588D-5CE9-4E4C-ABC1-049138D10DCE}", "{" + CLSID + "}")
    content = content.replace('"SimpleMediaSource Capture Source"', '"Meeting Assistant Camera PoC"')
    content = content.replace('"SimpleMediaSource Source"', '"Meeting Assistant Camera PoC"')
    content = content.replace(
        'ProviderString = "SimpleMediaSource"', 'ProviderString = "Meeting Assistant Experimental"'
    )
    content = content.replace("UmdfService=SimpleMediaSource,", "UmdfService=MeetingAssistantFrameServerPoC,")
    content = content.replace(
        "UmdfServiceOrder=SimpleMediaSource", "UmdfServiceOrder=MeetingAssistantFrameServerPoC"
    )
    assert "WUDFRD.inf" not in content
    assert "...19041" in content and HARDWARE_ID in content
    inf.write_text(content, encoding="utf-16")
    header = sample / "MediaSource/SimpleMediaSourceActivate.h"
    content = replace_once(
        header.read_text(encoding="utf-8-sig"), "9812588D-5CE9-4E4C-ABC1-049138D10DCE", CLSID
    )
    header.write_text(content, encoding="utf-8")
    for project in sample.rglob("*.vcxproj"):
        text = project.read_text(encoding="utf-8-sig")
        text = text.replace("stdcpp17", "stdcpp20")
        project.write_text(text, encoding="utf-8")
    # WDK/SDK versions must match; pin VS2022-compatible kits for the CI runner.
    props = root / "Directory.Build.props"
    packages = {
        "Microsoft.Windows.WDK.x64": "Microsoft.Windows.WDK.x64",
        "Microsoft.Windows.SDK.CPP.x64": "Microsoft.Windows.SDK.cpp.x64",
        "Microsoft.Windows.SDK.CPP": "Microsoft.Windows.SDK.cpp",
    }
    imports = [
        f'<Import Project="packages/{name}.10.0.26100.2454/build/native/{file}.props" />'
        for name, file in packages.items()
    ]
    props.write_text("<Project>\n" + "\n".join(imports) + "\n</Project>", encoding="utf-8")


if __name__ == "__main__":
    prepare(Path(sys.argv[1]))
