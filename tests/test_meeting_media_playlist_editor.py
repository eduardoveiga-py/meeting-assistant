from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QPointF, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QListWidgetItem, QMessageBox

from meeting_assistant.services.jwl_media_importer import (
    MediaImportItem,
    MediaImportResult,
    init_jwl_schema,
)
from meeting_assistant.services.settings import AppSettings
from meeting_assistant.ui.meeting_media_dialog import (
    AddSongDialog,
    AddVideoDialog,
    EditPlaylistDialog,
    LoadMeetingDialog,
    MeetingMediaDialog,
    PlaylistItemRowWidget,
    PlaylistListWidget,
    _DropForwardingScrollArea,
)


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_playlist_list_widget_drag_drop_and_signals(tmp_path: Path) -> None:
    _ = _ensure_app()
    widget = PlaylistListWidget()

    # 1. Test external file drop signal
    dropped_paths: list[list[Path]] = []
    widget.files_dropped.connect(lambda paths: dropped_paths.append(paths))

    file1 = tmp_path / "slide1.jpg"
    file1.write_bytes(b"image1")
    file2 = tmp_path / "video1.mp4"
    file2.write_bytes(b"video1")

    # Mock QDropEvent with URLs
    mock_mime = MagicMock()
    mock_mime.hasUrls.return_value = True
    u1 = QUrl.fromLocalFile(str(file1))
    u2 = QUrl.fromLocalFile(str(file2))
    mock_mime.urls.return_value = [u1, u2]

    mock_event = MagicMock(spec=QDropEvent)
    mock_event.mimeData.return_value = mock_mime

    widget.dropEvent(mock_event)

    assert len(dropped_paths) == 1
    assert file1 in dropped_paths[0]
    assert file2 in dropped_paths[0]
    assert mock_event.accept.called or mock_event.acceptProposedAction.called

    widget.close()


def test_playlist_list_widget_internal_reorder() -> None:
    _ = _ensure_app()
    widget = PlaylistListWidget()

    widget.addItem("Item 1")
    widget.addItem("Item 2")
    widget.addItem("Item 3")
    widget.setCurrentRow(0)

    reordered_events: list[tuple[int, int]] = []
    widget.item_reordered.connect(lambda src, dst: reordered_events.append((src, dst)))

    mock_mime = MagicMock()
    mock_mime.hasUrls.return_value = False

    mock_event = MagicMock(spec=QDropEvent)
    mock_event.mimeData.return_value = mock_mime
    mock_event.position.return_value = QPointF(10.0, 45.0)

    with patch.object(widget, "indexAt") as mock_index_at:
        mock_idx = MagicMock()
        mock_idx.isValid.return_value = True
        mock_idx.row.return_value = 2
        mock_index_at.return_value = mock_idx

        widget.dropEvent(mock_event)

    assert len(reordered_events) == 1
    assert reordered_events[0] == (0, 2)
    assert mock_event.accept.called or mock_event.acceptProposedAction.called

    widget.close()


def test_playlist_item_row_widget_end_action_and_editing(tmp_path: Path) -> None:
    _ = _ensure_app()

    dummy_media = tmp_path / "sample_video.mp4"
    dummy_media.write_bytes(b"dummy")

    item = MediaImportItem(
        source_path=dummy_media,
        label="Meu Vídeo de Apresentação",
        duration_seconds=125.0,
        end_action=2,
    )

    row = PlaylistItemRowWidget(item, index=0)

    assert row.label_edit.text() == "Meu Vídeo de Apresentação"
    assert "Vídeo MP4" in row.subtitle_label.text()
    assert "02:05" in row.subtitle_label.text()
    assert row.end_action_combo.currentData() == 2  # Parar

    # Test changing EndAction to 0 (Continuar), 1 (Pausar), 3 (Repetir)
    action_events: list[int] = []
    row.end_action_changed.connect(lambda val: action_events.append(val))

    row.end_action_combo.setCurrentIndex(row.end_action_combo.findData(0))
    assert item.end_action == 0
    assert action_events[-1] == 0

    row.end_action_combo.setCurrentIndex(row.end_action_combo.findData(1))
    assert item.end_action == 1
    assert action_events[-1] == 1

    row.end_action_combo.setCurrentIndex(row.end_action_combo.findData(3))
    assert item.end_action == 3
    assert action_events[-1] == 3

    # Test changing title
    labels_changed: list[str] = []
    row.label_changed.connect(lambda lbl: labels_changed.append(lbl))
    row.label_edit.setText("Vídeo Atualizado")
    assert item.label == "Vídeo Atualizado"
    assert "Vídeo Atualizado" in labels_changed

    # Test button signals
    up_called = False
    down_called = False
    remove_called = False

    def on_up():
        nonlocal up_called
        up_called = True

    def on_down():
        nonlocal down_called
        down_called = True

    def on_remove():
        nonlocal remove_called
        remove_called = True

    row.move_up_requested.connect(on_up)
    row.move_down_requested.connect(on_down)
    row.remove_requested.connect(on_remove)

    row.btn_up.click()
    assert up_called is True

    row.btn_down.click()
    assert down_called is True

    row.btn_remove.click()
    assert remove_called is True

    row.close()


