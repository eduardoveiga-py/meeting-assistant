import json
from dataclasses import replace

import pytest

from meeting_assistant.services import setup_assistant as service
from meeting_assistant.services.settings import AppSettings


def test_packaged_first_use_and_update_review(monkeypatch):
    monkeypatch.setattr(service, 'review_key', lambda: '0.5/setup-1')
    settings = AppSettings()
    assert not service.needs_setup(settings, packaged=False)
    assert service.needs_setup(settings, packaged=True)
    settings.setup_review_version = '0.5/setup-1'
    assert not service.needs_setup(settings, packaged=True)
    settings.setup_review_version = '0.4/setup-1'
    assert service.needs_setup(settings, packaged=True)


def test_websocket_preserves_other_settings_and_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'process_running', lambda _: False)
    path = tmp_path / 'config.json'
    original = {'server_enabled': False, 'custom': 123}
    path.write_text(json.dumps(original))
    service.configure_websocket(AppSettings(obs_password='test-password'), tmp_path)
    config = json.loads(path.read_text())
    assert config['server_enabled'] and config['auth_required']
    assert config['server_password'] == 'test-password'
    assert config['custom'] == 123
    assert json.loads(next(tmp_path.glob('config.backup-*.json')).read_text()) == original


@pytest.mark.parametrize('running,host,password', [
    (True, '127.0.0.1', 'password'), (False, '192.168.1.2', 'password'),
    (False, '127.0.0.1', ''),
])
def test_websocket_refuses_unsafe_or_incomplete_bootstrap(tmp_path, monkeypatch, running, host, password):
    monkeypatch.setattr(service, 'process_running', lambda _: running)
    with pytest.raises(ValueError):
        service.configure_websocket(AppSettings(obs_host=host, obs_password=password), tmp_path)
    assert not (tmp_path / 'config.json').exists()


def test_installation_is_allowlisted_and_keeps_hash_checks(monkeypatch):
    monkeypatch.setattr(service.shutil, 'which', lambda _: 'winget.exe')
    args = service.installation_command('OBS')
    assert args[args.index('--id') + 1] == 'OBSProject.OBSStudio'
    assert '--ignore-security-hash' not in args and '--force' not in args
    with pytest.raises(ValueError):
        service.installation_command('arbitrary.exe')


def test_scene_names_must_be_distinct():
    with pytest.raises(ValueError):
        service.validate_settings(replace(AppSettings(), scene_media='Palco'))


def test_assistant_embeds_forms_and_does_not_install_on_open(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from meeting_assistant.core.state import AppState
    from meeting_assistant.services.settings import SettingsService
    from meeting_assistant.ui.main_window import MainWindow
    from meeting_assistant.ui.setup_assistant_dialog import SetupAssistantDialog
    from meeting_assistant.ui.window_geometry import fit_window

    services = [MagicMock() for _ in range(6)]
    services[1].snapshot.return_value = []
    services[5].active = services[5].returning = False
    owner = MainWindow(AppState(), AppSettings(), SettingsService(tmp_path / 'settings.json'), *services)
    monkeypatch.setattr(SetupAssistantDialog, '_inspect', lambda self: None)
    install = MagicMock()
    monkeypatch.setattr(service, 'install_application', install)
    dialog = SetupAssistantDialog(owner)
    dialog.show()
    QApplication.processEvents()
    try:
        fit_window(dialog, QRect(0, 0, 800, 560))
        QApplication.processEvents()
        assert QRect(0, 0, 800, 560).contains(dialog.frameGeometry())
        assert not dialog.editor.isWindow() and not dialog.hall.isWindow()
        assert not install.called
        dialog._install('OBS')
        assert 'autorização' in dialog.status.text()
        assert not install.called
        dialog.editor.password_edit.setText('test')
        assert dialog._save()
        assert owner.settings.obs_password == 'test'
        assert dialog.isVisible()
    finally:
        dialog.close()
        owner.close()
