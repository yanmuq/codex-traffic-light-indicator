@echo off
setlocal
cd /d "%~dp0"
python indicator.py
if errorlevel 1 (
  echo.
  echo Traffic light indicator exited with an error.
  pause
)