def test_meeting_media_dialog_playlist_manipulation(tmp_path: Path) -> None:
    _ = _ensure_app()

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    settings = AppSettings(jwl_userdata_db_path=str(db_file))

    dialog = MeetingMediaDialog(settings=settings)

    # Prepare files
    f1 = tmp_path / "slide_01.jpg"
    f1.write_bytes(b"f1")
    f2 = tmp_path / "video_02.mp4"
    f2.write_bytes(b"f2")
    f3 = tmp_path / "audio_03.mp3"
    f3.write_bytes(b"f3")

    # 1. Drop files onto playlist
    dialog._on_files_dropped([f1, f2, f3])
    assert len(dialog._playlist_items) == 3
    assert dialog.local_files_list.count() == 3
    assert "slide 01" in dialog._playlist_items[0].label
    assert "video 02" in dialog._playlist_items[1].label
    assert "audio 03" in dialog._playlist_items[2].label
    assert "3 itens" in dialog.playlist_count_label.text()

    # 2. Reorder items: move item 0 (slide) to index 2
    dialog._move_playlist_item(0, 2)
    assert dialog._playlist_items[0].source_path == f2
    assert dialog._playlist_items[1].source_path == f3
    assert dialog._playlist_items[2].source_path == f1

    # 3. Remove item 1 (audio)
    dialog._remove_playlist_item(1)
    assert len(dialog._playlist_items) == 2
    assert dialog._playlist_items[0].source_path == f2
    assert dialog._playlist_items[1].source_path == f1

    # 4. Clear list
    dialog._on_clear_local_files()
    assert len(dialog._playlist_items) == 0
    assert dialog.local_files_list.count() == 0
    assert "0 itens" in dialog.playlist_count_label.text()

    dialog.close()


def test_add_song_dialog() -> None:
    _ = _ensure_app()
    dlg = AddSongDialog()

    # Validation: empty or non-numeric
    dlg.song_number_edit.setText("abc")
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        dlg._on_accept()
        assert mock_warn.called

    # Validation: out of bounds (> 999)
    dlg.song_number_edit.setText("1000")
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
        dlg._on_accept()
        assert mock_warn.called

    # Valid song beyond 151 (e.g. 154)
    dlg.song_number_edit.setText("154")
    dlg.format_combo.setCurrentIndex(dlg.format_combo.findData("mp4"))
    num, fmt = dlg.get_data()
    assert num == 154
    assert fmt == "mp4"

    dlg.close()


def test_add_video_dialog() -> None:
    _ = _ensure_app()
    with patch(
        "meeting_assistant.services.meeting_media_service.MeetingMediaService.get_category_videos",
        return_value=[],
    ):
        dlg = AddVideoDialog()

        # Empty selection on catalog tab warns
        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            dlg._on_accept()
            assert mock_warn.called

        # Switch to advanced tab
        dlg.tabs.setCurrentIndex(1)

        # Empty pub validation
        dlg.pub_edit.setText("")
        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            dlg._on_accept()
            assert mock_warn.called

        # Valid pub
        dlg.pub_edit.setText("mwbv")
        dlg.track_edit.setText("3")
        dlg.issue_edit.setText("202611")
        pub, track, issue = dlg.get_data()
        assert pub == "mwbv"
        assert track == 3
        assert issue == 202611

        dlg.close()


def test_load_meeting_dialog() -> None:
    _ = _ensure_app()
    dlg = LoadMeetingDialog()

    # Default is midweek
    data = dlg.get_data()
    assert data["meeting_type"] == "midweek"
    assert data["include_songs"] is True
    assert data["include_videos"] is True
    assert data["include_images"] is True
    assert data["replace_existing"] is True

    # Switch to weekend
    dlg.meeting_type_combo.setCurrentIndex(dlg.meeting_type_combo.findData("weekend"))
    assert "Sentinela" in dlg.chk_extra.text()
    data2 = dlg.get_data()
    assert data2["meeting_type"] == "weekend"
    dlg.close()

    import datetime
    target_dt = datetime.date(2026, 11, 2)
    dlg_custom = LoadMeetingDialog(meeting_date=target_dt, initial_issue="202611")
    assert dlg_custom.issue_edit.text() == "202611"
    assert dlg_custom.get_data()["meeting_date"] == target_dt
    dlg_custom.close()


