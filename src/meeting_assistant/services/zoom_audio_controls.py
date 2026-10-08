"""Identify the operator's Zoom microphone from UIA/legacy accessibility evidence."""

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from operator import index

_MEETING_CLASSES = {"ConfMultiTabContentWndClass", "ZPContentViewWndClass", "ZPPTopWndClass", "ZPFloatVideoWndClass", "ZPMiniVideoWndClass"}
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
    
    is_popup = window_class in {"ZPFloatVideoWndClass", "ZPMiniVideoWndClass"}
    return explicit or (toolbar and window_class in _MEETING_CLASSES) or is_popup


@dataclass
class AccessibleMicrophone:
    button: object
    # The logical own-microphone role is bound to a process instance and meeting
    # HWND. Zoom may recreate its accessible button when its mute state changes.
    identity: tuple
    window: object = None

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


def runtime_identity(button):
    """Optional enumeration key. Providers need not return a Python list/tuple."""
    try:
        value = button.element_info.runtime_id
    except Exception:
        return None, True
    if isinstance(value, (str, bytes, Mapping)):
        return None, False
    try:
        identity = tuple(index(part) for part in value)
    except (TypeError, ValueError):
        return None, False
    return identity or None, False


def find_control(*, windows=None, pids=None, diagnostic=None):
    process_errors = 0
    if pids is None:
        import psutil

        pids = {}
        for process in psutil.process_iter(["name"]):
            try:
                if (process.info["name"] or "").casefold() == "zoom.exe":
                    # A fresh Process avoids relying on process_iter's cached
                    # object if Windows reused a PID after Zoom restarted.
                    pids[process.pid] = psutil.Process(process.pid).create_time()
            except psutil.Error:
                process_errors += 1
    details = diagnostic if diagnostic is not None else {}
    details.update(
        zoom_processes=len(pids), window_classes=[], controls_examined=0,
        audio_controls_without_state=0, property_errors=0, candidates=0,
        runtime_ids_available=0, runtime_ids_unavailable=0, runtime_id_errors=0,
        process_identity_errors=process_errors,
        identity_method="meeting_window_self_microphone",
    )
    if not pids:
        if process_errors:
            raise MicrophoneError(
                "process_identity_unavailable", "Não foi possível verificar o processo do Zoom. "
                "Abra Zoom e Meeting Assistant com o mesmo nível de permissão.",
            )
        raise MicrophoneError(
            "zoom_not_running", "Abra o Zoom e entre na reunião para controlar seu microfone."
        )
    if windows is None:
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        windows = [window for pid in pids for window in desktop.windows(process=pid)]
    candidates = []
    enumerated = {}
    for window in windows:
        pid = window.process_id()
        if pid not in pids:
            continue
        window_class = window.class_name()
        details["window_classes"].append(window_class)
        
        buttons = []
        if window_class in {"ZPFloatVideoWndClass", "ZPMiniVideoWndClass"}:
            buttons = window.descendants(control_type="Button")
        else:
            for container in window.descendants(control_type="ToolBar"):
                buttons.extend(container.descendants(control_type="Button"))
            for container in window.descendants(class_name="ZPControlPanelClass"):
                buttons.extend(container.descendants(control_type="Button"))
                
        for button in buttons:
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
            try:
                handle = index(window.handle)
            except (TypeError, ValueError):
                handle = 0
            if handle <= 0:
                raise MicrophoneError(
                    "identity_unavailable", "Não foi possível identificar a janela da reunião. "
                    "Nenhuma ação enviada.",
                )
            birth = pids.get(pid) if isinstance(pids, Mapping) else None
            identity = (pid, birth, handle, window_class, "own_microphone")
            runtime_id, error = runtime_identity(button)
            details["runtime_id_errors"] += int(error)
            details["runtime_ids_available" if runtime_id is not None else "runtime_ids_unavailable"] += 1
            state = states.pop()
            # Runtime IDs only deduplicate the SAME element during enumeration.
            # Absence never collapses two distinct candidates into one role.
            if runtime_id is not None:
                key = (identity, runtime_id)
                if key in enumerated:
                    if enumerated[key] != state:
                        raise MicrophoneError(
                            "state_unavailable", "O estado do microfone mudou durante a consulta. "
                            "Tente novamente.",
                        )
                    continue
                enumerated[key] = state
            candidates.append((AccessibleMicrophone(button, identity, window), state))
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
