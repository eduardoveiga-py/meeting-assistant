$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [Console]::OutputEncoding
} catch {
    # A codificação não é crítica para o funcionamento do setup.
}

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

    # Evitamos `python -c` aqui porque o Windows PowerShell 5.1 pode alterar
    # aspas internas ao encaminhar argumentos para executáveis nativos.
    $rawOutput = & $FilePath @PrefixArguments --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Não foi possível consultar a versão do Python em '$FilePath'."
    }

    $output = (($rawOutput | Out-String).Trim())
    $pattern = '^Python\s+(?<version>\d+\.\d+\.\d+)(?<pre>a\d+|b\d+|rc\d+)?(?:\s.*)?$'
    $match = [regex]::Match($output, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)

    if (-not $match.Success) {
        throw "Resposta inesperada ao consultar a versão do Python: $output"
    }

    $releaseLevel = 'final'
    $pre = $match.Groups['pre'].Value.ToLowerInvariant()
    if ($pre.StartsWith('rc')) {
        $releaseLevel = 'candidate'
    } elseif ($pre.StartsWith('b')) {
        $releaseLevel = 'beta'
    } elseif ($pre.StartsWith('a')) {
        $releaseLevel = 'alpha'
    }

    return @{
        Version = $match.Groups['version'].Value
        ReleaseLevel = $releaseLevel
        Raw = $output
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Step "Verificando Python 3.12 estável"
$basePython = Get-PythonReleaseInfo -FilePath 'py' -PrefixArguments @('-3.12')
Write-Host "$($basePython.Raw) [$($basePython.ReleaseLevel)]"

if ($basePython.ReleaseLevel -ne 'final') {
    throw (
        "Foi encontrado $($basePython.Raw), uma versão de pré-lançamento. " +
        "Instale uma versão final estável do Python 3.12 x64 antes de continuar. " +
        "Use 'py -0p' para listar as instalações registradas."
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
