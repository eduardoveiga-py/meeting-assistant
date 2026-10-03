if ([Environment]::OSVersion.Version.Build -lt 22000) { throw "Meeting Assistant requires Windows 11 x64." }
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $false)][string[]]$ArgumentList = @()
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$Description falhou com codigo de saida $LASTEXITCODE."
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
. (Join-Path $PSScriptRoot 'python-environment.ps1')
$python = Ensure-ProjectPython -RepoRoot $repoRoot

Write-Step "Atualizando pip"
Invoke-Checked `
    -Description 'Atualizacao do pip' `
    -FilePath $python `
    -ArgumentList @('-m', 'pip', 'install', '--upgrade', 'pip')

Write-Step "Instalando Meeting Assistant e dependencias de desenvolvimento"
Invoke-Checked `
    -Description 'Instalacao das dependencias' `
    -FilePath $python `
    -ArgumentList @('-m', 'pip', 'install', '-e', '.[dev]')

Write-Step "Executando testes"
Invoke-Checked `
    -Description 'Testes automatizados' `
    -FilePath $python `
    -ArgumentList @('-m', 'pytest')

Write-Step "Executando verificacao de codigo"
Invoke-Checked `
    -Description 'Ruff' `
    -FilePath $python `
    -ArgumentList @('-m', 'ruff', 'check', '.')

Write-Host "`nAmbiente pronto e validado." -ForegroundColor Green
Write-Host "Para iniciar: powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1"
