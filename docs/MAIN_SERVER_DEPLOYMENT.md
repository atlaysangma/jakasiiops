# Main-server deployment

JAKASII Ops runs on the store's main-server PC because that machine owns the
authorized SQL Server connection and camera collector. A developer laptop can
build and test the package, but it is not a live store deployment and cannot
prove camera operation without access to the real collector.

The deployment is isolated from the POS application. It does not modify POS
files, SQL tables, sales/purchase sync queues, Firebase sync timers, or camera
software. SQL and staff connectors are read-only. Camera events remain
observations, and official business changes remain approval-gated.

## Build and transfer

```powershell
.\deployment\windows\Build-MainServerPackage.ps1
```

This produces `dist\jakasii-ops-mainserver.zip` plus a SHA-256 hash. The ZIP
contains an offline Python wheel, deployment scripts, documentation, and a file
manifest. It excludes Git history, virtual environments, local runtime data,
credentials, production records, and camera media.

Copy the ZIP to the main server through an owner-approved method, verify the
hash, and extract it. The logged-in Windows account needs Python 3.11+,
`sqlcmd.exe`, read-only SQL access, and access to the existing camera collector
folder.

## Install without starting

```powershell
.\scripts\Install-JakasiiOps.ps1 `
  -StoreId sangma_megha_mart `
  -StoreName "Sangma Megha Mart" `
  -ScanRoot C:\Users\MAIN_SERVER_USER
```

`ScanRoot` is an authorized filesystem boundary, not a schema or table hint.
JAKASII must still discover and rank accessible SQL databases and compatible
camera collectors itself. Add `-ServerCandidate` only when SQL is not exposed
as a discoverable local instance.

The installer creates an isolated virtual environment and non-secret
`config.json` under `C:\ProgramData\JAKASII Ops`. It registers the scheduled
task disabled and does not start discovery.

## Review and start

Review `C:\ProgramData\JAKASII Ops\config.json`. It must contain only store
identity, bounded scan roots, polling settings, and optional SQL server
candidates—never passwords, tokens, connection strings, RTSP URLs, or service
account contents.

```powershell
& "C:\ProgramData\JAKASII Ops\Start-JakasiiOps.ps1" -EnableTask
& "C:\ProgramData\JAKASII Ops\Get-JakasiiOpsStatus.ps1"
```

The first cycle establishes baseline cursors for existing rows and camera
events. It does not backfill old records or create stale operational tasks.
Verify that status reports the intended SQL database and camera collector
before approving any system-change action.

## Camera authority

Finding camera configuration is not proof that collection is live. If the
collector is stopped, JAKASII creates one pending approval request. Provision
required secrets only through the hidden Windows Credential Manager prompt on
the main server. Never paste DVR passwords or database credentials into chat,
source files, JSON, batch files, logs, or the Second Brain.

## Stop and rollback

```powershell
& "C:\ProgramData\JAKASII Ops\Stop-JakasiiOps.ps1"
& "C:\ProgramData\JAKASII Ops\Uninstall-JakasiiOps.ps1" -WhatIf
```

Uninstall preserves JAKASII data and store memory unless `-RemoveData` is
explicitly supplied. It never removes POS, SQL Server, Firebase, Supabase, or
camera collector files.
