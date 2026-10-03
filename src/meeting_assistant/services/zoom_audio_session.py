"""Keep an own-microphone reference on its COM worker; always read current state."""

import time

from meeting_assistant.services.zoom_audio_controls import (
    AccessibleMicrophone,
    MicrophoneError,
    accessible_fields,
    microphone_state,
    self_control_scope,
)


def process_birth(pid):
    import psutil

    return psutil.Process(pid).create_time()


def refresh_control(control, *, birth_reader=process_birth, diagnostic=None):
    """Revalidate the selected role/context and read uncached properties only."""
    pid, birth, handle, window_class, _role = control.identity
    window, button = control.window, control.button
    if window is None or birth is None or birth_reader(pid) != birth:
        raise MicrophoneError("control_changed", "O processo do Zoom mudou.")
    for wrapper in (window, button):
        # pywinauto descendants can memoize Name/visibility. Keep the element
        # reference, but never reuse a cached mute state or action name.
        setter = getattr(wrapper.element_info, "set_cache_strategy", None)
        if setter is not None:
            setter(False)
    if (window.process_id(), window.handle, window.class_name()) != (pid, handle, window_class):
        raise MicrophoneError("control_changed", "A janela do Zoom mudou.")
    if not button.is_enabled() or (not button.is_visible() and not window.is_minimized()):
        raise MicrophoneError("control_not_found", "O controle do microfone não está disponível.")
    fields, errors = accessible_fields(button)
    if diagnostic is not None:
        diagnostic["property_errors"] = diagnostic.get("property_errors", 0) + errors
    if not self_control_scope(button, fields, window_class):
        raise MicrophoneError("control_changed", "O controle deixou de ser seu microfone.")
    states = {state for value in fields.values() if (state := microphone_state(value))}
    if len(states) != 1:
        raise MicrophoneError("state_unavailable", "Zoom não informou o estado atual do microfone.")
    return control, states.pop()


class ZoomAudioSession:
    """Created/used/cleared on one persistent MTA thread, never on the GUI."""

    def __init__(self, discover, *, birth_reader=process_birth):
        self._discover = discover
        self._birth_reader = birth_reader
        self._control = None
        self._details = {}
        self._discovery_details = {}

    def begin(self, details):
        self._details = details
        details.update(discovery_calls=0, refresh_calls=0, cache_invalidations=0)

    def __call__(self):
        details = self._details
        if self._control is not None:
            started = time.monotonic()
            details["refresh_calls"] += 1
            # Keep only sanitized discovery evidence, not labels/IDs or wrappers.
            details.update(self._discovery_details)
            try:
                result = refresh_control(
                    self._control, birth_reader=self._birth_reader, diagnostic=details
                )
            except Exception as exc:
                # This is BEFORE dispatch. A stale element can be rediscovered;
                # a failed invocation is never routed through this fallback.
                self._control = None
                details["cache_invalidations"] += 1
                details["cache_error_type"] = type(exc).__name__
            else:
                details["lookup_path"] = "direct"
                return result
            finally:
                details["refresh_ms"] = details.get("refresh_ms", 0) + round(
                    (time.monotonic() - started) * 1000
                )
        details["discovery_calls"] += 1
        details["lookup_path"] = "discovery"
        snapshot = {}
        started = time.monotonic()
        try:
            control, state = self._discover(diagnostic=snapshot)
        finally:
            details.update(snapshot)
            details["discovery_ms"] = details.get("discovery_ms", 0) + round(
                (time.monotonic() - started) * 1000
            )
        self._discovery_details = snapshot
        if (
            isinstance(control, AccessibleMicrophone) and control.window is not None
            and len(control.identity) == 5 and control.identity[1] is not None
        ):
            self._control = control
        return control, state

    def clear(self):
        # Release COM element references before the owning apartment exits.
        self._control = None
        self._discovery_details = {}
        self._details = {}
