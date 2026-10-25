from __future__ import annotations

from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QFrame

from meeting_assistant.services.jwl_media_importer import MediaImportResult, init_jwl_schema
from meeting_assistant.services.settings import AppSettings
from meeting_assistant.ui.meeting_media_dialog import MeetingMediaDialog
from meeting_assistant.ui.settings_dialog import SettingsDialog


def test_meeting_media_dialog_tabs_and_controls(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)

    settings = AppSettings(
        jwl_userdata_db_path=str(db_file),
        meeting_media_folder=str(tmp_path / "Media"),
    )
    dialog = MeetingMediaDialog(settings=settings)

    assert dialog.tabs.count() == 4
    assert "Download JW.org" in dialog.tabs.tabText(0)
    assert "Discurso Público" in dialog.tabs.tabText(1)
    assert "Pasta Monitorada" in dialog.tabs.tabText(2)
    assert "Banco de Dados" in dialog.tabs.tabText(3)

    # Test songs input validation
    dialog.song_numbers_edit.setText("14, 88, 142")
    with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
        fake_result = MediaImportResult(success=True, imported_count=3, playlist_name="Cânticos da Reunião")
        with patch.object(dialog.service, "download_songs_and_import", return_value=fake_result):
            dialog._on_download_songs_clicked()
            assert dialog._worker is not None
            dialog._worker.wait(3000)
            app.processEvents()
            assert mock_info.called

    dialog.cleanup()
    dialog.close()


def test_settings_dialog_removed_media_and_language_group() -> None:
    _ = QApplication.instance() or QApplication([])

    settings = AppSettings()
    dialog = SettingsDialog(settings, available_scenes=["Palco", "Mídias"])

    # User requested removing duplicate "Mídias e idioma" group from SettingsDialog
    assert not hasattr(dialog, "media_group")
    assert not hasattr(dialog, "download_media_button")
    assert not hasattr(dialog, "media_language_combo")

    # Mute mic setting is kept in output form
    assert hasattr(dialog, "auto_mute_mic_for_jwl_media")
    assert dialog.auto_mute_mic_for_jwl_media.isChecked()

    dialog.close()


