param(
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CodexHome = Join-Path $env:USERPROFILE ".codex"
$HooksPath = Join-Path $CodexHome "hooks.json"
$BackupDir = Join-Path $AppDir "backups"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Test-IsTrafficLightGroup {
  param($Group)
  if (-not $Group.hooks) {
    return $false
  }
  foreach ($Hook in @($Group.hooks)) {
    foreach ($Key in @("command", "commandWindows", "command_windows")) {
      if ($Hook.PSObject.Properties.Name -contains $Key) {
        $Value = [string]$Hook.$Key
        if ($Value -like "*codex_status_hook.py*") {
          return $true
        }
      }
    }
  }
  return $false
}

if (-not (Test-Path -LiteralPath $HooksPath)) {
  Write-Host "No hooks.json found. Nothing to uninstall."
  exit 0
}

if (-not (Test-Path -LiteralPath $BackupDir)) {
  if (-not $DryRun) {
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
  }
}

$Raw = Get-Content -LiteralPath $HooksPath -Raw
$Config = $Raw | ConvertFrom-Json

if (-not $Config.hooks) {
  Write-Host "hooks.json has no hooks section. Nothing to uninstall."
  exit 0
}

foreach ($EventName in @("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PermissionRequest", "Stop")) {
  if ($Config.hooks.PSObject.Properties.Name -contains $EventName) {
    $Existing = @($Config.hooks.$EventName)
    $Filtered = @($Existing | Where-Object { -not (Test-IsTrafficLightGroup $_) })
    $Config.hooks.$EventName = $Filtered
  }
}

$OutputJson = $Config | ConvertTo-Json -Depth 30
$BackupPath = Join-Path $BackupDir "hooks-before-uninstall-$Stamp.json"

if ($DryRun) {
  Write-Host "Dry run only. Would write:"
  Write-Host $HooksPath
  Write-Host ""
  Write-Host $OutputJson
  exit 0
}

$Raw | Set-Content -LiteralPath $BackupPath -Encoding UTF8
$OutputJson | Set-Content -LiteralPath $HooksPath -Encoding UTF8

Write-Host "Removed traffic-light hooks."
Write-Host "Hooks file: $HooksPath"
Write-Host "Backup: $BackupPath"
