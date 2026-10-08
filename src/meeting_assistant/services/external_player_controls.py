"""Controls scoped to the selected player; no global media keys or guessed tabs."""

import multiprocessing
import re
import sys
import threading
import time
import unicodedata

BROWSERS = {"chrome.exe", "msedge.exe"}


class PlayerControlError(ValueError):
    pass


def control_action(label):
    text = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().casefold()
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip().rstrip(".")
    names = {
        "play": {"play", "reproduzir", "reproducir", "resume playback", "play the media",
                 "iniciar reproducao", "retomar reproducao", "reproduzir a midia"},
        "pause": {"pause", "pausa", "pausar", "pause the playback", "pausar a reproducao"},
        "stop": {"stop", "parar", "stop playback", "stop the playback", "parar a reproducao"},
        "fullscreen": {"full screen", "fullscreen", "enter full screen", "enter fullscreen",
                       "tela cheia", "ecra inteiro", "entrar em tela cheia", "pantalla completa"},
        "exit_fullscreen": {"exit full screen", "exit fullscreen", "leave full screen",
                            "sair da tela cheia", "sair de tela cheia", "sair do ecra inteiro",
                            "salir de pantalla completa"},
    }
    return next((action for action, labels in names.items() if text in labels), None)


def choose_control(buttons, action, *, browser):
    rows = [(button, control_action(button.window_text())) for button in buttons
            if button.is_enabled() and button.is_visible()]
    if action == "stop" and browser:
        action = "pause"  # Web players commonly have no Stop; pause before returning.
    if action in {"play", "pause"}:
        playback = [(button, name) for button, name in rows if name in {"play", "pause"}]
        if len(playback) != 1:
            raise PlayerControlError(
                "Não encontrei um único controle do vídeo. Deixe o vídeo visível na aba escolhida."
            )
        button, name = playback[0]
        return button, action if name == action else None
    if action == "fullscreen":
        candidates = [(button, name) for button, name in rows
                      if name in {"fullscreen", "exit_fullscreen"}]
    else:
        candidates = [(button, name) for button, name in rows if name == action]
    if action == "exit_fullscreen" and not candidates:
        return None, None
    if len(candidates) != 1:
        raise PlayerControlError(
                "Controle indisponível nesse vídeo. Use Maximizar para preencher o monitor."
            )
    return candidates[0]


def perform(action, lookup, valid, *, browser, cancelled=lambda: False,
            clock=time.monotonic, pause=time.sleep):
    if action not in {"play", "pause", "stop", "fullscreen", "exit_fullscreen"}:
        raise PlayerControlError("Comando de mídia desconhecido.")
    if cancelled() or not valid():
        raise PlayerControlError("A janela escolhida mudou; nenhum comando enviado.")
    button, dispatch = choose_control(lookup(), action, browser=browser)
    if dispatch is None:
        return {"confirmed": True, "dispatched": False, "action": action, "fullscreen_entered": False}
    if (cancelled() or not valid() or not button.is_enabled() or not button.is_visible()
            or control_action(button.window_text()) != dispatch):
        raise PlayerControlError("O controle do vídeo mudou; nenhum comando enviado.")
    # Invoke on this apartment. Do not use click_input, SendInput, WM_APPCOMMAND
    # or a fallback keystroke: those can act on the search box or another app.
    button.invoke()
    expected = {"play": "pause", "pause": "play", "stop": "play",
                "fullscreen": "exit_fullscreen", "exit_fullscreen": "fullscreen"}[dispatch]
    deadline = clock() + 1.4
    while not cancelled() and valid():
        actions = [control_action(item.window_text()) for item in lookup()
                   if item.is_enabled() and item.is_visible()]
        if actions.count(expected) == 1 and (dispatch == "stop" or dispatch not in actions):
            return {"confirmed": True, "dispatched": True, "action": action,
                    "fullscreen_entered": dispatch == "fullscreen"}
        if clock() >= deadline:
            break
        pause(0.05)
    raise PlayerControlError(
                "O vídeo não confirmou o comando. Confira a reprodução; o comando não foi repetido."
            )


def _is_nested_document(document, root):
    node = document
    for _ in range(24):
        node = node.parent()
        if node is None or node == root:
            return False
        if node.element_info.control_type == "Document":
            return True
    return True