def test_meeting_media_dialog_worker_lifecycle_and_rejection(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    settings = AppSettings(jwl_userdata_db_path=str(db_file))

    dialog = MeetingMediaDialog(settings=settings)

    def fake_download(*args, **kwargs):
        cancel_token = kwargs.get("cancel_token")
        import time
        for _ in range(50):
            if cancel_token and cancel_token.is_cancelled:
                return MediaImportResult(success=False, error_message="Cancelado")
            time.sleep(0.02)
        return MediaImportResult(success=True)

    with patch.object(dialog.service, "download_songs_and_import", side_effect=fake_download):
        dialog._start_worker("download_songs", {"song_numbers": [14], "playlist_name": "Test"})
        assert dialog._worker is not None

        # Verify reject safely cleans up worker and disconnects signals without crashing
        dialog.reject()
        assert dialog._worker is None
        assert dialog._cancel_token.is_cancelled is True
        app.processEvents()


def test_meeting_media_dialog_cancel_button(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    settings = AppSettings(jwl_userdata_db_path=str(db_file))

    dialog = MeetingMediaDialog(settings=settings)

    def fake_download(*args, **kwargs):
        cancel_token = kwargs.get("cancel_token")
        import time
        for _ in range(50):
            if cancel_token and cancel_token.is_cancelled:
                return MediaImportResult(success=False, error_message="Cancelado")
            time.sleep(0.02)
        return MediaImportResult(success=True)

    with patch.object(dialog.service, "download_songs_and_import", side_effect=fake_download):
        dialog._start_worker("download_songs", {"song_numbers": [999], "playlist_name": "Test"})
        assert dialog.cancel_button.isEnabled()

        dialog._on_cancel_clicked()
        assert dialog._cancel_token.is_cancelled is True
        assert not dialog.cancel_button.isEnabled()

        dialog.close()
        app.processEvents()


def test_settings_dialog_apply_to_preserves_media_settings() -> None:
    _ = QApplication.instance() or QApplication([])

    settings = AppSettings(
        meeting_media_folder="C:/Custom/Media",
        jwl_userdata_db_path="C:/Custom/userData.db",
        meeting_media_quality="480p",
        meeting_media_auto_sync=True,
    )
    dialog = SettingsDialog(settings, available_scenes=["Palco", "Mídias"])

    target = AppSettings()
    dialog.apply_to(target)

    assert target.meeting_media_folder == "C:/Custom/Media"
    assert target.jwl_userdata_db_path == "C:/Custom/userData.db"
    assert target.meeting_media_quality == "480p"
    assert target.meeting_media_auto_sync is True

    dialog.close()


def test_meeting_media_dialog_language_selector(tmp_path) -> None:
    _ = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)

    settings = AppSettings(
        jwl_userdata_db_path=str(db_file),
        congregation_language="T",
    )
    dialog = MeetingMediaDialog(settings=settings)

    assert hasattr(dialog, "language_combo")
    assert dialog.language_combo.count() >= 3

    # Check the 3 required languages and their MEPS codes
    codes = [dialog.language_combo.itemData(i) for i in range(dialog.language_combo.count())]
    assert "T" in codes
    assert "S" in codes
    assert "TCN" in codes

    # Switch to Ticuna
    tcn_idx = dialog.language_combo.findData("TCN")
    assert tcn_idx >= 0
    dialog.language_combo.setCurrentIndex(tcn_idx)
    assert dialog.settings.congregation_language == "TCN"

    # Switch to Spanish
    s_idx = dialog.language_combo.findData("S")
    assert s_idx >= 0
    dialog.language_combo.setCurrentIndex(s_idx)
    assert dialog.settings.congregation_language == "S"

    dialog.close()


def test_meeting_media_dialog_weekend_download_trigger(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)

    settings = AppSettings(jwl_userdata_db_path=str(db_file))
    dialog = MeetingMediaDialog(settings=settings)

    assert hasattr(dialog, "btn_download_weekend")
    assert hasattr(dialog, "weekend_issue_edit")
    assert hasattr(dialog, "weekend_playlist_edit")
    assert hasattr(dialog, "weekend_include_images")
    assert hasattr(dialog, "weekend_include_audio")

    dialog.weekend_issue_edit.setText("202610")
    dialog.weekend_playlist_edit.setText("Estudo de A Sentinela")
    dialog.weekend_include_images.setChecked(True)
    dialog.weekend_include_audio.setChecked(True)

    with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
        fake_result = MediaImportResult(
            success=True,
            imported_count=10,
            playlist_name="Estudo de A Sentinela",
        )
        with patch.object(
            dialog.service,
            "download_weekend_and_import",
            return_value=fake_result,
        ) as mock_dl:
            dialog._on_download_weekend_clicked()
            assert dialog._worker is not None
            dialog._worker.wait(3000)
            app.processEvents()
            assert mock_info.called
            assert mock_dl.called
            _, kwargs = mock_dl.call_args
            assert kwargs.get("issue") == "202610"
            assert kwargs.get("playlist_name") == "Estudo de A Sentinela"
            assert kwargs.get("include_images") is True
            assert kwargs.get("include_audio") is True

    dialog.close()


def test_settings_dialog_does_not_override_media_language() -> None:
    _ = QApplication.instance() or QApplication([])

    settings = AppSettings(congregation_language="TCN")
    dialog = SettingsDialog(settings, available_scenes=["Palco", "Mídias"])

    # Language controls removed from SettingsDialog per user requirement
    assert not hasattr(dialog, "media_language_combo")
    assert not hasattr(dialog, "media_language_edit")

    # apply_to does not wipe out or overwrite congregation_language
    target = AppSettings(congregation_language="TCN")
    dialog.apply_to(target)
    assert target.congregation_language == "TCN"

    dialog.close()


def test_meeting_media_dialog_midweek_download_trigger(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)

    settings = AppSettings(jwl_userdata_db_path=str(db_file))
    dialog = MeetingMediaDialog(settings=settings)

    assert hasattr(dialog, "btn_download_midweek")
    assert hasattr(dialog, "midweek_issue_edit")
    assert hasattr(dialog, "midweek_playlist_edit")
    assert hasattr(dialog, "midweek_include_images")
    assert hasattr(dialog, "midweek_include_videos")

    dialog.midweek_issue_edit.setText("202611")
    dialog.midweek_playlist_edit.setText("Reunião de Meio de Semana")
    dialog.midweek_include_images.setChecked(True)
    dialog.midweek_include_videos.setChecked(True)

    with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
        fake_result = MediaImportResult(
            success=True,
            imported_count=5,
            playlist_name="Reunião de Meio de Semana",
        )
        with patch.object(
            dialog.service,
            "download_midweek_and_import",
            return_value=fake_result,
        ) as mock_dl:
            dialog._on_download_midweek_clicked()
            assert dialog._worker is not None
            dialog._worker.wait(3000)
            app.processEvents()
            assert mock_info.called
            assert mock_dl.called
            _, kwargs = mock_dl.call_args
            assert kwargs.get("issue") == "202611"
            assert kwargs.get("playlist_name") == "Reunião de Meio de Semana"
            assert kwargs.get("include_images") is True
            assert kwargs.get("include_videos") is True

    dialog.close()


def test_meeting_media_dialog_compact_bounds_and_screen_fit(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)

    settings = AppSettings(jwl_userdata_db_path=str(db_file))
    dialog = MeetingMediaDialog(settings=settings)
    dialog.show()
    app.processEvents()

    try:
        # Dialog fits comfortably on standard displays (<= 600px default height)
        assert dialog.height() <= 600
        assert dialog.minimumHeight() <= 450
        assert dialog.minimumWidth() <= 600

        # Must have ScreenFitController attached to protect screen bounds
        assert hasattr(dialog, "_screen_fit")

        # Scrollable tabs (Download, Watch Folder, Backup) use QScrollArea,
        # while Playlist Tab uses direct PlaylistDropContainer to avoid nested scroll clipping
        from PySide6.QtWidgets import QScrollArea

        from meeting_assistant.ui.meeting_media_dialog import PlaylistDropContainer
        assert isinstance(dialog.tabs.widget(0), QScrollArea)
        assert isinstance(dialog.tabs.widget(1), PlaylistDropContainer)
        assert isinstance(dialog.tabs.widget(2), QScrollArea)
        assert isinstance(dialog.tabs.widget(3), QScrollArea)

        # Action buttons (Cancel, Close) and Progress Bar must be in the bottom status layout
        assert dialog.cancel_button.parent() is not None
        assert dialog.progress_bar.parent() is not None
    finally:
        dialog.close()


def test_meeting_media_dialog_message_reporting_with_synchronized_count(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)

    settings = AppSettings(jwl_userdata_db_path=str(db_file))
    dialog = MeetingMediaDialog(settings=settings)

    # 1. Test purely re-synchronized / verified files
    dialog._worker = None
    with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
        fake_result = MediaImportResult(
            success=True,
            imported_count=0,
            synchronized_count=4,
            playlist_name="Reunião de Meio de Semana",
        )
        with patch.object(dialog.service, "download_midweek_and_import", return_value=fake_result):
            dialog._on_download_midweek_clicked()
            assert dialog._worker is not None
            dialog._worker.wait(3000)
            app.processEvents()
            assert mock_info.called
            msg = mock_info.call_args[0][2]
            assert "4 item(ns) sincronizados e verificados" in msg
            assert "0 item(ns) importados" not in msg

    # 2. Test both new imports and synchronized
    with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
        fake_result = MediaImportResult(
            success=True,
            imported_count=2,
            synchronized_count=3,
            playlist_name="Reunião de Meio de Semana",
        )
        with patch.object(dialog.service, "download_midweek_and_import", return_value=fake_result):
            dialog._on_download_midweek_clicked()
            assert dialog._worker is not None
            dialog._worker.wait(3000)
            app.processEvents()
            assert mock_info.called
            msg = mock_info.call_args[0][2]
            assert "2 novo(s)" in msg
            assert "3 sincronizado(s)" in msg

    dialog.close()


def test_meeting_media_dialog_songs_and_cbs_checkboxes_and_parameters(tmp_path) -> None:
    _ = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    settings = AppSettings(jwl_userdata_db_path=str(db_file))
    dialog = MeetingMediaDialog(settings=settings)

    try:
        # Verify checkboxes exist and default to checked
        assert hasattr(dialog, "midweek_include_songs")
        assert dialog.midweek_include_songs.isChecked() is True
        assert hasattr(dialog, "midweek_include_cbs")
        assert dialog.midweek_include_cbs.isChecked() is True
        assert hasattr(dialog, "weekend_include_songs")
        assert dialog.weekend_include_songs.isChecked() is True

        # Test midweek download parameter passing
        started_workers = []
        dialog._start_worker = lambda task_type, params: started_workers.append((task_type, params))

        dialog.midweek_include_songs.setChecked(True)
        dialog.midweek_include_cbs.setChecked(False)
        dialog._on_download_midweek_clicked()

        assert len(started_workers) == 1
        task_type, params = started_workers[0]
        assert task_type == "download_midweek"
        assert params["include_songs"] is True
        assert params["include_cbs_videos"] is False

        # Test weekend download parameter passing
        started_workers.clear()
        dialog.weekend_include_songs.setChecked(False)
        dialog._on_download_weekend_clicked()

        assert len(started_workers) == 1
        task_type, params = started_workers[0]
        assert task_type == "download_weekend"
        assert params["include_songs"] is False
    finally:
        dialog.close()


def test_meeting_media_dialog_week_selector_and_issue_sync(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    settings = AppSettings(jwl_userdata_db_path=str(db_file))
    dialog = MeetingMediaDialog(settings=settings)

    try:
        assert hasattr(dialog, "week_combo")
        assert dialog.week_combo.count() > 0

        # Current week is selected by default
        cur_week_data = dialog.week_combo.currentData()
        assert cur_week_data is not None
        assert cur_week_data.is_current is True
        assert dialog.selected_meeting_date == cur_week_data.monday
        assert dialog.midweek_issue_edit.text() == cur_week_data.mwb_issue
        assert dialog.weekend_issue_edit.text() == cur_week_data.w_issue

        # Changing selection updates issue fields and selected_meeting_date
        if dialog.week_combo.count() > 1:
            target_idx = 0 if dialog.week_combo.currentIndex() != 0 else 1
            dialog.week_combo.setCurrentIndex(target_idx)
            app.processEvents()
            new_week = dialog.week_combo.itemData(target_idx)
            assert dialog.selected_meeting_date == new_week.monday
            assert dialog.midweek_issue_edit.text() == new_week.mwb_issue
            assert dialog.weekend_issue_edit.text() == new_week.w_issue

        # Changing language triggers refresh of weeks
        with patch.object(dialog, "_refresh_weeks", wraps=dialog._refresh_weeks) as mock_refresh:
            s_idx = dialog.language_combo.findData("S")
            if s_idx >= 0:
                dialog.language_combo.setCurrentIndex(s_idx)
                app.processEvents()
                assert mock_refresh.called
    finally:
        dialog.close()


def test_meeting_media_dialog_meeting_date_and_cleanup_parameters(tmp_path) -> None:
    _ = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    settings = AppSettings(
        jwl_userdata_db_path=str(db_file),
        meeting_media_cleanup_after_import=True,
    )
    dialog = MeetingMediaDialog(settings=settings)

    try:
        started_workers = []
        dialog._start_worker = lambda task_type, params: started_workers.append((task_type, params))

        assert hasattr(dialog, "chk_cleanup_after_import")
        assert dialog.chk_cleanup_after_import.isChecked() is True

        # Test midweek download parameter passing
        dialog._on_download_midweek_clicked()
        assert len(started_workers) == 1
        task_type, params = started_workers[0]
        assert task_type == "download_midweek"
        assert params["meeting_date"] == dialog.selected_meeting_date
        assert params["cleanup_cache_after_import"] is True

        # Toggle cleanup checkbox and test weekend download
        started_workers.clear()
        dialog.chk_cleanup_after_import.setChecked(False)
        assert dialog.settings.meeting_media_cleanup_after_import is False
        dialog._on_download_weekend_clicked()
        assert len(started_workers) == 1
        task_type, params = started_workers[0]
        assert task_type == "download_weekend"
        assert params["meeting_date"] == dialog.selected_meeting_date
        assert params["cleanup_cache_after_import"] is False
    finally:
        dialog.close()


def test_meeting_media_dialog_check_and_install_jwpub_button_and_worker(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    settings = AppSettings(jwl_userdata_db_path=str(db_file))
    dialog = MeetingMediaDialog(settings=settings)

    try:
        assert hasattr(dialog, "btn_check_jwpub")

        from meeting_assistant.services.meeting_media_service import (
            NewPublicationsResult,
            PublicationCheckStatus,
        )

        dummy_item = PublicationCheckStatus(
            pub_symbol="mwb",
            issue="202611",
            title="Apostila Novembro-Dezembro 2026",
            is_installed=True,
            is_available_online=True,
            installed_now=True,
        )
        fake_result = NewPublicationsResult(
            success=True,
            checked_items=[dummy_item],
            newly_installed=[dummy_item],
        )

        with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
            with patch.object(dialog.service, "check_and_install_new_publications", return_value=fake_result):
                with patch.object(dialog, "_refresh_weeks") as mock_refresh:
                    dialog._on_check_jwpub_clicked()
                    assert dialog._worker is not None
                    dialog._worker.wait(3000)
                    app.processEvents()

                    assert mock_info.called
                    info_text = mock_info.call_args[0][2]
                    assert "Apostila Novembro-Dezembro 2026" in info_text
                    assert mock_refresh.called

        # Test failure branch
        fail_result = NewPublicationsResult(
            success=False,
            error_message="Sem conexão de rede",
        )
        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            with patch.object(dialog.service, "check_and_install_new_publications", return_value=fail_result):
                dialog._on_check_jwpub_clicked()
                assert dialog._worker is not None
                dialog._worker.wait(3000)
                app.processEvents()

                assert mock_warn.called
                warn_text = mock_warn.call_args[0][2]
                assert "Sem conexão de rede" in warn_text
    finally:
        dialog.close()


def test_meeting_media_dialog_cleanup_storage_ui_and_worker(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    settings = AppSettings(jwl_userdata_db_path=str(db_file))
    dialog = MeetingMediaDialog(settings=settings)

    try:
        assert hasattr(dialog, "cleanup_weeks_combo")
        assert hasattr(dialog, "chk_clean_app_box")
        assert hasattr(dialog, "chk_clean_jwl_box")
        assert hasattr(dialog, "btn_run_cleanup")

        from PySide6.QtWidgets import QMessageBox

        from meeting_assistant.services.meeting_media_service import StorageCleanupResult

        # If user cancels the prompt, worker is NOT launched
        with patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
            dialog._on_run_cleanup_clicked()
            assert dialog._worker is None

        # When confirmed, worker is launched and executes cleanup_storage
        cleanup_res = StorageCleanupResult(
            success=True,
            total_bytes_freed=2097152,  # 2 MB
            app_files_deleted=["cache1.mp4"],
            jwl_files_deleted=["mwbv_old.mp4"],
        )
        with patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            with patch.object(dialog.service, "cleanup_storage", return_value=cleanup_res) as mock_cleanup:
                with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
                    dialog._on_run_cleanup_clicked()
                    assert dialog._worker is not None
                    dialog._worker.wait(3000)
                    app.processEvents()

                    assert mock_cleanup.called
                    assert mock_info.called
                    info_text = mock_info.call_args[0][2]
                    assert "2 arquivo(s) removidos" in info_text
                    assert "2.0 MB" in info_text
    finally:
        dialog.close()


def test_playlist_widget_and_dialog_drag_drop(tmp_path) -> None:
    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent

    from meeting_assistant.ui.meeting_media_dialog import (
        PlaylistDropContainer,
        PlaylistListWidget,
    )

    app = QApplication.instance() or QApplication([])

    # 1. Test extract_file_paths with QUrl and URI list
    f1 = tmp_path / "slide_01.jpg"
    f1.write_bytes(b"img1")
    f2 = tmp_path / "video_02.mp4"
    f2.write_bytes(b"vid2")

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(f1)), QUrl.fromLocalFile(str(f2))])
    extracted = PlaylistListWidget.extract_file_paths(mime)
    assert extracted == [f1, f2]

    mime2 = QMimeData()
    mime2.setData(
        "text/uri-list",
        f"file:///{f1.as_posix()}\r\nfile:///{f2.as_posix()}\r\n".encode(),
    )
    extracted2 = PlaylistListWidget.extract_file_paths(mime2)
    assert len(extracted2) == 2
    assert extracted2[0].name == "slide_01.jpg"

    # 2. Test PlaylistListWidget drag events
    list_widget = PlaylistListWidget()
    assert list_widget.defaultDropAction() == Qt.DropAction.CopyAction
    dropped_files = []
    list_widget.files_dropped.connect(lambda paths: dropped_files.extend(paths))

    enter_event = QDragEnterEvent(
        QPoint(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    list_widget.dragEnterEvent(enter_event)
    assert enter_event.isAccepted()
    assert enter_event.dropAction() == Qt.DropAction.CopyAction

    drop_event = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    list_widget.dropEvent(drop_event)
    assert drop_event.isAccepted()
    assert len(dropped_files) == 2
    assert dropped_files == [f1, f2]

    # 3. Test PlaylistDropContainer
    container = PlaylistDropContainer()
    container_dropped = []
    container.files_dropped.connect(lambda paths: container_dropped.extend(paths))

    container_enter = QDragEnterEvent(
        QPoint(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    container.dragEnterEvent(container_enter)
    assert container_enter.isAccepted()

    container_drop = QDropEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    container.dropEvent(container_drop)
    assert len(container_dropped) == 2

    # 4. Test MeetingMediaDialog integration
    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    settings = AppSettings(jwl_userdata_db_path=str(db_file))
    dialog = MeetingMediaDialog(settings=settings)
    try:
        dialog.tabs.setCurrentIndex(1)
        assert dialog.local_files_list.count() == 0

        dlg_drop = QDropEvent(
            QPointF(20, 20),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        dialog.dropEvent(dlg_drop)
        app.processEvents()

        # 5. Test native Windows Explorer OLE formats (FileNameW and FileName)
        mime_w = QMimeData()
        # Null-separated UTF-16LE paths
        payload_w = f"{str(f1)}\x00{str(f2)}\x00".encode("utf-16le")
        mime_w.setData('application/x-qt-windows-mime;value="FileNameW"', payload_w)
        extracted_w = PlaylistListWidget.extract_file_paths(mime_w)
        assert len(extracted_w) == 2
        assert extracted_w[0] == f1
        assert extracted_w[1] == f2

        mime_a = QMimeData()
        payload_a = f"{str(f1)}\x00{str(f2)}\x00".encode("latin1")
        mime_a.setData('application/x-qt-windows-mime;value="FileName"', payload_a)
        extracted_a = PlaylistListWidget.extract_file_paths(mime_a)
        assert len(extracted_a) == 2
        assert extracted_a[0] == f1

        # 6. Test dropped directory expansion
        media_folder = tmp_path / "SubMedia"
        media_folder.mkdir(exist_ok=True)
        img_sub = media_folder / "foto_nested.jpg"
        img_sub.write_bytes(b"nested")
        mime_folder = QMimeData()
        mime_folder.setUrls([QUrl.fromLocalFile(str(media_folder))])
        extracted_folder = PlaylistListWidget.extract_file_paths(mime_folder)
        assert len(extracted_folder) == 1
        assert extracted_folder[0] == img_sub

        # 7. Test dropping a .jwlplaylist package unpacking
        from meeting_assistant.services.jwl_media_importer import MediaImportItem
        from meeting_assistant.services.jwlibrary_backup_exporter import export_playlist_to_jwlplaylist

        pkg_file = tmp_path / "pacote_teste.jwlplaylist"
        export_playlist_to_jwlplaylist(
            [MediaImportItem(source_path=f1, label="Item Exportado", duration_seconds=5.0)],
            "Playlist Pacote",
            pkg_file,
        )
        assert pkg_file.is_file()

        mime_pkg = QMimeData()
        mime_pkg.setUrls([QUrl.fromLocalFile(str(pkg_file))])
        pkg_drop = QDropEvent(
            QPointF(20, 20),
            Qt.DropAction.CopyAction,
            mime_pkg,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        dialog.dropEvent(pkg_drop)
        app.processEvents()
        # Item from package unpacked into playlist
        assert any(
            "Item Exportado" in it.label or pkg_file.stem in str(it.source_path)
            for it in dialog._playlist_items
        )

        # 8. Test dragMoveEvent accepts proposed action
        from PySide6.QtGui import QDragMoveEvent
        move_event = QDragMoveEvent(
            QPoint(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        list_widget.dragMoveEvent(move_event)
        assert move_event.isAccepted()
        assert move_event.dropAction() == Qt.DropAction.CopyAction
    finally:
        dialog.close()


def test_setup_assistant_dialog_drag_drop_forwarding(tmp_path) -> None:
    from unittest.mock import MagicMock

    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    from meeting_assistant.core.state import AppState
    from meeting_assistant.services.settings import SettingsService
    from meeting_assistant.ui.main_window import MainWindow
    from meeting_assistant.ui.setup_assistant_dialog import SetupAssistantDialog

    app = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    settings = AppSettings(jwl_userdata_db_path=str(db_file))

    services = [MagicMock() for _ in range(6)]
    services[1].snapshot.return_value = []
    services[5].active = services[5].returning = False
    owner = MainWindow(AppState(), settings, SettingsService(tmp_path / "settings.json"), *services)
    dlg = SetupAssistantDialog(owner, page="meeting")
    try:
        assert dlg.acceptDrops() is True
        f_drop = tmp_path / "foto_drag.jpg"
        f_drop.write_bytes(b"content")

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(f_drop))])

        drop_evt = QDropEvent(
            QPointF(50, 50),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        dlg.dropEvent(drop_evt)
        app.processEvents()

        assert drop_evt.isAccepted()
        # Automatically navigated to media and loaded file
        assert dlg.navigation.currentData()[0] == "media"
        assert len(dlg.media_dialog._playlist_items) >= 1
        assert dlg.media_dialog._playlist_items[-1].source_path == f_drop
    finally:
        dlg.close()
        owner.close()


def test_playlist_drag_drop_event_filters_and_actions(tmp_path) -> None:
    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtWidgets import QApplication

    from meeting_assistant.services.jwl_media_importer import init_jwl_schema
    from meeting_assistant.services.settings import AppSettings
    from meeting_assistant.ui.meeting_media_dialog import (
        MeetingMediaDialog,
        _DropForwardingScrollArea,
    )

    app = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    settings = AppSettings(jwl_userdata_db_path=str(db_file))
    dialog = MeetingMediaDialog(settings=settings)
    try:
        dialog.show()
        app.processEvents()

        # 1. Verify self and tabs do not filter themselves out
        assert dialog not in getattr(dialog, "_eventFilters", [])

        # 2. Test dropping on dialog.tabs.tabBar() switches tab to 1 and drops files
        f1 = tmp_path / "tab_drop.jpg"
        f1.write_bytes(b"tab_content")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(f1))])

        tab_enter = QDragEnterEvent(
            QPoint(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        assert dialog.eventFilter(dialog.tabs.tabBar(), tab_enter) is True
        assert tab_enter.dropAction() == Qt.DropAction.CopyAction

        dialog.tabs.setCurrentIndex(0)
        assert dialog.tabs.currentIndex() == 0

        tab_drop = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        assert dialog.eventFilter(dialog.tabs.tabBar(), tab_drop) is True
        assert dialog.tabs.currentIndex() == 1
        assert len(dialog._playlist_items) >= 1
        assert dialog._playlist_items[-1].source_path == f1

        # 3. Test PlaylistDropContainer is directly in tab 1 (no nested scroll clamping)
        from meeting_assistant.ui.meeting_media_dialog import PlaylistDropContainer

        container = dialog.tabs.widget(1)
        assert isinstance(container, PlaylistDropContainer)

        # Tab 0 uses _DropForwardingScrollArea
        scroll0 = dialog.tabs.widget(0)
        assert isinstance(scroll0, _DropForwardingScrollArea)
    finally:
        dialog.close()


def test_meeting_media_dialog_restart_jwl(tmp_path) -> None:
    _app = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    settings = AppSettings(jwl_userdata_db_path=str(db_file))
    dialog = MeetingMediaDialog(settings=settings)

    with patch.object(dialog.service, "is_jwl_running", return_value=True):
        assert dialog.is_jwl_running() is True

    with patch.object(dialog.service, "restart_jwl", return_value=True) as mock_restart:
        ok = dialog.restart_jwl()
        assert ok is True
        assert mock_restart.called
        assert "reiniciado" in dialog.status_label.text()

    dialog.close()


def test_meeting_media_dialog_playlist_space_and_reload_button(tmp_path) -> None:
    _app = QApplication.instance() or QApplication([])

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    settings = AppSettings(jwl_userdata_db_path=str(db_file))
    dialog = MeetingMediaDialog(settings=settings)

    # Verify playlist list widget minimum height allows generous display
    assert dialog.local_files_list.minimumHeight() >= 200

    # Verify reload button is present and wired
    assert hasattr(dialog, "btn_restart_jwl")
    assert dialog.btn_restart_jwl.isEnabled()

    # Verify status bar is compact frame
    status_frame = dialog.findChild(QFrame, "statusFrame")
    assert status_frame is not None

    dialog.close()








