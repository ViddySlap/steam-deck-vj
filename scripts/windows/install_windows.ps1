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

function Assert-Command {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw $Message
    }
}

Assert-Command -Name "py" -Message "Python Launcher for Windows ('py') was not found. Install Python 3.12 first."

$pythonCheck = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.12 is required. Install it, then rerun this installer."
}

$venvPath = Join-Path $RepoRoot ".venv"
if (-not (Test-Path $venvPath)) {
    Write-Host "Creating virtual environment..."
    & py -3.12 -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create virtual environment."
    }
}

$venvPython = Join-Path $venvPath "Scripts\python.exe"
Write-Host "Installing Python dependencies..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip."
}
& $venvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install Python dependencies."
}

$exampleSettingsPath = Join-Path $RepoRoot "config\windows_receiver_settings.example.json"
$localSettingsPath = Join-Path $RepoRoot "config\windows_receiver_settings.local.json"
if (-not (Test-Path $localSettingsPath)) {
    Copy-Item $exampleSettingsPath $localSettingsPath
}

$launcherPath = Join-Path $RepoRoot "scripts\windows\start_receiver.ps1"
$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "Steam Deck VJ Receiver.lnk"
$workingDirectory = $RepoRoot
$arguments = "-ExecutionPolicy Bypass -NoLogo -NoExit -File `"$launcherPath`" -RepoRoot `"$RepoRoot`""

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $workingDirectory
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,70"
$shortcut.Description = "Start the Steam Deck VJ Windows receiver"
$shortcut.Save()

Write-Host ""
Write-Host "Install complete."
Write-Host "Desktop shortcut: $shortcutPath"
Write-Host "Local settings:   $localSettingsPath"
Write-Host ""
Write-Host "Before launching:"
Write-Host "1. Open loopMIDI and create a DECK_IN port."
Write-Host "2. Edit windows_receiver_settings.local.json if your MIDI port name should differ."
Write-Host "3. Double-click the desktop shortcut to start the receiver."
