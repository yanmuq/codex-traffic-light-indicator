@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart-indicator.ps1"
echo.
echo restart-indicator.ps1 exit code: %ERRORLEVEL%
echo.
pause
