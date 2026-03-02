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

$pythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Python virtual environment not found at '$pythonExe'. Run install-windows.cmd first."
}

$localSettingsPath = Join-Path $RepoRoot "config\windows_receiver_settings.local.json"
$exampleSettingsPath = Join-Path $RepoRoot "config\windows_receiver_settings.example.json"
$settingsPath = $exampleSettingsPath
if (Test-Path $localSettingsPath) {
    $settingsPath = $localSettingsPath
}

$settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
$mapPath = Join-Path $RepoRoot $settings.map_path
if (-not (Test-Path $mapPath)) {
    throw "MIDI map file not found at '$mapPath'."
}

$args = @(
    "-m",
    "windows.win_recv",
    "--listen",
    [string]$settings.listen,
    "--map",
    $mapPath,
    "--midi-port",
    [string]$settings.midi_port,
    "--timeout",
    [string]$settings.timeout
)

if ($settings.verbose) {
    $args += "--verbose"
}

Write-Host "STEAMDECK MIDI receiver"
Write-Host "Repo:     $RepoRoot"
Write-Host "Settings: $settingsPath"
Write-Host "Map:      $mapPath"
Write-Host "Port:     $($settings.midi_port)"
Write-Host ""

Push-Location $RepoRoot
try {
    & $pythonExe @args
} finally {
    Pop-Location
}
