from __future__ import annotations

import datetime
import logging
import os
import re
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QThread, Signal
from PySide6.QtGui import QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from meeting_assistant.services.jwl_media_importer import MediaImportItem
from meeting_assistant.services.meeting_media_downloader import (
    POPULAR_VIDEO_CATEGORIES,
    SUPPORTED_MEPS_LANGUAGES,
    CancelToken,
    MediaDownloadItem,
    MeetingWeekInfo,
    normalize_meps_language,
)
from meeting_assistant.services.meeting_media_service import MeetingMediaService
from meeting_assistant.services.settings import AppSettings, SettingsService
from meeting_assistant.ui.media_thumbnail_helper import (
    format_duration,
    render_media_thumbnail,
)
from meeting_assistant.ui.window_geometry import ScreenFitController

logger = logging.getLogger(__name__)


def _unblock_windows_drag_drop(win_id: int) -> None:
    if os.name != "nt" or not win_id:
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        wm_dropfiles = 0x0233
        wm_copydata = 0x004A
        wm_copyglobaldata = 0x0049
        msgflt_allow = 1
        if hasattr(user32, "ChangeWindowMessageFilter"):
            user32.ChangeWindowMessageFilter(wm_dropfiles, msgflt_allow)
            user32.ChangeWindowMessageFilter(wm_copydata, msgflt_allow)
            user32.ChangeWindowMessageFilter(wm_copyglobaldata, msgflt_allow)
        if hasattr(user32, "ChangeWindowMessageFilterEx"):
            user32.ChangeWindowMessageFilterEx.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.DWORD,
                ctypes.c_void_p,
            ]
            user32.ChangeWindowMessageFilterEx.restype = wintypes.BOOL
            hwnd = wintypes.HWND(win_id)
            user32.ChangeWindowMessageFilterEx(hwnd, wm_dropfiles, msgflt_allow, None)
            user32.ChangeWindowMessageFilterEx(hwnd, wm_copydata, msgflt_allow, None)
            user32.ChangeWindowMessageFilterEx(hwnd, wm_copyglobaldata, msgflt_allow, None)
    except Exception as exc:
        logger.debug("Falha em _unblock_windows_drag_drop: %s", exc)


