[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "..\..\dist"),
    [string]$PythonCommand
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$outputRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
$expectedOutputRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "dist"))
if (-not $outputRoot.StartsWith($expectedOutputRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDirectory must remain inside $expectedOutputRoot"
}

function Resolve-Python {
    param([string]$Requested)
    $candidates = @()
    if ($Requested) {
        $candidates += (Get-Command $Requested -ErrorAction Stop).Source
    } else {
        foreach ($candidate in @("python.exe", "python")) {
            $resolved = Get-Command $candidate -ErrorAction SilentlyContinue
            if ($resolved) { $candidates += $resolved.Source }
        }
        $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
        if (Test-Path -LiteralPath $venvPython) { $candidates += $venvPython }
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        & $candidate -c "import setuptools.build_meta" 2>$null
        if ($LASTEXITCODE -eq 0) { return $candidate }
    }
    throw "Python 3.11+ with setuptools.build_meta was not found."
}

$python = Resolve-Python $PythonCommand
$versionText = & $python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if ($LASTEXITCODE -ne 0 -or [version]$versionText -lt [version]"3.11") {
    throw "Python 3.11+ is required to build the package. Found: $versionText"
}

$stage = Join-Path $outputRoot "jakasii-ops-mainserver"
$zip = Join-Path $outputRoot "jakasii-ops-mainserver.zip"
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
New-Item -ItemType Directory -Force -Path (Join-Path $stage "wheelhouse") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $stage "scripts") | Out-Null

& $python -m pip wheel --no-deps --no-build-isolation --wheel-dir (Join-Path $stage "wheelhouse") $repoRoot
if ($LASTEXITCODE -ne 0) { throw "Building the offline JAKASII Ops wheel failed." }

Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot "runtime") -File | Copy-Item -Destination (Join-Path $stage "scripts") -Force
Copy-Item -LiteralPath (Join-Path $repoRoot "LICENSE") -Destination $stage
Copy-Item -LiteralPath (Join-Path $repoRoot "README.md") -Destination $stage
Copy-Item -LiteralPath (Join-Path $repoRoot "docs\MAIN_SERVER_DEPLOYMENT.md") -Destination $stage

$gitCommit = (& git -C $repoRoot rev-parse HEAD 2>$null)
$gitDirty = [bool](& git -C $repoRoot status --porcelain 2>$null)
$files = Get-ChildItem -LiteralPath $stage -Recurse -File | Sort-Object FullName | ForEach-Object {
    [ordered]@{
        path = $_.FullName.Substring($stage.Length + 1).Replace("\", "/")
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        bytes = $_.Length
    }
}
$manifest = [ordered]@{
    protocol = "jakasii.mainserver.package.v1"
    built_at = [DateTimeOffset]::UtcNow.ToString("o")
    python = $versionText
    git_commit = [string]$gitCommit
    git_worktree_dirty = $gitDirty
    contains_secrets = $false
    contains_production_data = $false
    files = $files
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $stage "manifest.json") -Encoding UTF8

Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -CompressionLevel Optimal
$zipHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
[ordered]@{
    package = $zip
    sha256 = $zipHash
    bytes = (Get-Item -LiteralPath $zip).Length
    git_worktree_dirty = $gitDirty
    next_step = "Copy the ZIP to the main server, extract it, then run scripts\Install-JakasiiOps.ps1 in PowerShell."
} | ConvertTo-Json
