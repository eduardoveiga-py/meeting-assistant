param([string]$BuildRoot = "$PSScriptRoot\..\build\jwl-capture")
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$BuildRoot = [IO.Path]::GetFullPath($BuildRoot)
function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "$Exe failed ($LASTEXITCODE)." }
}
New-Item -ItemType Directory -Force $BuildRoot | Out-Null
$obs = Join-Path $BuildRoot 'obs-headers'
if (Test-Path $obs) { throw 'Use a clean BuildRoot.' }
$revision = 'fcd1910bf5116b69404a6ecdda6efedd1d00ebdf' # OBS 31.0.3
Invoke-Checked git @('init', $obs)
Invoke-Checked git @('-C', $obs, 'remote', 'add', 'origin', 'https://github.com/obsproject/obs-studio.git')
Invoke-Checked git @('-C', $obs, 'fetch', '--depth', '1', 'origin', $revision)
Invoke-Checked git @('-C', $obs, 'checkout', '--detach', 'FETCH_HEAD')
$actual = & git -C $obs rev-parse HEAD
if ($actual.Trim() -ne $revision) { throw 'OBS headers revision mismatch.' }
$build = Join-Path $BuildRoot 'cmake'
Invoke-Checked cmake @('-S', (Join-Path $repoRoot 'native\jwl-capture'), '-B', $build, '-A', 'x64', "-DOBS_HEADERS=$obs")
Invoke-Checked cmake @('--build', $build, '--config', 'Release')
Invoke-Checked ctest @('--test-dir', $build, '-C', 'Release', '--output-on-failure')
$package = Join-Path $BuildRoot 'package'
New-Item -ItemType Directory -Force $package | Out-Null
Copy-Item (Join-Path $build 'Release\meeting-assistant-jwl-capture.dll') $package
Copy-Item (Join-Path $repoRoot 'scripts\install-jwl-capture.ps1') $package
Copy-Item (Join-Path $repoRoot 'docs\jwl-hwnd-capture.md') $package
Copy-Item (Join-Path $obs 'COPYING') (Join-Path $package 'LICENSE-OBS.txt')
$sourceRevision = (& git -C $repoRoot rev-parse HEAD).Trim()
@{ protocol = 1; build_id = 'jwl-hwnd-v1.1'; source_revision = $sourceRevision; obs_headers_revision = $revision;
    source_kind = 'meeting_assistant_jwl_capture'; windows_min_build = 22000; obs_min_version = '31.0.3';
    physical_validation = 'pending' } | ConvertTo-Json | Set-Content (Join-Path $package 'BUILD-INFO.json') -Encoding utf8
Get-ChildItem $package -File | Get-FileHash -Algorithm SHA256 |
    Select-Object Hash,@{Name='File';Expression={Split-Path $_.Path -Leaf}} |
    ConvertTo-Json | Set-Content (Join-Path $package 'SHA256SUMS.json') -Encoding utf8
Invoke-Checked powershell.exe @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $package 'install-jwl-capture.ps1'), '-VerifyOnly')
Invoke-Checked powershell.exe @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $repoRoot 'scripts\test-jwl-package.ps1'), '-PackageDirectory', $package)
Write-Host "JWL capture package: $package"
