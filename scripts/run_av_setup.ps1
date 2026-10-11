[CmdletBinding()]
param(
    [switch]$Elevated,
    [switch]$Diagnose,
    [switch]$ApplyOS,
    [switch]$Json,
    [switch]$Gui,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$ExtraArgs
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([Environment]::OSVersion.Version.Build -lt 22000 -or -not [Environment]::Is64BitProcess) {
    throw 'Use Windows 11 e PowerShell x64.'
}

# Elevation handler
if ($Elevated) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
        if ($Diagnose) { $argList += '-Diagnose' }
        if ($ApplyOS) { $argList += '-ApplyOS' }
        if ($Json) { $argList += '-Json' }
        if ($Gui) { $argList += '-Gui' }
        if ($ExtraArgs) { $argList += $ExtraArgs }

        $proc = Start-Process powershell.exe -ArgumentList ($argList -join ' ') -Verb RunAs -PassThru -Wait
        exit $proc.ExitCode
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'python-environment.ps1')
$python = Ensure-ProjectPython -RepoRoot $repoRoot

$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $repoRoot 'src'

try {
    $scriptArgs = @()
    if ($Diagnose) { $scriptArgs += '--diagnose' }
    if ($ApplyOS) { $scriptArgs += '--apply-os' }
    if ($Json) { $scriptArgs += '--json' }
    if ($Gui) { $scriptArgs += '--gui' }
    if ($ExtraArgs) { $scriptArgs += $ExtraArgs }

    $targetScript = Join-Path $PSScriptRoot 'av_setup_tool.py'
    & $python $targetScript @scriptArgs
    $appExitCode = $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

exit $appExitCode
