from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

if TYPE_CHECKING:
    from meeting_assistant.services.jwl_media_importer import MediaImportItem

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
_VIDEO_EXTS = {".mp4", ".m4v", ".webm", ".mkv", ".mov", ".avi"}
_AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".wma"}

_THUMBNAIL_CACHE: dict[str, QPixmap] = {}


def get_video_thumbnail_shell(file_path: Path, width: int = 128, height: int | None = None) -> QPixmap | None:
    """Extracts native Windows 11 Shell thumbnail for a video file (.mp4, .m4v, etc.)."""
    if not file_path or not file_path.is_file():
        return None
    w = max(16, width)
    h = max(16, height if height is not None else width)
    try:
        import ctypes
        import ctypes.wintypes
        import uuid

        clsid_bytes = uuid.UUID("{bcc18b79-ba16-442f-80c4-8a59c30c463b}").bytes_le

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        iid = GUID.from_buffer_copy(clsid_bytes)
        shell32 = ctypes.windll.shell32
        gdi32 = ctypes.windll.gdi32
        ole32 = ctypes.windll.ole32
        co_init_hr = ole32.CoInitialize(None)
        try:
            p_item = ctypes.c_void_p()
            hr = shell32.SHCreateItemFromParsingName(
                ctypes.c_wchar_p(str(file_path.resolve())),
                None,
                ctypes.byref(iid),
                ctypes.byref(p_item),
            )
            if hr != 0 or not p_item:
                return None
            vtable = ctypes.cast(p_item, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            GetImage = ctypes.WINFUNCTYPE(
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.wintypes.SIZE,
                ctypes.c_int,
                ctypes.POINTER(ctypes.wintypes.HBITMAP),
            )(vtable[3])
            Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
            hbm = ctypes.wintypes.HBITMAP()
            sz = ctypes.wintypes.SIZE(w, h)
            # SIIGBF_BIGGERSIZEOK (0x01) ensures fast return even if aspect/size is not exact
            hr = GetImage(p_item, sz, 0x01, ctypes.byref(hbm))
            if (hr != 0 or not hbm) and hr != 0:
                # Fallback to standard 0x0
                hr = GetImage(p_item, sz, 0x00, ctypes.byref(hbm))
            Release(p_item)
            if hr != 0 or not hbm:
                return None
            img = QImage.fromHBITMAP(hbm.value)
            gdi32.DeleteObject(hbm)
            if img and not img.isNull():
                return QPixmap.fromImage(img)
            return None
        finally:
            if co_init_hr == 0:
                ole32.CoUninitialize()
    except Exception:
        return None


def format_duration(seconds: float) -> str:
    """Formats duration in seconds to M:SS or H:MM:SS."""
    if seconds <= 0:
        return ""
    total_sec = int(round(seconds))
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hrs > 0:
        return f"{hrs}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def render_media_thumbnail(
    item: MediaImportItem | Path,
    width: int = 72,
    height: int = 48,
) -> QPixmap:
    """Renders a polished thumbnail for an image, video, audio file, or JW Library media item."""
    from meeting_assistant.services.jwl_media_importer import MediaImportItem

    if isinstance(item, MediaImportItem):
        source_path = item.source_path
        duration = item.duration_seconds
        track = item.track
        thumbnail_path = item.thumbnail_path
        thumb_str = str(thumbnail_path) if thumbnail_path else ""
        cache_key = f"{source_path}:{thumb_str}:{duration}:{track}:{width}x{height}"
    else:
        source_path = Path(item)
        duration = 0.0
        track = None
        thumbnail_path = None
        cache_key = f"{source_path}::0:None:{width}x{height}"

    if cache_key in _THUMBNAIL_CACHE:
        return _THUMBNAIL_CACHE[cache_key]

    canvas = QPixmap(width, height)
    canvas.fill(Qt.GlobalColor.transparent)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    clip_rect = QRectF(0, 0, width, height)
    clip_path = QPainterPath()
    clip_path.addRoundedRect(clip_rect, 5.0, 5.0)
    painter.setClipPath(clip_path)

    ext = source_path.suffix.lower() if source_path else ""

    # Check for thumbnail image (direct thumbnail_path, image source_path,
    # sibling image, or native video thumbnail)
    preview_img_path = None
    native_video_pix = None
    if thumbnail_path and thumbnail_path.is_file():
        preview_img_path = thumbnail_path
    elif ext in _IMAGE_EXTS and source_path.is_file():
        preview_img_path = source_path
    elif source_path:
        for candidate_ext in (".thumb.jpg", ".thumb.png", ".jpg", ".jpeg", ".png"):
            sibling = source_path.with_suffix(candidate_ext)
            if sibling.is_file() and sibling != source_path:
                preview_img_path = sibling
                break

    if not preview_img_path and ext in _VIDEO_EXTS and source_path and source_path.is_file():
        native_video_pix = get_video_thumbnail_shell(source_path, width * 2, height * 2)

    # 1. Image or video with thumbnail
    img_pix = None
    if preview_img_path and preview_img_path.is_file():
        img_pix = QPixmap(str(preview_img_path))
    elif native_video_pix and not native_video_pix.isNull():
        img_pix = native_video_pix

    if img_pix and not img_pix.isNull():
        scaled = img_pix.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Center cropped
        x_off = (scaled.width() - width) / 2
        y_off = (scaled.height() - height) / 2
        painter.drawPixmap(QPointF(0, 0), scaled, QRectF(x_off, y_off, width, height))

        # Overlay play badge for video
        is_video = ext in _VIDEO_EXTS or (
            isinstance(item, MediaImportItem) and item.mime_type.startswith("video/")
        )
        if is_video:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 110))
            painter.drawEllipse(QPointF(width / 2, height / 2), 10, 10)
            painter.setPen(QColor(255, 255, 255, 240))
            font = QFont("Segoe UI", 9, QFont.Weight.Bold)
            painter.setFont(font)
            painter.drawText(
                QRectF(width / 2 - 9, height / 2 - 10, 20, 20),
                Qt.AlignmentFlag.AlignCenter,
                "▶",
            )

        if track is not None and track > 0:
            _draw_badge(painter, f"#{track}", QRectF(3, 3, 24, 11), bg_color=QColor(37, 99, 235, 220))

        if duration > 0:
            _draw_badge(painter, format_duration(duration), QRectF(width - 33, height - 14, 30, 11))

        _draw_border(painter, width, height)
        painter.end()
        _THUMBNAIL_CACHE[cache_key] = canvas
        return canvas

    # 2. Audio or Video or Fallback
    if ext in _AUDIO_EXTS or (isinstance(item, MediaImportItem) and item.mime_type.startswith("audio/")):
        _render_audio_card(painter, width, height, duration)
    elif ext in _VIDEO_EXTS or (isinstance(item, MediaImportItem) and item.mime_type.startswith("video/")):
        _render_video_card(painter, width, height, duration, track)
    else:
        # Generic media card (or song without file extension yet)
        if track is not None and track > 0:
            _render_song_card(painter, width, height, duration, track)
        else:
            _render_generic_card(painter, width, height, ext)

    _draw_border(painter, width, height)
    painter.end()

    _THUMBNAIL_CACHE[cache_key] = canvas
    return canvas


