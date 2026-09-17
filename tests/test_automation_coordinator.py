from meeting_assistant.services.automation_coordinator import AutomationCoordinator


class FakeSceneController:
    def __init__(self) -> None:
        self.scenes: list[str] = []

    def set_program_scene(self, scene_name: str) -> None:
        self.scenes.append(scene_name)


class FakeToggleService:
    def __init__(self) -> None:
        self.values: list[bool] = []

    def set_enabled(self, enabled: bool) -> None:
        self.values.append(enabled)


def make_coordinator(
    obs: FakeSceneController,
    media: FakeToggleService,
    guard: FakeToggleService,
    current_scene: list[str | None],
) -> AutomationCoordinator:
    return AutomationCoordinator(
        obs,
        media,
        guard,
        lambda: "Palco",
        lambda: current_scene[0],
    )


def test_automation_requests_palco_before_arming_sensor() -> None:
    obs = FakeSceneController()
    media = FakeToggleService()
    guard = FakeToggleService()
    current_scene: list[str | None] = ["Mídias"]
    coordinator = make_coordinator(obs, media, guard, current_scene)

    coordinator.request(True)

    assert coordinator.requested is True
    assert coordinator.armed is False
    assert media.values == [False]
    assert guard.values == [True]
    assert obs.scenes == ["Palco"]

    coordinator.on_scene_changed("Mídias")
    assert coordinator.armed is False
    assert media.values == [False]

    current_scene[0] = "Palco"
    coordinator.on_scene_changed("Palco")
    assert coordinator.armed is True
    assert media.values == [False, True]


def test_automation_arms_immediately_when_obs_is_already_on_palco() -> None:
    obs = FakeSceneController()
    media = FakeToggleService()
    guard = FakeToggleService()
    current_scene: list[str | None] = ["Palco"]
    coordinator = make_coordinator(obs, media, guard, current_scene)

    coordinator.request(True)

    assert coordinator.requested is True
    assert coordinator.armed is True
    assert obs.scenes == []
    assert media.values == [False, True]
    assert guard.values == [True]


def test_pausing_automation_disables_sensor_and_hall_guard() -> None:
    obs = FakeSceneController()
    media = FakeToggleService()
    guard = FakeToggleService()
    current_scene: list[str | None] = ["Mídias"]
    coordinator = make_coordinator(obs, media, guard, current_scene)

    coordinator.request(True)
    current_scene[0] = "Palco"
    coordinator.on_scene_changed("Palco")
    coordinator.request(False)

    assert coordinator.requested is False
    assert coordinator.armed is False
    assert media.values[-1] is False
    assert guard.values[-1] is False


def test_reconnect_requests_palco_again_before_arming() -> None:
    obs = FakeSceneController()
    media = FakeToggleService()
    guard = FakeToggleService()
    current_scene: list[str | None] = ["Mídias"]
    coordinator = make_coordinator(obs, media, guard, current_scene)

    coordinator.request(True)
    coordinator.on_obs_connected(True, "reconectado")

    assert obs.scenes == ["Palco", "Palco"]
    assert coordinator.armed is False
    assert media.values == [False]


def test_reconnect_arms_immediately_when_palco_is_already_confirmed() -> None:
    obs = FakeSceneController()
    media = FakeToggleService()
    guard = FakeToggleService()
    current_scene: list[str | None] = ["Mídias"]
    coordinator = make_coordinator(obs, media, guard, current_scene)

    coordinator.request(True)
    current_scene[0] = "Palco"
    coordinator.on_obs_connected(True, "reconectado")

    assert coordinator.armed is True
    assert media.values == [False, True]
