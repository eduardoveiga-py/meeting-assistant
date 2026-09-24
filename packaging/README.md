# Empacotamento do Meeting Assistant

O build oficial é feito no Windows pelo GitHub Actions.

## Build local

Requer Python 3.12, dependências do projeto, PyInstaller e Inno Setup 6.

```powershell
python -m pip install ".[dev]"
python -m pip install "pyinstaller==6.16.0"
ruff check .
pytest
./scripts/build-windows.ps1
```

Saída:

- `dist/MeetingAssistant/` — aplicativo empacotado.
- `release/MeetingAssistant-Setup-<versão>.exe` — instalador.
- `dist/smoke-test.json` — resultado do teste do executável.
- `release/SHA256SUMS.txt` — hashes SHA-256 gerados pelo workflow de release.

O workflow `Windows Release` compila no Windows e publica os artefatos no GitHub Release.

O CI também gera instalador e executa o smoke test a cada PR. O teste carrega Qt,
recursos SVG e metadados de versão, mas não inicia OBS, Zoom, guardiões ou telemetria.
Ele não substitui o ensaio físico. Para compilar só o aplicativo, use
`./scripts/build-windows.ps1 -SkipInstaller`.

O pacote usa distribuição em pasta (`COLLECT`) e a versão do instalador vem dos
metadados do projeto. Na release, a tag deve ser `v<versão do pyproject.toml>`.
Não reutilize a tag `v0.5.0`: uma nova publicação exige nova versão/tag.
