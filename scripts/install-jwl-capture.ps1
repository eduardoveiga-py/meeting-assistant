[CmdletBinding()]
param([string]$ObsDirectory = "$env:ProgramFiles\obs-studio", [switch]$VerifyOnly)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$manifestPath = Join-Path $PSScriptRoot 'SHA256SUMS.json'
if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'SHA256SUMS.json missing.' }
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
foreach ($name in @('meeting-assistant-jwl-capture.dll','install-jwl-capture.ps1','BUILD-INFO.json')) {
    $entries = @($manifest | Where-Object { $_.File -eq $name })
    $path = Join-Path $PSScriptRoot $name
    if ($entries.Count -ne 1 -or -not (Test-Path -LiteralPath $path)) { throw "Artifact incomplete: $name" }
    if ($entries[0].Hash -notmatch '^[0-9a-fA-F]{64}$' -or
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $entries[0].Hash) {
        throw "Artifact checksum mismatch: $name"
    }
}
$info = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'BUILD-INFO.json') | ConvertFrom-Json
if ($info.protocol -ne 1 -or $info.build_id -ne 'jwl-hwnd-v1.1' -or $info.source_kind -ne 'meeting_assistant_jwl_capture') {
    throw 'Unsupported JWL capture package.'
}
if ($VerifyOnly) { Write-Host 'JWL capture package integrity OK. No files installed.'; return }
if ([Environment]::OSVersion.Version.Build -lt 22000 -or -not [Environment]::Is64BitProcess) {
    throw 'Windows 11 e PowerShell x64 necessarios.'
}
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Abra PowerShell como administrador para instalar este componente.' }
if (Get-Process obs64 -ErrorAction SilentlyContinue) { throw 'Feche OBS antes de atualizar a DLL JWL. Nenhum processo foi encerrado.' }
$exe = Join-Path $ObsDirectory 'bin\64bit\obs64.exe'
$backend = Join-Path $ObsDirectory 'bin\64bit\libobs-winrt.dll'
if (-not (Test-Path -LiteralPath $exe) -or -not (Test-Path -LiteralPath $backend)) { throw 'OBS x64 com Windows Graphics Capture nao encontrado.' }
$versionInfo = (Get-Item -LiteralPath $exe).VersionInfo
$version = [version]::new($versionInfo.FileMajorPart, $versionInfo.FileMinorPart, $versionInfo.FileBuildPart, $versionInfo.FilePrivatePart)
if ($version -lt [version]'31.0.3') { throw 'Atualize OBS para 31.0.3 ou posterior.' }
$source = Join-Path $PSScriptRoot 'meeting-assistant-jwl-capture.dll'
$target = Join-Path $ObsDirectory 'obs-plugins\64bit\meeting-assistant-jwl-capture.dll'
New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
if (Test-Path -LiteralPath $target) {
    if ((Get-FileHash -LiteralPath $source).Hash -eq (Get-FileHash -LiteralPath $target).Hash) { return }
    Copy-Item -LiteralPath $target -Destination "$target.backup-$(Get-Date -Format yyyyMMddHHmmss)"
}
Copy-Item -LiteralPath $source -Destination $target -Force
if ((Get-FileHash -LiteralPath $target).Hash -ne (Get-FileHash -LiteralPath $source).Hash) { throw 'Installed JWL DLL integrity failed.' }
Write-Host 'Captura JWL instalada. Abra o OBS e prepare Midias nos Ajustes do Meeting Assistant.'
