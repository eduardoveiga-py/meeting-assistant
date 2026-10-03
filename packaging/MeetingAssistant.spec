from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent
datas = collect_data_files("meeting_assistant.resources") + copy_metadata("meeting-assistant")

a = Analysis(
    [str(root / "src/meeting_assistant/bootstrap.py")],
    pathex=[str(root / "src")],
datas = collect_data_files("meeting_assistant.resources") + copy_metadata("meeting-assistant")
source = Path(SPECPATH).resolve().parent / "src"

a = Analysis(
    [str(source / "meeting_assistant/main.py")],
    pathex=[str(source)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "comtypes",
        "comtypes.client",
        "pythoncom",
        "pywintypes",
        # windows_audio imports pycaw lazily so non-Windows development stays
        # importable; keep the Windows package explicit in frozen builds.
        "pycaw",
        "pycaw.pycaw",
    ],
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
coll = COLLECT(
    exe, a.binaries, a.datas, strip=False, upx=False, name="MeetingAssistant"
)
