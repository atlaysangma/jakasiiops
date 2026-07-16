[CmdletBinding()]
param([string]$ConfigPath = (Join-Path $PSScriptRoot "config.json"))

$ErrorActionPreference = "Stop"
$config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
$task = Get-ScheduledTask -TaskName ([string]$config.task_name) -ErrorAction SilentlyContinue
$info = Get-ScheduledTaskInfo -TaskName ([string]$config.task_name) -ErrorAction SilentlyContinue
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$log = Join-Path $PSScriptRoot "logs\agent.log"
[ordered]@{
    task_present = [bool]$task
    task_state = if ($task) { [string]$task.State } else { "not_registered" }
    last_run_time = if ($info) { $info.LastRunTime.ToString("o") } else { $null }
    last_task_result = if ($info) { $info.LastTaskResult } else { $null }
    runtime_present = Test-Path -LiteralPath $python
    data_present = Test-Path -LiteralPath ([string]$config.data_root)
    log_last_write = if (Test-Path -LiteralPath $log) { (Get-Item -LiteralPath $log).LastWriteTimeUtc.ToString("o") } else { $null }
} | ConvertTo-Json

if (Test-Path -LiteralPath $python) {
    & $python -m jakasii_ops.cli --data-root ([string]$config.data_root) status ([string]$config.store_id)
}
