
from PySide6.QtCore import QObject, Signal

try:
    import win32api
    import win32con
    import win32gui
except ImportError:
    win32api = None
    win32con = None
    win32gui = None

from meeting_assistant.services.display_service import DisplayInfo


class ExternalMediaService(QObject):
    state_changed = Signal(bool, str)

    def __init__(self, display_provider):
        super().__init__()
        self._display_provider = display_provider
        self.active = False
        self._media_hwnd = 0
        self._original_placement = None

    def _get_target_display(self) -> DisplayInfo | None:
        return self._display_provider()

    def _find_media_player(self) -> int:
        candidates = []
        def callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            class_name = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd)
            # Detect VLC, MPC-HC, Windows Photos, Movies & TV
            media_titles = ("Fotos", "Filmes", "Photos", "Movies")
            is_media_frame = (
                "ApplicationFrameWindow" in class_name
                and any(t in title for t in media_titles)
            )
            if "VLC" in title or "MediaPlayerClassicW" in class_name or is_media_frame:
                candidates.append(hwnd)
            return True
        win32gui.EnumWindows(callback, None)
        # If no specific player found, check if foreground is a valid window
        if not candidates:
            hwnd = win32gui.GetForegroundWindow()
            if hwnd and win32gui.IsWindowVisible(hwnd):
                class_name = win32gui.GetClassName(hwnd)
                if class_name not in ["Progman", "WorkerW", "Shell_TrayWnd"]:
                    candidates.append(hwnd)
        return candidates[0] if candidates else 0

    def start_external_media(self) -> bool:
        if not win32gui:
            self.state_changed.emit(False, "API Windows indisponível.")
            return False

        target = self._get_target_display()
        if not target:
            self.state_changed.emit(False, "Monitor 2 (Salão) não encontrado.")
            return False

        hwnd = self._find_media_player()
        if not hwnd:
            self.state_changed.emit(False, "Nenhum player de mídia encontrado.")
            return False

        self._media_hwnd = hwnd
        self._original_placement = win32gui.GetWindowPlacement(hwnd)

        # Move to Monitor 2 and Maximize
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_TOP,
            target.x, target.y, target.width, target.height,
            win32con.SWP_SHOWWINDOW
        )
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        
        self.active = True
        self.state_changed.emit(True, "Mídia Externa ativa.")
        return True

    def stop_external_media(self) -> None:
        if not self.active or not win32gui:
            return
            
        if self._media_hwnd and win32gui.IsWindow(self._media_hwnd):
            if self._original_placement:
                win32gui.SetWindowPlacement(self._media_hwnd, self._original_placement)
            win32gui.ShowWindow(self._media_hwnd, win32con.SW_MINIMIZE)
            
        self.active = False
        self._media_hwnd = 0
        self.state_changed.emit(False, "Mídia Externa encerrada.")
