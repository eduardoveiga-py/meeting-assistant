"""One policy for the periodic guardian and the automatic media sensor.

Explicit one-shot returns are handled by ZoomHallService even while paused.
"""


def hall_runtime_flags(enabled, zoom_active, returning, switching_to_zoom=False, *, external_active=False):
    protect = bool(enabled and not (zoom_active or returning or switching_to_zoom or external_active))
    return protect, protect
