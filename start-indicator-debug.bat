@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%CODEX_TRAFFIC_LIGHT_PYTHON%"
if not defined PYTHON set "PYTHON=C:\Python313\python.exe"
if not exist "%PYTHON%" set "PYTHON=%~dp0python-runtime-release\python.exe"
if not exist "%PYTHON%" set "PYTHON=python.exe"
if "%PYTHON%"=="python.exe" (
  where python.exe >nul 2>&1
  if errorlevel 1 set "PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
)
if defined CODEX_TRAFFIC_LIGHT_TCL_LIBRARY set "TCL_LIBRARY=%CODEX_TRAFFIC_LIGHT_TCL_LIBRARY%"
if defined CODEX_TRAFFIC_LIGHT_TK_LIBRARY set "TK_LIBRARY=%CODEX_TRAFFIC_LIGHT_TK_LIBRARY%"
if not exist "%PYTHON%" (
  echo Cannot find python.exe. Install Python 3 or run this from the Codex desktop environment.
  pause
  exit /b 1
)
"%PYTHON%" indicator.py
if errorlevel 1 (
  echo.
  echo Traffic light indicator exited with an error.
  pause
)