class _Button:
    def __init__(self, wrapper):
        self.wrapper = wrapper

    def window_text(self):
        self.wrapper.element_info.set_cache_strategy(False)
        name = self.wrapper.window_text()
        if control_action(name):
            return name
        # Icon-only Qt/VLC buttons can expose their current action as help or
        # legacy description instead of Name. Accept only one recognized action.
        labels = []
        for attribute in ("CurrentHelpText", "CurrentItemStatus"):
            try:
                label = getattr(self.wrapper.element_info.element, attribute)
            except Exception:
                continue  # Optional accessibility properties are not universal.
            if isinstance(label, str):
                labels.append(label)
        try:
            legacy = self.wrapper.legacy_properties()
        except Exception:
            legacy = {}
        labels.extend(value for key in ("Name", "Description", "Help")
                      if isinstance(value := legacy.get(key), str))
        actions = {action for label in labels if (action := control_action(label))}
        if len(actions) == 1:
            return next(label for label in labels if control_action(label) in actions)
        return name

    def is_enabled(self):
        return self.wrapper.is_enabled()

    def is_visible(self):
        return self.wrapper.is_visible()

    def invoke(self):
        from pywinauto.uia_defines import NoPatternInterfaceError

        try:
            pattern = self.wrapper.iface_invoke
        except NoPatternInterfaceError:
            pattern = None
        if pattern is not None:
            pattern.Invoke()
        else:
            # Select pattern is not a playback action. Only a supported legacy
            # default action is an alternative, chosen BEFORE dispatch.
            self.wrapper.iface_legacy_iaccessible.DoDefaultAction()


def _uia_lookup(window, browser):
    import win32process
    from pywinauto import Desktop

    root = Desktop(backend="uia").window(handle=window.hwnd).wrapper_object()
    raw_pid = win32process.GetWindowThreadProcessId(window.hwnd)[1]
    if (root.handle != window.hwnd or root.class_name() != window.class_name
            or root.process_id() not in {window.pid, raw_pid}):
        raise PlayerControlError("A janela escolhida mudou; controle cancelado.")
    scope = root
    if browser:
        documents = [item for item in root.descendants(control_type="Document", depth=12)
                     if item.is_visible() and not _is_nested_document(item, root)]
        if len(documents) != 1:
            raise PlayerControlError(
                "Não identifiquei a aba visível do navegador. Deixe apenas o vídeo nessa janela."
            )
        scope = documents[0]
    buttons = scope.descendants(control_type="Button", depth=18)
    # Includes embedded players in this tab. Multiple playback controls are
    # refused by choose_control rather than arbitrarily selecting an iframe/ad.
    return [_Button(item) for item in buttons]


def _control_process(pipe, window, action):
    # The UIA provider can hang. This short-lived isolated process is terminated
    # on cancel/deadline; no COM wrappers escape into Qt or other threads.
    sys.coinit_flags = 0
    import pythoncom

    pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
    try:
        from meeting_assistant.services.window_inventory import WindowBackend

        backend = WindowBackend()
        browser = window.process.casefold() in BROWSERS
        result = perform(action, lambda: _uia_lookup(window, browser),
                         lambda: backend.same_window(window), browser=browser)
        pipe.send({"ok": True, **result})
    except PlayerControlError as exc:
        pipe.send({"ok": False, "message": str(exc)})
    except Exception as exc:
        pipe.send({"ok": False, "message": "Controle do vídeo indisponível; confira o aplicativo.",
                   "error_type": type(exc).__name__})
    finally:
        pipe.close()
        pythoncom.CoUninitialize()


class PlayerControlBackend:
    def __init__(self, *, timeout=5.0, context=None, worker=None, platform=None):
        self.timeout = timeout
        self._context = context
        self._worker = worker or _control_process
        self._platform = platform or sys.platform
        self._lock = threading.Lock()
        self._process = None
        self.fullscreen_owned = False

    def command(self, window, action, cancel):
        if self._platform != "win32":
            raise PlayerControlError("Controles de mídia disponíveis somente no Windows 11.")
        if cancel.is_set():
            raise PlayerControlError("Controle de mídia cancelado.")
        if action == "fullscreen":
            # Invocation can change the page even if confirmation times out.
            # Stop must still try to exit a fullscreen we may have requested.
            self.fullscreen_owned = True
        context = self._context or multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=self._worker, args=(sender, window, action), daemon=True)
        replied = False
        try:
            with self._lock:
                self._process = process
                process.start()
            sender.close()
            deadline = time.monotonic() + self.timeout
            while not cancel.is_set() and time.monotonic() < deadline:
                if receiver.poll(0.05):
                    result = receiver.recv()
                    replied = True
                    if not result["ok"]:
                        raise PlayerControlError(result["message"])
                    if action == "fullscreen":
                        self.fullscreen_owned = result["fullscreen_entered"]
                    elif action == "exit_fullscreen":
                        self.fullscreen_owned = False
                    return result
                if not process.is_alive():
                    break
            raise PlayerControlError(
                "Controle cancelado ou sem resposta. Confira o vídeo; nenhum comando repetido."
            )
        finally:
            sender.close()
            receiver.close()
            with self._lock:
                if self._process is process:
                    self._process = None
            if process.pid is not None:
                if replied:
                    process.join(timeout=0.15)  # Give a responsive provider time to release COM normally.
                if process.is_alive():
                    process.terminate()
                process.join(timeout=0.3)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=0.3)
                process.close()

    def close(self):
        with self._lock:
            if self._process is not None and self._process.pid and self._process.is_alive():
                self._process.terminate()
