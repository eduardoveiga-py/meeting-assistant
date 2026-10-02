[CmdletBinding()]
param(
    [switch]$Refresh,
    [string]$PackageDirectory = '',
    [string]$BundleUrl = $env:MEETING_ASSISTANT_NATIVE_URL,
    [string]$ObsDirectory = "$env:ProgramFiles\obs-studio"
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$defaultBundleUrl = 'https://github.com/eduardoveiga-py/meeting-assistant/releases/download/native-latest/MeetingAssistant-Windows11-native.zip'
if ([string]::IsNullOrWhiteSpace($BundleUrl)) { $BundleUrl = $defaultBundleUrl }

# Preserve the already validated installation for Python-only updates.
$cameraClass = 'Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Classes\CLSID\{5108191D-9AD8-44F5-B760-7A35D433A427}\InprocServer32'
$cameraExe = Join-Path $env:ProgramFiles 'MeetingAssistant\VirtualCamera\meeting-assistant-camera.exe'
$bridge = Join-Path $ObsDirectory 'obs-plugins\64bit\meeting-assistant-bridge.dll'
if (-not $Refresh -and [string]::IsNullOrWhiteSpace($PackageDirectory) -and
    (Test-Path -LiteralPath $cameraExe) -and (Test-Path -LiteralPath $bridge) -and
    (Test-Path -LiteralPath $cameraClass)) {
    Write-Host 'Usando camera e ponte nativas ja instaladas.'
    return
}

$bundleCache = Join-Path $repoRoot 'build\video-native-cache'
New-Item -ItemType Directory -Force -Path $bundleCache | Out-Null

function Test-Bundle([string]$Root) {
    $app = Test-Path -LiteralPath (Join-Path $Root 'SHA256SUMS.json')
    $installer = Test-Path -LiteralPath (Join-Path $Root 'install-video-native.ps1')
    $dll = Test-Path -LiteralPath (Join-Path $Root 'MeetingAssistantMediaSource.dll')
    $hostExe = Test-Path -LiteralPath (Join-Path $Root 'meeting-assistant-camera.exe')
    $bridgeDll = Test-Path -LiteralPath (Join-Path $Root 'meeting-assistant-bridge.dll')
    return ($app -and $installer -and $dll -and $hostExe -and $bridgeDll)
}

function Get-CachedBundle {
    if (Test-Bundle $bundleCache) {
        return $bundleCache
    }

    $candidate = Get-ChildItem -LiteralPath $bundleCache -Directory -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Where-Object { Test-Bundle $_.FullName } |
        Select-Object -First 1
    if ($null -ne $candidate) {
        return $candidate.FullName
    }
    return $null
}

function Download-Bundle {
    $downloadRoot = Join-Path $repoRoot 'build\downloads'
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $extractRoot = Join-Path $downloadRoot ("extract-$stamp-" + [guid]::NewGuid().ToString('N'))
    $zipPath = Join-Path $downloadRoot ("MeetingAssistant-Windows11-$stamp.zip")
    New-Item -ItemType Directory -Force -Path $downloadRoot, $extractRoot | Out-Null

    $downloaded = $false
    # A CLI autenticada tambem permite usar um repositorio privado sem colocar
    # token em URL ou em arquivo de configuracao.
    if ($BundleUrl -eq $defaultBundleUrl) {
        $gh = Get-Command gh -ErrorAction SilentlyContinue
        if ($null -ne $gh) {
            $remote = $null
            if (Get-Command git -ErrorAction SilentlyContinue) {
                $remote = (& git -C $repoRoot remote get-url origin 2>$null | Select-Object -First 1)
            }
            if ($null -ne $remote) {
                $remote = ([string]$remote).Trim()
            }
            $slug = $null
            if ($remote -match '^git@github\.com:(?<slug>[^/]+/[^/]+?)(?:\.git)?$') {
                $slug = $Matches['slug']
            } elseif ($remote -match '^https://github\.com/(?<slug>[^/]+/[^/]+?)(?:\.git)?$') {
                $slug = $Matches['slug']
            }
            if (-not [string]::IsNullOrWhiteSpace($slug)) {
                & $gh.Source release download native-latest --repo $slug --pattern 'MeetingAssistant-Windows11-native.zip' --dir $downloadRoot --clobber
                if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath (Join-Path $downloadRoot 'MeetingAssistant-Windows11-native.zip'))) {
                    Move-Item -LiteralPath (Join-Path $downloadRoot 'MeetingAssistant-Windows11-native.zip') -Destination $zipPath -Force
                    $downloaded = $true
                }
            }
        }
    }
    if (-not $downloaded) {
        Write-Host "Baixando pacote nativo Windows 11: $BundleUrl" -ForegroundColor Cyan
        Invoke-WebRequest -UseBasicParsing -Uri $BundleUrl -OutFile $zipPath
    }
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractRoot -Force

    $root = $extractRoot
    if (-not (Test-Bundle $root)) {
        $root = Get-ChildItem -LiteralPath $extractRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Bundle $_.FullName } |
            Select-Object -First 1 -ExpandProperty FullName
    }
    if ([string]::IsNullOrWhiteSpace($root) -or -not (Test-Bundle $root)) {
        throw "O pacote baixado nao contem DLLs, host da camera, instalador e manifesto completos. URL: $BundleUrl"
    }

    $target = Join-Path $bundleCache ("dev-$stamp-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
    Move-Item -LiteralPath $root -Destination $target
    Write-Host "Pacote pronto armazenado em $target" -ForegroundColor Green
    return $target
}

