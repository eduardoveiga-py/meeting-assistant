# Empacotamento do Meeting Assistant

## Fluxo atual de desenvolvimento

```powershell
git pull --ff-only
.\scripts\run.ps1
```

O aplicativo roda do codigo Python local. O script prepara o ambiente e baixa
apenas os componentes nativos quando faltarem; `-Refresh` atualiza esse pacote.
Nao e necessario compilar C++ ou criar o executavel do aplicativo para testar.

O workflow **Windows 11 video** compila DLLs e auxiliares da camera, testa a
integridade e prepara a release `native-latest`. Ele nao empacota o app Python.
O workflow **Windows Release** compila e testa o executável e instalador da release
candidata 0.6.0-rc1, incluindo o pacote nativo e Microsoft Visual C++ x64.
Os downloads ficam em https://github.com/eduardoveiga-py/meeting-assistant/releases.
O usuário final não precisa de Python, Git, MSBuild ou Inno Setup.

## Build de mantenedor

As etapas abaixo existem somente para o CI ou para quem estiver alterando o código
C++ da câmera. Elas não são necessárias para o uso diário.

O build completo é feito em um Windows 11 x64 e tem duas partes: o aplicativo
Python/PyInstaller e os componentes nativos da câmera/ponte do OBS.

## Pré-requisitos

- Windows 11 x64.
- Git para Windows, Python 3.12 x64 e CMake 3.24 ou superior.
- Visual Studio Build Tools 2022 com **Desktop development with C++**, MSVC x64/x86,
  Windows SDK e ferramentas CMake.
- NuGet CLI (`nuget.exe`) disponível no `PATH`.
- Inno Setup 6 (`ISCC.exe`).

No instalador do Visual Studio, a carga **Desktop development with C++** fornece o
MSVC/MSBuild usado pelo projeto.

## 1. Preparar o terminal

Abra o **Developer PowerShell for VS 2022** (x64), extraia o projeto para um caminho
curto, como `C:\MeetingAssistant\meeting-assistant`, e confira:

```powershell
cd C:\MeetingAssistant\meeting-assistant
python --version
git --version
cmake --version
msbuild -version
nuget help
```

O Python deve ser 3.12.x. Corrija qualquer comando ausente antes de continuar.

## 2. Compilar a câmera nativa e a ponte do OBS

O script baixa versões fixadas do OBS Studio e do Windows Camera, compila os
componentes, executa CTest e cria um pacote com hashes:

```powershell
Unblock-File -LiteralPath .\scripts\build-video-native.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\build-video-native.ps1
```

Saída esperada: `build\video-native\package\`.

O script rejeita um diretório já usado. Para repetir, use outro diretório:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\build-video-native.ps1 `
  -BuildRoot .\build\video-native-02
```

## 3. Instalar os componentes nativos

Feche OBS, WhatsApp e Meeting Assistant. Abra o PowerShell como administrador e
execute dentro de `build\video-native\package`:

```powershell
cd C:\MeetingAssistant\meeting-assistant\build\video-native\package
Unblock-File -LiteralPath .\install-video-native.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\install-video-native.ps1 -Component All -VerifyOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\install-video-native.ps1 -Component All
```

`-ExecutionPolicy Bypass` vale somente para esse processo; não é necessário alterar
a política global do Windows. Se o OBS estiver em outro diretório, acrescente
`-ObsDirectory 'D:\Apps\obs-studio'`.

## 4. Empacotar o aplicativo Python

```powershell
cd C:\MeetingAssistant\meeting-assistant
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
python -m pip install 'pyinstaller>=6,<7'
python -m pytest -q
python -m PyInstaller --clean --noconfirm .\packaging\MeetingAssistant.spec
```

Saída esperada: `dist\MeetingAssistant\MeetingAssistant.exe`.

Valide o runtime empacotado:

```powershell
$report = Join-Path $PWD 'runtime-check.json'
& .\dist\MeetingAssistant\MeetingAssistant.exe --self-check $report
Get-Content $report
```

Os campos `ok` e `frozen` devem ser `true`.

## 5. Criar o instalador `.exe`

```powershell
New-Item -ItemType Directory -Force .\release | Out-Null
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" .\packaging\MeetingAssistant.iss
```

O instalador será criado em `release\MeetingAssistant-Setup-0.6.0-rc1.exe`.

Para gerar hashes:

```powershell
Remove-Item .\release\SHA256SUMS.txt -ErrorAction SilentlyContinue
Get-ChildItem .\release -File |
  Where-Object Name -ne 'SHA256SUMS.txt' |
  ForEach-Object {
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $($_.Name)" | Out-File .\release\SHA256SUMS.txt -Encoding ascii -Append
  }
```

## 6. Ensaio em máquina limpa

O instalador Python instala o aplicativo, mas os componentes nativos da câmera ainda
são um pacote administrativo separado. Em uma máquina limpa, instale o Meeting
Assistant, execute o pacote nativo com `install-video-native.ps1`, instale
OBS/Zoom/JW Library/VB-CABLE e abra o app.

Teste nesta ordem: OBS WebSocket e cenas; câmera WhatsApp; preview e troca Texto do
Ano/Palco/Mídia; Zoom → Salão → restauração do JW Library; áudio OBS → VB-CABLE →
Zoom/WhatsApp. O primeiro ensaio deve ser fora de uma reunião pública.

## Build automatizado

O workflow `Windows 11 video` compila e testa somente as dependencias nativas,
preparando `MeetingAssistant-Windows11-native.zip` para o downloader do script.
O workflow `Windows Release` permanece reservado para empacotar Python/Inno Setup
na distribuicao final. A publicacao final deve combinar os componentes e revisar
os hashes; ela nao e requisito para executar o codigo Python agora.