def test_import_playlist_items_end_action_db_persistence(tmp_path: Path) -> None:
    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)

    settings = AppSettings(
        jwl_userdata_db_path=str(db_file),
        meeting_media_folder=str(tmp_path),
    )

    # Create dummy media files
    f_stop = tmp_path / "stop_media.mp4"
    f_stop.write_bytes(b"video_stop")
    f_cont = tmp_path / "cont_song.mp3"
    f_cont.write_bytes(b"song_continue")
    f_pause = tmp_path / "pause_slide.jpg"
    f_pause.write_bytes(b"slide_pause")
    f_repeat = tmp_path / "repeat_video.mp4"
    f_repeat.write_bytes(b"loop_repeat")

    items = [
        MediaImportItem(source_path=f_stop, label="Mídia Parar", end_action=2),
        MediaImportItem(source_path=f_cont, label="Cântico Continuar", end_action=0),
        MediaImportItem(source_path=f_pause, label="Slide Pausar", end_action=1),
        MediaImportItem(source_path=f_repeat, label="Loop Repetir", end_action=3),
    ]

    from meeting_assistant.services.meeting_media_service import MeetingMediaService

    service = MeetingMediaService(settings=settings)

    result = service.import_playlist_items(
        items,
        playlist_name="Reunião Especial",
        clear_existing=True,
    )

    assert result.success is True
    assert result.imported_count == 4

    # Direct SQLite verification
    con = sqlite3.connect(db_file)
    cur = con.cursor()

    cur.execute(
        """
        SELECT pi.Label, pi.EndAction, tm.Position
        FROM PlaylistItem pi
        JOIN TagMap tm ON pi.PlaylistItemId = tm.PlaylistItemId
        JOIN Tag t ON tm.TagId = t.TagId
        WHERE t.Name = 'Reunião Especial'
        ORDER BY tm.Position ASC
        """
    )
    rows = cur.fetchall()
    con.close()

    assert len(rows) == 4
    # Check exact labels, EndActions and positions
    assert rows[0] == ("Mídia Parar", 2, 0)
    assert rows[1] == ("Cântico Continuar", 0, 1)
    assert rows[2] == ("Slide Pausar", 1, 2)
    assert rows[3] == ("Loop Repetir", 3, 3)


def test_import_playlist_clear_existing_vs_append(tmp_path: Path) -> None:
    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)

    from meeting_assistant.services.meeting_media_service import MeetingMediaService

    settings = AppSettings(jwl_userdata_db_path=str(db_file), meeting_media_folder=str(tmp_path))
    service = MeetingMediaService(settings=settings)

    f1 = tmp_path / "initial_1.jpg"
    f1.write_bytes(b"initial_1")
    f2 = tmp_path / "initial_2.jpg"
    f2.write_bytes(b"initial_2")

    init_items = [
        MediaImportItem(source_path=f1, label="Antigo 1", end_action=2),
        MediaImportItem(source_path=f2, label="Antigo 2", end_action=2),
    ]

    res1 = service.import_playlist_items(init_items, playlist_name="Minha Playlist", clear_existing=False)
    assert res1.success is True
    assert res1.imported_count == 2

    # Now import with clear_existing=True
    f3 = tmp_path / "novo_1.jpg"
    f3.write_bytes(b"novo_1")
    f4 = tmp_path / "novo_2.jpg"
    f4.write_bytes(b"novo_2")
    f5 = tmp_path / "novo_3.jpg"
    f5.write_bytes(b"novo_3")

    new_items = [
        MediaImportItem(source_path=f3, label="Novo 1", end_action=0),
        MediaImportItem(source_path=f4, label="Novo 2", end_action=1),
        MediaImportItem(source_path=f5, label="Novo 3", end_action=3),
    ]

    res2 = service.import_playlist_items(new_items, playlist_name="Minha Playlist", clear_existing=True)
    assert res2.success is True
    assert res2.imported_count == 3

    con = sqlite3.connect(db_file)
    cur = con.cursor()
    cur.execute(
        """
        SELECT pi.Label, pi.EndAction, tm.Position
        FROM PlaylistItem pi
        JOIN TagMap tm ON pi.PlaylistItemId = tm.PlaylistItemId
        JOIN Tag t ON tm.TagId = t.TagId
        WHERE t.Name = 'Minha Playlist'
        ORDER BY tm.Position ASC
        """
    )
    rows2 = cur.fetchall()

    # The old items should have been removed, replaced by the 3 new ones at positions 0, 1, 2
    assert len(rows2) == 3
    assert rows2[0] == ("Novo 1", 0, 0)
    assert rows2[1] == ("Novo 2", 1, 1)
    assert rows2[2] == ("Novo 3", 3, 2)

    # Now append an item with clear_existing=False
    f6 = tmp_path / "extra.jpg"
    f6.write_bytes(b"extra")
    extra_items = [MediaImportItem(source_path=f6, label="Extra", end_action=2)]
    res3 = service.import_playlist_items(extra_items, playlist_name="Minha Playlist", clear_existing=False)
    assert res3.success is True
    assert res3.imported_count == 1

    cur.execute(
        """
        SELECT pi.Label, tm.Position
        FROM PlaylistItem pi
        JOIN TagMap tm ON pi.PlaylistItemId = tm.PlaylistItemId
        JOIN Tag t ON tm.TagId = t.TagId
        WHERE t.Name = 'Minha Playlist'
        ORDER BY tm.Position ASC
        """
    )
    rows3 = cur.fetchall()
    con.close()

    assert len(rows3) == 4
    assert rows3[3] == ("Extra", 3)


