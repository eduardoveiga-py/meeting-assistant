param([Parameter(Mandatory=$true)][string]$PackageDirectory)
$ErrorActionPreference = 'Stop'
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('ma-jwl-integrity-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $testRoot | Out-Null
try {
    Copy-Item (Join-Path $PackageDirectory '*') $testRoot
    $installer = Join-Path $testRoot 'install-jwl-capture.ps1'
    & $installer -VerifyOnly
    $dll = Join-Path $testRoot 'meeting-assistant-jwl-capture.dll'
    $bytes = [IO.File]::ReadAllBytes($dll)
    [IO.File]::WriteAllBytes($dll, [byte[]](1,2,3))
    $rejected = $false
    try { & $installer -VerifyOnly } catch { $rejected = $_.Exception.Message -like 'Artifact checksum mismatch:*' }
    if (-not $rejected) { throw 'Corrupt JWL binary was accepted.' }
    [IO.File]::WriteAllBytes($dll, $bytes)
    $manifestPath = Join-Path $testRoot 'SHA256SUMS.json'
    $entries = Get-Content -Raw $manifestPath | ConvertFrom-Json
    @($entries) + @($entries[0]) | ConvertTo-Json | Set-Content $manifestPath
    $rejected = $false
    try { & $installer -VerifyOnly } catch { $rejected = $_.Exception.Message -like 'Artifact incomplete:*' }
    if (-not $rejected) { throw 'Duplicate manifest entries were accepted.' }
    Write-Host 'JWL package: corruption and duplicate entries rejected on PowerShell 5.1.'
} finally { Remove-Item -LiteralPath $testRoot -Recurse -Force }
