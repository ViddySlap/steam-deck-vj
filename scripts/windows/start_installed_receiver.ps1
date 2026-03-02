param(
    [string]$InstallRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = Split-Path -Parent $PSScriptRoot
} else {
    $InstallRoot = (Resolve-Path $InstallRoot).Path
}

$exePath = Join-Path $InstallRoot "STEAMDECK-MIDI-RECEIVER.exe"
if (-not (Test-Path $exePath)) {
    throw "Receiver executable not found at '$exePath'."
}

$settingsPath = Join-Path $InstallRoot "config\windows_receiver_settings.local.json"
if (-not (Test-Path $settingsPath)) {
    $settingsPath = Join-Path $InstallRoot "config\windows_receiver_settings.example.json"
}
if (-not (Test-Path $settingsPath)) {
    throw "Receiver settings file not found under '$InstallRoot\config'."
}

$settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
$mapPath = Join-Path $InstallRoot $settings.map_path
if (
    $settings.map_path -eq "config/windows_midi_map.json" -and
    -not (Test-Path $mapPath)
) {
    $mapPath = Join-Path $InstallRoot "config\windows_midi_map.local.json"
}
if (
    $settings.map_path -eq "config/windows_midi_map.json" -and
    (Test-Path (Join-Path $InstallRoot "config\windows_midi_map.local.json"))
) {
    $mapPath = Join-Path $InstallRoot "config\windows_midi_map.local.json"
}
if (-not (Test-Path $mapPath)) {
    throw "MIDI map file not found at '$mapPath'."
}

$args = @(
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

Write-Host "STEAMDECK MIDI Receiver"
Write-Host "Install:   $InstallRoot"
Write-Host "Settings:  $settingsPath"
Write-Host "Map:       $mapPath"
Write-Host "MIDI port: $($settings.midi_port)"
Write-Host ""

Push-Location $InstallRoot
try {
    & $exePath --check-midi-port --midi-port ([string]$settings.midi_port)
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "Configured MIDI port check failed."
        Write-Host "Install loopMIDI, create a DECK_IN port, then relaunch the receiver."
        exit $LASTEXITCODE
    }

    & $exePath @args
} finally {
    Pop-Location
}