def test_import_playlist_items_launch_jwl_preserves_userdata_db(tmp_path: Path) -> None:
    from unittest.mock import patch

    from meeting_assistant.services.meeting_media_service import MeetingMediaService

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    settings = AppSettings(
        meeting_media_folder=str(tmp_path / "media"),
        jwl_userdata_db_path=str(db_file),
    )
    service = MeetingMediaService(settings)

    f1 = tmp_path / "slide_preservar.jpg"
    f1.write_bytes(b"slide_content")
    item = MediaImportItem(source_path=f1, label="Slide Importado", duration_seconds=0.0)

    p_launch = patch(
        "meeting_assistant.services.meeting_media_service.launch_jwl_with_playlist",
        return_value=True,
    )
    p_detect = patch(
        "meeting_assistant.services.meeting_media_service.detect_jwl_userdata_db",
        return_value=db_file,
    )
    with p_launch as mock_launch, p_detect:
        res = service.import_playlist_items(
            [item],
            playlist_name="Playlist Não Deletada",
            clear_existing=True,
            launch_jwl=True,
        )

    assert res.success is True
    assert res.activated_jwl is True
    mock_launch.assert_called_once()

    # Crucial assertion: playlist MUST remain in userData.db even when launch_jwl is True
    con = sqlite3.connect(db_file)
    cur = con.cursor()
    cur.execute("SELECT Name FROM Tag WHERE Name = 'Playlist Não Deletada'")
    tag_row = cur.fetchone()
    assert tag_row is not None, "Tag was deleted from userData.db!"
    assert tag_row[0] == "Playlist Não Deletada"

    cur.execute("SELECT Label FROM PlaylistItem WHERE Label = 'Slide Importado'")
    item_row = cur.fetchone()
    assert item_row is not None, "PlaylistItem was deleted from userData.db!"
    assert item_row[0] == "Slide Importado"
    con.close()


def test_export_playlist_items_creates_valid_package(tmp_path: Path) -> None:
    from meeting_assistant.services.meeting_media_service import MeetingMediaService

    f1 = tmp_path / "export_media.mp4"
    f1.write_bytes(b"video_bytes")

    items = [
        MediaImportItem(
            source_path=f1,
            label="Mídia Exportada",
            duration_seconds=60.0,
            end_action=3,  # Repetir
        )
    ]

    settings = AppSettings(meeting_media_folder=str(tmp_path))
    service = MeetingMediaService(settings=settings)
    target_zip = tmp_path / "BackupTest.jwlibrary"

    exported = service.export_playlist_items(items, "Playlist Exportada", target_zip)
    assert exported.is_file()

    # Verify zip content
    with zipfile.ZipFile(exported, "r") as zf:
        namelist = zf.namelist()
        assert "userData.db" in namelist
        assert "manifest.json" in namelist

        # Read inner userData.db to verify PlaylistItem and EndAction
        db_bytes = zf.read("userData.db")
        inner_db_path = tmp_path / "exported_userData.db"
        inner_db_path.write_bytes(db_bytes)

        con = sqlite3.connect(inner_db_path)
        cur = con.cursor()
        cur.execute("SELECT Label, EndAction FROM PlaylistItem")
        row = cur.fetchone()
        con.close()

        assert row is not None
        assert row[0] == "Mídia Exportada"
        assert row[1] == 3  # Repetir preserved in export!


def test_meeting_media_dialog_import_playlist_worker(tmp_path: Path) -> None:
    app = _ensure_app()

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    settings = AppSettings(jwl_userdata_db_path=str(db_file))

    dialog = MeetingMediaDialog(settings=settings)

    f1 = tmp_path / "slide_test.jpg"
    f1.write_bytes(b"slide")

    dialog._on_files_dropped([f1])
    assert len(dialog._playlist_items) == 1

    with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
        fake_result = MediaImportResult(success=True, imported_count=1, playlist_name="Discurso Público")
        with patch.object(dialog.service, "import_playlist_items", return_value=fake_result):
            dialog._on_import_local_clicked()
            assert dialog._worker is not None
            dialog._worker.wait(3000)
            app.processEvents()
            assert mock_info.called

    dialog.close()


def test_meeting_media_dialog_load_meeting_worker(tmp_path: Path) -> None:
    app = _ensure_app()

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)
    settings = AppSettings(jwl_userdata_db_path=str(db_file))

    dialog = MeetingMediaDialog(settings=settings)

    f1 = tmp_path / "cantico_14.mp4"
    f1.write_bytes(b"song")
    loaded = [
        MediaImportItem(
            source_path=f1,
            label="Cântico 14",
            duration_seconds=180.0,
            end_action=2,
        )
    ]

    with patch.object(dialog.service, "download_midweek_items", return_value=loaded):
        with patch("PySide6.QtWidgets.QMessageBox.information"):
            dialog._start_worker(
                "load_meeting_for_playlist",
                {
                    "meeting_type": "midweek",
                    "issue": "202611",
                    "include_songs": True,
                    "include_videos": True,
                    "include_images": True,
                    "include_cbs_videos": True,
                },
            )
            assert dialog._worker is not None
            dialog._worker.wait(3000)
            app.processEvents()

    dialog.close()


