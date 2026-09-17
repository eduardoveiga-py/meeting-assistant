$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Script = Join-Path $PSScriptRoot "test-hall-output.py"

if (-not (Test-Path $Python)) {
    throw "Ambiente virtual não encontrado. Execute .\scripts\setup-dev.ps1 primeiro."
}

& $Python $Script
if ($LASTEXITCODE -ne 0) {
    throw "Teste da Saída do Salão terminou com código $LASTEXITCODE."
}
