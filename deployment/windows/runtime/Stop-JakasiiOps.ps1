[CmdletBinding()]
param([string]$ConfigPath = (Join-Path $PSScriptRoot "config.json"))

$ErrorActionPreference = "Stop"
$config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
Stop-ScheduledTask -TaskName ([string]$config.task_name) -ErrorAction SilentlyContinue
Get-ScheduledTask -TaskName ([string]$config.task_name) -ErrorAction SilentlyContinue | Select-Object TaskName, State
