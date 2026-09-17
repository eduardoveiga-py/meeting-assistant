$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$testScript = Join-Path $repoRoot 'scripts\test-jwl-window-capture.py'

if (-not (Test-Path $python)) {
    throw "Ambiente virtual nao encontrado. Execute primeiro: .\scripts\setup-dev.ps1"
}

Set-Location $repoRoot
& $python $testScript
