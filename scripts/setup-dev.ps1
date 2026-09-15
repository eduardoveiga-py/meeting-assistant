$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Step "Verificando Python 3.12"
try {
    & py -3.12 --version
} catch {
    throw "Python 3.12 não foi encontrado. Instale o Python 3.12 x64 e execute novamente."
}

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    Write-Step "Criando ambiente virtual"
    & py -3.12 -m venv .venv
}

$python = Join-Path $repoRoot '.venv\Scripts\python.exe'

Write-Step "Atualizando pip"
& $python -m pip install --upgrade pip

Write-Step "Instalando Meeting Assistant e dependências de desenvolvimento"
& $python -m pip install -e '.[dev]'

Write-Step "Executando testes"
& $python -m pytest

Write-Step "Executando verificação de código"
& $python -m ruff check .

Write-Host "`nAmbiente pronto." -ForegroundColor Green
Write-Host "Para iniciar: .\scripts\run-dev.ps1"
