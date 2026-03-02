@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -ExecutionPolicy Bypass -NoLogo -File "%SCRIPT_DIR%scripts\windows\install_windows.ps1" -RepoRoot "%SCRIPT_DIR%"
exit /b %ERRORLEVEL%