def test_download_media_item_by_pub_track_registers_media(tmp_path: Path) -> None:
    from meeting_assistant.services.meeting_media_downloader import MediaDownloadItem
    from meeting_assistant.services.meeting_media_service import MeetingMediaService

    fake_video = tmp_path / "mwbv_202611_01.mp4"
    fake_video.write_bytes(b"sample_video_bytes")

    fake_download_item = MediaDownloadItem(
        title="Tesouros da Bíblia",
        url="https://fake.url/video.mp4",
        filesize=len(b"sample_video_bytes"),
        duration_seconds=185.0,
        media_type="video",
        suggested_filename="mwbv_202611_01.mp4",
        pub_symbol="mwbv",
        track_num=1,
        issue_tag=202611,
        docid=0,
    )

    settings = AppSettings(meeting_media_folder=str(tmp_path))
    service = MeetingMediaService(settings=settings)

    with (
        patch(
            "meeting_assistant.services.meeting_media_service.fetch_media_item_by_pub_track",
            return_value=fake_download_item,
        ),
        patch("meeting_assistant.services.meeting_media_service.download_file") as mock_dl,
        patch(
            "meeting_assistant.services.meeting_media_service.register_media_in_jwl_collection"
        ) as mock_register,
    ):
        mock_dl.side_effect = lambda url, dest, **kwargs: dest.write_bytes(b"sample_video_bytes")

        res_item = service.download_media_item_by_pub_track(
            pub="mwbv",
            track=1,
            issue_tag=202611,
        )

        assert res_item is not None
        assert res_item.label == "Tesouros da Bíblia"
        assert res_item.duration_seconds == 185.0
        assert mock_register.called
        call_kwargs = mock_register.call_args.kwargs
        assert call_kwargs["key_symbol"] == "mwbv"
        assert call_kwargs["track"] == 1
        assert call_kwargs["duration"] == 185.0


def test_playlist_drop_directory_with_natural_sorting(tmp_path: Path) -> None:
    _ = _ensure_app()
    dialog = MeetingMediaDialog()

    # Create directory with unsorted slide numbers: slide_1, slide_2, slide_10, slide_3
    slide_dir = tmp_path / "slides_discurso"
    slide_dir.mkdir()
    (slide_dir / "slide_10.jpg").write_bytes(b"img10")
    (slide_dir / "slide_1.jpg").write_bytes(b"img1")
    (slide_dir / "slide_3.jpg").write_bytes(b"img3")
    (slide_dir / "slide_2.jpg").write_bytes(b"img2")

    dialog._on_files_dropped([slide_dir])

    assert len(dialog._playlist_items) == 4
    # Naturally sorted order: 1, 2, 3, 10
    labels = [it.label for it in dialog._playlist_items]
    assert labels == ["slide 1", "slide 2", "slide 3", "slide 10"]

    dialog.close()


def test_playlist_row_widget_button_enabled_states(tmp_path: Path) -> None:
    _ = _ensure_app()
    f1 = tmp_path / "media_1.mp4"
    f1.write_bytes(b"1")
    f2 = tmp_path / "media_2.mp4"
    f2.write_bytes(b"2")
    f3 = tmp_path / "media_3.mp4"
    f3.write_bytes(b"3")

    it1 = MediaImportItem(source_path=f1, label="Item 1")
    it2 = MediaImportItem(source_path=f2, label="Item 2")
    it3 = MediaImportItem(source_path=f3, label="Item 3")

    # Single item
    row_single = PlaylistItemRowWidget(it1, index=0, total_count=1)
    assert row_single.btn_up.isEnabled() is False
    assert row_single.btn_down.isEnabled() is False
    row_single.close()

    # 3 items
    row0 = PlaylistItemRowWidget(it1, index=0, total_count=3)
    assert row0.btn_up.isEnabled() is False
    assert row0.btn_down.isEnabled() is True
    row0.close()

    row1 = PlaylistItemRowWidget(it2, index=1, total_count=3)
    assert row1.btn_up.isEnabled() is True
    assert row1.btn_down.isEnabled() is True
    row1.close()

    row2 = PlaylistItemRowWidget(it3, index=2, total_count=3)
    assert row2.btn_up.isEnabled() is True
    assert row2.btn_down.isEnabled() is False
    row2.close()


def test_render_media_thumbnail_with_thumbnail_path_and_sibling(tmp_path: Path) -> None:
    from meeting_assistant.ui.media_thumbnail_helper import render_media_thumbnail

    video_file = tmp_path / "estudo.mp4"
    video_file.write_bytes(b"video")
    thumb_file = tmp_path / "estudo_capa.jpg"
    thumb_file.write_bytes(b"fake_jpeg")

    # Write a real 10x10 dummy image so QPixmap can load it
    from PySide6.QtGui import QColor, QImage
    img = QImage(20, 20, QImage.Format.Format_RGB32)
    img.fill(QColor(255, 0, 0))
    img.save(str(thumb_file), "JPG")

    item = MediaImportItem(
        source_path=video_file,
        label="Estudo com Miniatura",
        duration_seconds=120.0,
        thumbnail_path=thumb_file,
    )

    pix = render_media_thumbnail(item, width=68, height=46)
    assert not pix.isNull()
    assert pix.width() == 68
    assert pix.height() == 46