class PlaylistListWidget(QListWidget):
    """ListWidget with drag & drop support for dropping files from Windows Explorer
    and reordering items.
    """

    files_dropped = Signal(list)
    item_reordered = Signal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setStyleSheet(
            "QListWidget { background-color: #161b22; border: 1px solid #30363d; border-radius: 6px; }"
            "QListWidget::item { border-bottom: 1px solid #21262d; margin: 0px; padding: 2px; }"
            "QListWidget::item:selected { background-color: #1f242c; }"
        )

    @staticmethod
    def has_acceptable_files(mime_data: QMimeData | None) -> bool:
        """Verificação rápida (sem I/O de disco) de se há arquivos aceitáveis no drag."""
        if not mime_data:
            return False
        if hasattr(mime_data, "hasUrls") and mime_data.hasUrls():
            return True
        return any(
            mime_data.hasFormat(fmt)
            for fmt in (
                "text/uri-list",
                'application/x-qt-windows-mime;value="FileNameW"',
                "FileNameW",
                'application/x-qt-windows-mime;value="FileName"',
                "FileName",
            )
        )

    @staticmethod
    def extract_file_paths(mime_data: QMimeData | None) -> list[Path]:
        if not mime_data:
            return []
        paths: list[Path] = []
        try:
            # 1. Standard Qt URLs
            if hasattr(mime_data, "hasUrls") and mime_data.hasUrls():
                for url in mime_data.urls():
                    if hasattr(url, "isLocalFile") and url.isLocalFile():
                        paths.append(Path(url.toLocalFile()))
                    elif hasattr(url, "scheme") and url.scheme() in ("file", ""):
                        p = url.path()
                        if p.startswith("/") and len(p) > 2 and p[2] == ":":
                            p = p[1:]
                        if p:
                            paths.append(Path(p))

            # 2. text/uri-list
            if not paths and hasattr(mime_data, "hasFormat"):
                if mime_data.hasFormat("text/uri-list") is True:
                    raw_data = mime_data.data("text/uri-list")
                    text_data = (
                        bytes(raw_data).decode("utf-8", errors="ignore")
                        if raw_data
                        else ""
                    )
                    for line in text_data.splitlines():
                        line = line.strip()
                        if line.startswith("file:///"):
                            line = line[8:]
                        elif line.startswith("file://"):
                            line = line[7:]
                        if line:
                            paths.append(Path(line))

            # 3. Windows Explorer native OLE CF_HDROP WideChar format (FileNameW)
            if not paths and hasattr(mime_data, "hasFormat"):
                for fmt in ('application/x-qt-windows-mime;value="FileNameW"', "FileNameW"):
                    if mime_data.hasFormat(fmt) is True:
                        raw_data = mime_data.data(fmt)
                        if raw_data:
                            decoded = bytes(raw_data).decode("utf-16le", errors="ignore")
                            for item in decoded.split("\x00"):
                                item = item.strip()
                                if item:
                                    paths.append(Path(item))
                        if paths:
                            break

            # 4. Windows Explorer native OLE CF_HDROP ANSI format (FileName)
            if not paths and hasattr(mime_data, "hasFormat"):
                for fmt in ('application/x-qt-windows-mime;value="FileName"', "FileName"):
                    if mime_data.hasFormat(fmt) is True:
                        raw_data = mime_data.data(fmt)
                        if raw_data:
                            decoded = bytes(raw_data).decode("mbcs", errors="ignore")
                            for item in decoded.split("\x00"):
                                item = item.strip()
                                if item:
                                    paths.append(Path(item))
                        if paths:
                            break

            # 5. Plain text file paths (e.g. copied/dragged path string)
            if not paths and hasattr(mime_data, "hasText") and mime_data.hasText():
                txt = mime_data.text().strip()
                for line in txt.splitlines():
                    line = line.strip().strip('"').strip("'")
                    if line.startswith("file:///"):
                        line = line[8:]
                    elif line.startswith("file://"):
                        line = line[7:]
                    if line and ((len(line) > 2 and line[1] == ":") or line.startswith("\\\\")):
                        p = Path(line)
                        if p.exists():
                            paths.append(p)
        except Exception:
            pass

        # Expand any dropped folders to include supported media items recursively
        expanded: list[Path] = []
        valid_exts = {
            ".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov",
            ".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac",
            ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif",
            ".jwpub", ".jwlplaylist",
        }

        def natural_sort_key(path: Path):
            return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]

        for p in paths:
            try:
                if p.is_dir():
                    sub_files = [
                        child
                        for child in p.rglob("*")
                        if child.is_file() and child.suffix.lower() in valid_exts
                    ]
                    sub_files.sort(key=natural_sort_key)
                    expanded.extend(sub_files)
                else:
                    expanded.append(p)
            except Exception:
                expanded.append(p)

        seen = set()
        unique = []
        for p in expanded:
            s = str(p).strip()
            if s and s != "\x00" and p not in seen:
                seen.add(p)
                unique.append(p)
        return unique

    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        item = self.currentItem()
        if not item:
            return
        row = self.row(item)
        mime_data = QMimeData()
        mime_data.setData("application/x-meeting-assistant-playlist-row", str(row).encode("utf-8"))

        drag = QDrag(self)
        drag.setMimeData(mime_data)

        widget = self.itemWidget(item)
        if widget:
            pixmap = widget.grab()
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(20, 20))

        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self.has_acceptable_files(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        if (
            hasattr(event.mimeData(), "hasFormat")
            and event.mimeData().hasFormat("application/x-meeting-assistant-playlist-row") is True
        ):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if (
            hasattr(event.mimeData(), "hasFormat")
            and event.mimeData().hasFormat("application/x-meeting-assistant-playlist-row") is True
        ):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return

        if self.has_acceptable_files(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return

        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = self.extract_file_paths(event.mimeData())
        if paths:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.files_dropped.emit(paths)
            return

        if (
            hasattr(event.mimeData(), "hasFormat")
            and event.mimeData().hasFormat("application/x-meeting-assistant-playlist-row") is True
        ):
            data = event.mimeData().data("application/x-meeting-assistant-playlist-row")
            try:
                src_row = int(bytes(data).decode("utf-8"))
            except (ValueError, TypeError):
                src_row = self.currentRow()
        else:
            src_row = self.currentRow()
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        target_idx = self.indexAt(pos)
        dst_row = target_idx.row() if target_idx.isValid() else self.count() - 1
        if src_row >= 0 and dst_row >= 0 and src_row != dst_row:
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            self.item_reordered.emit(src_row, dst_row)
        else:
            event.ignore()


class PlaylistDropContainer(QWidget):
    """Container widget that accepts drag & drop anywhere on the playlist page."""

    files_dropped = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if PlaylistListWidget.has_acceptable_files(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if PlaylistListWidget.has_acceptable_files(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = PlaylistListWidget.extract_file_paths(event.mimeData())
        if paths:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.files_dropped.emit(paths)
        else:
            event.ignore()



class PlaylistItemRowWidget(QWidget):
    """Custom widget for a playlist item showing thumbnail, title, subtitle,

    EndAction selector, and reorder/remove buttons.
    """

    label_changed = Signal(str)
    end_action_changed = Signal(int)
    move_up_requested = Signal()
    move_down_requested = Signal()
    remove_requested = Signal()

    def __init__(
        self,
        item: MediaImportItem,
        index: int,
        total_count: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.item = item
        self.index = index
        self.total_count = total_count
        self.setAcceptDrops(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        # 1. Order Index indicator
        self.idx_label = QLabel(f"{index + 1}.")
        self.idx_label.setFixedWidth(20)
        self.idx_label.setStyleSheet("color: #8b949e; font-weight: bold; font-size: 11px;")
        self.idx_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.idx_label)

        # 2. Thumbnail
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(50, 32)
        pix = render_media_thumbnail(item, width=50, height=32)
        self.thumb_label.setPixmap(pix)
        self.thumb_label.setToolTip(item.label)
        layout.addWidget(self.thumb_label)

        # 3. Label & Details
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        self.label_edit = QLineEdit(item.label)
        self.label_edit.setAcceptDrops(False)
        self.label_edit.setStyleSheet(
            "QLineEdit { background: transparent; border: 1px solid transparent; "
            "border-radius: 3px; color: #f0f6fc; font-weight: 600; padding: 1px 3px; }"
            "QLineEdit:focus { background: #0d1117; border: 1px solid #58a6ff; }"
            "QLineEdit:hover { border: 1px solid #30363d; }"
        )
        self.label_edit.textChanged.connect(self._on_text_changed)
        text_layout.addWidget(self.label_edit)

        # Subtitle info
        src_name = item.source_path.name if item.source_path else ""
        dur_str = f" • {format_duration(item.duration_seconds)}" if item.duration_seconds > 0 else ""
        ext = (
            item.source_path.suffix.upper().replace(".", "")
            if (item.source_path and item.source_path.suffix)
            else ""
        )
        if ext in ("MP3", "M4A", "WAV"):
            media_type = "Áudio"
        elif ext in ("MP4", "M4V"):
            media_type = "Vídeo"
        elif ext in ("JPG", "JPEG", "PNG", "WEBP"):
            media_type = "Imagem"
        elif item.key_symbol == "sjj":
            media_type = f"Cântico {item.track}" if item.track else "Cântico"
            ext = "JW.ORG"
        elif item.key_symbol:
            media_type = "Vídeo" if (not item.mime_type or item.mime_type.startswith("video")) else "Áudio"
            ext = f"JWL ({item.key_symbol})"
        else:
            media_type = ext or "Mídia"

        if src_name:
            subtitle_text = f"{media_type} {ext}{dur_str}  [{src_name}]"
        else:
            subtitle_text = f"{media_type} {ext}{dur_str}".strip()

        self.subtitle_label = QLabel(subtitle_text)
        self.subtitle_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        text_layout.addWidget(self.subtitle_label)

        layout.addLayout(text_layout, 1)

        # 4. End Action Combo
        end_box = QHBoxLayout()
        end_box.setSpacing(4)
        end_lbl = QLabel("Ação:")
        end_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        end_box.addWidget(end_lbl)

        self.end_action_combo = QComboBox()
        self.end_action_combo.addItem("⏹️ Parar", 2)
        self.end_action_combo.addItem("▶️ Continuar", 0)
        self.end_action_combo.addItem("⏸️ Pausar", 1)
        self.end_action_combo.addItem("🔁 Repetir", 3)
        self.end_action_combo.setToolTip(
            "Ação a executar no JW Library ao terminar de reproduzir esta mídia."
        )

        idx = self.end_action_combo.findData(item.end_action)
        if idx >= 0:
            self.end_action_combo.setCurrentIndex(idx)
        else:
            self.end_action_combo.setCurrentIndex(0)

        self.end_action_combo.currentIndexChanged.connect(self._on_action_changed)
        end_box.addWidget(self.end_action_combo)
        layout.addLayout(end_box)

        # 5. Buttons: Up, Down, Remove
        btn_box = QHBoxLayout()
        btn_box.setSpacing(2)

        self.btn_up = QPushButton("⬆️")
        self.btn_up.setFixedSize(24, 24)
        self.btn_up.setToolTip("Mover para cima")
        if total_count is not None:
            self.btn_up.setEnabled(index > 0)
        self.btn_up.clicked.connect(self.move_up_requested.emit)
        btn_box.addWidget(self.btn_up)

        self.btn_down = QPushButton("⬇️")
        self.btn_down.setFixedSize(24, 24)
        self.btn_down.setToolTip("Mover para baixo")
        if total_count is not None:
            self.btn_down.setEnabled(index < total_count - 1)
        self.btn_down.clicked.connect(self.move_down_requested.emit)
        btn_box.addWidget(self.btn_down)

        self.btn_remove = QPushButton("✖️")
        self.btn_remove.setFixedSize(24, 24)
        self.btn_remove.setToolTip("Remover da playlist")
        self.btn_remove.clicked.connect(self.remove_requested.emit)
        btn_box.addWidget(self.btn_remove)

        layout.addLayout(btn_box)

    def _find_playlist_list_widget(self) -> PlaylistListWidget | None:
        p = self.parent()
        while p is not None:
            if isinstance(p, PlaylistListWidget):
                return p
            p = p.parent()
        return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if PlaylistListWidget.has_acceptable_files(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        if (
            hasattr(event.mimeData(), "hasFormat")
            and event.mimeData().hasFormat("application/x-meeting-assistant-playlist-row")
        ):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if PlaylistListWidget.has_acceptable_files(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        if (
            hasattr(event.mimeData(), "hasFormat")
            and event.mimeData().hasFormat("application/x-meeting-assistant-playlist-row")
        ):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = PlaylistListWidget.extract_file_paths(event.mimeData())
        list_widget = self._find_playlist_list_widget()
        if paths:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            if list_widget:
                list_widget.files_dropped.emit(paths)
            return
        if (
            hasattr(event.mimeData(), "hasFormat")
            and event.mimeData().hasFormat("application/x-meeting-assistant-playlist-row")
        ):
            if list_widget:
                list_widget.dropEvent(event)
                return
        super().dropEvent(event)

    def _on_text_changed(self, new_text: str) -> None:
        clean = new_text.strip()
        if clean:
            self.item.label = clean
            self.label_changed.emit(clean)

    def _on_action_changed(self) -> None:
        val = self.end_action_combo.currentData()
        if val is not None:
            self.item.end_action = int(val)
            self.end_action_changed.emit(int(val))


class AddSongDialog(QDialog):
    """Dialog to search and add a song from JW.org to the playlist."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Adicionar Cântico do Reino à Playlist")
        self.setFixedSize(380, 180)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setVerticalSpacing(6)

        self.song_number_edit = QLineEdit()
        self.song_number_edit.setPlaceholderText("Ex: 14, 88, 151 ou 154")
        form.addRow("Número do Cântico (1 a 999):", self.song_number_edit)

        self.format_combo = QComboBox()
        self.format_combo.addItem("MP4 Vídeo com Letra (720p HD)", "mp4")
        self.format_combo.addItem("MP3 Áudio Vocal", "mp3")
        form.addRow("Formato de Mídia:", self.format_combo)
        layout.addLayout(form)

        hint = QLabel(
            "💡 O cântico será baixado do JW.org e inserido na playlist com miniatura e título oficial."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(hint)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        add_btn = QPushButton("➕ Adicionar à Playlist")
        add_btn.setDefault(True)
        add_btn.clicked.connect(self._on_accept)
        btn_box.addWidget(add_btn)
        layout.addLayout(btn_box)

    def _on_accept(self) -> None:
        nums = [int(n) for n in re.findall(r"\d+", self.song_number_edit.text())]
        if not nums or nums[0] < 1 or nums[0] > 999:
            QMessageBox.warning(self, "Número Inválido", "Digite um número de cântico válido entre 1 e 999.")
            return
        self.accept()

    def get_data(self) -> tuple[int, str]:
        nums = [int(n) for n in re.findall(r"\d+", self.song_number_edit.text())]
        num = nums[0] if nums else 1
        fmt = self.format_combo.currentData() or "mp4"
        return num, fmt


class CategoryFetchWorker(QThread):
    finished_items = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, service: MeetingMediaService, category_key: str) -> None:
        super().__init__(None)  # Worker without parent per AGENTS.md rules
        self.service = service
        self.category_key = category_key

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                return
            items = self.service.get_category_videos(self.category_key)
            if not self.isInterruptionRequested():
                self.finished_items.emit(items)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.error_occurred.emit(str(exc))


class AddVideoDialog(QDialog):
    """Dialog to search and add a video to the playlist.

    Provides friendly browsing/search by category and title from JW.org
    as well as an advanced pub/track tab.
    """

    def __init__(self, parent=None, service: MeetingMediaService | None = None) -> None:
        super().__init__(parent)
        self.service = service or MeetingMediaService()
        self._selected_item: MediaDownloadItem | None = None
        self._category_items: list[MediaDownloadItem] = []
        self._worker: CategoryFetchWorker | None = None

        self.setWindowTitle("Adicionar Vídeo do JW.org à Playlist")
        self.setMinimumSize(540, 420)
        self.resize(580, 460)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        self.tabs = QTabWidget()

        # --- Tab 1: Friendly Catalog ---
        catalog_tab = QWidget()
        cat_layout = QVBoxLayout(catalog_tab)
        cat_layout.setContentsMargins(8, 8, 8, 8)
        cat_layout.setSpacing(6)

        cat_form = QFormLayout()
        cat_form.setVerticalSpacing(6)

        self.category_combo = QComboBox()
        for cat_key, cat_name in POPULAR_VIDEO_CATEGORIES:
            self.category_combo.addItem(cat_name, cat_key)
        self.category_combo.currentIndexChanged.connect(self._on_category_changed)
        cat_form.addRow("Categoria JW.org:", self.category_combo)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Filtrar vídeos por título em tempo real…")
        self.search_edit.textChanged.connect(self._filter_items)
        cat_form.addRow("Filtrar Título:", self.search_edit)

        cat_layout.addLayout(cat_form)

        self.video_list = QListWidget()
        self.video_list.setStyleSheet(
            "QListWidget { background-color: #161b22; border: 1px solid #30363d; border-radius: 6px; }"
            "QListWidget::item { padding: 4px; border-bottom: 1px solid #21262d; }"
            "QListWidget::item:selected { background-color: #1f242c; color: #58a6ff; }"
        )
        self.video_list.itemDoubleClicked.connect(lambda _it: self._on_accept())
        cat_layout.addWidget(self.video_list, 1)

        self.catalog_status = QLabel("Selecione uma categoria para listar os vídeos.")
        self.catalog_status.setStyleSheet("color: #8b949e; font-size: 11px;")
        cat_layout.addWidget(self.catalog_status)

        self.tabs.addTab(catalog_tab, "🎬 Catálogo JW.org (por Categoria e Título)")

        # --- Tab 2: Advanced (pub / track) ---
        adv_tab = QWidget()
        adv_layout = QVBoxLayout(adv_tab)
        adv_layout.setContentsMargins(8, 8, 8, 8)
        adv_layout.setSpacing(6)

        form = QFormLayout()
        form.setVerticalSpacing(6)

        self.pub_edit = QLineEdit("mwbv")
        self.pub_edit.setPlaceholderText("Ex: mwbv, jwb, pub-xxx")
        form.addRow("Código da Publicação:", self.pub_edit)

        self.track_edit = QLineEdit("1")
        self.track_edit.setPlaceholderText("Ex: 1, 2, 3")
        form.addRow("Faixa (Track):", self.track_edit)

        self.issue_edit = QLineEdit()
        self.issue_edit.setPlaceholderText("Ex: 202611 (opcional)")
        form.addRow("Edição / Issue:", self.issue_edit)
        adv_layout.addLayout(form)

        hint = QLabel("💡 Busca e baixa o vídeo oficial do JW.org diretamente por código e faixa.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b949e; font-size: 11px;")
        adv_layout.addWidget(hint)
        adv_layout.addStretch()

        self.tabs.addTab(adv_tab, "⚙️ Avançado (Código / Faixa)")
        main_layout.addWidget(self.tabs, 1)

        # Dialog buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        self.add_btn = QPushButton("➕ Adicionar à Playlist")
        self.add_btn.setDefault(True)
        self.add_btn.clicked.connect(self._on_accept)
        btn_box.addWidget(self.add_btn)
        main_layout.addLayout(btn_box)

        # Load first category
        self._on_category_changed()

    def _on_category_changed(self) -> None:
        cat_key = self.category_combo.currentData()
        if not cat_key:
            return
        self.video_list.clear()
        self.catalog_status.setText("Carregando vídeos do JW.org…")
        self._clean_worker()
        self._worker = CategoryFetchWorker(self.service, cat_key)
        self._worker.finished_items.connect(self._on_items_loaded)
        self._worker.error_occurred.connect(self._on_fetch_error)
        self._worker.start()

    def _on_items_loaded(self, items: list[MediaDownloadItem]) -> None:
        self._category_items = items
        self._filter_items()
        self._clean_worker()

    def _on_fetch_error(self, err: str) -> None:
        self.catalog_status.setText(f"Falha ao carregar categoria: {err}")
        self._clean_worker()

    def _filter_items(self) -> None:
        term = self.search_edit.text().strip().lower()
        self.video_list.clear()
        matching = [
            it for it in self._category_items
            if not term or term in it.title.lower()
        ]
        for it in matching:
            dur = format_duration(it.duration_seconds)
            item_widget = QListWidgetItem(f"▶  {it.title}  ({dur})")
            item_widget.setData(Qt.ItemDataRole.UserRole, it)
            self.video_list.addItem(item_widget)

        self.catalog_status.setText(
            f"{len(matching)} vídeo(s) disponível(is)."
            if matching
            else ("Nenhum vídeo correspondente." if term else "Nenhum vídeo nesta categoria.")
        )

    def _on_accept(self) -> None:
        if self.tabs.currentIndex() == 0:
            cur_item = self.video_list.currentItem()
            if not cur_item:
                QMessageBox.warning(
                    self, "Seleção Necessária", "Selecione um vídeo da lista acima para adicionar."
                )
                return
            self._selected_item = cur_item.data(Qt.ItemDataRole.UserRole)
            self.accept()
        else:
            pub = self.pub_edit.text().strip()
            if not pub:
                QMessageBox.warning(self, "Publicação", "Informe o código da publicação (ex: mwbv, jwb).")
                return
            self._selected_item = None
            self.accept()

    def get_selected_item(self) -> MediaDownloadItem | None:
        return self._selected_item

    def get_advanced_data(self) -> tuple[str, int, int]:
        pub = self.pub_edit.text().strip() or "mwbv"
        track_nums = [int(n) for n in re.findall(r"\d+", self.track_edit.text())]
        track = track_nums[0] if track_nums else 1
        issue_nums = [int(n) for n in re.findall(r"\d+", self.issue_edit.text())]
        issue = issue_nums[0] if issue_nums else 0
        return pub, track, issue

    def get_data(self) -> tuple[str, int, int]:
        if self._selected_item is not None:
            return (
                self._selected_item.pub_symbol or "video",
                self._selected_item.track_num or 1,
                self._selected_item.issue_tag or 0,
            )
        return self.get_advanced_data()

    def _clean_worker(self) -> None:
        if self._worker is not None:
            try:
                self._worker.finished_items.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                self._worker.error_occurred.disconnect()
            except (RuntimeError, TypeError):
                pass
            if self._worker.isRunning():
                self._worker.requestInterruption()
                self._worker.quit()
                self._worker.wait(500)
            self._worker = None

    def closeEvent(self, event) -> None:
        self._clean_worker()
        super().closeEvent(event)

    def close(self) -> bool:
        self._clean_worker()
        return super().close()

    def reject(self) -> None:
        self._clean_worker()
        super().reject()


class LoadMeetingDialog(QDialog):
    """Dialog to preload all media from a midweek or weekend meeting into the custom playlist."""

    def __init__(
        self,
        parent=None,
        meeting_date: datetime.date | None = None,
        initial_issue: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.meeting_date = meeting_date
        self.setWindowTitle("Carregar Mídias de Reunião Completa na Playlist")
        self.setFixedSize(440, 325)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setVerticalSpacing(6)

        self.meeting_type_combo = QComboBox()
        self.meeting_type_combo.addItem("Meio de Semana (Apostila Nossa Vida e Ministério)", "midweek")
        self.meeting_type_combo.addItem("Final de Semana (Estudo de A Sentinela)", "weekend")
        self.meeting_type_combo.currentIndexChanged.connect(self._on_meeting_type_changed)
        form.addRow("Tipo de Reunião:", self.meeting_type_combo)

        self.playlist_name_edit = QLineEdit("Reunião de Meio de Semana")
        self.playlist_name_edit.setPlaceholderText("Ex: Reunião de Meio de Semana, Estudo de A Sentinela")
        form.addRow("Nome da Playlist:", self.playlist_name_edit)

        self.issue_edit = QLineEdit()
        if initial_issue:
            self.issue_edit.setText(initial_issue)
        self.issue_edit.setPlaceholderText("Ex: 202611 (ou em branco para detecção automática)")
        form.addRow("Edição / Mês:", self.issue_edit)
        layout.addLayout(form)

        # Checkboxes group
        opts_group = QGroupBox("Conteúdo a Carregar")
        opts_grid = QGridLayout(opts_group)
        opts_grid.setContentsMargins(6, 6, 6, 6)

        self.chk_songs = QCheckBox("Cânticos da Reunião")
        self.chk_songs.setChecked(True)
        opts_grid.addWidget(self.chk_songs, 0, 0)

        self.chk_videos = QCheckBox("Vídeos da Reunião")
        self.chk_videos.setChecked(True)
        opts_grid.addWidget(self.chk_videos, 0, 1)

        self.chk_images = QCheckBox("Gravuras e Imagens")
        self.chk_images.setChecked(True)
        opts_grid.addWidget(self.chk_images, 1, 0)

        self.chk_extra = QCheckBox("Estudo Bíblico (EBC)")
        self.chk_extra.setChecked(True)
        opts_grid.addWidget(self.chk_extra, 1, 1)

        layout.addWidget(opts_group)

        # Mode
        mode_box = QHBoxLayout()
        self.chk_replace = QCheckBox("Limpar lista atual antes de carregar")
        self.chk_replace.setChecked(True)
        mode_box.addWidget(self.chk_replace)
        layout.addLayout(mode_box)

        hint = QLabel(
            "💡 Carrega todas as mídias para você reordenar, ajustar ações ao final "
            "e personalizar antes de importar."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(hint)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        add_btn = QPushButton("📥 Carregar Mídias")
        add_btn.setDefault(True)
        add_btn.clicked.connect(self.accept)
        btn_box.addWidget(add_btn)
        layout.addLayout(btn_box)

    def _on_meeting_type_changed(self) -> None:
        mtype = self.meeting_type_combo.currentData()
        if mtype == "midweek":
            self.chk_extra.setText("Estudo Bíblico (EBC)")
            if self.playlist_name_edit.text().strip() in ("Estudo de A Sentinela", ""):
                self.playlist_name_edit.setText("Reunião de Meio de Semana")
        else:
            self.chk_extra.setText("Áudio de A Sentinela")
            if self.playlist_name_edit.text().strip() in ("Reunião de Meio de Semana", ""):
                self.playlist_name_edit.setText("Estudo de A Sentinela")

    def get_data(self) -> dict:
        mtype = self.meeting_type_combo.currentData() or "midweek"
        default_name = "Reunião de Meio de Semana" if mtype == "midweek" else "Estudo de A Sentinela"
        return {
            "meeting_type": mtype,
            "playlist_name": self.playlist_name_edit.text().strip() or default_name,
            "issue": self.issue_edit.text().strip() or None,
            "include_songs": self.chk_songs.isChecked(),
            "include_videos": self.chk_videos.isChecked(),
            "include_images": self.chk_images.isChecked(),
            "include_cbs_videos": self.chk_extra.isChecked(),
            "include_audio": self.chk_extra.isChecked(),
            "replace_existing": self.chk_replace.isChecked(),
            "meeting_date": self.meeting_date,
        }


class EditPlaylistDialog(QDialog):
    """Dialog to choose an existing playlist from JW Library or open a .jwlplaylist file to edit."""

    def __init__(self, service: MeetingMediaService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self._selected_playlist_name: str = ""
        self._selected_items: list[MediaImportItem] = []
        self._all_playlists: list[dict] = []

        self.setWindowTitle("Editar Playlist Existente")
        self.resize(540, 440)
        self.setMinimumSize(440, 340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header_lbl = QLabel(
            "Selecione uma playlist cadastrada no JW Library para carregar seus itens e editar,\n"
            "ou abra um arquivo .jwlplaylist salvo no computador:"
        )
        header_lbl.setWordWrap(True)
        header_lbl.setStyleSheet("color: #c9d1d9; font-size: 12px;")
        layout.addWidget(header_lbl)

        search_row = QHBoxLayout()
        search_lbl = QLabel("Filtrar:")
        search_lbl.setStyleSheet("color: #8b949e;")
        search_row.addWidget(search_lbl)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Digite para filtrar playlists...")
        self.search_edit.textChanged.connect(self._filter_playlists)
        search_row.addWidget(self.search_edit, 1)

        refresh_btn = QPushButton("🔄 Atualizar")
        refresh_btn.setToolTip("Recarregar playlists do banco de dados do JW Library")
        refresh_btn.clicked.connect(self._load_playlists)
        search_row.addWidget(refresh_btn)
        layout.addLayout(search_row)

        self.playlist_list = QListWidget()
        self.playlist_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.playlist_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.playlist_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.playlist_list, 1)

        self.preview_label = QLabel("Nenhuma playlist selecionada.")
        self.preview_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)

        open_file_btn = QPushButton("📂 Abrir Arquivo .jwlplaylist do Computador…")
        open_file_btn.setToolTip("Carregar itens diretamente de um arquivo .jwlplaylist salvo")
        open_file_btn.clicked.connect(self._on_open_file_clicked)
        layout.addWidget(open_file_btn)

        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)
        self.load_btn = QPushButton("✏️ Carregar Playlist para Edição")
        self.load_btn.setStyleSheet(
            "QPushButton { background-color: #238636; color: white; "
            "font-weight: bold; padding: 6px 12px; border-radius: 4px; }\n"
            "QPushButton:hover { background-color: #2ea043; }\n"
            "QPushButton:disabled { background-color: #21262d; color: #8b949e; }"
        )
        self.load_btn.setEnabled(False)
        self.load_btn.clicked.connect(self._on_accept)
        btn_box.addWidget(self.load_btn, 1)

        self.delete_btn = QPushButton("🗑️ Excluir Playlist…")
        self.delete_btn.setStyleSheet("QPushButton { color: #f85149; }")
        self.delete_btn.setEnabled(False)
        self.delete_btn.setToolTip("Excluir permanentemente a playlist selecionada do JW Library")
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        btn_box.addWidget(self.delete_btn)

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)
        layout.addLayout(btn_box)

        self._load_playlists()

    def _load_playlists(self) -> None:
        try:
            self._all_playlists = self.service.list_existing_playlists()
        except Exception as exc:
            self._all_playlists = []
            self.preview_label.setText(f"Erro ao listar playlists: {exc}")
        self._filter_playlists()

    def _filter_playlists(self) -> None:
        term = self.search_edit.text().strip().lower()
        self.playlist_list.clear()
        for p in self._all_playlists:
            name = p.get("name", "")
            count = p.get("item_count", 0)
            if not term or term in name.lower():
                item = QListWidgetItem(f"🎬 {name}  ({count} itens)")
                item.setData(Qt.ItemDataRole.UserRole, p)
                self.playlist_list.addItem(item)
        if self.playlist_list.count() > 0:
            self.playlist_list.setCurrentRow(0)
        else:
            self.load_btn.setEnabled(False)
            if hasattr(self, "delete_btn"):
                self.delete_btn.setEnabled(False)
            self.preview_label.setText("Nenhuma playlist encontrada no JW Library.")

    def _on_selection_changed(self) -> None:
        item = self.playlist_list.currentItem()
        if not item:
            self.load_btn.setEnabled(False)
            if hasattr(self, "delete_btn"):
                self.delete_btn.setEnabled(False)
            self.preview_label.setText("Nenhuma playlist selecionada.")
            return
        p_data = item.data(Qt.ItemDataRole.UserRole)
        name = p_data.get("name", "")
        count = p_data.get("item_count", 0)
        self.load_btn.setEnabled(True)
        if hasattr(self, "delete_btn"):
            self.delete_btn.setEnabled(True)
        self.preview_label.setText(
            f"Playlist selecionada: '{name}' com {count} item(ns). Clique para carregar."
        )

    def _on_delete_clicked(self) -> None:
        item = self.playlist_list.currentItem()
        if not item:
            return
        p_data = item.data(Qt.ItemDataRole.UserRole)
        name = p_data.get("name", "")
        if not name:
            return

        confirm = QMessageBox.question(
            self,
            "Excluir Playlist",
            f"Deseja realmente excluir a playlist '{name}' do JW Library permanentemente?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            success = self.service.delete_playlist(name)
            if success:
                QMessageBox.information(
                    self,
                    "Playlist Excluída",
                    f"A playlist '{name}' foi excluída com sucesso do JW Library.",
                )
                self._load_playlists()
            else:
                QMessageBox.warning(
                    self,
                    "Erro ao Excluir",
                    f"Não foi possível excluir a playlist '{name}'. "
                    "Verifique se o JW Library não está bloqueando o arquivo.",
                )

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self._on_accept()

    def _on_open_file_clicked(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Arquivo .jwlplaylist",
            "",
            "JW Library Playlist (*.jwlplaylist);;Todos (*.*)",
        )
        if file_path:
            try:
                name, items = self.service.load_playlist_from_file(Path(file_path))
                self._selected_playlist_name = name
                self._selected_items = items
                self.accept()
            except Exception as exc:
                QMessageBox.warning(self, "Erro ao Abrir", f"Falha ao carregar playlist do arquivo:\n{exc}")

    def _on_accept(self) -> None:
        item = self.playlist_list.currentItem()
        if not item:
            return
        p_data = item.data(Qt.ItemDataRole.UserRole)
        tag_id = p_data.get("tag_id")
        name = p_data.get("name", "")
        try:
            p_name, items = self.service.load_playlist_from_db(tag_id=tag_id, playlist_name=name)
            self._selected_playlist_name = p_name
            self._selected_items = items
            self.accept()
        except Exception as exc:
            QMessageBox.warning(
                self, "Erro ao Carregar", f"Falha ao carregar playlist do banco de dados:\n{exc}"
            )

    def get_selected_playlist(self) -> tuple[str, list[MediaImportItem]]:
        return self._selected_playlist_name, self._selected_items


class MediaTaskWorker(QThread):
    progress = Signal(int)
    status_message = Signal(str)
    task_finished = Signal(bool, str)
    items_ready = Signal(list)

    def __init__(
        self,
        service: MeetingMediaService,
        task_type: str,
        params: dict,
        cancel_token: CancelToken,
    ) -> None:
        super().__init__(None)  # DO NOT pass parent=self to prevent qFatal crashes on dialog close
        self.service = service
        self.task_type = task_type
        self.params = params
        self.cancel_token = cancel_token

    def run(self) -> None:
        try:
            if self.task_type == "download_songs":
                song_numbers = self.params.get("song_numbers", [])
                playlist_name = self.params.get("playlist_name", "Cânticos da Reunião")
                format_type = self.params.get("format_type", "mp4")

                result = self.service.download_songs_and_import(
                    song_numbers=song_numbers,
                    playlist_name=playlist_name,
                    format_type=format_type,
                    progress_cb=self.progress.emit,
                    status_cb=self.status_message.emit,
                    cancel_token=self.cancel_token,
                )
                if result.success:
                    if result.imported_count > 0 and getattr(result, "synchronized_count", 0) > 0:
                        msg = (
                            f"Sucesso: {result.imported_count} novo(s) e "
                            f"{result.synchronized_count} sincronizado(s) "
                            f"na playlist '{result.playlist_name}' do JW Library!"
                        )
                    elif result.imported_count > 0:
                        msg = (
                            f"Sucesso: {result.imported_count} cântico(s) importados "
                            f"na playlist '{result.playlist_name}' do JW Library!"
                        )
                    elif getattr(result, "synchronized_count", 0) > 0:
                        msg = (
                            f"Sucesso: {result.synchronized_count} cântico(s) sincronizados e verificados "
                            f"na playlist '{result.playlist_name}' do JW Library!"
                        )
                    else:
                        msg = (
                            f"Cânticos da playlist '{result.playlist_name}' "
                            "verificados com sucesso no JW Library!"
                        )
                    self.task_finished.emit(True, msg)
                else:
                    self.task_finished.emit(False, result.error_message)

            elif self.task_type == "download_midweek":
                playlist_name = self.params.get("playlist_name", "Reunião de Meio de Semana")
                issue = self.params.get("issue")
                include_images = self.params.get("include_images", True)
                include_videos = self.params.get("include_videos", True)
                include_songs = self.params.get("include_songs", True)
                include_cbs_videos = self.params.get("include_cbs_videos", True)
                meeting_date = self.params.get("meeting_date")
                cleanup_cache = self.params.get("cleanup_cache_after_import")
                result = self.service.download_midweek_and_import(
                    playlist_name=playlist_name,
                    issue=issue,
                    include_images=include_images,
                    include_videos=include_videos,
                    include_songs=include_songs,
                    include_cbs_videos=include_cbs_videos,
                    meeting_date=meeting_date,
                    progress_cb=self.progress.emit,
                    status_cb=self.status_message.emit,
                    cancel_token=self.cancel_token,
                    cleanup_cache_after_import=cleanup_cache,
                )
                if result.success:
                    if result.imported_count > 0 and getattr(result, "synchronized_count", 0) > 0:
                        msg = (
                            f"Sucesso: {result.imported_count} novo(s) e "
                            f"{result.synchronized_count} sincronizado(s) "
                            f"na playlist '{result.playlist_name}' do JW Library!"
                        )
                    elif result.imported_count > 0:
                        msg = (
                            f"Sucesso: {result.imported_count} item(ns) importados "
                            f"na playlist '{result.playlist_name}' do JW Library!"
                        )
                    elif getattr(result, "synchronized_count", 0) > 0:
                        msg = (
                            f"Sucesso: {result.synchronized_count} item(ns) sincronizados e verificados "
                            f"na playlist '{result.playlist_name}' do JW Library!"
                        )
                    else:
                        msg = (
                            f"Mídias da playlist '{result.playlist_name}' "
                            "verificadas com sucesso no JW Library!"
                        )
                    self.task_finished.emit(True, msg)
                else:
                    self.task_finished.emit(False, result.error_message)

            elif self.task_type == "download_weekend":
                playlist_name = self.params.get("playlist_name", "Estudo de A Sentinela")
                issue = self.params.get("issue")
                include_images = self.params.get("include_images", True)
                include_audio = self.params.get("include_audio", False)
                include_videos = self.params.get("include_videos", True)
                include_songs = self.params.get("include_songs", True)
                meeting_date = self.params.get("meeting_date")
                cleanup_cache = self.params.get("cleanup_cache_after_import")
                result = self.service.download_weekend_and_import(
                    issue=issue,
                    playlist_name=playlist_name,
                    include_images=include_images,
                    include_audio=include_audio,
                    include_videos=include_videos,
                    include_songs=include_songs,
                    meeting_date=meeting_date,
                    progress_cb=self.progress.emit,
                    status_cb=self.status_message.emit,
                    cancel_token=self.cancel_token,
                    cleanup_cache_after_import=cleanup_cache,
                )
                if result.success:
                    if result.imported_count > 0 and getattr(result, "synchronized_count", 0) > 0:
                        msg = (
                            f"Sucesso: {result.imported_count} novo(s) e "
                            f"{result.synchronized_count} sincronizado(s) "
                            f"na playlist '{result.playlist_name}' do JW Library!"
                        )
                    elif result.imported_count > 0:
                        msg = (
                            f"Sucesso: {result.imported_count} item(ns) importados "
                            f"na playlist '{result.playlist_name}' do JW Library!"
                        )
                    elif getattr(result, "synchronized_count", 0) > 0:
                        msg = (
                            f"Sucesso: {result.synchronized_count} item(ns) sincronizados e verificados "
                            f"na playlist '{result.playlist_name}' do JW Library!"
                        )
                    else:
                        msg = (
                            f"Mídias da playlist '{result.playlist_name}' "
                            "verificadas com sucesso no JW Library!"
                        )
                    self.task_finished.emit(True, msg)
                else:
                    self.task_finished.emit(False, result.error_message)

            elif self.task_type == "import_local":
                files = self.params.get("files", [])
                playlist_name = self.params.get("playlist_name", "Discurso Público")
                result = self.service.import_local_files(
                    files, playlist_name=playlist_name, launch_jwl=False
                )
                if result.success:
                    msg = (
                        "Playlist importada no JW Library! "
                        "Se o JW Library já estiver aberto, alterne de aba "
                        "(ex: vá em Bíblia e volte em Mídias) para atualizar a exibição."
                    )
                    if getattr(result, "package_path", None):
                        msg += f"\n\n📦 Pacote oficial gerado: {result.package_path.name}"
                    self.task_finished.emit(True, msg)
                else:
                    self.task_finished.emit(False, result.error_message)

            elif self.task_type == "import_playlist":
                items = self.params.get("items", [])
                playlist_name = self.params.get("playlist_name", "Playlist Personalizada")
                clear_existing = self.params.get("clear_existing", True)
                result = self.service.import_playlist_items(
                    items,
                    playlist_name=playlist_name,
                    clear_existing=clear_existing,
                    launch_jwl=False,
                )
                if result.success:
                    msg = (
                        "Playlist importada no JW Library! "
                        "Se o JW Library já estiver aberto, alterne de aba "
                        "(ex: vá em Bíblia e volte em Mídias) para atualizar a exibição."
                    )
                    if getattr(result, "package_path", None):
                        msg += f"\n\n📦 Pacote oficial gerado: {result.package_path.name}"
                    self.task_finished.emit(True, msg)
                else:
                    self.task_finished.emit(False, result.error_message)

            elif self.task_type == "load_meeting_for_playlist":
                meeting_type = self.params.get("meeting_type", "midweek")
                issue = self.params.get("issue")
                meeting_date = self.params.get("meeting_date")
                if meeting_type == "midweek":
                    loaded_items = self.service.download_midweek_items(
                        issue=issue,
                        include_images=self.params.get("include_images", True),
                        include_videos=self.params.get("include_videos", True),
                        include_songs=self.params.get("include_songs", True),
                        include_cbs_videos=self.params.get("include_cbs_videos", True),
                        meeting_date=meeting_date,
                        progress_cb=self.progress.emit,
                        status_cb=self.status_message.emit,
                        cancel_token=self.cancel_token,
                    )
                else:
                    loaded_items = self.service.download_weekend_items(
                        issue=issue,
                        include_images=self.params.get("include_images", True),
                        include_audio=self.params.get("include_audio", False),
                        include_videos=self.params.get("include_videos", True),
                        include_songs=self.params.get("include_songs", True),
                        meeting_date=meeting_date,
                        progress_cb=self.progress.emit,
                        status_cb=self.status_message.emit,
                        cancel_token=self.cancel_token,
                    )
                self.items_ready.emit(loaded_items)
                if loaded_items:
                    self.task_finished.emit(
                        True,
                        f"{len(loaded_items)} mídias carregadas com sucesso para a playlist!",
                    )
                else:
                    if self.cancel_token.is_cancelled:
                        self.task_finished.emit(False, "Operação cancelada pelo operador.")
                    else:
                        self.task_finished.emit(False, "Nenhuma mídia pôde ser obtida da reunião.")

            elif self.task_type == "load_song_for_playlist":
                song_number = self.params.get("song_number")
                format_type = self.params.get("format_type", "mp4")
                song_items = self.service.download_songs_items(
                    song_numbers=[song_number],
                    format_type=format_type,
                    progress_cb=self.progress.emit,
                    status_cb=self.status_message.emit,
                    cancel_token=self.cancel_token,
                )
                self.items_ready.emit(song_items)
                if song_items:
                    self.task_finished.emit(True, f"Cântico {song_number} adicionado à playlist!")
                else:
                    if self.cancel_token.is_cancelled:
                        self.task_finished.emit(False, "Operação cancelada pelo operador.")
                    else:
                        self.task_finished.emit(False, f"Não foi possível obter o cântico {song_number}.")

            elif self.task_type == "load_video_for_playlist":
                pub = self.params.get("pub", "")
                track = self.params.get("track", 0)
                issue = self.params.get("issue", 0)
                docid = self.params.get("docid", 0)
                video_item = self.service.download_media_item_by_pub_track(
                    pub=pub,
                    track=track,
                    issue_tag=issue,
                    docid=docid,
                    progress_cb=self.progress.emit,
                    status_cb=self.status_message.emit,
                    cancel_token=self.cancel_token,
                )
                if video_item:
                    self.items_ready.emit([video_item])
                    self.task_finished.emit(True, f"Vídeo '{video_item.label}' adicionado à playlist!")
                else:
                    if self.cancel_token.is_cancelled:
                        self.task_finished.emit(False, "Operação cancelada pelo operador.")
                    else:
                        self.task_finished.emit(False, "Vídeo não localizado no JW.org.")

            elif self.task_type == "download_media_item":
                item = self.params.get("item")
                imported = self.service.download_media_item(
                    item,
                    progress_cb=self.progress.emit,
                    status_cb=self.status_message.emit,
                    cancel_token=self.cancel_token,
                )
                if imported:
                    self.items_ready.emit([imported])
                    self.task_finished.emit(True, f"Vídeo '{imported.label}' adicionado à playlist!")
                else:
                    if self.cancel_token.is_cancelled:
                        self.task_finished.emit(False, "Operação cancelada pelo operador.")
                    else:
                        self.task_finished.emit(False, "Falha ao baixar o vídeo selecionado.")

            elif self.task_type == "sync_watch_folder":
                playlist_name = self.params.get("playlist_name", "Mídias do Salão")
                result = self.service.sync_watch_folder(playlist_name=playlist_name)
                if result.success:
                    if result.imported_count > 0:
                        msg = (
                            f"Sucesso: {result.imported_count} arquivo(s) sincronizados "
                            f"na playlist '{result.playlist_name}'!"
                        )
                    elif getattr(result, "synchronized_count", 0) > 0:
                        msg = (
                            f"Sucesso: {result.synchronized_count} arquivo(s) verificados "
                            f"na playlist '{result.playlist_name}'!"
                        )
                    else:
                        msg = (
                            "Pasta monitorada sincronizada com sucesso "
                            f"na playlist '{result.playlist_name}'!"
                        )
                    self.task_finished.emit(True, msg)
                else:
                    self.task_finished.emit(False, result.error_message)

            elif self.task_type == "create_backup":
                backup_path = self.service.create_manual_backup()
                self.task_finished.emit(True, f"Backup criado com sucesso: {backup_path.name}")

            elif self.task_type == "restore_backup":
                backup_file = self.params.get("backup_file")
                self.service.restore_backup(backup_file)
                msg = f"Backup restaurado com sucesso a partir de {backup_file.name}!"
                self.task_finished.emit(True, msg)

            elif self.task_type == "check_and_install_jwpub":
                auto_install = self.params.get("auto_install", True)
                result = self.service.check_and_install_new_publications(
                    auto_install=auto_install,
                    progress_cb=self.progress.emit,
                    status_cb=self.status_message.emit,
                    cancel_token=self.cancel_token,
                )
                if result.success:
                    if result.newly_installed:
                        titles = ", ".join(it.title for it in result.newly_installed)
                        msg = (
                            f"Sucesso: {len(result.newly_installed)} nova(s) publicação(ões) "
                            f"instaladas no JW Library: {titles}!"
                        )
                    else:
                        msg = (
                            "O JW Library já possui todas as apostilas e "
                            "publicações mais recentes instaladas!"
                        )
                    self.task_finished.emit(True, msg)
                else:
                    self.task_finished.emit(
                        False, result.error_message or "Falha ao verificar publicações no JW.org."
                    )

            elif self.task_type == "cleanup_storage":
                keep_weeks = self.params.get("keep_weeks", 2)
                clean_app = self.params.get("clean_app_cache", True)
                clean_jwl = self.params.get("clean_jwl_storage", True)
                result = self.service.cleanup_storage(
                    keep_weeks=keep_weeks,
                    clean_app_cache=clean_app,
                    clean_jwl_storage=clean_jwl,
                )
                mb_freed = result.total_bytes_freed / (1024 * 1024)
                total_files = len(result.app_files_deleted) + len(result.jwl_files_deleted)
                msg = (
                    f"Limpeza de armazenamento concluída: {total_files} arquivo(s) removidos, "
                    f"liberando {mb_freed:.1f} MB de espaço!"
                )
                self.task_finished.emit(True, msg)

            else:
                self.task_finished.emit(False, f"Tipo de tarefa desconhecido: {self.task_type}")

        except Exception as exc:
            self.task_finished.emit(False, f"Erro inesperado durante a operação: {exc}")


class _DropForwardingScrollArea(QScrollArea):
    """QScrollArea that forwards file drag & drop events to its content widget or parent."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.viewport().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if watched == self.viewport():
            from PySide6.QtCore import QEvent

            if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                child = self.viewport().childAt(pos)
                w = child
                while w and w != self.viewport():
                    if w.acceptDrops() and (
                        isinstance(w, (PlaylistListWidget, PlaylistItemRowWidget, PlaylistDropContainer))
                        or w.inherits("QAbstractItemView")
                    ):
                        return False
                    w = w.parent()

                if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                    if PlaylistListWidget.has_acceptable_files(event.mimeData()):
                        event.setDropAction(Qt.DropAction.CopyAction)
                        event.accept()
                    return False
                elif event.type() == QEvent.Type.Drop:
                    paths = PlaylistListWidget.extract_file_paths(event.mimeData())
                    if paths:
                        event.setDropAction(Qt.DropAction.CopyAction)
                        event.accept()
                        top = self.window()
                        if hasattr(top, "_on_files_dropped"):
                            if hasattr(top, "tabs") and top.tabs.currentIndex() != 1:
                                top.tabs.setCurrentIndex(1)
                            top._on_files_dropped(paths)
                        elif isinstance(self.widget(), PlaylistDropContainer):
                            self.widget().files_dropped.emit(paths)
                        return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if PlaylistListWidget.has_acceptable_files(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if PlaylistListWidget.has_acceptable_files(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = PlaylistListWidget.extract_file_paths(event.mimeData())
        if paths:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            top = self.window()
            if hasattr(top, "_on_files_dropped"):
                if hasattr(top, "tabs") and top.tabs.currentIndex() != 1:
                    top.tabs.setCurrentIndex(1)
                top._on_files_dropped(paths)
            elif isinstance(self.widget(), PlaylistDropContainer):
                self.widget().files_dropped.emit(paths)
            return
        super().dropEvent(event)


class MeetingMediaDialog(QDialog):
    """Gerenciador e sincronizador de mídias de reuniões para o JW Library."""

    def _make_scrollable(self, content_widget: QWidget) -> QScrollArea:
        scroll = _DropForwardingScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollBar:vertical { width: 8px; background: transparent; }"
            "QScrollBar::handle:vertical { background: #444c56; border-radius: 4px; min-height: 20px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        )
        scroll.setWidget(content_widget)
        return scroll

    def __init__(
        self,
        parent=None,
        settings: AppSettings | None = None,
        embedded: bool = False,
    ) -> None:
        super().__init__(parent)
        self.settings = settings or AppSettings()
        self.service = MeetingMediaService(self.settings)
        self.embedded = embedded
        self.setAcceptDrops(True)

        self.setWindowTitle("Gerenciador de Mídias e Importação no JW Library")
        if not embedded:
            self.setMinimumSize(600, 450)
            self.resize(780, 580)
            self._screen_fit = ScreenFitController(self)
        else:
            self._screen_fit = None

        self._worker: MediaTaskWorker | None = None
        self._cancel_token = CancelToken()
        self._playlist_items: list[MediaImportItem] = []
        self._local_files: list[Path] = []
        self._available_weeks: list[MeetingWeekInfo] = []
        self.selected_meeting_date: datetime.date = datetime.date.today()

        layout = QVBoxLayout(self)
        if embedded:
            layout.setContentsMargins(0, 0, 0, 0)
        else:
            layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._make_scrollable(self._build_download_tab()), "📥 Download JW.org")
        self.tabs.addTab(
            self._build_local_files_tab(),
            "🎬 Playlist Personalizada & Discurso Público",
        )
        self.tabs.addTab(self._make_scrollable(self._build_watch_folder_tab()), "👀 Pasta Monitorada")
        self.tabs.addTab(self._make_scrollable(self._build_backup_tab()), "🛡️ Banco de Dados & Backups")
        self.tabs.tabBar().installEventFilter(self)
        layout.addWidget(self.tabs, 1)

        # Common progress and status bar (compact)
        status_frame = QFrame()
        status_frame.setObjectName("statusFrame")
        status_frame.setStyleSheet(
            "#statusFrame { background: #161b22; border-top: 1px solid #30363d; "
            "border-radius: 4px; padding: 2px 6px; }"
        )
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(6, 2, 6, 2)
        status_layout.setSpacing(8)

        self.status_label = QLabel("Pronto para gerenciar mídias.")
        self.status_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        status_layout.addWidget(self.status_label, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setFixedWidth(120)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        status_layout.addWidget(self.progress_bar)

        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.setFixedHeight(22)
        self.cancel_button.setStyleSheet("font-size: 11px; padding: 1px 8px;")
        self.cancel_button.setEnabled(False)
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        status_layout.addWidget(self.cancel_button)

        if not embedded:
            close_btn = QPushButton("Fechar")
            close_btn.setFixedHeight(22)
            close_btn.setStyleSheet("font-size: 11px; padding: 1px 8px;")
            close_btn.clicked.connect(self.close)
            status_layout.addWidget(close_btn)

        layout.addWidget(status_frame)

    def eventFilter(self, watched, event) -> bool:
        from PySide6.QtCore import QEvent

        if hasattr(self, "tabs") and watched == self.tabs.tabBar():
            if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                if PlaylistListWidget.has_acceptable_files(event.mimeData()):
                    event.setDropAction(Qt.DropAction.CopyAction)
                    event.accept()
                    return True
                return False
            elif event.type() == QEvent.Type.Drop:
                paths = PlaylistListWidget.extract_file_paths(event.mimeData())
                if paths:
                    event.setDropAction(Qt.DropAction.CopyAction)
                    event.accept()
                    if self.tabs.currentIndex() != 1:
                        self.tabs.setCurrentIndex(1)
                    self._on_files_dropped(paths)
                    return True
        return super().eventFilter(watched, event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        _unblock_windows_drag_drop(int(self.winId()))
        top_win = self.window()
        if top_win and top_win != self:
            _unblock_windows_drag_drop(int(top_win.winId()))
            top_win.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if PlaylistListWidget.has_acceptable_files(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if PlaylistListWidget.has_acceptable_files(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = PlaylistListWidget.extract_file_paths(event.mimeData())
        if paths:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            if hasattr(self, "tabs") and self.tabs.currentIndex() != 1:
                self.tabs.setCurrentIndex(1)
            self._on_files_dropped(paths)
            return
        super().dropEvent(event)

    def cleanup(self) -> None:
        """Safely stops workers and cleans up resources when dialog or embedding parent closes."""
        self._cleanup_worker()
        self._clear_playlist_widgets()
        if hasattr(self, "_screen_fit") and self._screen_fit is not None:
            self._screen_fit.cleanup()

    def _build_download_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Language selection group
        lang_group = QGroupBox("Idioma das Reuniões e Mídias (JW.org)")
        lang_form = QFormLayout(lang_group)
        lang_form.setContentsMargins(6, 4, 6, 4)
        lang_form.setVerticalSpacing(3)

        self.language_combo = QComboBox()
        for name, code in SUPPORTED_MEPS_LANGUAGES:
            self.language_combo.addItem(f"{name} ({code})", code)

        cur_lang = normalize_meps_language(getattr(self.settings, "congregation_language", "") or "T")
        idx = self.language_combo.findData(cur_lang)
        if idx >= 0:
            self.language_combo.setCurrentIndex(idx)
        else:
            self.language_combo.addItem(f"Outro ({cur_lang})", cur_lang)
            self.language_combo.setCurrentIndex(self.language_combo.count() - 1)

        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_form.addRow("Idioma Selecionado:", self.language_combo)
        layout.addWidget(lang_group)

        # Week selection group
        week_group = QGroupBox("📅 Programação e Semana da Reunião (JW.org)")
        week_form = QFormLayout(week_group)
        week_form.setContentsMargins(6, 4, 6, 4)
        week_form.setVerticalSpacing(3)

        week_row = QHBoxLayout()
        week_row.setSpacing(6)
        self.week_combo = QComboBox()
        self.week_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._available_weeks = self.service.get_available_weeks()
        for w in self._available_weeks:
            self.week_combo.addItem(w.label, w)
        self._cur_week_idx = next((i for i, w in enumerate(self._available_weeks) if w.is_current), 0)
        self.week_combo.setCurrentIndex(self._cur_week_idx)
        self.week_combo.currentIndexChanged.connect(self._on_week_changed)
        week_row.addWidget(self.week_combo, 1)

        self.btn_check_jwpub = QPushButton("🔍 Verificar Novas Apostilas")
        self.btn_check_jwpub.setToolTip(
            "Verifica no JW.org se há novas edições da Apostila ou Sentinela e instala no JW Library."
        )
        self.btn_check_jwpub.clicked.connect(self._on_check_jwpub_clicked)
        week_row.addWidget(self.btn_check_jwpub)
        week_form.addRow("Semana Selecionada:", week_row)

        self.chk_cleanup_after_import = QCheckBox(
            "Apagar arquivos temporários da pasta do app após importar no JW Library (Economizar espaço)"
        )
        self.chk_cleanup_after_import.setChecked(
            getattr(self.settings, "meeting_media_cleanup_after_import", True)
        )
        self.chk_cleanup_after_import.toggled.connect(self._on_cleanup_checkbox_toggled)
        week_form.addRow("", self.chk_cleanup_after_import)
        layout.addWidget(week_group)

        # Songs group
        songs_group = QGroupBox("Cânticos da Reunião (JW.org)")
        songs_form = QFormLayout(songs_group)
        songs_form.setContentsMargins(6, 4, 6, 4)
        songs_form.setVerticalSpacing(3)

        self.song_numbers_edit = QLineEdit()
        self.song_numbers_edit.setPlaceholderText("Ex: 14, 88, 142 (separe com vírgulas ou espaços)")
        songs_form.addRow("Números dos Cânticos:", self.song_numbers_edit)

        self.quality_combo = QComboBox()
        self.quality_combo.addItem("MP4 Vídeo com Letra (720p HD)", ("mp4", "720p"))
        self.quality_combo.addItem("MP4 Vídeo com Letra (480p SD)", ("mp4", "480p"))
        self.quality_combo.addItem("MP4 Vídeo com Letra (240p Leve)", ("mp4", "240p"))
        self.quality_combo.addItem("MP3 Áudio", ("mp3", "audio"))

        self.songs_playlist_edit = QLineEdit("Cânticos da Reunião")

        songs_row = QHBoxLayout()
        songs_row.setSpacing(6)
        songs_row.addWidget(QLabel("Formato:"))
        songs_row.addWidget(self.quality_combo, 1)
        songs_row.addWidget(QLabel("Playlist:"))
        songs_row.addWidget(self.songs_playlist_edit, 1)
        songs_form.addRow(songs_row)

        self.btn_download_songs = QPushButton("⬇️ Baixar e Importar Cânticos no JW Library")
        self.btn_download_songs.clicked.connect(self._on_download_songs_clicked)
        songs_form.addRow("", self.btn_download_songs)

        layout.addWidget(songs_group)

        # Midweek meeting group - 2x2 grid for responsive display without clipping
        midweek_group = QGroupBox("Mídias da Reunião de Meio de Semana (Apostila)")
        midweek_form = QFormLayout(midweek_group)
        midweek_form.setContentsMargins(6, 4, 6, 4)
        midweek_form.setVerticalSpacing(3)

        self.midweek_issue_edit = QLineEdit()
        self.midweek_issue_edit.setPlaceholderText("Ex: 202611 (ou deixe em branco para detecção automática)")
        self.midweek_playlist_edit = QLineEdit("Reunião de Meio de Semana")

        midweek_meta_row = QHBoxLayout()
        midweek_meta_row.setSpacing(6)
        midweek_meta_row.addWidget(QLabel("Edição:"))
        midweek_meta_row.addWidget(self.midweek_issue_edit, 1)
        midweek_meta_row.addWidget(QLabel("Playlist:"))
        midweek_meta_row.addWidget(self.midweek_playlist_edit, 1)
        midweek_form.addRow(midweek_meta_row)

        midweek_opts_grid = QGridLayout()
        midweek_opts_grid.setHorizontalSpacing(12)
        midweek_opts_grid.setVerticalSpacing(4)
        self.midweek_include_songs = QCheckBox("Cânticos da semana (3 cânticos)")
        self.midweek_include_songs.setChecked(True)
        midweek_opts_grid.addWidget(self.midweek_include_songs, 0, 0)

        self.midweek_include_videos = QCheckBox("Vídeos da semana (mwbv)")
        self.midweek_include_videos.setChecked(True)
        midweek_opts_grid.addWidget(self.midweek_include_videos, 0, 1)

        self.midweek_include_cbs = QCheckBox("Vídeos do Estudo Bíblico (EBC)")
        self.midweek_include_cbs.setChecked(True)
        midweek_opts_grid.addWidget(self.midweek_include_cbs, 1, 0)

        self.midweek_include_images = QCheckBox("Gravuras e imagens")
        self.midweek_include_images.setChecked(True)
        midweek_opts_grid.addWidget(self.midweek_include_images, 1, 1)
        midweek_form.addRow("Opções:", midweek_opts_grid)

        self.btn_download_midweek = QPushButton("⬇️ Baixar Mídias da Semana e Importar no JW Library")
        self.btn_download_midweek.clicked.connect(self._on_download_midweek_clicked)
        midweek_form.addRow("", self.btn_download_midweek)

        layout.addWidget(midweek_group)

        # Weekend meeting group (Watchtower Study) - 2x2 grid
        weekend_group = QGroupBox("Mídias da Reunião de Final de Semana (Estudo de A Sentinela)")
        weekend_form = QFormLayout(weekend_group)
        weekend_form.setContentsMargins(6, 4, 6, 4)
        weekend_form.setVerticalSpacing(3)

        self.weekend_issue_edit = QLineEdit()
        self.weekend_issue_edit.setPlaceholderText("Ex: 202610 (ou deixe em branco para detecção automática)")
        self.weekend_playlist_edit = QLineEdit("Estudo de A Sentinela")

        weekend_meta_row = QHBoxLayout()
        weekend_meta_row.setSpacing(6)
        weekend_meta_row.addWidget(QLabel("Edição:"))
        weekend_meta_row.addWidget(self.weekend_issue_edit, 1)
        weekend_meta_row.addWidget(QLabel("Playlist:"))
        weekend_meta_row.addWidget(self.weekend_playlist_edit, 1)
        weekend_form.addRow(weekend_meta_row)

        weekend_opts_grid = QGridLayout()
        weekend_opts_grid.setHorizontalSpacing(12)
        weekend_opts_grid.setVerticalSpacing(4)
        self.weekend_include_songs = QCheckBox("Cânticos do estudo")
        self.weekend_include_songs.setChecked(True)
        weekend_opts_grid.addWidget(self.weekend_include_songs, 0, 0)

        self.weekend_include_videos = QCheckBox("Vídeos de estudo (MP4)")
        self.weekend_include_videos.setChecked(True)
        weekend_opts_grid.addWidget(self.weekend_include_videos, 0, 1)

        self.weekend_include_images = QCheckBox("Gravuras da Sentinela")
        self.weekend_include_images.setChecked(True)
        weekend_opts_grid.addWidget(self.weekend_include_images, 1, 0)

        self.weekend_include_audio = QCheckBox("Áudio dos artigos (MP3)")
        self.weekend_include_audio.setChecked(False)
        weekend_opts_grid.addWidget(self.weekend_include_audio, 1, 1)
        weekend_form.addRow("Opções:", weekend_opts_grid)

        self.btn_download_weekend = QPushButton("⬇️ Baixar Mídias da Sentinela e Importar no JW Library")
        self.btn_download_weekend.clicked.connect(self._on_download_weekend_clicked)
        weekend_form.addRow("", self.btn_download_weekend)

        layout.addWidget(weekend_group)
        if self._available_weeks and 0 <= getattr(self, "_cur_week_idx", 0) < len(self._available_weeks):
            self._on_week_changed(self._cur_week_idx)

        layout.addStretch()
        return widget

    def _build_local_files_tab(self) -> QWidget:
        widget = PlaylistDropContainer()
        widget.files_dropped.connect(self._on_files_dropped)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        # 1. Compact Header Panel: Playlist Name, Options & Actions
        top_group = QGroupBox("Playlist no JW Library")
        top_layout = QVBoxLayout(top_group)
        top_layout.setContentsMargins(6, 4, 6, 4)
        top_layout.setSpacing(4)

        # Row 1: Name, Replace checkbox, Edit, Clear
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(QLabel("Nome:"))
        self.local_playlist_edit = QLineEdit("Discurso Público")
        self.local_playlist_edit.setPlaceholderText("Ex: Discurso Público, Reunião...")
        row1.addWidget(self.local_playlist_edit, 2)

        self.replace_playlist_check = QCheckBox("Substituir se existir")
        self.replace_playlist_check.setChecked(True)
        self.replace_playlist_check.setToolTip(
            "Se marcado, recria a playlist no JW Library preservando a ordem e opções exatas desta lista."
        )
        row1.addWidget(self.replace_playlist_check)

        edit_playlist_btn = QPushButton("✏️ Carregar / Editar…")
        edit_playlist_btn.setToolTip(
            "Abrir e editar uma playlist já salva no JW Library ou carregar de arquivo .jwlplaylist"
        )
        edit_playlist_btn.clicked.connect(self._on_edit_playlist_clicked)
        row1.addWidget(edit_playlist_btn)

        clear_btn = QPushButton("🧹 Limpar")
        clear_btn.setToolTip("Limpar todos os itens da lista")
        clear_btn.clicked.connect(self._on_clear_local_files)
        row1.addWidget(clear_btn)
        top_layout.addLayout(row1)

        # Row 2: Add Files, Song, Video, Meeting
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        add_files_btn = QPushButton("📂 Adicionar Arquivos / Pasta…")
        add_files_btn.setToolTip(
            "Adicionar slides, imagens, vídeos ou pasta do computador\n"
            "(ou arraste e solte arquivos/pastas diretamente na lista abaixo)"
        )
        add_files_btn.clicked.connect(self._on_add_local_files)
        row2.addWidget(add_files_btn)

        add_song_btn = QPushButton("🎵 Cântico JW.org…")
        add_song_btn.setToolTip("Adicionar um cântico do Reino pelo número oficial (1 a 999)")
        add_song_btn.clicked.connect(self._on_add_song_clicked)
        row2.addWidget(add_song_btn)

        add_video_btn = QPushButton("🎬 Vídeo JW.org…")
        add_video_btn.setToolTip("Adicionar um vídeo oficial do JW.org (por catálogo/busca ou código)")
        add_video_btn.clicked.connect(self._on_add_video_clicked)
        row2.addWidget(add_video_btn)

        load_meeting_btn = QPushButton("📅 Mídias de Reunião…")
        load_meeting_btn.setToolTip(
            "Carregar todas as mídias da reunião de meio ou fim de semana diretamente nesta playlist"
        )
        load_meeting_btn.clicked.connect(self._on_load_meeting_clicked)
        row2.addWidget(load_meeting_btn)
        top_layout.addLayout(row2)

        layout.addWidget(top_group)

        # 2. Main Playlist List Header with counter
        list_header_row = QHBoxLayout()
        self.playlist_count_label = QLabel(
            "Mídias da Playlist (0 itens) — Arraste arquivos aqui para adicionar:"
        )
        self.playlist_count_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        list_header_row.addWidget(self.playlist_count_label)
        list_header_row.addStretch()

        help_drop = QLabel("💡 Arraste itens para reordenar")
        help_drop.setStyleSheet("color: #6e7681; font-size: 11px;")
        list_header_row.addWidget(help_drop)
        layout.addLayout(list_header_row)

        # 3. Playlist List Widget with drag-and-drop support
        self.local_files_list = PlaylistListWidget()
        self.local_files_list.setMinimumHeight(200)
        self.local_files_list.files_dropped.connect(self._on_files_dropped)
        self.local_files_list.item_reordered.connect(self._move_playlist_item)
        layout.addWidget(self.local_files_list, 1)

        # 4. Bottom Actions
        action_row = QHBoxLayout()
        action_row.setSpacing(6)

        self.btn_import_local = QPushButton("📥 Importar Direto no JW Library")
        self.btn_import_local.setStyleSheet(
            "QPushButton { background-color: #238636; color: white; font-weight: bold; "
            "padding: 5px 12px; border-radius: 4px; }\n"
            "QPushButton:hover { background-color: #2ea043; }\n"
            "QPushButton:pressed { background-color: #1a7f37; }"
        )
        self.btn_import_local.clicked.connect(self._on_import_local_clicked)
        action_row.addWidget(self.btn_import_local, 2)

        self.btn_restart_jwl = QPushButton("🔄 Recarregar JW Library")
        self.btn_restart_jwl.setToolTip(
            "Reinicia o JW Library rapidamente para atualizar e exibir as playlists importadas."
        )
        self.btn_restart_jwl.clicked.connect(self._on_restart_jwl_clicked)
        action_row.addWidget(self.btn_restart_jwl, 1)

        export_pkg_btn = QPushButton("📦 Exportar (.jwlplaylist)…")
        export_pkg_btn.setToolTip(
            "Gera uma playlist oficial .jwlplaylist para importar diretamente no JW Library"
        )
        export_pkg_btn.clicked.connect(self._on_export_backup_package)
        action_row.addWidget(export_pkg_btn, 1)

        layout.addLayout(action_row)
        return widget

    def _build_watch_folder_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        folder_group = QGroupBox("Pasta Monitorada para Mídias de Reunião")
        folder_layout = QVBoxLayout(folder_group)

        path_row = QHBoxLayout()
        self.watch_folder_label = QLineEdit(str(self.service.media_folder))
        self.watch_folder_label.setReadOnly(True)
        path_row.addWidget(self.watch_folder_label, 1)

        change_folder_btn = QPushButton("Alterar Pasta…")
        change_folder_btn.clicked.connect(self._on_change_watch_folder)
        path_row.addWidget(change_folder_btn)
        folder_layout.addLayout(path_row)

        desc = QLabel(
            "Coloque imagens ou vídeos recebidos (por exemplo, via WhatsApp ou pendrive) "
            "nesta pasta. Eles serão importados automaticamente ou sob demanda com um clique."
        )
        desc.setWordWrap(True)
        folder_layout.addWidget(desc)

        action_row = QHBoxLayout()
        self.btn_sync_watch = QPushButton("🔄 Sincronizar Pasta Agora com o JW Library")
        self.btn_sync_watch.clicked.connect(self._on_sync_watch_folder_clicked)
        action_row.addWidget(self.btn_sync_watch)

        open_exp_btn = QPushButton("📁 Abrir Pasta no Explorer")
        open_exp_btn.clicked.connect(self.service.open_media_folder)
        action_row.addWidget(open_exp_btn)
        folder_layout.addLayout(action_row)

        layout.addWidget(folder_group)
        layout.addStretch()
        return widget

    def _build_backup_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        info_group = QGroupBox("Banco de Dados do JW Library")
        info_layout = QVBoxLayout(info_group)

        db_path = self.service.jwl_db_path
        status_text = (
            f"Caminho detectado: {db_path}"
            if db_path
            else "JW Library não localizado nesta máquina."
        )
        self.db_status_label = QLabel(status_text)
        self.db_status_label.setWordWrap(True)
        info_layout.addWidget(self.db_status_label)

        btn_row = QHBoxLayout()
        self.btn_create_backup = QPushButton("💾 Fazer Backup de Segurança Agora")
        self.btn_create_backup.clicked.connect(self._on_create_manual_backup)
        btn_row.addWidget(self.btn_create_backup)

        refresh_btn = QPushButton("🔄 Atualizar Lista")
        refresh_btn.clicked.connect(self._refresh_backups_list)
        btn_row.addWidget(refresh_btn)
        info_layout.addLayout(btn_row)

        layout.addWidget(info_group)

        layout.addWidget(QLabel("Backups salvos de userData.db:"))
        self.backups_list = QListWidget()
        self.backups_list.setMinimumHeight(80)
        layout.addWidget(self.backups_list, 1)

        restore_row = QHBoxLayout()
        self.btn_restore_backup = QPushButton("⏮️ Restaurar Backup Selecionado")
        self.btn_restore_backup.clicked.connect(self._on_restore_backup_clicked)
        restore_row.addWidget(self.btn_restore_backup)
        layout.addLayout(restore_row)

        # Storage cleanup group
        cleanup_group = QGroupBox("🧹 Limpeza de Armazenamento e Mídias Antigas (App e JW Library)")
        cleanup_layout = QVBoxLayout(cleanup_group)
        cleanup_layout.setContentsMargins(6, 6, 6, 6)
        cleanup_layout.setSpacing(5)

        lbl_clean_info = QLabel(
            "Libere espaço em disco removendo vídeos e imagens de semanas anteriores do JW Library "
            "e o cache de reuniões do aplicativo. Mídias de playlists personalizadas "
            "e discursos são preservadas."
        )
        lbl_clean_info.setWordWrap(True)
        lbl_clean_info.setStyleSheet("color: #8b949e; font-size: 11px;")
        cleanup_layout.addWidget(lbl_clean_info)

        opts_row = QHBoxLayout()
        opts_row.setSpacing(8)
        opts_row.addWidget(QLabel("Manter mídias das últimas:"))
        self.cleanup_weeks_combo = QComboBox()
        self.cleanup_weeks_combo.addItem("1 semana atrás", 1)
        self.cleanup_weeks_combo.addItem("2 semanas atrás (Recomendado)", 2)
        self.cleanup_weeks_combo.addItem("3 semanas atrás", 3)
        self.cleanup_weeks_combo.addItem("4 semanas atrás", 4)
        self.cleanup_weeks_combo.setCurrentIndex(1)
        opts_row.addWidget(self.cleanup_weeks_combo)
        opts_row.addStretch()
        cleanup_layout.addLayout(opts_row)

        chk_row = QHBoxLayout()
        chk_row.setSpacing(12)
        self.chk_clean_jwl_box = QCheckBox("Limpar vídeos do JW Library (Videos/JWLibrary e Userdata)")
        self.chk_clean_jwl_box.setChecked(True)
        chk_row.addWidget(self.chk_clean_jwl_box)

        self.chk_clean_app_box = QCheckBox("Limpar cache local de reuniões do aplicativo")
        self.chk_clean_app_box.setChecked(True)
        chk_row.addWidget(self.chk_clean_app_box)
        cleanup_layout.addLayout(chk_row)

        self.btn_run_cleanup = QPushButton("🧹 Executar Limpeza e Liberar Espaço")
        self.btn_run_cleanup.clicked.connect(self._on_run_cleanup_clicked)
        cleanup_layout.addWidget(self.btn_run_cleanup)

        layout.addWidget(cleanup_group)

        self._refresh_backups_list()
        return widget

    def _refresh_backups_list(self) -> None:
        self.backups_list.clear()
        backups = self.service.list_backups()
        for b in backups:
            size_kb = b["size_bytes"] / 1024
            item_text = f"{b['filename']} — {size_kb:.1f} KB ({b['timestamp']})"
            self.backups_list.addItem(item_text)

    def _clear_playlist_widgets(self) -> None:
        if hasattr(self, "local_files_list") and self.local_files_list is not None:
            for i in range(self.local_files_list.count()):
                it = self.local_files_list.item(i)
                if it is not None:
                    w = self.local_files_list.itemWidget(it)
                    if w is not None:
                        self.local_files_list.removeItemWidget(it)
                        w.setParent(None)
                        w.deleteLater()
            self.local_files_list.clear()

    def _refresh_playlist_list(self) -> None:
        self._clear_playlist_widgets()
        total = len(self._playlist_items)
        for idx, item in enumerate(self._playlist_items):
            list_item = QListWidgetItem()
            list_item.setSizeHint(QSize(0, 42))
            row_widget = PlaylistItemRowWidget(item, idx, total_count=total)
            row_widget.move_up_requested.connect(lambda i=idx: self._move_playlist_item(i, i - 1))
            row_widget.move_down_requested.connect(lambda i=idx: self._move_playlist_item(i, i + 1))
            row_widget.remove_requested.connect(lambda i=idx: self._remove_playlist_item(i))
            self.local_files_list.addItem(list_item)
            self.local_files_list.setItemWidget(list_item, row_widget)
        self._update_playlist_summary()

    def _update_playlist_summary(self) -> None:
        count = len(self._playlist_items)
        tot_sec = sum(it.duration_seconds for it in self._playlist_items if it.duration_seconds > 0)
        dur_info = f" • Duração estimada: {format_duration(tot_sec)}" if tot_sec > 0 else ""
        plural_text = "itens" if count != 1 else "item"
        self.playlist_count_label.setText(
            f"Mídias da Playlist ({count} {plural_text}{dur_info}) — "
            "Arraste arquivos aqui para adicionar:"
        )

    def _move_playlist_item(self, from_idx: int, to_idx: int) -> None:
        if 0 <= from_idx < len(self._playlist_items) and 0 <= to_idx < len(self._playlist_items):
            item = self._playlist_items.pop(from_idx)
            self._playlist_items.insert(to_idx, item)
            self._local_files = [it.source_path for it in self._playlist_items]
            self._refresh_playlist_list()
            self.local_files_list.setCurrentRow(to_idx)

    def _remove_playlist_item(self, idx: int) -> None:
        if 0 <= idx < len(self._playlist_items):
            self._playlist_items.pop(idx)
            self._local_files = [it.source_path for it in self._playlist_items]
            self._refresh_playlist_list()

    def _on_files_dropped(self, paths: list[Path]) -> None:
        supported_exts = {
            ".mp4",
            ".m4v",
            ".mkv",
            ".webm",
            ".avi",
            ".mov",
            ".mp3",
            ".m4a",
            ".aac",
            ".wav",
            ".ogg",
            ".flac",
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
            ".bmp",
            ".gif",
            ".jwpub",
            ".jwlplaylist",
        }
        def natural_sort_key(path: Path):
            return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]

        all_files: list[Path] = []
        for p in paths:
            if p.is_dir():
                sub_files = [
                    sub
                    for sub in p.rglob("*")
                    if sub.is_file() and sub.suffix.lower() in supported_exts
                ]
                sub_files.sort(key=natural_sort_key)
                all_files.extend(sub_files)
            elif p.is_file() and p.suffix.lower() in supported_exts:
                all_files.append(p)

        for p in all_files:
            if p.suffix.lower() == ".jwlplaylist":
                try:
                    name, items = self.service.load_playlist_from_file(p)
                    if name and (
                        not self._playlist_items
                        or self.local_playlist_edit.text().strip() in ("", "Discurso Público")
                    ):
                        self.local_playlist_edit.setText(name)
                    for item in items:
                        self._playlist_items.append(item)
                        if item.source_path:
                            self._local_files.append(item.source_path)
                except Exception:
                    pass
                continue

            if p.suffix.lower() == ".jwpub":
                try:
                    img_dir = p.parent / f"{p.stem}_imagens"
                    from meeting_assistant.services.meeting_media_downloader import extract_images_from_jwpub

                    extracted = extract_images_from_jwpub(p, img_dir)
                    extracted.sort(key=natural_sort_key)
                    for img in extracted:
                        label = img.stem.replace("_", " ").strip()
                        item = MediaImportItem(source_path=img, label=label or img.name, end_action=2)
                        self._playlist_items.append(item)
                        self._local_files.append(img)
                except Exception:
                    pass
                continue

            label = p.stem.replace("_", " ").strip()
            item = MediaImportItem(source_path=p, label=label or p.name, end_action=2)
            self._playlist_items.append(item)
            self._local_files.append(p)

        self._refresh_playlist_list()

    def _on_edit_playlist_clicked(self) -> None:
        dlg = EditPlaylistDialog(self.service, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name, items = dlg.get_selected_playlist()
            if name:
                self.local_playlist_edit.setText(name)
            self._playlist_items.clear()
            self._local_files.clear()
            for it in items:
                self._playlist_items.append(it)
                if it.source_path:
                    self._local_files.append(it.source_path)
            self._refresh_playlist_list()

    def _on_add_local_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Selecionar arquivos de mídia",
            "",
            (
                "Mídias (*.jpg *.jpeg *.png *.mp4 *.m4v *.mp3 *.m4a *.webp *.wav *.jwpub *.jwlplaylist);;"
                "Todos (*.*)"
            ),
        )
        if files:
            paths = [Path(f) for f in files]
            self._on_files_dropped(paths)

    def _on_remove_local_file(self) -> None:
        row = self.local_files_list.currentRow()
        if 0 <= row < len(self._playlist_items):
            self._remove_playlist_item(row)

    def _on_clear_local_files(self) -> None:
        self._playlist_items.clear()
        self._local_files.clear()
        self._refresh_playlist_list()

    def _on_add_song_clicked(self) -> None:
        dlg = AddSongDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            num, fmt = dlg.get_data()
            self._start_worker(
                "load_song_for_playlist",
                {"song_number": num, "format_type": fmt},
            )

    def _on_add_video_clicked(self) -> None:
        dlg = AddVideoDialog(self, service=self.service)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            selected_item = dlg.get_selected_item()
            if selected_item:
                self._start_worker(
                    "download_media_item",
                    {"item": selected_item},
                )
            else:
                pub, track, issue = dlg.get_advanced_data()
                self._start_worker(
                    "load_video_for_playlist",
                    {"pub": pub, "track": track, "issue": issue},
                )

    def _on_load_meeting_clicked(self) -> None:
        init_issue = self.midweek_issue_edit.text().strip() if hasattr(self, "midweek_issue_edit") else None
        dlg = LoadMeetingDialog(
            self,
            meeting_date=getattr(self, "selected_meeting_date", None),
            initial_issue=init_issue,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            if data["replace_existing"]:
                self._playlist_items.clear()
                self._local_files.clear()
                self._refresh_playlist_list()
            pl_name = data.get("playlist_name")
            if pl_name:
                self.local_playlist_edit.setText(pl_name)
            self._start_worker("load_meeting_for_playlist", data)

    def _on_cleanup_checkbox_toggled(self, checked: bool) -> None:
        self.settings.meeting_media_cleanup_after_import = checked
        try:
            SettingsService().save(self.settings)
        except Exception:
            pass

    def _on_change_watch_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Selecionar Pasta para Mídias",
            str(self.service.media_folder),
        )
        if folder:
            p = Path(folder)
            self.settings.meeting_media_folder = str(p)
            self.watch_folder_label.setText(str(p))
            try:
                SettingsService().save(self.settings)
            except Exception:
                pass

    def _start_worker(self, task_type: str, params: dict) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.warning(
                self,
                "Operação em Andamento",
                "Uma tarefa já está em execução. Aguarde ou cancele.",
            )
            return

        self._cancel_token = CancelToken()
        self.cancel_button.setEnabled(True)
        self.cancel_button.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self._set_controls_enabled(False)

        self._last_task_type = task_type
        # Worker created without parent=self as required by AGENTS.md rules
        self._worker = MediaTaskWorker(self.service, task_type, params, self._cancel_token)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.status_message.connect(self.status_label.setText)
        self._worker.task_finished.connect(self._on_task_finished)
        self._worker.items_ready.connect(self._on_worker_items_ready)
        self._worker.start()

    def _on_worker_items_ready(self, items: list[MediaImportItem]) -> None:
        for it in items:
            self._playlist_items.append(it)
            if it.source_path:
                self._local_files.append(it.source_path)
        self._refresh_playlist_list()

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.language_combo.setEnabled(enabled)
        self.btn_download_songs.setEnabled(enabled)
        self.btn_download_midweek.setEnabled(enabled)
        self.btn_download_weekend.setEnabled(enabled)
        self.btn_import_local.setEnabled(enabled)
        self.btn_sync_watch.setEnabled(enabled)
        self.btn_create_backup.setEnabled(enabled)
        self.btn_restore_backup.setEnabled(enabled)
        if hasattr(self, "btn_restart_jwl"):
            self.btn_restart_jwl.setEnabled(enabled)
        if hasattr(self, "btn_check_jwpub"):
            self.btn_check_jwpub.setEnabled(enabled)
        if hasattr(self, "week_combo"):
            self.week_combo.setEnabled(enabled)
        if hasattr(self, "btn_run_cleanup"):
            self.btn_run_cleanup.setEnabled(enabled)

    def _on_language_changed(self) -> None:
        code = self.language_combo.currentData() or "T"
        self.settings.congregation_language = code
        try:
            SettingsService().save(self.settings)
        except Exception:
            pass
        self._refresh_weeks()

    def _on_week_changed(self, index: int) -> None:
        if not hasattr(self, "_available_weeks") or index < 0 or index >= len(self._available_weeks):
            return
        week = self._available_weeks[index]
        self.selected_meeting_date = week.monday
        if hasattr(self, "midweek_issue_edit"):
            self.midweek_issue_edit.setText(week.mwb_issue)
        if hasattr(self, "weekend_issue_edit"):
            self.weekend_issue_edit.setText(week.w_issue)

    def _refresh_weeks(self) -> None:
        if not hasattr(self, "week_combo"):
            return
        cur_item = self.week_combo.currentData()
        cur_monday = getattr(cur_item, "monday", None)
        self.week_combo.blockSignals(True)
        self.week_combo.clear()
        self._available_weeks = self.service.get_available_weeks()
        selected_idx = 0
        for idx, w in enumerate(self._available_weeks):
            self.week_combo.addItem(w.label, w)
            if cur_monday and w.monday == cur_monday:
                selected_idx = idx
            elif not cur_monday and w.is_current:
                selected_idx = idx
        self.week_combo.setCurrentIndex(selected_idx)
        self.week_combo.blockSignals(False)
        self._on_week_changed(selected_idx)

    def _on_check_jwpub_clicked(self) -> None:
        self._start_worker(
            "check_and_install_jwpub",
            {"auto_install": True},
        )

    def _on_run_cleanup_clicked(self) -> None:
        keep_w = self.cleanup_weeks_combo.currentData() if hasattr(self, "cleanup_weeks_combo") else 2
        clean_app = self.chk_clean_app_box.isChecked() if hasattr(self, "chk_clean_app_box") else True
        clean_jwl = self.chk_clean_jwl_box.isChecked() if hasattr(self, "chk_clean_jwl_box") else True

        if not (clean_app or clean_jwl):
            QMessageBox.warning(
                self, "Limpeza de Armazenamento", "Selecione pelo menos um local para limpar."
            )
            return

        confirm = QMessageBox.question(
            self,
            "Confirmar Limpeza de Armazenamento",
            f"Deseja remover as mídias de reuniões de mais de {keep_w} semanas atrás?\n\n"
            "• Mídias do JW Library e cache local expirados serão excluídos para liberar espaço em disco.\n"
            "• Playlists personalizadas e arquivos de discursos serão preservados intactos.\n\n"
            "Deseja prosseguir com a limpeza?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._start_worker(
            "cleanup_storage",
            {
                "keep_weeks": keep_w,
                "clean_app_cache": clean_app,
                "clean_jwl_storage": clean_jwl,
            },
        )

    def _on_cancel_clicked(self) -> None:
        self._cancel_token.cancel()
        if self._worker:
            self._worker.requestInterruption()
        self.status_label.setText("Cancelamento solicitado…")
        self.cancel_button.setEnabled(False)

    def is_jwl_running(self) -> bool:
        """Checks if JW Library is currently open."""
        return self.service.is_jwl_running()

    def restart_jwl(self) -> bool:
        """Restarts JW Library to refresh in-memory SQLite playlist cache."""
        ok = self.service.restart_jwl()
        if ok:
            self.status_label.setText("JW Library reiniciado para atualizar playlists.")
        return ok

    def _on_restart_jwl_clicked(self) -> None:
        if self.is_jwl_running():
            confirm = QMessageBox.question(
                self,
                "Recarregar JW Library",
                "Deseja fechar e reabrir o JW Library agora para atualizar e exibir as playlists?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        self.restart_jwl()
        QMessageBox.information(
            self,
            "JW Library",
            "JW Library reiniciado para atualizar a exibição das playlists.",
        )

    def _on_task_finished(self, success: bool, message: str) -> None:
        self._set_controls_enabled(True)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setVisible(False)
        self.progress_bar.setVisible(False)
        self.status_label.setText(message)
        self._refresh_backups_list()

        if getattr(self, "_last_task_type", "") == "check_and_install_jwpub":
            self._refresh_weeks()

        is_staging_task = getattr(self, "_last_task_type", "") in (
            "load_meeting_for_playlist",
            "load_song_for_playlist",
            "load_video_for_playlist",
        )

        if success:
            if not is_staging_task:
                info_msg = message
                has_jwl = "JW Library" in message
                is_sync_or_import = (
                    "importado" in message or "sincronizado" in message or "sucesso" in message.lower()
                )
                if has_jwl and is_sync_or_import:
                    if getattr(self, "_last_task_type", "") == "import_playlist" and self.is_jwl_running():
                        prompt = (
                            f"{message}\n\n"
                            "O JW Library já está aberto. Para que a nova playlist apareça "
                            "imediatamente na tela, deseja recarregar o JW Library agora?"
                        )
                        reply = QMessageBox.question(
                            self,
                            "Mídias do JW Library",
                            prompt,
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.Yes,
                        )
                        if reply == QMessageBox.StandardButton.Yes:
                            self.restart_jwl()
                    else:
                        QMessageBox.information(self, "Mídias do JW Library", info_msg)
                else:
                    QMessageBox.information(self, "Mídias do JW Library", info_msg)
        else:
            QMessageBox.warning(self, "Mídias do JW Library", message)

        if self._worker is not None:
            self._worker.quit()
            self._worker.wait(500)
            self._worker = None

    def _on_download_songs_clicked(self) -> None:
        raw_text = self.song_numbers_edit.text()
        nums = [int(n) for n in re.findall(r"\d+", raw_text)]
        if not nums:
            QMessageBox.warning(
                self,
                "Cânticos",
                "Digite pelo menos um número de cântico válido (ex: 14, 88).",
            )
            return

        format_data = self.quality_combo.currentData() or ("mp4", "720p")
        format_type, quality = format_data
        self.settings.meeting_media_quality = quality
        try:
            SettingsService().save(self.settings)
        except Exception:
            pass
        playlist_name = self.songs_playlist_edit.text().strip() or "Cânticos da Reunião"

        self._start_worker(
            "download_songs",
            {
                "song_numbers": nums,
                "playlist_name": playlist_name,
                "format_type": format_type,
            },
        )

    def _on_download_midweek_clicked(self) -> None:
        issue = self.midweek_issue_edit.text().strip() or None
        playlist_name = self.midweek_playlist_edit.text().strip() or "Reunião de Meio de Semana"
        include_songs = self.midweek_include_songs.isChecked()
        include_videos = self.midweek_include_videos.isChecked()
        include_cbs = self.midweek_include_cbs.isChecked()
        include_images = self.midweek_include_images.isChecked()
        meeting_date = getattr(self, "selected_meeting_date", None) or datetime.date.today()
        cleanup = (
            self.chk_cleanup_after_import.isChecked()
            if hasattr(self, "chk_cleanup_after_import")
            else None
        )

        if not (include_songs or include_videos or include_cbs or include_images):
            QMessageBox.warning(
                self,
                "Meio de Semana",
                "Selecione pelo menos uma opção para baixar.",
            )
            return

        self._start_worker(
            "download_midweek",
            {
                "issue": issue,
                "playlist_name": playlist_name,
                "include_images": include_images,
                "include_videos": include_videos,
                "include_songs": include_songs,
                "include_cbs_videos": include_cbs,
                "meeting_date": meeting_date,
                "cleanup_cache_after_import": cleanup,
            },
        )

    def _on_download_weekend_clicked(self) -> None:
        issue = self.weekend_issue_edit.text().strip() or None
        playlist_name = self.weekend_playlist_edit.text().strip() or "Estudo de A Sentinela"
        include_songs = self.weekend_include_songs.isChecked()
        include_images = self.weekend_include_images.isChecked()
        include_audio = self.weekend_include_audio.isChecked()
        include_videos = self.weekend_include_videos.isChecked()
        meeting_date = getattr(self, "selected_meeting_date", None) or datetime.date.today()
        cleanup = (
            self.chk_cleanup_after_import.isChecked()
            if hasattr(self, "chk_cleanup_after_import")
            else None
        )

        if not (include_songs or include_images or include_audio or include_videos):
            QMessageBox.warning(
                self,
                "Final de Semana",
                "Selecione pelo menos uma opção para baixar.",
            )
            return

        self._start_worker(
            "download_weekend",
            {
                "issue": issue,
                "playlist_name": playlist_name,
                "include_images": include_images,
                "include_audio": include_audio,
                "include_videos": include_videos,
                "include_songs": include_songs,
                "meeting_date": meeting_date,
                "cleanup_cache_after_import": cleanup,
            },
        )

    def _on_import_local_clicked(self) -> None:
        if not self._playlist_items and not self._local_files:
            QMessageBox.warning(self, "Arquivos Locais", "Nenhum arquivo adicionado à lista.")
            return

        playlist_name = self.local_playlist_edit.text().strip() or "Discurso Público"
        chk = getattr(self, "replace_playlist_check", None)
        clear_existing = chk.isChecked() if chk is not None else True

        # If items are in _playlist_items, use rich import
        if self._playlist_items:
            self._start_worker(
                "import_playlist",
                {
                    "items": list(self._playlist_items),
                    "playlist_name": playlist_name,
                    "clear_existing": clear_existing,
                },
            )
        else:
            self._start_worker(
                "import_local",
                {"files": list(self._local_files), "playlist_name": playlist_name},
            )

    def _on_export_backup_package(self) -> None:
        if not self._playlist_items and not self._local_files:
            QMessageBox.warning(self, "Exportar Playlist", "Nenhum arquivo na lista para exportar.")
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar Playlist (.jwlplaylist)",
            "MidiasReuniao.jwlplaylist",
            "JW Library Playlist (*.jwlplaylist);;JW Library Backup (*.jwlibrary)",
        )
        if not save_path:
            return

        playlist_name = self.local_playlist_edit.text().strip() or "Discurso Público"
        try:
            if self._playlist_items:
                exported = self.service.export_playlist_items(
                    self._playlist_items,
                    playlist_name,
                    Path(save_path),
                )
            else:
                exported = self.service.export_backup_package(
                    self._local_files,
                    playlist_name,
                    Path(save_path),
                )
            QMessageBox.information(
                self,
                "Playlist Exportada",
                f"Playlist oficial gerada com sucesso em:\n{exported}\n\n"
                "Você pode importá-la diretamente no JW Library através do menu 'Importar playlist'.",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Erro na Exportação", f"Falha ao gerar playlist:\n{exc}")

    def _on_sync_watch_folder_clicked(self) -> None:
        self._start_worker(
            "sync_watch_folder",
            {"playlist_name": "Mídias do Salão"},
        )

    def _on_create_manual_backup(self) -> None:
        self._start_worker("create_backup", {})

    def _on_restore_backup_clicked(self) -> None:
        row = self.backups_list.currentRow()
        backups = self.service.list_backups()
        if row < 0 or row >= len(backups):
            QMessageBox.warning(
                self,
                "Restaurar Backup",
                "Selecione um backup na lista acima para restaurar.",
            )
            return

        chosen = backups[row]
        reply = QMessageBox.question(
            self,
            "Confirmar Restauração",
            f"Deseja realmente restaurar o banco de dados a partir de:\n{chosen['filename']}?\n\n"
            "Isso substituirá o banco atual do JW Library pelos dados deste backup.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._start_worker("restore_backup", {"backup_file": chosen["path"]})

    def _cleanup_worker(self) -> None:
        # Strictly follow worker cancellation and disconnection lifecycle per AGENTS.md rules
        if self._worker is not None:
            self._cancel_token.cancel()
            try:
                self._worker.progress.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                self._worker.status_message.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                self._worker.task_finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                self._worker.items_ready.disconnect()
            except (RuntimeError, TypeError):
                pass
            if self._worker.isRunning():
                self._worker.requestInterruption()
                self._worker.quit()
                self._worker.wait(1500)
            self._worker = None

    def reject(self) -> None:
        self._cleanup_worker()
        self._clear_playlist_widgets()
        if hasattr(self, "_screen_fit") and self._screen_fit is not None:
            self._screen_fit.cleanup()
        super().reject()

    def closeEvent(self, event) -> None:
        self._cleanup_worker()
        self._clear_playlist_widgets()
        if hasattr(self, "_screen_fit") and self._screen_fit is not None:
            self._screen_fit.cleanup()
        super().closeEvent(event)
