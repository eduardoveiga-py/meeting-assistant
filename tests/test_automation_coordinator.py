from meeting_assistant.services.automation_coordinator import AutomationCoordinator


class FakeToggleService:
    def __init__(self) -> None:
        self.values: list[bool] = []

    def set_enabled(self, enabled: bool) -> None:
        self.values.append(enabled)


def test_automation_enables_guard_and_media_sensor() -> None:
    media = FakeToggleService()
    guard = FakeToggleService()
    coordinator = AutomationCoordinator(media, guard)

    coordinator.request(True)

    assert coordinator.requested is True
    assert coordinator.armed is True
    assert guard.values == [True]
    assert media.values == [True]


def test_pausing_automation_disables_sensor_and_hall_guard() -> None:
    media = FakeToggleService()
    guard = FakeToggleService()
    coordinator = AutomationCoordinator(media, guard)

    coordinator.request(True)
    coordinator.request(False)

    assert coordinator.requested is False
    assert coordinator.armed is False
    assert media.values[-1] is False
    assert guard.values[-1] is False