def test_load_meeting_dialog_playlist_name_and_auto_update() -> None:
    _ = _ensure_app()
    dlg = LoadMeetingDialog()

    assert dlg.playlist_name_edit.text() == "Reunião de Meio de Semana"

    # Switch to weekend
    dlg.meeting_type_combo.setCurrentIndex(dlg.meeting_type_combo.findData("weekend"))
    assert dlg.playlist_name_edit.text() == "Estudo de A Sentinela"

    # Switch back to midweek
    dlg.meeting_type_combo.setCurrentIndex(dlg.meeting_type_combo.findData("midweek"))
    assert dlg.playlist_name_edit.text() == "Reunião de Meio de Semana"

    # Custom edit is preserved when not default
    dlg.playlist_name_edit.setText("Minha Playlist Especial")
    dlg.meeting_type_combo.setCurrentIndex(dlg.meeting_type_combo.findData("weekend"))
    assert dlg.playlist_name_edit.text() == "Minha Playlist Especial"

    data = dlg.get_data()
    assert data["playlist_name"] == "Minha Playlist Especial"
    dlg.close()


def test_playlist_list_widget_drop_same_row_ignored() -> None:
    _ = _ensure_app()
    widget = PlaylistListWidget()
    widget.addItem("Item 0")
    widget.addItem("Item 1")
    widget.setCurrentRow(0)

    reordered = []
    widget.item_reordered.connect(lambda s, d: reordered.append((s, d)))

    mock_mime = MagicMock()
    mock_mime.hasUrls.return_value = False
    mock_event = MagicMock(spec=QDropEvent)
    mock_event.mimeData.return_value = mock_mime
    mock_event.position.return_value = QPointF(10.0, 10.0)

    with patch.object(widget, "indexAt") as mock_idx:
        m = MagicMock()
        m.isValid.return_value = True
        m.row.return_value = 0  # Dropped onto same row
        mock_idx.return_value = m

        widget.dropEvent(mock_event)

    assert len(reordered) == 0
    mock_event.ignore.assert_called_once()
    widget.close()


def test_import_playlist_items_persists_thumbnail_path(tmp_path: Path) -> None:
    import uuid

    from PySide6.QtGui import QColor, QImage

    from meeting_assistant.services.meeting_media_service import MeetingMediaService

    db_file = tmp_path / "userData.db"
    init_jwl_schema(db_file)

    vid = tmp_path / "video.mp4"
    vid.write_bytes(b"vid_content")
    thumb = tmp_path / "thumb.jpg"
    img = QImage(10, 10, QImage.Format.Format_RGB32)
    img.fill(QColor(0, 255, 0))
    img.save(str(thumb), "JPG")

    item = MediaImportItem(
        source_path=vid,
        label="Vídeo com Capa",
        end_action=0,
        thumbnail_path=thumb,
    )

    settings = AppSettings(jwl_userdata_db_path=str(db_file), meeting_media_folder=str(tmp_path))
    service = MeetingMediaService(settings=settings)

    res = service.import_playlist_items([item], playlist_name="Playlist Miniaturas", clear_existing=True)
    assert res.success is True

    con = sqlite3.connect(db_file)
    cur = con.cursor()
    cur.execute("SELECT Label, EndAction, ThumbnailFilePath FROM PlaylistItem")
    row = cur.fetchone()
    con.close()

    assert row is not None
    assert row[0] == "Vídeo com Capa"
    assert row[1] == 0
    assert row[2] is not None
    assert uuid.UUID(row[2])


def test_edit_playlist_dialog_listing_and_filter() -> None:
    _ = _ensure_app()
    mock_service = MagicMock()
    mock_service.list_existing_playlists.return_value = [
        {"tag_id": 1, "name": "Discurso Público Especial", "item_count": 3},
        {"tag_id": 2, "name": "Estudo de A Sentinela", "item_count": 5},
        {"tag_id": 3, "name": "Cânticos do Salão", "item_count": 2},
    ]

    dlg = EditPlaylistDialog(service=mock_service)
    assert dlg.playlist_list.count() == 3
    assert dlg.load_btn.isEnabled() is True

    # Filter
    dlg.search_edit.setText("Sentinela")
    assert dlg.playlist_list.count() == 1
    assert "Sentinela" in dlg.playlist_list.item(0).text()

    # Filter with no results
    dlg.search_edit.setText("Inexistente")
    assert dlg.playlist_list.count() == 0
    assert dlg.load_btn.isEnabled() is False

    dlg.search_edit.setText("")
    assert dlg.playlist_list.count() == 3
    dlg.close()


