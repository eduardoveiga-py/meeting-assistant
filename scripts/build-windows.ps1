param([switch]$SkipInstaller)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

python -m PyInstaller --clean --noconfirm packaging/MeetingAssistant.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller falhou.' }
$executable = Join-Path $PWD 'dist/MeetingAssistant/MeetingAssistant.exe'
if (-not (Test-Path -LiteralPath $executable)) { throw 'Executável não foi criado.' }

$report = Join-Path $PWD 'dist/smoke-test.json'
if (Test-Path -LiteralPath $report) { Remove-Item -LiteralPath $report }
$env:QT_QPA_PLATFORM = 'offscreen'
$process = Start-Process -FilePath $executable -ArgumentList @('--smoke-test', ('"' + $report + '"')) -WindowStyle Hidden -PassThru
if (-not $process.WaitForExit(60000)) {
    $process.Kill()
    throw 'Smoke test excedeu 60 segundos.'
}
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $report)) { throw 'Smoke test falhou.' }
$result = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
if (-not $result.ok) { throw 'Smoke test não confirmou recursos e dependências.' }
if ($result.review_key -like 'development/*') { throw 'Metadados da versão ausentes.' }

if (-not $SkipInstaller) {
    $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path -LiteralPath $iscc)) { throw 'Inno Setup não foi encontrado.' }
    & $iscc "/DMyAppVersion=$($result.version)" packaging/MeetingAssistant.iss
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup falhou.' }
}
