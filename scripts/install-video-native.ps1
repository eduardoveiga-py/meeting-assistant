param(
    [ValidateSet('Bridge','Camera','RemoveCamera','RemoveBridge')][string]$Component = 'Bridge',
    [string]$ObsDirectory = "$env:ProgramFiles\obs-studio"
)
$ErrorActionPreference = 'Stop'
if (-not [Environment]::Is64BitProcess) { throw 'Use PowerShell x64.' }
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Open PowerShell as administrator for this explicit installation step.' }
$cameraRoot = Join-Path $env:ProgramFiles 'MeetingAssistant\VirtualCamera'
$clsid = 'HKLM:\SOFTWARE\Classes\CLSID\{5108191D-9AD8-44F5-B760-7A35D433A427}'
if ($Component -in @('Bridge','RemoveBridge')) {
    if (Get-Process obs64 -ErrorAction SilentlyContinue) { throw 'Close OBS first. No process will be terminated.' }
    $target = Join-Path $ObsDirectory 'obs-plugins\64bit\meeting-assistant-bridge.dll'
    if (-not (Test-Path (Join-Path $ObsDirectory 'bin\64bit\obs64.exe'))) { throw 'OBS x64 path not found.' }
    if ($Component -eq 'RemoveBridge') {
        if (Test-Path $target) { Remove-Item $target }
    } else {
        $source = Join-Path $PSScriptRoot 'meeting-assistant-bridge.dll'
        if (-not (Test-Path $source)) { throw 'Run this script from the compiled artifact folder.' }
        if (Test-Path $target) { Copy-Item $target "$target.backup-$(Get-Date -Format yyyyMMddHHmmss)" }
        Copy-Item $source $target -Force
    }
    Write-Host 'Bridge step complete. Restart OBS and verify in Meeting Assistant.'
    exit
}
if ([Environment]::OSVersion.Version.Build -lt 22000) { throw 'Camera component requires Windows 11 build 22000+.' }
if (Get-Process meeting-assistant-camera -ErrorAction SilentlyContinue) { throw 'Stop the Meeting Assistant camera first.' }
if ($Component -eq 'RemoveCamera') {
    if (Test-Path $clsid) { Remove-Item $clsid -Recurse }
    Write-Host 'Camera class removed. Files retained until applications release the DLL.'
    exit
}
foreach ($name in @('MeetingAssistantMediaSource.dll','meeting-assistant-camera.exe')) {
    if (-not (Test-Path (Join-Path $PSScriptRoot $name))) { throw "Compiled artifact missing: $name" }
}
New-Item -ItemType Directory -Force $cameraRoot | Out-Null
foreach ($name in @('MeetingAssistantMediaSource.dll','meeting-assistant-camera.exe')) {
    $target = Join-Path $cameraRoot $name
    if (Test-Path $target) { Copy-Item $target "$target.backup-$(Get-Date -Format yyyyMMddHHmmss)" }
    Copy-Item (Join-Path $PSScriptRoot $name) $target -Force
}
New-Item -Path "$clsid\InprocServer32" -Force | Out-Null
Set-Item -Path "$clsid\InprocServer32" -Value (Join-Path $cameraRoot 'MeetingAssistantMediaSource.dll')
New-ItemProperty -Path "$clsid\InprocServer32" -Name ThreadingModel -Value Both -PropertyType String -Force | Out-Null
Write-Host 'Camera provider installed. Start the session camera from Meeting Assistant; verify WhatsApp separately.'
