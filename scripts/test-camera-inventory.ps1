param([Parameter(Mandatory=$true)][string]$Executable)
$ErrorActionPreference = 'Stop'
$output = & $Executable
if ($LASTEXITCODE -ne 0) { throw 'Inventory process failed' }
$report = $output | ConvertFrom-Json
if ($report.diagnostic_revision -ne 1 -or $report.capture_started -ne $false -or $report.process_architecture -ne 'x64') {
    throw 'Invalid inventory schema'
}
foreach ($api in @('directshow', 'media_foundation')) {
    $entry = $report.$api
    if ($entry.ok -isnot [bool] -or $entry.hresult -notmatch '^0x[0-9a-f]{8}$' -or
        $entry.unreadable_names -lt 0 -or $entry.devices -isnot [array]) {
        throw "Invalid inventory entry: $api"
    }
    # Hardware need not be present. An API failure must stay explicit in the report.
    if ($entry.ok -ne ($entry.hresult -match '^0x[0-7]')) { throw "Inconsistent HRESULT: $api" }
    foreach ($name in $entry.devices) {
        if ($name -isnot [string]) { throw "Invalid device name: $api" }
    }
}
Write-Host 'Camera inventory JSON validated; no capture started.'
