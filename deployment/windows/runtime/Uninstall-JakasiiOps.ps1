[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "config.json"),
    [switch]$RemoveData
)

$ErrorActionPreference = "Stop"
$config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
$taskName = [string]$config.task_name
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$installRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$dataRoot = [System.IO.Path]::GetFullPath([string]$config.data_root)
if ($RemoveData -and $PSCmdlet.ShouldProcess($dataRoot, "Remove JAKASII Ops data and store memory")) {
    if ($dataRoot.Length -lt 10 -or $dataRoot -eq [System.IO.Path]::GetPathRoot($dataRoot)) { throw "Refusing unsafe data path." }
    Remove-Item -LiteralPath $dataRoot -Recurse -Force
}
if ($PSCmdlet.ShouldProcess($installRoot, "Remove JAKASII Ops isolated runtime")) {
    if ($installRoot.Length -lt 10 -or $installRoot -eq [System.IO.Path]::GetPathRoot($installRoot)) { throw "Refusing unsafe install path." }
    Remove-Item -LiteralPath $installRoot -Recurse -Force
}
