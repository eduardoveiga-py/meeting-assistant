import json
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage

from meeting_assistant.services.hall_capture import obs_window_key, verified_hall_target
from meeting_assistant.services.yeartext_store import YeartextStore


def png(color=0xFF000000):
    image = QImage(32, 18, QImage.Format_RGB32)
    image.fill(color)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, 'PNG')
    return bytes(data)


def test_save_missing_corrupt_and_new_year(tmp_path):
    store = YeartextStore(tmp_path)
    assert store.current() is None
    year = datetime.now().year
    current = store.save(png(), year)
    assert current['obs_pending']
    assert 'atualizar' in store.status(year + 1)
    assert 'salva' in store.status(year)
    Path(current['path']).write_bytes(b'corrupt')
    assert store.current() is None
    assert 'inválida' in store.status(year)


def test_failed_manifest_commit_preserves_previous_photo(tmp_path, monkeypatch):
    store = YeartextStore(tmp_path)
    original = store.save(png(), datetime.now().year)
    def fail(data):
        raise OSError('disk error')
    monkeypatch.setattr(store, '_commit', fail)
    with pytest.raises(OSError):
        store.save(png(0xFFFFFFFF), datetime.now().year)
    assert store.current()['sha256'] == original['sha256']
    assert Path(original['path']).is_file()


def test_stale_obs_completion_does_not_clear_new_photo_pending(tmp_path):
    store = YeartextStore(tmp_path)
    old = store.save(png(), datetime.now().year)
    new = store.save(png(0xFFFFFFFF), datetime.now().year)
    store.mark_applied(old['sha256'])
    assert store.current()['obs_pending']
    store.mark_applied(new['sha256'])
    assert not store.current()['obs_pending']


def test_missing_metadata_is_invalid(tmp_path):
    store = YeartextStore(tmp_path)
    store.save(png(), datetime.now().year)
    data = json.loads(store.manifest.read_text())
    del data['captured_at']
    store.manifest.write_text(json.dumps(data))
    assert store.current() is None


def test_capture_refuses_zoom_or_missing_window_before_native_calls():
    with pytest.raises(ValueError, match='Zoom'):
        verified_hall_target(None, None, True)
    with pytest.raises(ValueError, match='disponível'):
        verified_hall_target(None, None, False)


def test_obs_selector_uses_official_escaping():
    assert obs_window_key('JW: #', 'Class', 'JWLibrary.exe') == 'JW#3A #22:Class:JWLibrary.exe'


def test_same_pixels_new_capture_is_not_marked_applied_by_old_request(tmp_path):
    store = YeartextStore(tmp_path)
    old = store.save(png(), datetime.now().year)
    new = store.save(png(), datetime.now().year)
    store.mark_applied(old['sha256'], old['file'])
    assert store.current()['obs_pending']
    store.mark_applied(new['sha256'], new['file'])
    assert not store.current()['obs_pending']
