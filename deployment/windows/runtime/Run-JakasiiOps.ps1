[CmdletBinding()]
param([string]$ConfigPath = (Join-Path $PSScriptRoot "config.json"))

$ErrorActionPreference = "Stop"
$config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
if ($config.protocol -ne "jakasii.mainserver.config.v1") { throw "Unsupported or invalid JAKASII Ops config." }
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "The isolated JAKASII Ops Python runtime is missing." }

$argsList = @(
    "-m", "jakasii_ops.cli", "--data-root", [string]$config.data_root,
    "auto-watch-store", "--store-id", [string]$config.store_id,
    "--store-name", [string]$config.store_name,
    "--poll-seconds", [string]$config.poll_seconds,
    "--rescan-seconds", [string]$config.rescan_seconds,
    "--limit", [string]$config.sql_limit
)
foreach ($root in @($config.scan_roots)) { $argsList += @("--scan-root", [string]$root) }
foreach ($server in @($config.server_candidates)) { $argsList += @("--server-candidate", [string]$server) }

$logDirectory = Join-Path $PSScriptRoot "logs"
$logPath = Join-Path $logDirectory "agent.log"
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
if ((Test-Path -LiteralPath $logPath) -and (Get-Item -LiteralPath $logPath).Length -gt 5242880) {
    $oldPath = "$logPath.1"
    if (Test-Path -LiteralPath $oldPath) { Remove-Item -LiteralPath $oldPath -Force }
    Move-Item -LiteralPath $logPath -Destination $oldPath
}
$env:PYTHONUTF8 = "1"
"[$([DateTimeOffset]::Now.ToString('o'))] starting JAKASII Ops" | Add-Content -LiteralPath $logPath
& $python @argsList *>> $logPath
exit $LASTEXITCODE
