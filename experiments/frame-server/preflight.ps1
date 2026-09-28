# Read-only. Does not change boot options, certificates, services or drivers.
$ErrorActionPreference = 'Stop'
$secureBoot = $null
try { $secureBoot = Confirm-SecureBootUEFI -ErrorAction Stop } catch { }
$os = Get-CimInstance Win32_OperatingSystem
$catalog = Join-Path $PSScriptRoot 'SimpleMediaSourceDriver.cat'
$signature = if (Test-Path $catalog) { (Get-AuthenticodeSignature $catalog).Status.ToString() } else { 'Missing' }
@{
    diagnostic = 'frame-server-poc-preflight-v1'
    windows_build = $os.BuildNumber
    architecture = $os.OSArchitecture
    secure_boot = $secureBoot
    catalog_signature = $signature
    installation_performed = $false
    production_ready = $false
} | ConvertTo-Json
