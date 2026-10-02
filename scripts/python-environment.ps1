# Shared by operator startup and developer setup. No application imports.
function Get-ProjectPythonInfo {
    param([string]$Executable, [string]$Probe, [string[]]$PrefixArguments = @())
    $raw = & $Executable @PrefixArguments $Probe
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao consultar o interpretador Python.' }
    return (($raw | Out-String) | ConvertFrom-Json)
}

function Ensure-ProjectPython {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    $venvRoot = Join-Path $RepoRoot '.venv'
    $python = Join-Path $venvRoot 'Scripts\python.exe'
    $probe = Join-Path $RepoRoot 'scripts\python-runtime-check.py'
    $existingInfo = $null
    if (Test-Path -LiteralPath $python) {
        try { $existingInfo = Get-ProjectPythonInfo -Executable $python -Probe $probe }
        catch { Write-Host 'O ambiente existente nao pode ser executado; ele sera preservado.' -ForegroundColor Yellow }
    }
    if ($null -ne $existingInfo -and $existingInfo.compatible) {
        Write-Host "Python $($existingInfo.version) x$($existingInfo.bits) confirmado." -ForegroundColor Green
        return $python
    }
    # Confirm a working 3.12 x64 installation before changing the old environment.
    try {
        $baseInfo = Get-ProjectPythonInfo -Executable 'py' -PrefixArguments @('-3.12') -Probe $probe
    } catch {
        throw 'Python 3.12 x64 nao encontrado. Instale essa versao e execute novamente. Confira as instalacoes com: py -0p. O ambiente existente foi mantido.'
    }
    if (-not $baseInfo.compatible) {
        throw "Necessario Python 3.12 estavel x64; encontrado $($baseInfo.version) x$($baseInfo.bits) $($baseInfo.releaselevel). O ambiente existente foi mantido."
    }
    if (Test-Path -LiteralPath $venvRoot) {
        $backupName = '.venv-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
        $backupPath = Join-Path $RepoRoot $backupName
        if ($null -ne $existingInfo) {
            Write-Host "Ambiente incompativel: Python $($existingInfo.version) x$($existingInfo.bits)." -ForegroundColor Yellow
        }
        Move-Item -LiteralPath $venvRoot -Destination $backupPath
        Write-Host "Ambiente anterior preservado em: $backupPath" -ForegroundColor Yellow
    }
    Write-Host 'Criando .venv com Python 3.12 x64...' -ForegroundColor Cyan
    & py -3.12 -m venv $venvRoot | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar .venv. O ambiente anterior, se existente, permanece no backup.' }
    $createdInfo = Get-ProjectPythonInfo -Executable $python -Probe $probe
    if (-not $createdInfo.compatible) { throw 'O novo ambiente nao confirmou Python 3.12 estavel x64.' }
    return $python
}