$bundleRoot = $null
if (-not [string]::IsNullOrWhiteSpace($PackageDirectory)) {
    $bundleRoot = (Resolve-Path -LiteralPath $PackageDirectory).Path
    if (-not (Test-Bundle $bundleRoot)) { throw 'Pacote nativo local incompleto.' }
} elseif (-not $Refresh) {
    $bundleRoot = Get-CachedBundle
}
if ($null -eq $bundleRoot) {
    try {
        $bundleRoot = Download-Bundle
    } catch {
        $message = $_.Exception.Message
        $cached = Get-CachedBundle
        if ($null -ne $cached) {
            Write-Warning "Nao foi possivel baixar um pacote novo; usando o cache local '$cached'. Motivo: $message"
            $bundleRoot = $cached
        } else {
            throw (
                "Nao foi possivel obter o pacote Windows 11 pronto. $message`n" +
                "Para usar os componentes ja instalados: .\scripts\run.ps1 -SkipNativeInstall. Ou forneca -NativePackageDirectory com o pacote nativo completo."
            )
        }
    }
}

function Get-BundleHash([string]$Root, [string]$Name) {
    $manifest = Join-Path $Root 'SHA256SUMS.json'
    if (-not (Test-Path -LiteralPath $manifest)) {
        return $null
    }
    $manifestEntries = Get-Content -Raw -LiteralPath $manifest | ConvertFrom-Json
    $entries = @($manifestEntries | Where-Object { $_.File -eq $Name })
    if ($entries.Count -ne 1) {
        return $null
    }
    return ([string]$entries[0].Hash).ToLowerInvariant()
}

function Test-Hash([string]$Path, [string]$Expected) {
    if ([string]::IsNullOrWhiteSpace($Expected) -or -not (Test-Path -LiteralPath $Path)) {
        return $false
    }
    return ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Expected)
}

