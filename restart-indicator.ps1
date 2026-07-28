$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$IndicatorPath = Join-Path $ScriptDir 'indicator.py'
$HiddenLauncher = Join-Path $ScriptDir 'start-indicator-hidden.vbs'

Write-Host "Restarting Codex traffic-light indicator..."
Write-Host "Indicator: $IndicatorPath"

$processes = @()
try {
    $processes = Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine.Contains($IndicatorPath)
        }
} catch {
    Write-Host "Could not inspect process command lines: $($_.Exception.Message)"
    Write-Host "Right-click the existing traffic light and choose Exit, then run start-indicator-hidden.vbs."
    exit 1
}

foreach ($process in $processes) {
    Write-Host "Stopping PID $($process.ProcessId): $($process.Name)"
    try {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    } catch [Microsoft.PowerShell.Commands.ProcessCommandException] {
        Write-Host "PID $($process.ProcessId) already exited."
    }
}

Start-Process -FilePath 'wscript.exe' -ArgumentList "`"$HiddenLauncher`"" -WindowStyle Hidden
Start-Sleep -Seconds 2

$running = @(Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -and
        $_.CommandLine.Contains($IndicatorPath)
    })

if ($running.Count -eq 0) {
    Write-Host "Indicator did not appear to start. Run start-indicator-debug.bat to see the Python error."
    exit 1
}

Write-Host "Indicator is running:"
$running | Select-Object ProcessId, Name, CommandLine | Format-List
