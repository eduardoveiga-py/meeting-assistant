param(
    [ValidateSet('All','Bridge','Camera','RemoveCamera','RemoveBridge','RemoveLegacy')][string]$Component = 'All',
    [string]$ObsDirectory = "$env:ProgramFiles\obs-studio",
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
function Assert-PackageFile([string]$Name) {
    $manifestPath = Join-Path $PSScriptRoot 'SHA256SUMS.json'
    if (-not (Test-Path $manifestPath)) { throw 'SHA256SUMS.json missing. Extract the complete artifact.' }
    # Windows PowerShell 5.1 emits the JSON array as one pipeline object.
    # Store it first so the next pipeline enumerates each manifest entry.
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    $entries = @($manifest | Where-Object { $_.File -eq $Name })
    $source = Join-Path $PSScriptRoot $Name
    if ($entries.Count -ne 1 -or -not (Test-Path $source)) { throw "Artifact incomplete: $Name" }
    $expected = $entries[0].Hash
    if ($expected -isnot [string] -or $expected -notmatch '^[0-9a-fA-F]{64}$') {
        throw "Invalid SHA256 manifest entry: $Name"
    }
    $actual = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    if ($actual -ne $expected) {
        throw "Artifact checksum mismatch: $Name. Expected: $expected. Actual: $actual. Download and extract again."
    }
}
if ($VerifyOnly) {
    if ($Component -eq 'Bridge') { Assert-PackageFile 'meeting-assistant-bridge.dll' }
    elseif ($Component -eq 'Camera') {
        Assert-PackageFile 'MeetingAssistantMediaSource.dll'
        Assert-PackageFile 'meeting-assistant-camera.exe'
    } elseif ($Component -eq 'All') {
        Assert-PackageFile 'meeting-assistant-bridge.dll'
        Assert-PackageFile 'MeetingAssistantMediaSource.dll'
        Assert-PackageFile 'meeting-assistant-camera.exe'
    } else { throw 'VerifyOnly requires All, Bridge or Camera.' }
    Write-Host "Package integrity OK ($Component). No files installed. PowerShell $($PSVersionTable.PSVersion)"
    return
}
if ([Environment]::OSVersion.Version.Build -lt 22000) { throw 'Meeting Assistant requires Windows 11 build 22000+.' }
if (-not [Environment]::Is64BitProcess) { throw 'Use PowerShell x64.' }
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Open PowerShell as administrator for this explicit installation step.' }
if ($Component -eq 'All') {
    & $PSCommandPath -Component All -VerifyOnly
    if (Get-Process obs64,WhatsApp,meeting-assistant-camera -ErrorAction SilentlyContinue) { throw 'Close OBS, WhatsApp and Meeting Assistant first.' }
    & $PSCommandPath -Component Bridge -ObsDirectory $ObsDirectory
    & $PSCommandPath -Component Camera
    return
}
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
        Assert-PackageFile 'meeting-assistant-bridge.dll'
        if (Test-Path $target) { Copy-Item $target "$target.backup-$(Get-Date -Format yyyyMMddHHmmss)" }
        Copy-Item $source $target -Force
    }
    Write-Host 'Bridge step complete. Restart OBS and verify in Meeting Assistant.'
    return
}
if ($Component -eq 'RemoveLegacy') {
    if (Get-Process WhatsApp,Zoom,obs64 -ErrorAction SilentlyContinue) { throw 'Close WhatsApp, Zoom and OBS first.' }
    $target = Join-Path $env:ProgramFiles 'MeetingAssistant\CompatCamera\meeting-assistant-compat.dll'
    if (Test-Path $target) {
        $process = Start-Process -FilePath "$env:WINDIR\System32\regsvr32.exe" -ArgumentList @('/s','/u',('"' + $target + '"')) -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "Legacy unregister failed: $($process.ExitCode)" }
    }
    Write-Host 'Legacy Meeting Assistant Compat unregistered if installed. No other cameras changed.'
    return
}
if ([Environment]::OSVersion.Version.Build -lt 22000) { throw 'Camera component requires Windows 11 build 22000+.' }
if (Get-Process meeting-assistant-camera -ErrorAction SilentlyContinue) { throw 'Stop the Meeting Assistant camera first.' }
if ($Component -eq 'RemoveCamera') {
    if (Test-Path $clsid) { Remove-Item $clsid -Recurse }
    Write-Host 'Camera class removed. Files retained until applications release the DLL.'
    return
}
foreach ($name in @('MeetingAssistantMediaSource.dll','meeting-assistant-camera.exe','meeting-assistant-source-probe.exe','meeting-assistant-camera-inventory.exe')) {
    Assert-PackageFile $name
}
& (Join-Path $PSScriptRoot 'meeting-assistant-source-probe.exe') (Join-Path $PSScriptRoot 'MeetingAssistantMediaSource.dll')
if ($LASTEXITCODE -ne 0) { throw 'Media source activation failed. Copy the HRESULT above.' }
New-Item -ItemType Directory -Force $cameraRoot | Out-Null
$sourceDll = Join-Path $PSScriptRoot 'MeetingAssistantMediaSource.dll'
$sourceHash = (Get-FileHash -LiteralPath $sourceDll -Algorithm SHA256).Hash.ToLowerInvariant()
# A client such as WhatsApp or the Windows camera broker may keep the previous
# COM DLL mapped even after the visible app has closed. Install each build under
# its content hash so an in-use previous version never blocks an update.
$versionedDll = Join-Path $cameraRoot "MeetingAssistantMediaSource.$($sourceHash.Substring(0,16)).dll"
if (Test-Path $versionedDll) {
    $installedHash = (Get-FileHash -LiteralPath $versionedDll -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($installedHash -ne $sourceHash) { throw "Installed camera DLL hash mismatch: $versionedDll" }
} else {
    Copy-Item $sourceDll $versionedDll -Force
}
foreach ($name in @('meeting-assistant-camera.exe','meeting-assistant-source-probe.exe','meeting-assistant-camera-inventory.exe')) {
    $target = Join-Path $cameraRoot $name
    if (Test-Path $target) { Copy-Item $target "$target.backup-$(Get-Date -Format yyyyMMddHHmmss)" }
    Copy-Item (Join-Path $PSScriptRoot $name) $target -Force
}
New-Item -Path "$clsid\InprocServer32" -Force | Out-Null
Set-Item -Path "$clsid\InprocServer32" -Value $versionedDll
New-ItemProperty -Path "$clsid\InprocServer32" -Name ThreadingModel -Value Both -PropertyType String -Force | Out-Null
Write-Host "Camera provider installed ($($versionedDll | Split-Path -Leaf)). Start the session camera from Meeting Assistant; verify WhatsApp separately."
