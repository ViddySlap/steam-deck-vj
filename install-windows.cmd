@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%.") do set "REPO_ROOT=%%~fI"
powershell.exe -ExecutionPolicy Bypass -NoLogo -File "%REPO_ROOT%\scripts\windows\install_windows.ps1" -RepoRoot "%REPO_ROOT%"
exit /b %ERRORLEVEL%
