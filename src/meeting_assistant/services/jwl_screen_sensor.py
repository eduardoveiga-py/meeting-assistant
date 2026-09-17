from __future__ import annotations

from dataclasses import dataclass

import mss
from mss.exception import ScreenShotError

from meeting_assistant.services.jwl_service import JwlWindowInfo

SAMPLE_WIDTH = 160
SAMPLE_HEIGHT = 90


@dataclass(frozen=True, slots=True)
class CaptureRegion:
    hwnd: int
    left: int
    top: int
    width: int
    height: int

    @property
    def monitor(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


def window_center_inside_display(
    window: JwlWindowInfo,
    display_bounds: tuple[int, int, int, int],
) -> bool:
    display_x, display_y, display_width, display_height = display_bounds
    center_x = window.left + max(0, window.right - window.left) // 2
    center_y = window.top + max(0, window.bottom - window.top) // 2
    return (
        display_x <= center_x < display_x + display_width
        and display_y <= center_y < display_y + display_height
    )


def choose_capture_regions(
    windows: list[JwlWindowInfo],
    preferred_display_bounds: tuple[int, int, int, int] | None = None,
    preferred_hwnd: int | None = None,
) -> list[CaptureRegion]:
    """Seleciona pequenas regiões centrais das janelas do JW Library.

    Em modo físico, ``preferred_hwnd`` é a fonte de verdade: ele vem do guardião
    que identificou persistentemente a janela de saída do Salão. A geometria do
    monitor é mantida apenas como fallback para simulação/compatibilidade.
    """

    candidates = [
        item
        for item in windows
        if item.visible
        and not item.minimized
        and item.right - item.left >= 400
        and item.bottom - item.top >= 300
    ]

    if preferred_hwnd is not None:
        candidates = [item for item in candidates if item.hwnd == preferred_hwnd]
    elif preferred_display_bounds is not None:
        candidates = [
            item
            for item in candidates
            if window_center_inside_display(item, preferred_display_bounds)
        ]

    candidates.sort(
        key=lambda item: (
            item.class_name == "ApplicationFrameWindow",
            item.foreground,
            (item.right - item.left) * (item.bottom - item.top),
        ),
        reverse=True,
    )

    max_regions = 1 if (preferred_hwnd is not None or preferred_display_bounds is not None) else 3
    regions: list[CaptureRegion] = []
    for item in candidates[:max_regions]:
        window_width = item.right - item.left
        window_height = item.bottom - item.top
        crop_width = min(640, max(320, int(window_width * 0.72)))
        crop_height = min(360, max(180, int(window_height * 0.58)))
        left = item.left + max(0, (window_width - crop_width) // 2)
        top = item.top + max(0, (window_height - crop_height) // 2)
        regions.append(
            CaptureRegion(
                hwnd=item.hwnd,
                left=left,
                top=top,
                width=crop_width,
                height=crop_height,
            )
        )
    return regions


def screenshot_to_luma(
    raw_bgra: bytes,
    width: int,
    height: int,
    *,
    output_width: int = SAMPLE_WIDTH,
    output_height: int = SAMPLE_HEIGHT,
) -> bytes:
    if width <= 0 or height <= 0:
        raise ValueError("dimensões de captura inválidas")
    expected = width * height * 4
    if len(raw_bgra) < expected:
        raise ValueError("frame BGRA incompleto")

    sample = bytearray(output_width * output_height)
    cursor = 0
    for out_y in range(output_height):
        source_y = min(height - 1, (out_y * height) // output_height)
        row_offset = source_y * width * 4
        for out_x in range(output_width):
            source_x = min(width - 1, (out_x * width) // output_width)
            offset = row_offset + source_x * 4
            blue = raw_bgra[offset]
            green = raw_bgra[offset + 1]
            red = raw_bgra[offset + 2]
            sample[cursor] = (77 * red + 150 * green + 29 * blue) >> 8
            cursor += 1
    return bytes(sample)


class JwlScreenSensor:
    """Captura somente regiões das janelas do JW Library usando pixels do Windows."""

    def __init__(self) -> None:
        self._capture = mss.mss()

    def close(self) -> None:
        close = getattr(self._capture, "close", None)
        if callable(close):
            close()

    def capture(self, region: CaptureRegion) -> bytes | None:
        try:
            shot = self._capture.grab(region.monitor)
        except (OSError, ValueError, ScreenShotError):
            return None
        return screenshot_to_luma(shot.bgra, shot.width, shot.height)
