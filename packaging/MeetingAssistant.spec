from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("meeting_assistant.resources")

a = Analysis(
    ["src/meeting_assistant/main.py"],
    pathex=["src"],
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
    upx=True,
    console=False,
    argv_emulation=False,
    target_arch=None,
)

coll = COLLECT(
    exe, a.binaries, a.datas, strip=False, upx=False, name="MeetingAssistant"
)