def test_edit_playlist_dialog_load_from_db() -> None:
    _ = _ensure_app()
    mock_service = MagicMock()
    mock_service.list_existing_playlists.return_value = [
        {"tag_id": 10, "name": "Playlist de Teste", "item_count": 2},
    ]
    test_items = [
        MediaImportItem(source_path=Path("sample.mp4"), label="Vídeo 1", end_action=1),
        MediaImportItem(source_path=Path("sample.jpg"), label="Slide 2", end_action=2),
    ]
    mock_service.load_playlist_from_db.return_value = ("Playlist de Teste", test_items)

    dlg = EditPlaylistDialog(service=mock_service)
    dlg.playlist_list.setCurrentRow(0)
    dlg._on_accept()

    name, items = dlg.get_selected_playlist()
    assert name == "Playlist de Teste"
    assert len(items) == 2
    assert items[0].label == "Vídeo 1"
    dlg.close()


def test_edit_playlist_dialog_load_from_file(tmp_path: Path) -> None:
    _ = _ensure_app()
    mock_service = MagicMock()
    test_items = [
        MediaImportItem(source_path=tmp_path / "vid.mp4", label="Vídeo Exportado"),
    ]
    mock_service.load_playlist_from_file.return_value = ("Minha Playlist Exportada", test_items)

    dlg = EditPlaylistDialog(service=mock_service)
    pkg = tmp_path / "teste.jwlplaylist"
    pkg.write_bytes(b"PK\x03\x04")

    with patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=(str(pkg), "")):
        dlg._on_open_file_clicked()

    mock_service.load_playlist_from_file.assert_called_once_with(pkg)
    name, items = dlg.get_selected_playlist()
    assert name == "Minha Playlist Exportada"
    assert len(items) == 1
    dlg.close()


def test_meeting_media_dialog_on_edit_playlist_clicked(tmp_path: Path) -> None:
    _ = _ensure_app()
    settings = AppSettings(meeting_media_folder=str(tmp_path))
    dlg = MeetingMediaDialog(settings=settings)

    mock_items = [
        MediaImportItem(source_path=tmp_path / "img1.png", label="Slide A", end_action=0),
        MediaImportItem(source_path=tmp_path / "img2.png", label="Slide B", end_action=1),
    ]

    with patch("meeting_assistant.ui.meeting_media_dialog.EditPlaylistDialog") as MockEditDlg:
        instance = MockEditDlg.return_value
        instance.exec.return_value = 1  # Accepted
        instance.get_selected_playlist.return_value = ("Playlist Carregada", mock_items)

        dlg._on_edit_playlist_clicked()

    assert dlg.local_playlist_edit.text() == "Playlist Carregada"
    assert len(dlg._playlist_items) == 2
    assert dlg._playlist_items[0].label == "Slide A"
    assert dlg.local_files_list.count() == 2
    dlg.close()


def test_meeting_media_dialog_drop_jwlplaylist(tmp_path: Path) -> None:
    _ = _ensure_app()
    settings = AppSettings(meeting_media_folder=str(tmp_path))
    dlg = MeetingMediaDialog(settings=settings)

    pkg = tmp_path / "Pacote.jwlplaylist"
    pkg.write_bytes(b"dummy")

    mock_items = [
        MediaImportItem(source_path=tmp_path / "item1.mp4", label="Cântico 1", end_action=2),
    ]

    with patch.object(
        dlg.service, "load_playlist_from_file", return_value=("Playlist do Pacote", mock_items)
    ):
        dlg._on_files_dropped([pkg])

    assert dlg.local_playlist_edit.text() == "Playlist do Pacote"
    assert len(dlg._playlist_items) == 1
    assert dlg._playlist_items[0].label == "Cântico 1"
    dlg.close()


def test_drop_forwarding_scroll_area(tmp_path: Path) -> None:
    _ = _ensure_app()
    scroll = _DropForwardingScrollArea()

    f = tmp_path / "slide.jpg"
    f.write_bytes(b"test")

    mock_mime = MagicMock()
    mock_mime.hasUrls.return_value = True
    mock_mime.urls.return_value = [QUrl.fromLocalFile(str(f))]

    mock_event = MagicMock(spec=QDropEvent)
    mock_event.mimeData.return_value = mock_mime

    scroll.dragEnterEvent(mock_event)
    assert mock_event.accept.called or mock_event.acceptProposedAction.called

    mock_event.reset_mock()
    scroll.dragMoveEvent(mock_event)
    assert mock_event.accept.called or mock_event.acceptProposedAction.called

    scroll.close()


