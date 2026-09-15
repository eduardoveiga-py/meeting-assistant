from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class OperatingMode(StrEnum):
    BACKGROUND = "background"
    SPEAKER = "speaker"
    MEDIA = "media"
    ZOOM = "zoom"


class HealthLevel(StrEnum):
    UNKNOWN = "unknown"
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True)
class ComponentHealth:
    name: str
    level: HealthLevel = HealthLevel.UNKNOWN
    message: str = "Aguardando verificação"
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def update(self, level: HealthLevel, message: str) -> None:
        self.level = level
        self.message = message
        self.updated_at = datetime.now(UTC)


@dataclass(slots=True)
class AppState:
    current_mode: OperatingMode = OperatingMode.BACKGROUND
    automation_enabled: bool = False
    manual_override: bool = False
    second_display_available: bool = False
    simulation_enabled: bool = True

    @property
    def can_use_audience_output(self) -> bool:
        return self.second_display_available or self.simulation_enabled

    def set_mode(self, mode: OperatingMode) -> None:
        if not isinstance(mode, OperatingMode):
            raise TypeError("mode deve ser uma instância de OperatingMode")
        self.current_mode = mode
