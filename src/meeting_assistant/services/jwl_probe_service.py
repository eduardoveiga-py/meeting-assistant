from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from meeting_assistant.services.obs_controller import ObsConnectionConfig
from meeting_assistant.services.obs_visual_probe_service import ObsVisualProbeService


class JwlProbeService(QObject):
    """Adapta o probe visual do OBS à interface de diagnóstico do JW Library.

    A detecção estrutural por HWND foi descartada após o teste real mostrar que o
    JW Library mantém as mesmas janelas durante play/stop. O probe agora observa a
    cena de mídia do OBS, que é o sinal visual relevante para a futura automação.
    """

    started = Signal()
    progress_changed = Signal(int, int)
    finished = Signal(str, str)

    def __init__(
        self,
        visual_probe: ObsVisualProbeService,
        config: ObsConnectionConfig,
        media_scene: str,
    ) -> None:
        super().__init__()
        self._probe = visual_probe
        self._config = config
        self._media_scene = media_scene

        self._probe.started.connect(self.started.emit)
        self._probe.progress_changed.connect(self.progress_changed.emit)
        self._probe.finished.connect(self.finished.emit)
        self._probe.failed.connect(self._on_failed)

    @property
    def active(self) -> bool:
        return self._probe.active

    def start(self) -> bool:
        return self._probe.start(self._config, self._media_scene)

    def stop(self) -> None:
        self._probe.stop()

    def reconfigure(self, config: ObsConnectionConfig, media_scene: str) -> None:
        if self.active:
            return
        self._config = config
        self._media_scene = media_scene

    def _on_failed(self, message: str) -> None:
        report = (
            "Meeting Assistant — probe visual de mídia pelo OBS\n\n"
            f"Falha: {message}\n\n"
            "Nenhuma cena do OBS foi alterada."
        )
        self.finished.emit(report, "relatório não gerado")
