param(
    [ValidateSet('Bridge','Camera','Compat','RemoveCamera','RemoveBridge','RemoveCompat')][string]$Component = 'Bridge',
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
    } elseif ($Component -eq 'Compat') {
        Assert-PackageFile 'meeting-assistant-compat.dll'
        Assert-PackageFile 'meeting-assistant-compat-check.exe'
    } else { throw 'VerifyOnly requires Bridge, Camera or Compat.' }
    Write-Host "Package integrity OK ($Component). No files installed. PowerShell $($PSVersionTable.PSVersion)"
    return
}
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
        Assert-PackageFile 'meeting-assistant-bridge.dll'
        if (Test-Path $target) { Copy-Item $target "$target.backup-$(Get-Date -Format yyyyMMddHHmmss)" }
        Copy-Item $source $target -Force
    }
    Write-Host 'Bridge step complete. Restart OBS and verify in Meeting Assistant.'
    exit
}
if ($Component -in @('Compat','RemoveCompat')) {
    if ([Environment]::OSVersion.Version.Build -lt 19041) { throw 'Compatibility prototype requires Windows 10 2004+ x64.' }
    if (Get-Process WhatsApp,Zoom,obs64 -ErrorAction SilentlyContinue) { throw 'Close WhatsApp, Zoom and OBS before installing/removing the compatibility camera.' }
    $compatRoot = Join-Path $env:ProgramFiles 'MeetingAssistant\CompatCamera'
    $target = Join-Path $compatRoot 'meeting-assistant-compat.dll'
    $regsvr = Join-Path $env:WINDIR 'System32\regsvr32.exe'
    if ($Component -eq 'RemoveCompat') {
        if (-not (Test-Path $target)) { throw 'Installed compatibility DLL not found.' }
        $process = Start-Process -FilePath $regsvr -ArgumentList @('/s','/u',('"' + $target + '"')) -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "Compatibility unregister failed: $($process.ExitCode)" }
        Write-Host 'Compatibility camera unregistered. Files retained until clients release the DLL.'
        exit
    }
    Assert-PackageFile 'meeting-assistant-compat.dll'
    Assert-PackageFile 'meeting-assistant-compat-check.exe'
    New-Item -ItemType Directory -Force $compatRoot | Out-Null
    foreach ($name in @('meeting-assistant-compat.dll','meeting-assistant-compat-check.exe')) {
        $dest = Join-Path $compatRoot $name
        if (Test-Path $dest) { Copy-Item $dest "$dest.backup-$(Get-Date -Format yyyyMMddHHmmss)" }
        Copy-Item (Join-Path $PSScriptRoot $name) $dest -Force
    }
    $process = Start-Process -FilePath $regsvr -ArgumentList @('/s',('"' + $target + '"')) -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Compatibility registration failed: $($process.ExitCode)" }
    & (Join-Path $compatRoot 'meeting-assistant-compat-check.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Compatibility component check failed. Copy the HRESULT above.' }
    Write-Host 'Meeting Assistant Compat installed. Open the experimental camera screen and select Compatibility.'
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
    Assert-PackageFile $name
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
