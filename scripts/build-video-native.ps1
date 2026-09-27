param([string]$BuildRoot = "$PSScriptRoot\..\build\video-native")
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$BuildRoot = [IO.Path]::GetFullPath($BuildRoot)
New-Item -ItemType Directory -Force $BuildRoot | Out-Null
function Run-Native([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "$Exe failed ($LASTEXITCODE)" }
}
function Get-PinnedSource([string]$Name, [string]$Url, [string]$Commit) {
    $dest = Join-Path $BuildRoot $Name
    if (Test-Path $dest) { throw "Build source exists: $dest. Use a new BuildRoot for a clean reproducible build." }
    Run-Native git @('init', $dest)
    Run-Native git @('-C', $dest, 'remote', 'add', 'origin', $Url)
    Run-Native git @('-C', $dest, 'fetch', '--depth', '1', 'origin', $Commit)
    Run-Native git @('-C', $dest, 'checkout', '--detach', 'FETCH_HEAD')
    $actual = & git -C $dest rev-parse HEAD
    if ($actual.Trim() -ne $Commit) { throw 'Source revision mismatch' }
    return $dest
}
$obs = Get-PinnedSource 'obs' 'https://github.com/obsproject/obs-studio.git' 'fcd1910bf5116b69404a6ecdda6efedd1d00ebdf'
$ms = Get-PinnedSource 'camera' 'https://github.com/microsoft/Windows-Camera.git' '626f8b19c5f367602f2e89c6b314573d3776c9df'
$native = Join-Path $repo 'native\virtual-camera'
$cmakeBuild = Join-Path $BuildRoot 'cmake'
Run-Native cmake @('-S', $native, '-B', $cmakeBuild, '-A', 'x64', "-DOBS_HEADERS=$obs")
Run-Native cmake @('--build', $cmakeBuild, '--config', 'Release')
Run-Native ctest @('--test-dir', $cmakeBuild, '-C', 'Release', '--output-on-failure')
Run-Native python @((Join-Path $repo 'scripts\prepare-camera-source.py'), $ms, $native)
$sample = Join-Path $ms 'Samples\VirtualCamera'
$project = Join-Path $sample 'VirtualCameraMediaSource\VirtualCameraMediaSource.vcxproj'
Run-Native nuget @('restore', (Join-Path $sample 'VirtualCameraMediaSource\packages.config'), '-PackagesDirectory', (Join-Path $sample 'packages'), '-NonInteractive')
Run-Native msbuild @($project, '/m', '/p:Configuration=Release', '/p:Platform=x64', "/p:SolutionDir=$sample\", '/p:WindowsTargetPlatformVersion=10.0', '/p:TargetName=MeetingAssistantMediaSource', "/p:OutDir=$BuildRoot\provider\")
$out = Join-Path $BuildRoot 'package'
New-Item -ItemType Directory -Force $out | Out-Null
Copy-Item (Join-Path $cmakeBuild 'Release\meeting-assistant-bridge.dll') $out
Copy-Item (Join-Path $cmakeBuild 'Release\meeting-assistant-camera.exe') $out
Copy-Item (Join-Path $BuildRoot 'provider\MeetingAssistantMediaSource.dll') $out
Copy-Item (Join-Path $ms 'LICENSE') (Join-Path $out 'LICENSE-Microsoft.txt')
Copy-Item (Join-Path $obs 'COPYING') (Join-Path $out 'LICENSE-OBS.txt')
Copy-Item (Join-Path $repo 'scripts\install-video-native.ps1') $out
Copy-Item (Join-Path $repo 'docs\test-virtual-camera.md') $out
$revision = & git -C $repo rev-parse HEAD
@{ revision = $revision.Trim(); protocol = 1; video_revision = 2; target_fps = 30; width = 1280; height = 720 } | ConvertTo-Json | Set-Content (Join-Path $out 'BUILD-INFO.json')
Get-ChildItem $out -File | Get-FileHash -Algorithm SHA256 | Select-Object Hash,@{Name='File';Expression={Split-Path $_.Path -Leaf}} | ConvertTo-Json | Set-Content (Join-Path $out 'SHA256SUMS.json')
Write-Host "Test package: $out"