function Test-NativeInstallation([string]$Root) {
    $obsRoot = if ([string]::IsNullOrWhiteSpace($ObsDirectory)) {
        Join-Path $env:ProgramFiles 'obs-studio'
    } else {
        $ObsDirectory
    }
    $bridge = Join-Path $obsRoot 'obs-plugins\64bit\meeting-assistant-bridge.dll'
    $cameraRoot = Join-Path $env:ProgramFiles 'MeetingAssistant\VirtualCamera'
    $cameraExe = Join-Path $cameraRoot 'meeting-assistant-camera.exe'
    $cameraClass = 'Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Classes\CLSID\{5108191D-9AD8-44F5-B760-7A35D433A427}\InprocServer32'
    $bridgeHash = Get-BundleHash $Root 'meeting-assistant-bridge.dll'
    $cameraHash = Get-BundleHash $Root 'meeting-assistant-camera.exe'
    $cameraDllHash = Get-BundleHash $Root 'MeetingAssistantMediaSource.dll'
    $installedCameraDll = Get-ChildItem -LiteralPath $cameraRoot -Filter 'MeetingAssistantMediaSource.*.dll' -File -ErrorAction SilentlyContinue |
        Where-Object { Test-Hash $_.FullName $cameraDllHash } |
        Select-Object -First 1
    $bridgeOk = Test-Hash $bridge $bridgeHash
    $cameraOk = Test-Hash $cameraExe $cameraHash
    $dllOk = $null -ne $installedCameraDll
    $classOk = $false
    if (Test-Path -LiteralPath $cameraClass) {
        $registeredDll = (Get-Item -LiteralPath $cameraClass).GetValue('')
        $classOk = Test-Hash $registeredDll $cameraDllHash
    }
    return ($bridgeOk -and $cameraOk -and $dllOk -and $classOk)
}

function Install-NativeIfNeeded([string]$Root) {
    if (Test-NativeInstallation $Root) {
        return
    }

    $installer = Join-Path $Root 'install-video-native.ps1'
    Write-Host 'Os componentes nativos Windows 11 ainda nao estao instalados.' -ForegroundColor Yellow
    Write-Host 'Feche OBS, WhatsApp e Meeting Assistant quando o Windows solicitar elevacao.' -ForegroundColor Yellow
    $obsRoot = if ([string]::IsNullOrWhiteSpace($ObsDirectory)) {
        Join-Path $env:ProgramFiles 'obs-studio'
    } else {
        $ObsDirectory
    }
    $active = Get-Process obs64,WhatsApp,meeting-assistant-camera -ErrorAction SilentlyContinue
    if ($active) {
        throw 'Feche OBS, WhatsApp e a camera do Meeting Assistant antes de instalar/atualizar os componentes nativos. Nenhum processo foi encerrado.'
    }
    $quotedInstaller = '"' + $installer.Replace('"', '\"') + '"'
    $quotedObs = '"' + $obsRoot.Replace('"', '\"') + '"'
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File $quotedInstaller -Component All -ObsDirectory $quotedObs"
    $process = Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "A instalacao nativa terminou com codigo $($process.ExitCode). Feche OBS/WhatsApp e execute .\scripts\run.ps1 novamente."
    }
    if (-not (Test-NativeInstallation $Root)) {
        throw 'A instalacao nativa terminou, mas a ponte do OBS/camera nao foi encontrada.'
    }
}

# Validate the complete native payload before any elevated execution.
$entries = Get-Content -Raw -LiteralPath (Join-Path $bundleRoot 'SHA256SUMS.json') | ConvertFrom-Json
foreach ($name in @('install-video-native.ps1','meeting-assistant-bridge.dll','MeetingAssistantMediaSource.dll',
    'meeting-assistant-camera.exe','meeting-assistant-source-probe.exe','meeting-assistant-camera-inventory.exe')) {
    $matchesForFile = @($entries | Where-Object { $_.File -eq $name })
    if ($matchesForFile.Count -ne 1 -or -not (Test-Hash (Join-Path $bundleRoot $name) ([string]$matchesForFile[0].Hash))) {
        throw "Pacote nativo incompleto ou corrompido: $name"
    }
}
Install-NativeIfNeeded $bundleRoot
