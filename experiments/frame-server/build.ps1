$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$build = Join-Path $repo 'build\frame-server'
$source = Join-Path $build 'upstream'
$revision = 'f17f4ea91d6c3eafd26d950d40f1df462e0e0844'
function Run([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "$Exe failed ($LASTEXITCODE)" }
}
if (Test-Path $build) { throw 'Use a clean build/frame-server directory.' }
New-Item -ItemType Directory -Force $build | Out-Null
Run git @('init', $source)
Run git @('-C', $source, 'remote', 'add', 'origin', 'https://github.com/microsoft/Windows-driver-samples.git')
Run git @('-C', $source, 'fetch', '--depth', '1', 'origin', $revision)
Run git @('-C', $source, 'checkout', '--detach', 'FETCH_HEAD')
Run git @('-C', $source, 'submodule', 'update', '--init', '--depth', '1', 'wil')
Run python @((Join-Path $PSScriptRoot 'prepare.py'), $source)
Run nuget @('install', 'Microsoft.Windows.WDK.x64', '-Version', '10.0.26100.2454', '-OutputDirectory', (Join-Path $source 'packages'), '-NonInteractive', '-Source', 'https://api.nuget.org/v3/index.json')
$sample = Join-Path $source 'general\SimpleMediaSource'
Run msbuild @((Join-Path $sample 'SimpleMediaSource.sln'), '/m', '/p:Configuration=Release', '/p:Platform=x64', '/p:SignMode=Off', '/p:DriverTargetPlatform=Desktop', '/p:UMDF_VERSION_MAJOR=2', '/p:UMDF_VERSION_MINOR=31', '/p:Driver_SpectreMitigation=false', '/p:SpectreMitigation=false', '/p:Inf2CatUseLocalTime=true', '/p:Inf2CatWindowsVersionList=10_VB_X64')
$out = Join-Path $build 'package'
New-Item -ItemType Directory -Force $out | Out-Null
foreach ($name in @('SimpleMediaSource.dll','SimpleMediaSourceDriver.dll','SimpleMediaSourceDriver.inf','SimpleMediaSourceDriver.cat')) {
    $file = Get-ChildItem $sample -Recurse -File -Filter $name | Where-Object { $_.FullName -match '\\x64\\Release\\SimpleMediaSourceDriver\\' } | Select-Object -First 1
    if (-not $file) { throw "Missing driver package file: $name" }
    Copy-Item $file.FullName $out
}
$probeBuild = Join-Path $build 'probe'
Run cmake @('-S', $PSScriptRoot, '-B', $probeBuild, '-A', 'x64')
Run cmake @('--build', $probeBuild, '--config', 'Release')
Copy-Item (Join-Path $probeBuild 'Release\meeting-assistant-source-probe.exe') $out
Run (Join-Path $out 'meeting-assistant-source-probe.exe') @((Join-Path $out 'SimpleMediaSource.dll'))
Copy-Item (Join-Path $source 'LICENSE') (Join-Path $out 'LICENSE-Microsoft.txt')
Copy-Item (Join-Path $PSScriptRoot 'README.md') $out
Copy-Item (Join-Path $PSScriptRoot 'preflight.ps1') $out
@{ upstream = $revision; hardware_id = 'root\MeetingAssistantFrameServerPoC'; name = 'Meeting Assistant Camera PoC'; signed_for_distribution = $false; live_tested = $false; windows10_target_build = 19041 } | ConvertTo-Json | Set-Content (Join-Path $out 'BUILD-INFO.json')
Get-ChildItem $out -File | Get-FileHash -Algorithm SHA256 | Select-Object Hash,@{Name='File';Expression={Split-Path $_.Path -Leaf}} | ConvertTo-Json | Set-Content (Join-Path $out 'SHA256SUMS.json')
Write-Host 'UNSIGNED research package compiled. Not a production installer. No driver installed.'