def test_main_window_drag_and_drop_handling(tmp_path: Path) -> None:
    from meeting_assistant.core.state import AppState
    from meeting_assistant.ui.main_window import MainWindow

    _ = _ensure_app()
    services = [MagicMock() for _ in range(7)]
    services[1].active = False
    services[1].returning = False
    services[2].snapshot.return_value = []
    services[3].snapshot.return_value = []
    services[6].active = False
    services[6].returning = False
    settings = AppSettings()
    win = MainWindow(
        AppState(),
        settings,
        *services,
    )
    win.settings_service = MagicMock()

    f = tmp_path / "video.mp4"
    f.write_bytes(b"vid")

    mock_mime = MagicMock()
    mock_mime.hasUrls.return_value = True
    mock_mime.urls.return_value = [QUrl.fromLocalFile(str(f))]

    mock_event = MagicMock(spec=QDropEvent)
    mock_event.mimeData.return_value = mock_mime

    win.dragEnterEvent(mock_event)
    mock_event.acceptProposedAction.assert_called_once()

    mock_event.reset_mock()
    win.dragMoveEvent(mock_event)
    mock_event.acceptProposedAction.assert_called_once()

    with patch.object(win, "_open_setup_assistant_with_dropped_media") as mock_open:
        win.dropEvent(mock_event)
        mock_open.assert_called_once_with([f])

    win.close()


def test_playlist_item_row_widget_drag_drop_acceptance_and_forwarding(tmp_path: Path) -> None:
    _ = _ensure_app()
    item = MediaImportItem(source_path=tmp_path / "sample.mp4", label="Sample")
    row_widget = PlaylistItemRowWidget(item=item, index=0, total_count=1)

    assert row_widget.acceptDrops() is True
    assert row_widget.label_edit.acceptDrops() is False

    mock_mime = MagicMock()
    mock_mime.hasUrls.return_value = True
    f = tmp_path / "new_video.mp4"
    f.write_bytes(b"content")
    mock_mime.urls.return_value = [QUrl.fromLocalFile(str(f))]

    mock_event = MagicMock(spec=QDropEvent)
    mock_event.mimeData.return_value = mock_mime

    row_widget.dragEnterEvent(mock_event)
    assert mock_event.accept.called or mock_event.acceptProposedAction.called

    mock_event.reset_mock()
    row_widget.dragMoveEvent(mock_event)
    assert mock_event.accept.called or mock_event.acceptProposedAction.called

    # When embedded in PlaylistListWidget, dropping on row forwards to list widget
    list_widget = PlaylistListWidget()
    list_widget.setItemWidget(QListWidgetItem(list_widget), row_widget)
    dropped_paths = []
    list_widget.files_dropped.connect(dropped_paths.extend)

    mock_event.reset_mock()
    row_widget.dropEvent(mock_event)
    assert mock_event.accept.called or mock_event.acceptProposedAction.called
    assert len(dropped_paths) == 1
    assert dropped_paths[0] == f

    row_widget.close()
    list_widget.close()


def test_playlist_item_row_widget_location_subtitles() -> None:
    _ = _ensure_app()
    song_item = MediaImportItem(
        source_path=None,
        label="Cântico 14",
        key_symbol="sjj",
        track=14,
        duration_seconds=125.0,
    )
    row_song = PlaylistItemRowWidget(item=song_item, index=0)
    assert "Cântico 14" in row_song.subtitle_label.text()
    assert "JW.ORG" in row_song.subtitle_label.text()
    row_song.close()

    pub_item = MediaImportItem(
        source_path=None,
        label="Vídeo da Apostila",
        key_symbol="mwbv",
        track=1,
        duration_seconds=90.0,
    )
    row_pub = PlaylistItemRowWidget(item=pub_item, index=1)
    assert "JWL (mwbv)" in row_pub.subtitle_label.text()
    row_pub.close()


def test_edit_playlist_dialog_delete_playlist() -> None:
    _ = _ensure_app()
    mock_service = MagicMock()
    mock_service.list_existing_playlists.return_value = [
        {"tag_id": 1, "name": "Playlist Antiga", "item_count": 2},
    ]
    mock_service.delete_playlist.return_value = True

    dlg = EditPlaylistDialog(service=mock_service)
    assert hasattr(dlg, "delete_btn")
    assert dlg.delete_btn.isEnabled() is True

    with patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
        with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info:
            dlg._on_delete_clicked()
            mock_service.delete_playlist.assert_called_once_with("Playlist Antiga")
            mock_info.assert_called_once()

    dlg.close()


def test_drop_forwarding_scroll_area_routes_to_media_dialog(tmp_path: Path) -> None:
    _ = _ensure_app()
    settings = AppSettings(meeting_media_folder=str(tmp_path))
    dlg = MeetingMediaDialog(settings=settings)
    dlg.tabs.setCurrentIndex(0)  # Start on Download tab

    f = tmp_path / "slide.png"
    f.write_bytes(b"image")

    mock_mime = MagicMock()
    mock_mime.hasUrls.return_value = True
    mock_mime.urls.return_value = [QUrl.fromLocalFile(str(f))]

    mock_event = MagicMock(spec=QDropEvent)
    mock_event.mimeData.return_value = mock_mime

    # Simulate drop on download tab's scroll area
    scroll = dlg.tabs.widget(0)
    assert isinstance(scroll, _DropForwardingScrollArea)

    scroll.dropEvent(mock_event)
    assert mock_event.accept.called or mock_event.acceptProposedAction.called
    assert dlg.tabs.currentIndex() == 1  # Switched to Playlist tab
    assert len(dlg._playlist_items) == 1
    assert dlg._playlist_items[0].label == "slide"

    dlg.close()