def _draw_border(painter: QPainter, width: int, height: int) -> None:
    pen = QPen(QColor(255, 255, 255, 35))
    pen.setWidthF(1.0)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(0.5, 0.5, width - 1.0, height - 1.0), 5.0, 5.0)


def _render_audio_card(painter: QPainter, width: int, height: int, duration: float) -> None:
    # Audio background: warm violet gradient
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0.0, QColor(67, 36, 102))
    gradient.setColorAt(1.0, QColor(36, 18, 56))
    painter.fillRect(0, 0, width, height, gradient)

    # Music note icon symbol
    painter.setPen(QColor(230, 210, 255))
    font = QFont("Segoe UI", 14, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(QRectF(0, 4, width, height - 16), Qt.AlignmentFlag.AlignCenter, "🎵")

    # Format badge
    _draw_badge(painter, "MP3", QRectF(4, height - 14, 26, 11), bg_color=QColor(0, 0, 0, 160))

    if duration > 0:
        dur_str = format_duration(duration)
        _draw_badge(painter, dur_str, QRectF(width - 32, height - 14, 28, 11))


def _render_video_card(
    painter: QPainter,
    width: int,
    height: int,
    duration: float,
    track: int | None,
) -> None:
    # Video background: deep navy gradient
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0.0, QColor(24, 43, 73))
    gradient.setColorAt(1.0, QColor(13, 23, 40))
    painter.fillRect(0, 0, width, height, gradient)

    # Play badge in center
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 45))
    painter.drawEllipse(QPointF(width / 2, height / 2 - 2), 11, 11)

    painter.setPen(QColor(255, 255, 255, 230))
    font = QFont("Segoe UI", 10, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(
        QRectF(width / 2 - 10, height / 2 - 12, 22, 20),
        Qt.AlignmentFlag.AlignCenter,
        "▶",
    )

    if track is not None and track > 0:
        _draw_badge(painter, f"#{track}", QRectF(3, 3, 24, 11), bg_color=QColor(37, 99, 235, 220))

    if duration > 0:
        dur_str = format_duration(duration)
        _draw_badge(painter, dur_str, QRectF(width - 33, height - 14, 30, 11))
    else:
        _draw_badge(painter, "MP4", QRectF(width - 28, height - 14, 25, 11))


def _render_song_card(
    painter: QPainter,
    width: int,
    height: int,
    duration: float,
    track: int,
) -> None:
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0.0, QColor(26, 68, 128))
    gradient.setColorAt(1.0, QColor(15, 35, 68))
    painter.fillRect(0, 0, width, height, gradient)

    # Song symbol
    painter.setPen(QColor(200, 225, 255))
    font = QFont("Segoe UI", 12, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(QRectF(0, 2, width, height - 14), Qt.AlignmentFlag.AlignCenter, "🎼")

    _draw_badge(painter, f"#{track}", QRectF(3, 3, 25, 11), bg_color=QColor(30, 64, 175, 230))

    if duration > 0:
        dur_str = format_duration(duration)
        _draw_badge(painter, dur_str, QRectF(width - 33, height - 14, 30, 11))


def _render_generic_card(painter: QPainter, width: int, height: int, ext: str) -> None:
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0.0, QColor(45, 55, 72))
    gradient.setColorAt(1.0, QColor(26, 32, 44))
    painter.fillRect(0, 0, width, height, gradient)

    painter.setPen(QColor(203, 213, 225))
    font = QFont("Segoe UI", 11, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(QRectF(0, 4, width, height - 16), Qt.AlignmentFlag.AlignCenter, "📁")

    tag = ext.replace(".", "").upper()[:4] or "DOC"
    _draw_badge(painter, tag, QRectF(width - 28, height - 14, 25, 11))


def _draw_badge(
    painter: QPainter,
    text: str,
    rect: QRectF,
    bg_color: QColor | None = None,
) -> None:
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(bg_color or QColor(0, 0, 0, 175)))
    painter.drawRoundedRect(rect, 2.5, 2.5)

    painter.setPen(QColor(255, 255, 255, 240))
    font = QFont("Segoe UI", 6, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()
