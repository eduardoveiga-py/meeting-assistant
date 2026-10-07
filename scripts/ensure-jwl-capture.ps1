[CmdletBinding()]
param([string]$ObsDirectory = "$env:ProgramFiles\obs-studio")
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ([Environment]::OSVersion.Version.Build -lt 22000 -or -not [Environment]::Is64BitProcess) {
    throw 'A captura JWL requer Windows 11 e PowerShell x64.'
}
$repoRoot = Split-Path -Parent $PSScriptRoot
$lock = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'jwl-capture-package.json') | ConvertFrom-Json
foreach ($field in @('zip_sha256','dll_sha256','installer_sha256')) {
    if ($lock.$field -notmatch '^[a-f0-9]{64}$') { throw "Invalid JWL package pin: $field" }
}
function Test-JwlHash([string]$Path, [string]$Expected) {
    return (Test-Path -LiteralPath $Path) -and ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Expected)
}
$obsExe = Join-Path $ObsDirectory 'bin\64bit\obs64.exe'
if (-not (Test-Path -LiteralPath $obsExe)) {
    throw "OBS x64 nao encontrado em '$ObsDirectory'. Informe -ObsDirectory no scripts/run.ps1."
}
$versionInfo = (Get-Item -LiteralPath $obsExe).VersionInfo
$version = [version]::new($versionInfo.FileMajorPart, $versionInfo.FileMinorPart, $versionInfo.FileBuildPart, $versionInfo.FilePrivatePart)
if ($version -lt [version]'31.0.3') {
    throw 'Atualize o OBS para 31.0.3 ou posterior para capturar JWL por HWND.'
}
$target = Join-Path $ObsDirectory 'obs-plugins\64bit\meeting-assistant-jwl-capture.dll'
if (Test-JwlHash $target $lock.dll_sha256) {
    Write-Host 'Captura nativa JWL por HWND ja instalada e verificada.'
    return
}
$cache = Join-Path $repoRoot "build\jwl-capture-cache\$($lock.zip_sha256)"
$zip = Join-Path $cache 'MeetingAssistant-JWL-HWND-Windows11-x64.zip'
$package = Join-Path $cache 'package'
$dll = Join-Path $package 'meeting-assistant-jwl-capture.dll'
$installer = Join-Path $package 'install-jwl-capture.ps1'
New-Item -ItemType Directory -Force $cache | Out-Null
if (-not (Test-JwlHash $zip $lock.zip_sha256)) {
    $temp = Join-Path $cache ('download-' + [guid]::NewGuid().ToString('N') + '.zip')
    try {
        Write-Host 'Baixando a DLL pronta de captura JWL por HWND...' -ForegroundColor Cyan
        Invoke-WebRequest -UseBasicParsing -Uri $lock.url -OutFile $temp
        if (-not (Test-JwlHash $temp $lock.zip_sha256)) { throw 'O pacote JWL baixado nao corresponde ao SHA-256 fixado nesta revisao. Nenhum arquivo foi instalado.' }
        Move-Item -LiteralPath $temp -Destination $zip -Force
    } finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force } }
}
# Verify the entire archive before extracting/executing a downloaded installer.
if (-not (Test-JwlHash $zip $lock.zip_sha256)) { throw 'JWL ZIP integrity failed.' }
if (Test-Path -LiteralPath $package) { Remove-Item -LiteralPath $package -Recurse -Force }
Expand-Archive -LiteralPath $zip -DestinationPath $package
if (-not (Test-JwlHash $dll $lock.dll_sha256) -or -not (Test-JwlHash $installer $lock.installer_sha256)) {
    throw 'JWL payload integrity failed. Nenhum arquivo foi instalado.'
}
$info = Get-Content -Raw -LiteralPath (Join-Path $package 'BUILD-INFO.json') | ConvertFrom-Json
if ($info.build_id -ne $lock.build_id -or $info.source_revision -ne $lock.source_revision) {
    throw 'JWL native revision mismatch.'
}
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -VerifyOnly
if ($LASTEXITCODE -ne 0) { throw 'JWL package verification failed.' }
if (Get-Process obs64 -ErrorAction SilentlyContinue) {
    throw 'A DLL JWL esta pronta. Feche o OBS e execute scripts/run.ps1 novamente para instalar. Nenhum processo foi encerrado.'
}
Write-Host 'Instalando somente o plugin JWL. Aceite a permissao de administrador do Windows.' -ForegroundColor Yellow
# Literal paths with spaces/accents are quoted for Start-Process.
$arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $installer + '" -ObsDirectory "' + $ObsDirectory + '"'
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($admin) {
    $process = Start-Process powershell.exe -ArgumentList $arguments -Wait -PassThru
} else {
    $process = Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -Wait -PassThru
}
if ($process.ExitCode -ne 0 -or -not (Test-JwlHash $target $lock.dll_sha256)) {
    throw 'A instalacao da captura JWL nao foi confirmada. Confira o OBS e tente novamente.'
}
Write-Host 'Captura JWL instalada e verificada. Abra OBS e prepare Midias nos Ajustes.' -ForegroundColor Green
