param(
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$HookScript = Join-Path $AppDir "codex_status_hook.py"
$CodexHome = Join-Path $env:USERPROFILE ".codex"
$HooksPath = Join-Path $CodexHome "hooks.json"
$BackupDir = Join-Path $AppDir "backups"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"

function New-HookHandler {
  param([string]$EventName)
  $Command = "python `"$HookScript`" --event $EventName"
  return [ordered]@{
    type = "command"
    command = $Command
    commandWindows = $Command
    timeout = 5
    statusMessage = "Update traffic light indicator"
  }
}

function New-HookGroup {
  param(
    [string]$EventName,
    [string]$Matcher
  )
  $Group = [ordered]@{
    hooks = @((New-HookHandler -EventName $EventName))
  }
  if ($Matcher) {
    $Group.matcher = $Matcher
  }
  return $Group
}

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

function Remove-TrafficLightHooks {
  param($Config)
  if (-not $Config.hooks) {
    $Config | Add-Member -MemberType NoteProperty -Name hooks -Value ([pscustomobject]@{})
  }

  foreach ($EventName in @("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PermissionRequest", "Stop")) {
    if ($Config.hooks.PSObject.Properties.Name -contains $EventName) {
      $Existing = @($Config.hooks.$EventName)
      $Filtered = @($Existing | Where-Object { -not (Test-IsTrafficLightGroup $_) })
      $Config.hooks.$EventName = $Filtered
    }
  }
  return $Config
}

function Add-TrafficLightHooks {
  param($Config)
  $Definitions = @(
    @{ event = "SessionStart"; matcher = "startup|resume|clear" },
    @{ event = "UserPromptSubmit"; matcher = $null },
    @{ event = "PreToolUse"; matcher = "*" },
    @{ event = "PostToolUse"; matcher = "*" },
    @{ event = "PermissionRequest"; matcher = "*" },
    @{ event = "Stop"; matcher = $null }
  )

  foreach ($Definition in $Definitions) {
    $EventName = $Definition.event
    $Group = New-HookGroup -EventName $EventName -Matcher $Definition.matcher
    if ($Config.hooks.PSObject.Properties.Name -contains $EventName) {
      $Current = @($Config.hooks.$EventName)
      $Config.hooks.$EventName = @($Current + [pscustomobject]$Group)
    } else {
      $Config.hooks | Add-Member -MemberType NoteProperty -Name $EventName -Value @([pscustomobject]$Group)
    }
  }
  return $Config
}

if (-not (Test-Path -LiteralPath $HookScript)) {
  throw "Cannot find hook script: $HookScript"
}

if (-not (Test-Path -LiteralPath $CodexHome)) {
  if (-not $DryRun) {
    New-Item -ItemType Directory -Path $CodexHome | Out-Null
  }
}

if (-not (Test-Path -LiteralPath $BackupDir)) {
  if (-not $DryRun) {
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
  }
}

if (Test-Path -LiteralPath $HooksPath) {
  $Raw = Get-Content -LiteralPath $HooksPath -Raw
  $Config = $Raw | ConvertFrom-Json
  $BackupPath = Join-Path $BackupDir "hooks-before-install-$Stamp.json"
} else {
  $Config = [pscustomobject]@{ hooks = [pscustomobject]@{} }
  $Raw = $Config | ConvertTo-Json -Depth 30
  $BackupPath = Join-Path $BackupDir "hooks-before-install-$Stamp.new-file.json"
}

$Config = Remove-TrafficLightHooks -Config $Config
$Config = Add-TrafficLightHooks -Config $Config
$OutputJson = $Config | ConvertTo-Json -Depth 30

if ($DryRun) {
  Write-Host "Dry run only. Would write:"
  Write-Host $HooksPath
  Write-Host ""
  Write-Host $OutputJson
  exit 0
}

$Raw | Set-Content -LiteralPath $BackupPath -Encoding UTF8
$OutputJson | Set-Content -LiteralPath $HooksPath -Encoding UTF8

Write-Host "Installed traffic-light hooks."
Write-Host "Hooks file: $HooksPath"
Write-Host "Backup: $BackupPath"
Write-Host "If Codex asks for hook review, open /hooks and trust these commands."
