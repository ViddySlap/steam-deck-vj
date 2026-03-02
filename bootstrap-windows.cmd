@echo off
setlocal
set "INSTALL_DIR=%USERPROFILE%\steam-deck-midi"
if not "%~1"=="" set "INSTALL_DIR=%~1"
for %%I in ("%INSTALL_DIR%") do set "INSTALL_DIR=%%~fI"

powershell.exe -ExecutionPolicy Bypass -NoLogo -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$repoUrl = 'https://github.com/ViddySlap/steam-deck-midi.git';" ^
  "$installDir = [System.IO.Path]::GetFullPath('%INSTALL_DIR%');" ^
  "if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git for Windows was not found. Install Git first.' };" ^
  "if (Test-Path (Join-Path $installDir '.git')) { git -C $installDir pull --ff-only } else { git clone $repoUrl $installDir };" ^
  "& powershell.exe -ExecutionPolicy Bypass -NoLogo -File (Join-Path $installDir 'scripts\windows\install_windows.ps1') -RepoRoot $installDir"

exit /b %ERRORLEVEL%
