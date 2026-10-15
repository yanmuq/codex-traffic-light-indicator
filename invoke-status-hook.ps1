param(
  [Parameter(Mandatory = $true)][string]$PythonPath,
  [Parameter(Mandatory = $true)][string]$EventName
)

$ErrorActionPreference = "Stop"
# Use PowerShell's call operator inside a script, regardless of the outer hook shell.
& $PythonPath (Join-Path $PSScriptRoot "codex_status_hook.py") --event $EventName
exit $LASTEXITCODE
