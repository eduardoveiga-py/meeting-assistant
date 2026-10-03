"""Identify the operator's Zoom microphone from UIA/legacy accessibility evidence."""

import re
import unicodedata
from dataclasses import dataclass

_MEETING_CLASSES = {"ConfMultiTabContentWndClass", "ZPContentViewWndClass", "ZPPTopWndClass"}
_FORBIDDEN = re.compile(
    r"\b(all|todos|todas|participants?|participantes?|video|camera|legendas?|captions?|"
    r"settings|configuracoes|original|speaker|altofalante|join|ingressar|conectar)\b"
)
_AUDIO = r"(?:audio|som|microfone|microphone|mic)"


class MicrophoneError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def normalized(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().strip()


def microphone_state(label):
    value = normalized(label)
    if _FORBIDDEN.search(value) or re.search(r"\b(not|nao)\b", value):
        return None
    states = set()
    # Action names and current-state descriptions are different evidence. Both
    # must refer to audio; bare "ativar" also occurs on video/captions buttons.
    for verb, state in (("unmute", "muted"), ("mute", "live")):
        if re.fullmatch(rf"{verb}(?:\s*\([^)]*\))?", value) or re.search(
            rf"\b{verb}\s+(?:(?:my|your)\s+)?{_AUDIO}\b", value
        ):
            states.add(state)
    for verb, state in (("(?:ativar|reativar)", "muted"), ("(?:desativar|silenciar)", "live")):
        if re.search(rf"\b{verb}\s+(?:(?:o|meu|seu)\s+)*{_AUDIO}\b", value):
            states.add(state)
    if re.search(r"\bdesativar\s+(?:o\s+)?mudo\b", value):
        states.add("muted")
    if re.search(r"\bativar\s+(?:o\s+)?mudo\b", value):
        states.add("live")
    for status, state in (
        ("(?:muted|silenciado|desativado|mudo)", "muted"),
        ("(?:unmuted|ativado|aberto)", "live"),
    ):
        if re.fullmatch(status, value) or re.search(
            rf"\b{_AUDIO}\s*(?:[,.:]\s*)?(?:(?:is|esta)\s+)?{status}\b", value
        ):
            states.add(state)
    return states.pop() if len(states) == 1 else None


def accessible_fields(button):
    """Read current properties, not the visible caption alone. Never log their text."""
    fields = {"name": button.window_text()}
    errors = 0
    for name, attribute in (("help", "CurrentHelpText"), ("status", "CurrentItemStatus")):
        try:
            fields[name] = getattr(button.element_info.element, attribute)
        except Exception:
            # Optional properties/patterns are absent on some providers.
            # Count failures so sanitized diagnostics retain the evidence.
            errors += 1
    try:
        properties = button.legacy_properties()
        for key in ("Name", "Description", "Help", "Value", "DefaultAction", "KeyboardShortcut"):
            fields["legacy_" + key.lower()] = properties.get(key, "")
    except Exception:
        errors += 1
    return {key: value for key, value in fields.items() if isinstance(value, str) and value}, errors


def self_control_scope(button, fields, window_class):
    text = normalized(" ".join(fields.values()))
    if _FORBIDDEN.search(text):
        return False
    explicit = bool(
        re.search(r"\b(?:my|your|meu|seu)\s+" + _AUDIO + r"\b", text)
        or re.search(r"\balt\s*\+\s*a\b", text)
    )
    toolbar = False
    parent = button
    for _ in range(6):
        try:
            parent = parent.parent()
            kind = parent.element_info.control_type
            class_name = parent.class_name()
        except Exception:
            break
        # Participant-row controls are never the operator's toolbar command.
        if kind in {"DataItem", "ListItem", "TreeItem", "MenuItem"}:
            return False
        if kind == "ToolBar" or class_name == "ZPControlPanelClass":
            toolbar = True
        if kind == "Window":
            break
    return explicit or (toolbar and window_class in _MEETING_CLASSES)


@dataclass
class AccessibleMicrophone:
    button: object
    identity: tuple

    def invoke(self):
        from pywinauto.uia_defines import NoPatternInterfaceError

        # Select a supported pattern BEFORE dispatching. Never retry through a
        # second pattern after Invoke may already have changed the microphone.
        try:
            pattern = self.button.iface_invoke
        except NoPatternInterfaceError:
            try:
                pattern = self.button.iface_legacy_iaccessible
            except NoPatternInterfaceError as exc:
                raise MicrophoneError(
                    "action_unavailable", "Zoom não expõe uma ação acessível para seu microfone."
                ) from exc
            pattern.DoDefaultAction()
        else:
            pattern.Invoke()


def find_control(*, windows=None, pids=None, diagnostic=None):
    if pids is None:
        import psutil

        pids = set()
        for process in psutil.process_iter(["name"]):
            try:
                if (process.info["name"] or "").casefold() == "zoom.exe":
                    pids.add(process.pid)
            except psutil.Error:
                continue
    details = diagnostic if diagnostic is not None else {}
    details.update(
        zoom_processes=len(pids), window_classes=[], controls_examined=0,
        audio_controls_without_state=0, property_errors=0, candidates=0,
    )
    if not pids:
        raise MicrophoneError(
            "zoom_not_running", "Abra o Zoom e entre na reunião para controlar seu microfone."
        )
    if windows is None:
        from pywinauto import Desktop

        windows = Desktop(backend="uia").windows()
    candidates = []
    identities = set()
    for window in windows:
        if window.process_id() not in pids:
            continue
        window_class = window.class_name()
        details["window_classes"].append(window_class)
        for button in window.descendants(control_type="Button"):
            details["controls_examined"] += 1
            if not button.is_enabled():
                continue
            try:
                fields, errors = accessible_fields(button)
            except Exception:
                details["property_errors"] += 1
                continue
            details["property_errors"] += errors
            if not self_control_scope(button, fields, window_class):
                continue
            # A minimized meeting can still expose its own accessible command.
            if not button.is_visible():
                try:
                    if not window.is_minimized():
                        continue
                except Exception:
                    continue
            states = {state for value in fields.values() if (state := microphone_state(value))}
            if len(states) != 1:
                if re.search(r"\b" + _AUDIO + r"\b", normalized(" ".join(fields.values()))):
                    details["audio_controls_without_state"] += 1
                continue
            runtime_id = button.element_info.runtime_id
            if not isinstance(runtime_id, (tuple, list)) or not runtime_id:
                raise MicrophoneError(
                    "identity_unavailable", "Zoom não informa a identidade do controle. Nenhuma ação enviada."
                )
            identity = (window.process_id(), window.handle, tuple(runtime_id))
            if identity not in identities:
                identities.add(identity)
                candidates.append((AccessibleMicrophone(button, identity), states.pop()))
    details["window_classes"] = sorted(set(details["window_classes"]))
    details["candidates"] = len(candidates)
    if len(candidates) > 1:
        raise MicrophoneError(
            "ambiguous_control",
            "Há mais de um controle de microfone no Zoom. Feche menus/painéis de áudio e tente novamente.",
        )
    if not candidates:
        if details["audio_controls_without_state"]:
            raise MicrophoneError(
                "state_unavailable",
                "Zoom mostra Áudio, mas não informa mudo/aberto à acessibilidade. "
                "Exiba a barra da reunião e tente novamente.",
            )
        raise MicrophoneError(
            "control_not_found",
            "Microfone do operador não localizado. "
            "Exiba a barra de controles da reunião no Zoom e tente novamente.",
        )
    return candidates[0]
