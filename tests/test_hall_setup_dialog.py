from PySide6.QtWidgets import QApplication
from test_yeartext_store import png

from meeting_assistant.services.obs_controller import ObsController
from meeting_assistant.services.settings import AppSettings
from meeting_assistant.services.yeartext_store import YeartextStore
from meeting_assistant.ui import hall_setup_dialog


def test_preview_does_not_save_until_operator_confirms(tmp_path, monkeypatch):
    controller = ObsController()
    store = YeartextStore(tmp_path)
    target = {'hwnd': 7, 'rect': (0, 0, 1920, 1080), 'selectors': []}
    monkeypatch.setattr(hall_setup_dialog, 'capture_png', lambda value: png())
    dialog = hall_setup_dialog.HallSetupDialog(store, lambda: target, controller, AppSettings())
    dialog._capture()
    assert dialog.pending_png is not None
    assert store.current() is None
    dialog._save()
    assert store.current() is None
    dialog.confirm.setChecked(True)
    dialog._save()
    assert store.current()['obs_pending']
    action, payload = controller._commands.get_nowait()
    assert action == 'hall_task' and payload[0] == 'yeartext'
    dialog.close()


def test_window_change_during_capture_is_rejected(tmp_path, monkeypatch):
    targets = iter([{'hwnd': 7, 'rect': (0, 0, 1920, 1080)}, {'hwnd': 8, 'rect': (0, 0, 1920, 1080)}])
    monkeypatch.setattr(hall_setup_dialog, 'capture_png', lambda value: png())
    dialog = hall_setup_dialog.HallSetupDialog(
        YeartextStore(tmp_path), lambda: next(targets), ObsController(), AppSettings(),
    )
    dialog._capture()
    assert dialog.pending_png is None
    assert 'mudou' in dialog.result.text()
    dialog.close()


def test_preview_fits_narrow_dialog(tmp_path):
    store = YeartextStore(tmp_path)
    from datetime import datetime
    store.save(png(), datetime.now().year)
    dialog = hall_setup_dialog.HallSetupDialog(store, lambda: None, ObsController(), AppSettings())
    dialog.show()
    dialog.resize(380, 500)
    QApplication.processEvents()
    assert dialog.preview.pixmap().width() <= dialog.preview.width()
    dialog.close()


def test_pending_photo_is_distinct_and_save_controls_stay_visible(tmp_path, monkeypatch):
    from datetime import datetime

    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QScrollArea

    store = YeartextStore(tmp_path)
    store.save(png(), datetime.now().year)
    old_file = store.current()['file']
    monkeypatch.setattr(hall_setup_dialog, 'capture_png', lambda _: png())
    dialog = hall_setup_dialog.HallSetupDialog(
        store, lambda: {'hwnd': 7, 'rect': (0, 0, 100, 100)}, ObsController(), AppSettings(),
    )
    dialog.show()
    dialog.resize(380, 500)
    dialog._capture()
    QApplication.processEvents()
    assert 'NÃO salva' in dialog.photo_status.text()
    assert not dialog.save_button.isEnabled()
    assert store.current()['file'] == old_file
    scroll = dialog.findChild(QScrollArea)
    for position in (0, scroll.verticalScrollBar().maximum()):
        scroll.verticalScrollBar().setValue(position)
        QApplication.processEvents()
        for widget in (dialog.confirm, dialog.save_button, dialog.result):
            bounds = widget.rect().translated(widget.mapTo(dialog, QPoint(0, 0)))
            assert dialog.rect().contains(bounds)
    dialog._finished('yeartext', True, 'Aplicada ao OBS.')
    assert 'nova prévia ainda não foi salva' in dialog.result.text()
    dialog.confirm.setChecked(True)
    assert dialog.save_button.isEnabled()
    dialog._save()
    assert store.current()['file'] != old_file
    assert 'NÃO salva' not in dialog.photo_status.text()
    dialog.close()


def test_failed_recapture_cannot_save_stale_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(hall_setup_dialog, 'capture_png', lambda _: png())
    dialog = hall_setup_dialog.HallSetupDialog(
        YeartextStore(tmp_path), lambda: {'hwnd': 7, 'rect': (0, 0, 100, 100)},
        ObsController(), AppSettings(),
    )
    dialog._capture()
    dialog.confirm.setChecked(True)
    def unavailable():
        raise ValueError('JWL indisponível')
    dialog.target_provider = unavailable
    dialog._capture()
    assert dialog.pending_png is None
    assert not dialog.save_button.isEnabled()
    assert 'indisponível' in dialog.result.text()
    dialog.close()
