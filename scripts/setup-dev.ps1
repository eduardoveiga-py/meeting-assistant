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
        throw "$Description falhou com código de saída $LASTEXITCODE."
    }
}

function Get-PythonReleaseInfo {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $false)][string[]]$PrefixArguments = @()
    )

    $script = @'
import sys
v = sys.version_info
print(f"{v.major}.{v.minor}.{v.micro}|{v.releaselevel}")
'@

    $output = & $FilePath @PrefixArguments -c $script
    if ($LASTEXITCODE -ne 0) {
        throw "Não foi possível consultar a versão do Python em '$FilePath'."
    }

    $parts = $output.Trim().Split('|')
    if ($parts.Count -ne 2) {
        throw "Resposta inesperada ao consultar a versão do Python: $output"
    }

    return @{
        Version = $parts[0]
        ReleaseLevel = $parts[1]
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Step "Verificando Python 3.12 estável"
$basePython = Get-PythonReleaseInfo -FilePath 'py' -PrefixArguments @('-3.12')
Write-Host "Python $($basePython.Version) ($($basePython.ReleaseLevel))"

if ($basePython.ReleaseLevel -ne 'final') {
    throw (
        "Foi encontrado Python $($basePython.Version) $($basePython.ReleaseLevel). " +
        "Instale uma versão final estável do Python 3.12 x64 antes de continuar."
    )
}

$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$createVenv = -not (Test-Path $venvPython)

if (-not $createVenv) {
    $venvInfo = Get-PythonReleaseInfo -FilePath $venvPython
    if ($venvInfo.ReleaseLevel -ne 'final') {
        Write-Step "Recriando ambiente virtual criado com Python de pré-lançamento"
        Remove-Item '.venv' -Recurse -Force
        $createVenv = $true
    }
}

if ($createVenv) {
    Write-Step "Criando ambiente virtual"
    Invoke-Checked `
        -Description 'Criação do ambiente virtual' `
        -FilePath 'py' `
        -ArgumentList @('-3.12', '-m', 'venv', '.venv')
}

$python = Join-Path $repoRoot '.venv\Scripts\python.exe'

Write-Step "Atualizando pip"
Invoke-Checked `
    -Description 'Atualização do pip' `
    -FilePath $python `
    -ArgumentList @('-m', 'pip', 'install', '--upgrade', 'pip')

Write-Step "Instalando Meeting Assistant e dependências de desenvolvimento"
Invoke-Checked `
    -Description 'Instalação das dependências' `
    -FilePath $python `
    -ArgumentList @('-m', 'pip', 'install', '-e', '.[dev]')

Write-Step "Executando testes"
Invoke-Checked `
    -Description 'Testes automatizados' `
    -FilePath $python `
    -ArgumentList @('-m', 'pytest')

Write-Step "Executando verificação de código"
Invoke-Checked `
    -Description 'Ruff' `
    -FilePath $python `
    -ArgumentList @('-m', 'ruff', 'check', '.')

Write-Host "`nAmbiente pronto e validado." -ForegroundColor Green
Write-Host "Para iniciar: .\scripts\run-dev.ps1"
