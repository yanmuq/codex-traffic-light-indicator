@echo off
setlocal
cd /d "%~dp0"

echo === Codex Traffic Light Status Probe ===
echo.

echo [rollout fallback]
python codex_rollout_status.py
echo.

echo [hook state file]
if exist "runtime\state.json" (
  type "runtime\state.json"
) else (
  echo runtime\state.json not found
)
echo.

echo [indicator diagnostics]
if exist "runtime\diagnostics.json" (
  type "runtime\diagnostics.json"
) else (
  echo runtime\diagnostics.json not found
)
echo.

echo If rollout says green while Codex is running, that is expected.
echo If Codex has finished but rollout still lists active_sources, send this output back for review.
echo.
pause

