param([Parameter(Mandatory=$true)][string]$PackageDirectory)
$ErrorActionPreference = 'Stop'
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('ma-video-integrity-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $testRoot | Out-Null
function Expect-Rejection([string]$Pattern) {
    $message = ''
    try { & (Join-Path $testRoot 'install-video-native.ps1') -Component Bridge -VerifyOnly }
    catch { $message = $_.Exception.Message }
    if ($message -notlike $Pattern) { throw "Expected $Pattern; received: $message" }
}
try {
    Copy-Item (Join-Path $PackageDirectory '*') $testRoot
    $installer = Join-Path $testRoot 'install-video-native.ps1'
    $manifestPath = Join-Path $testRoot 'SHA256SUMS.json'
    $originalManifest = Get-Content -Raw $manifestPath
    $manifest = $originalManifest | ConvertFrom-Json
    $bridge = Join-Path $testRoot 'meeting-assistant-bridge.dll'
    # Reproduce the previous false negative on Windows PowerShell 5.1.
    $oldEntries = @($originalManifest | ConvertFrom-Json | Where-Object { $_.File -eq 'meeting-assistant-bridge.dll' })
    $oldMatches = (Get-FileHash $bridge -Algorithm SHA256).Hash -eq $oldEntries[0].Hash
    if ($PSVersionTable.PSVersion.Major -eq 5 -and $oldMatches) { throw 'Legacy bug was not reproduced.' }
    Write-Host "Legacy comparison matches on this shell: $oldMatches"
    & $installer -Component Bridge -VerifyOnly
    & $installer -Component Camera -VerifyOnly
    $originalBytes = [IO.File]::ReadAllBytes($bridge)
    [IO.File]::WriteAllBytes($bridge, [byte[]](1,2,3))
    Expect-Rejection 'Artifact checksum mismatch:*'
    [IO.File]::WriteAllBytes($bridge, $originalBytes)
    $entry = @($manifest | Where-Object { $_.File -eq 'meeting-assistant-bridge.dll' })[0]
    @($manifest) + @($entry) | ConvertTo-Json | Set-Content $manifestPath
    Expect-Rejection 'Artifact incomplete:*'
    $originalManifest | Set-Content $manifestPath
    Remove-Item $bridge
    Expect-Rejection 'Artifact incomplete:*'
    [IO.File]::WriteAllBytes($bridge, $originalBytes)
    Remove-Item $manifestPath
    Expect-Rejection 'SHA256SUMS.json missing*'
    Write-Host "Integrity tests passed on PowerShell $($PSVersionTable.PSVersion): valid package, corruption, duplicates, missing file/manifest."
} finally {
    Remove-Item -LiteralPath $testRoot -Recurse -Force
}
