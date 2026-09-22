# Empacotamento do Meeting Assistant

O build oficial é feito no Windows pelo GitHub Actions.

## Build local

Requer Python 3.12, dependências do projeto, PyInstaller e Inno Setup 6.

```powershell
python -m pip install .
python -m pip install "pyinstaller>=6,<7"
pyinstaller --clean --noconfirm packaging/MeetingAssistant.spec
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" packaging/MeetingAssistant.iss
```

Saída:

- `dist/MeetingAssistant/` — aplicativo empacotado.
- `release/MeetingAssistant-Setup-<versão>.exe` — instalador.
- `release/SHA256SUMS.txt` — hashes SHA-256.

O workflow `Windows Release` compila no Windows e publica os artefatos no GitHub Release.
