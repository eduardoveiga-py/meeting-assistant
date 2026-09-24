from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent
datas = collect_data_files("meeting_assistant.resources") + copy_metadata("meeting-assistant")

a = Analysis(
    [str(root / "src/meeting_assistant/bootstrap.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=["comtypes", "comtypes.client", "pythoncom", "pywintypes"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MeetingAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MeetingAssistant")
