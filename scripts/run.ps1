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
if (-not $PSBoundParameters.ContainsKey('ObsDirectory')) {
    # Use the OBS installation already configured in the app. Do not print the
    # settings object: it can contain WebSocket/camera credentials.
    $settingsPath = Join-Path $env:APPDATA 'MeetingAssistant\settings.json'
    if (Test-Path -LiteralPath $settingsPath) {
        try {
            $saved = Get-Content -Raw -Encoding UTF8 -LiteralPath $settingsPath | ConvertFrom-Json
            if ($saved.PSObject.Properties['obs_executable']) {
                $configuredObs = [string]$saved.obs_executable
                $configuredObs = $configuredObs.Trim().Trim('"')
                if (-not [string]::IsNullOrWhiteSpace($configuredObs) -and
                    (Split-Path $configuredObs -Leaf) -eq 'obs64.exe' -and
                    (Test-Path -LiteralPath $configuredObs)) {
                    $ObsDirectory = Split-Path (Split-Path (Split-Path $configuredObs -Parent) -Parent) -Parent
                }
            }
        } catch { Write-Warning 'Nao foi possivel ler o caminho OBS salvo; usando o caminho padrao.' }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $ObsDirectory 'bin\64bit\obs64.exe'))) {
        $userObs = Join-Path $env:LOCALAPPDATA 'Programs\obs-studio'
        if (Test-Path -LiteralPath (Join-Path $userObs 'bin\64bit\obs64.exe')) { $ObsDirectory = $userObs }
    }
}
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
        & (Join-Path $PSScriptRoot 'ensure-jwl-capture.ps1') -ObsDirectory $ObsDirectory
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
