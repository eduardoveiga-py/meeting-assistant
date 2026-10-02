[CmdletBinding()]
param(
    [switch]$Source, # Compatibility alias: Python is always the default.
    [switch]$Refresh, # Refresh native components only.
    [switch]$SkipNativeInstall,
    [switch]$UpdateDependencies,
    [string]$NativePackageDirectory = '',
    [string]$BundleUrl = $env:MEETING_ASSISTANT_NATIVE_URL,
    [string]$ObsDirectory = "$env:ProgramFiles\obs-studio"
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ([Environment]::OSVersion.Version.Build -lt 22000 -or -not [Environment]::Is64BitProcess) {
    throw 'Use Windows 11 e PowerShell x64.'
}
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'python-environment.ps1')
$python = Ensure-ProjectPython -RepoRoot $repoRoot
$project = Join-Path $repoRoot 'pyproject.toml'
$stampFile = Join-Path $repoRoot '.venv\meeting-assistant-dependencies.sha256'
$dependencyHash = (Get-FileHash -LiteralPath $project -Algorithm SHA256).Hash
Push-Location $repoRoot
try {
    $installedHash = if (Test-Path -LiteralPath $stampFile) { (Get-Content -Raw $stampFile).Trim() } else { '' }
    if ($UpdateDependencies -or $installedHash -ne $dependencyHash) {
        Write-Host 'Atualizando dependencias Python do projeto...' -ForegroundColor Cyan
        & $python -m pip install -e .
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependencias Python.' }
        $dependencyHash | Set-Content -LiteralPath $stampFile -Encoding ascii
    }
    if (-not $SkipNativeInstall) {
        & (Join-Path $PSScriptRoot 'ensure-video-native.ps1') -Refresh:$Refresh `
            -PackageDirectory $NativePackageDirectory -BundleUrl $BundleUrl -ObsDirectory $ObsDirectory
    }
    $previousPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = Join-Path $repoRoot 'src'
    try {
        Write-Host "Executando codigo Python de $repoRoot" -ForegroundColor Green
        & $python -m meeting_assistant.main
        $appExitCode = $LASTEXITCODE
    } finally {
        $env:PYTHONPATH = $previousPythonPath
    }
} finally {
    Pop-Location
}
exit $appExitCode
