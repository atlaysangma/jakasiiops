[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$')][string]$StoreId,
    [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$StoreName,
    [string]$InstallRoot = (Join-Path $env:ProgramData "JAKASII Ops"),
    [string]$DataRoot = (Join-Path $env:ProgramData "JAKASII Ops\data"),
    [string[]]$ScanRoot = @([Environment]::GetFolderPath("UserProfile")),
    [string[]]$ServerCandidate = @(),
    [ValidateRange(5, 3600)][int]$PollSeconds = 30,
    [ValidateRange(60, 86400)][int]$RescanSeconds = 3600,
    [ValidateRange(1, 100)][int]$SqlLimit = 10,
    [string]$TaskName = "JAKASII Ops",
    [switch]$SkipTaskRegistration,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "This installer is for Windows main servers." }

$packageRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$wheel = Get-ChildItem -LiteralPath (Join-Path $packageRoot "wheelhouse") -Filter "jakasii_ops-*.whl" -File | Select-Object -First 1
if (-not $wheel) { throw "The offline JAKASII Ops wheel is missing from wheelhouse." }

function Resolve-Python311 {
    $launchers = @(
        @{ command = "py.exe"; args = @("-3.12") },
        @{ command = "py.exe"; args = @("-3.11") },
        @{ command = "python.exe"; args = @() },
        @{ command = "python"; args = @() }
    )
    foreach ($item in $launchers) {
        $resolved = Get-Command $item.command -ErrorAction SilentlyContinue
        if (-not $resolved) { continue }
        try {
            $version = & $resolved.Source @($item.args) -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>$null
            if ($LASTEXITCODE -eq 0 -and [version]$version -ge [version]"3.11") {
                return @{ executable = $resolved.Source; prefix = @($item.args); version = $version }
            }
        } catch { }
    }
    throw "Python 3.11+ is required on the main server. Install it, then rerun this installer."
}

if (-not (Get-Command "sqlcmd.exe" -ErrorAction SilentlyContinue)) {
    throw "sqlcmd.exe is required for bounded read-only SQL Server discovery. Install Microsoft SQL command-line utilities first."
}

$installPath = [System.IO.Path]::GetFullPath($InstallRoot)
$dataPath = [System.IO.Path]::GetFullPath($DataRoot)
$configPath = Join-Path $installPath "config.json"
if ((Test-Path -LiteralPath $configPath) -and -not $Force) {
    throw "An installation already exists at $installPath. Use -Force only after reviewing the existing config and data path."
}

$python = Resolve-Python311
New-Item -ItemType Directory -Force -Path $installPath, $dataPath, (Join-Path $installPath "logs"), (Join-Path $installPath "wheelhouse") | Out-Null
Copy-Item -LiteralPath $wheel.FullName -Destination (Join-Path $installPath "wheelhouse") -Force
foreach ($name in @("Run-JakasiiOps.ps1", "Start-JakasiiOps.ps1", "Stop-JakasiiOps.ps1", "Get-JakasiiOpsStatus.ps1", "Uninstall-JakasiiOps.ps1")) {
    Copy-Item -LiteralPath (Join-Path $packageRoot "scripts\$name") -Destination $installPath -Force
}

$venv = Join-Path $installPath ".venv"
if (-not (Test-Path -LiteralPath (Join-Path $venv "Scripts\python.exe"))) {
    & $python.executable @($python.prefix) -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Creating the isolated Python environment failed." }
}
$venvPython = Join-Path $venv "Scripts\python.exe"
& $venvPython -m pip install --no-index --no-deps --force-reinstall $wheel.FullName
if ($LASTEXITCODE -ne 0) { throw "Installing the offline JAKASII Ops wheel failed." }
& $venvPython -c "import jakasii_ops; print('JAKASII Ops import: OK')"
if ($LASTEXITCODE -ne 0) { throw "The installed package failed its import check." }

$normalizedRoots = @($ScanRoot | ForEach-Object { [System.IO.Path]::GetFullPath($_) } | Select-Object -Unique)
$config = [ordered]@{
    protocol = "jakasii.mainserver.config.v1"
    store_id = $StoreId
    store_name = $StoreName
    data_root = $dataPath
    scan_roots = $normalizedRoots
    server_candidates = @($ServerCandidate | Select-Object -Unique)
    poll_seconds = $PollSeconds
    rescan_seconds = $RescanSeconds
    sql_limit = $SqlLimit
    task_name = $TaskName
    created_for_user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    contains_secrets = $false
}
$config | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $configPath -Encoding UTF8

$taskRegistered = $false
if (-not $SkipTaskRegistration) {
    $user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $runScript = Join-Path $installPath "Run-JakasiiOps.ps1"
    $actionArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`" -ConfigPath `"$configPath`""
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs -WorkingDirectory $installPath
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Headless JAKASII Ops main-server agent (read-only connectors; approval-gated actions)." -Force | Out-Null
    Disable-ScheduledTask -TaskName $TaskName | Out-Null
    $taskRegistered = $true
}

[ordered]@{
    installed = $true
    install_root = $installPath
    data_root = $dataPath
    python = $python.version
    task_registered = $taskRegistered
    task_enabled = $false
    live_discovery_started = $false
    contains_secrets = $false
    next_step = if ($taskRegistered) { "Review config.json, then run Start-JakasiiOps.ps1 -EnableTask." } else { "Offline installation test complete; no scheduled task was created." }
} | ConvertTo-Json
