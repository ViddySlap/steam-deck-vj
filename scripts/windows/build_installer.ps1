param(
    [string]$RepoRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
} else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

$exePath = Join-Path $RepoRoot "dist\STEAMDECK-MIDI-RECEIVER.exe"
if (-not (Test-Path $exePath)) {
    throw "Packaged receiver EXE not found at '$exePath'. Build it first with build_exe.ps1."
}

$versionPath = Join-Path $RepoRoot "VERSION"
if (-not (Test-Path $versionPath)) {
    throw "VERSION file not found at '$versionPath'."
}
$appVersion = (Get-Content $versionPath -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($appVersion)) {
    throw "VERSION file at '$versionPath' is empty."
}

$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
    $defaultIscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
    if (Test-Path $defaultIscc) {
        $iscc = Get-Item $defaultIscc
    }
}
if (-not $iscc) {
    $perUserIscc = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
    if (Test-Path $perUserIscc) {
        $iscc = Get-Item $perUserIscc
    }
}
if (-not $iscc) {
    throw "Inno Setup compiler (ISCC.exe) was not found. Install Inno Setup 6 first."
}

$issPath = Join-Path $RepoRoot "installer\windows\steamdeck-midi-receiver.iss"

Push-Location $RepoRoot
try {
    & $iscc.FullName "/DAppVersion=$appVersion" $issPath
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup build failed."
    }
} finally {
    Pop-Location
}

$outputDir = Join-Path $RepoRoot "installer-output"
$setupExe = Join-Path $outputDir ("STEAMDECK-MIDI-RECEIVER-Setup-{0}.exe" -f $appVersion)

Write-Host ""
Write-Host "Installer build complete."
Write-Host "Output directory: $outputDir"
Write-Host "Installer EXE:    $setupExe"
