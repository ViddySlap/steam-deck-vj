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

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python Launcher for Windows ('py') was not found. Install Python 3.12 first."
}

$pythonCheck = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.12 is required. Install it, then rerun this build."
}

$venvPath = Join-Path $RepoRoot ".venv-build"
if (-not (Test-Path $venvPath)) {
    Write-Host "Creating build virtual environment..."
    & py -3.12 -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create build virtual environment."
    }
}

$venvPython = Join-Path $venvPath "Scripts\python.exe"
$specPath = Join-Path $RepoRoot "steamdeck-midi-receiver.spec"
$versionPath = Join-Path $RepoRoot "VERSION"
if (-not (Test-Path $versionPath)) {
    throw "VERSION file not found at '$versionPath'."
}
$appVersion = (Get-Content $versionPath -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($appVersion)) {
    throw "VERSION file at '$versionPath' is empty."
}
$versionParts = $appVersion.Split(".")
while ($versionParts.Count -lt 4) {
    $versionParts += "0"
}
$versionInfoPath = Join-Path $RepoRoot "build\windows-file-version.txt"
$versionTuple = ($versionParts[0..3] | ForEach-Object { [int]$_ }) -join ", "
$versionText = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($versionTuple),
    prodvers=($versionTuple),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'040904B0',
          [
            StringStruct(u'CompanyName', u'ViddySlap'),
            StringStruct(u'FileDescription', u'STEAMDECK MIDI Receiver'),
            StringStruct(u'FileVersion', u'$appVersion'),
            StringStruct(u'InternalName', u'STEAMDECK-MIDI-RECEIVER'),
            StringStruct(u'OriginalFilename', u'STEAMDECK-MIDI-RECEIVER.exe'),
            StringStruct(u'ProductName', u'STEAMDECK MIDI Receiver'),
            StringStruct(u'ProductVersion', u'$appVersion')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"@
Set-Content -Path $versionInfoPath -Value $versionText -Encoding ASCII

Write-Host "Installing build dependencies..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip."
}
& $venvPython -m pip install -r (Join-Path $RepoRoot "requirements-build.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install build dependencies."
}

Push-Location $RepoRoot
try {
Write-Host "Building executable..."
    & $venvPython -m PyInstaller --clean --noconfirm --version-file $versionInfoPath $specPath
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }
} finally {
    Pop-Location
}

$distDir = Join-Path $RepoRoot "dist"
$exePath = Join-Path $distDir "STEAMDECK-MIDI-RECEIVER.exe"

Write-Host ""
Write-Host "Build complete."
Write-Host "Dist directory: $distDir"
Write-Host "Executable:     $exePath"
Write-Host ""
Write-Host "Example run:"
Write-Host ".\dist\STEAMDECK-MIDI-RECEIVER.exe --map .\config\windows_midi_map.json --midi-port `"DECK_IN`" --verbose"
