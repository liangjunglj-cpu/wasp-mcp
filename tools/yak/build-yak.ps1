<#
.SYNOPSIS
    Stages and builds the wasp-mcp-bridge Yak package (rh8-win) from
    build\GH_MCP_Wasp.gha + tools\yak\manifest.yml.

.DESCRIPTION
    - Stages the .gha and manifest into tools\yak\dist\.
    - If the Yak CLI is present (Rhino 8 ships it at
      C:\Program Files\Rhino 8\System\Yak.exe), runs `yak build --platform win`
      in the staging folder, producing wasp-mcp-bridge-0.5.0-rh8-win.yak.
    - If Yak is absent, just stages the folder and prints the command to run.
    Does NOT publish anything; pushing to the package server is a deliberate
    manual step (yak push <file>.yak).

.PARAMETER YakExe
    Path to Yak.exe. Default probes the Rhino 8 install.
#>
[CmdletBinding()]
param(
    [string]$YakExe = "C:\Program Files\Rhino 8\System\Yak.exe"
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$RepoRoot  = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$GhaSource = Join-Path $RepoRoot "build\GH_MCP_Wasp.gha"
$Manifest  = Join-Path $PSScriptRoot "manifest.yml"
$Dist      = Join-Path $PSScriptRoot "dist"

if (-not (Test-Path $GhaSource)) {
    throw "build\GH_MCP_Wasp.gha not found. Build it first: cd $RepoRoot\GH_MCP_Wasp; dotnet build -c Release"
}
if (-not (Test-Path $Manifest)) {
    throw "manifest.yml not found next to this script ($Manifest)."
}

# Stage: clean dist folder with exactly the package contents.
if (Test-Path $Dist) { Remove-Item $Dist -Recurse -Force -Confirm:$false }
New-Item -ItemType Directory -Path $Dist | Out-Null
Copy-Item $GhaSource $Dist
Copy-Item $Manifest  $Dist
Write-Host "Staged package contents in $Dist" -ForegroundColor Green
Get-ChildItem $Dist | ForEach-Object { Write-Host "  $($_.Name)  ($($_.Length) bytes)" }

# Probe alternate Yak locations if the default is missing.
if (-not (Test-Path $YakExe)) {
    $alt = @(
        "C:\Program Files\Rhino 8\System\yak.exe",
        "$env:ProgramFiles\Rhino 8\System\Yak.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($alt) { $YakExe = $alt }
}

if (Test-Path $YakExe) {
    Write-Host "`nRunning Yak CLI: $YakExe build --platform win" -ForegroundColor Cyan
    Push-Location $Dist
    try {
        & $YakExe build --platform win
        $exit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($exit -ne 0) { throw "yak build failed with exit code $exit" }
    $package = Get-ChildItem (Join-Path $Dist "*.yak") | Select-Object -First 1
    if ($package) {
        Write-Host "`nPackage built: $($package.FullName)" -ForegroundColor Green
        Write-Host "To publish later (deliberate manual step):"
        Write-Host "  & `"$YakExe`" login"
        Write-Host "  & `"$YakExe`" push `"$($package.FullName)`""
    } else {
        Write-Host "yak build reported success but no .yak found in $Dist -- check output above." -ForegroundColor Yellow
    }
} else {
    Write-Host "`nYak CLI not found (looked at $YakExe)." -ForegroundColor Yellow
    Write-Host "The package folder is staged. On a machine with Rhino 8, run:"
    Write-Host "  cd `"$Dist`""
    Write-Host "  & `"C:\Program Files\Rhino 8\System\Yak.exe`" build --platform win"
    Write-Host "Expected output: wasp-mcp-bridge-0.5.0-rh8-win.yak"
}
