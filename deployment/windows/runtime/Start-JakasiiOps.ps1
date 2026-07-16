[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "config.json"),
    [switch]$EnableTask
)

$ErrorActionPreference = "Stop"
$config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
$task = Get-ScheduledTask -TaskName ([string]$config.task_name) -ErrorAction Stop
if ($task.State -eq "Disabled" -and -not $EnableTask) {
    throw "The task is disabled by design. Review config.json, then rerun with -EnableTask."
}
if ($EnableTask) { Enable-ScheduledTask -TaskName ([string]$config.task_name) | Out-Null }
Start-ScheduledTask -TaskName ([string]$config.task_name)
Start-Sleep -Seconds 2
Get-ScheduledTask -TaskName ([string]$config.task_name) | Select-Object TaskName, State
