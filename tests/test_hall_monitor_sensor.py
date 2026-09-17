from meeting_assistant.services.display_service import DisplayInfo
from meeting_assistant.services.hall_monitor_sensor import (
    NativeMonitorInfo,
    central_capture_region,
    choose_native_monitor,
)


def target_display() -> DisplayInfo:
    return DisplayInfo(
        key="tv",
        name="TV-monitor",
        manufacturer="d",
        model="TV-monitor",
        serial="16843009",
        x=-629,
        y=-1080,
        width=1280,
        height=720,
        primary=False,
        device_pixel_ratio=1.5,
    )


def test_native_monitor_mapping_handles_mixed_dpi_geometry() -> None:
    monitors = [
        NativeMonitorInfo("DISPLAY2", True, 0, 0, 1920, 1080),
        NativeMonitorInfo("DISPLAY1", False, -629, -1080, 1291, 0),
    ]
    chosen = choose_native_monitor(monitors, target_display())
    assert chosen is not None
    assert chosen.device == "DISPLAY1"
    assert chosen.width == 1920
    assert chosen.height == 1080


def test_capture_region_stays_inside_native_monitor() -> None:
    monitor = NativeMonitorInfo("DISPLAY1", False, -629, -1080, 1291, 0)
    region = central_capture_region(monitor)
    assert region.left > monitor.left
    assert region.top > monitor.top
    assert region.left + region.width < monitor.right
    assert region.top + region.height < monitor.bottom
