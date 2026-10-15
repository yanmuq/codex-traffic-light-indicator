@echo off
setlocal
cd /d "%~dp0"
set "PYTHONW=%CODEX_TRAFFIC_LIGHT_PYTHONW%"
if not defined PYTHONW set "PYTHONW=C:\Python313\pythonw.exe"
if not exist "%PYTHONW%" set "PYTHONW=%~dp0python-runtime-release\pythonw.exe"
if not exist "%PYTHONW%" set "PYTHONW=pythonw.exe"
if "%PYTHONW%"=="pythonw.exe" (
  where pythonw.exe >nul 2>&1
  if errorlevel 1 set "PYTHONW=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
)
if defined CODEX_TRAFFIC_LIGHT_TCL_LIBRARY set "TCL_LIBRARY=%CODEX_TRAFFIC_LIGHT_TCL_LIBRARY%"
if defined CODEX_TRAFFIC_LIGHT_TK_LIBRARY set "TK_LIBRARY=%CODEX_TRAFFIC_LIGHT_TK_LIBRARY%"
if not exist "%PYTHONW%" (
  echo Cannot find pythonw.exe. Install Python 3 or run this from the Codex desktop environment.
  exit /b 1
)
start "" "%PYTHONW%" "%~dp0indicator.py"
