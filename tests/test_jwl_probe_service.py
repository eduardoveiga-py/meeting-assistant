from meeting_assistant.services.jwl_probe_service import (
    describe_changes,
    structural_signature,
)
from meeting_assistant.services.jwl_service import JwlWindowInfo


def make_window(
    hwnd: int = 100,
    *,
    title: str = "JW Library",
    left: int = 0,
    top: int = 0,
    right: int = 1280,
    bottom: int = 720,
    visible: bool = True,
    minimized: bool = False,
) -> JwlWindowInfo:
    return JwlWindowInfo(
        hwnd=hwnd,
        pid=42,
        process_name="JWLibrary.exe",
        title=title,
        class_name="ApplicationFrameWindow",
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        visible=visible,
        minimized=minimized,
        foreground=False,
    )


def test_structural_signature_ignores_foreground_only() -> None:
    first = make_window()
    second = JwlWindowInfo(
        hwnd=first.hwnd,
        pid=first.pid,
        process_name=first.process_name,
        title=first.title,
        class_name=first.class_name,
        left=first.left,
        top=first.top,
        right=first.right,
        bottom=first.bottom,
        visible=first.visible,
        minimized=first.minimized,
        foreground=True,
    )

    assert structural_signature([first]) == structural_signature([second])


def test_describe_changes_reports_created_window() -> None:
    result = describe_changes((make_window(),), (make_window(), make_window(200)))

    assert any("janela criada" in line and "HWND 200" in line for line in result)


def test_describe_changes_reports_geometry_change() -> None:
    result = describe_changes(
        (make_window(),),
        (make_window(left=1280, right=2560),),
    )

    assert any("retângulo" in line for line in result)


def test_describe_changes_reports_visibility_change() -> None:
    result = describe_changes(
        (make_window(),),
        (make_window(visible=False),),
    )

    assert any("visível True → False" in line for line in result)
