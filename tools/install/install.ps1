<#
.SYNOPSIS
    Installs wasp-mcp: the GH_MCP_Wasp Grasshopper bridge + the WaspMCP entry
    in Claude Desktop's config. Idempotent -- safe to re-run.

.DESCRIPTION
    Steps (each skipped or warned, never a hard stop unless a file is truly
    unusable):
      1. Verify Rhino 8 + Grasshopper presence (registry, then default paths).
         Warns but does not fail.
      2. Verify uv is installed; prints the official install command if not.
      3. Copy build\GH_MCP_Wasp.gha -> %APPDATA%\Grasshopper\Libraries\
         (Unblock-File'd; skipped when already identical).
      4. Detect Wasp UserObjects (%APPDATA%\Grasshopper\UserObjects\
         Wasp_*.ghuser); warns with the Food4Rhino link if absent.
      5. Merge a "WaspMCP" server entry into
         %APPDATA%\Claude\claude_desktop_config.json -- other servers are
         preserved, and the existing file is backed up first.
    All paths in the config entry are derived from THIS script's location, so
    the repo can live anywhere.

.PARAMETER Port
    Bridge TCP port. When given (and != 8090) it is written as WASP_MCP_PORT
    in the config entry's env block. Remember to set the WaspMCP component's
    Port input to the same value.

.PARAMETER Token
    Optional shared secret (PROTOCOL.md v0.5). Written as WASP_MCP_TOKEN in
    the config entry's env block. Set the same value on the WaspMCP
    component's Token input.

.PARAMETER ConfigPath
    Claude Desktop config file to merge into. Default:
    %APPDATA%\Claude\claude_desktop_config.json. Override for testing.

.PARAMETER DryRun
    Print every action without writing anything.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\install\install.ps1
.EXAMPLE
    .\install.ps1 -Port 8091 -Token s3cret -DryRun
#>
[CmdletBinding()]
param(
    [int]$Port = 0,
    [string]$Token = "",
    [string]$ConfigPath = "$env:APPDATA\Claude\claude_desktop_config.json",
    [switch]$DryRun
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------- helpers ---
$script:Warnings = @()

function Write-Step([string]$Text)  { Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text)    { Write-Host "    OK  $Text" -ForegroundColor Green }
function Write-Skip([string]$Text)  { Write-Host "    --  $Text" -ForegroundColor DarkGray }
function Write-Warn2([string]$Text) {
    Write-Host "    !!  $Text" -ForegroundColor Yellow
    $script:Warnings += $Text
}
function Write-Act([string]$Text) {
    if ($DryRun) { Write-Host "    [dry-run] would: $Text" -ForegroundColor Magenta }
    else         { Write-Host "    ->  $Text" }
}

if ($DryRun) { Write-Host "DRY RUN -- nothing will be written.`n" -ForegroundColor Magenta }

# Repo root = two levels above this script (tools\install\install.ps1).
$RepoRoot  = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ServerDir = Join-Path $RepoRoot "server"
$GhaSource = Join-Path $RepoRoot "build\GH_MCP_Wasp.gha"

Write-Host "wasp-mcp installer"
Write-Host "  repo root : $RepoRoot"
Write-Host "  config    : $ConfigPath"
Write-Host ""

if (-not (Test-Path (Join-Path $ServerDir "pyproject.toml"))) {
    throw "Cannot find server\pyproject.toml under '$RepoRoot'. Run this script from its checkout location (tools\install\install.ps1)."
}

# ------------------------------------------------- 1. Rhino 8 / Grasshopper ---
Write-Step "Checking Rhino 8 + Grasshopper"
$rhinoPath = $null
try {
    $reg = Get-ItemProperty "HKLM:\SOFTWARE\McNeel\Rhinoceros\8.0\Install" -ErrorAction Stop
    if ($reg.PSObject.Properties['InstallPath'] -and $reg.InstallPath) { $rhinoPath = $reg.InstallPath }
    elseif ($reg.PSObject.Properties['Path'] -and $reg.Path) { $rhinoPath = $reg.Path }
} catch { }
if (-not $rhinoPath) {
    if (Test-Path "C:\Program Files\Rhino 8\System\Rhino.exe") { $rhinoPath = "C:\Program Files\Rhino 8\" }
}
if ($rhinoPath) { Write-Ok "Rhino 8 found at $rhinoPath" }
else { Write-Warn2 "Rhino 8 not detected (registry + default path). Install Rhino 8 from https://www.rhino3d.com/download/ -- the bridge cannot run without it." }

$ghDir = Join-Path $env:APPDATA "Grasshopper"
if (Test-Path $ghDir) { Write-Ok "Grasshopper settings folder present ($ghDir)" }
else { Write-Warn2 "No %APPDATA%\Grasshopper folder -- Grasshopper may never have been launched. Start Rhino, type 'Grasshopper' once, then re-run this installer." }

# ---------------------------------------------------------------- 2. uv ------
Write-Step "Checking uv"
$uvPath = $null
try { $uvPath = (Get-Command uv.exe -ErrorAction Stop).Source } catch { }
if (-not $uvPath) {
    $candidate = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (Test-Path $candidate) { $uvPath = $candidate }
}
if ($uvPath) {
    Write-Ok "uv found at $uvPath"
} else {
    $uvPath = Join-Path $env:USERPROFILE ".local\bin\uv.exe"   # official installer target
    Write-Warn2 "uv not found. Install it with:"
    Write-Host  '        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"' -ForegroundColor Yellow
    Write-Warn2 "The Claude config will reference the default install location ($uvPath); install uv before restarting Claude Desktop."
}

# ------------------------------------------------ 3. bridge .gha deployment ---
Write-Step "Installing GH_MCP_Wasp.gha"
$libDir  = Join-Path $env:APPDATA "Grasshopper\Libraries"
$ghaDest = Join-Path $libDir "GH_MCP_Wasp.gha"
if (-not (Test-Path $GhaSource)) {
    Write-Warn2 "build\GH_MCP_Wasp.gha not found -- build it first: cd GH_MCP_Wasp; dotnet build -c Release. Skipping bridge install."
} else {
    $needCopy = $true
    if (Test-Path $ghaDest) {
        $srcHash = (Get-FileHash $GhaSource -Algorithm SHA256).Hash
        $dstHash = (Get-FileHash $ghaDest  -Algorithm SHA256).Hash
        if ($srcHash -eq $dstHash) {
            Write-Skip "Already up to date in $libDir"
            $needCopy = $false
        }
    }
    if ($needCopy) {
        Write-Act "copy $GhaSource -> $ghaDest (then Unblock-File)"
        if (-not $DryRun) {
            if (-not (Test-Path $libDir)) { New-Item -ItemType Directory -Force -Path $libDir | Out-Null }
            try {
                Copy-Item $GhaSource $ghaDest -Force
                try { Unblock-File $ghaDest -ErrorAction Stop } catch { }
                Write-Ok "Bridge installed to $ghaDest"
            } catch [System.IO.IOException] {
                Write-Warn2 "Could not overwrite $ghaDest -- Rhino is probably running and has the assembly locked. Close Rhino fully (check Task Manager for Rhino.exe) and re-run this installer."
            }
        }
    }
}

# --------------------------------------------------- 4. Wasp UserObjects -----
Write-Step "Checking Wasp plugin (UserObjects)"
$waspFiles = @(Get-ChildItem (Join-Path $env:APPDATA "Grasshopper\UserObjects\Wasp_*.ghuser") -ErrorAction SilentlyContinue)
if ($waspFiles.Count -gt 0) {
    Write-Ok "$($waspFiles.Count) Wasp_*.ghuser components found"
} else {
    Write-Warn2 "No Wasp UserObjects found in %APPDATA%\Grasshopper\UserObjects. Install Wasp from https://www.food4rhino.com/en/app/wasp (the Wasp macro tools need it; low-level gh_* tools work without)."
}

# --------------------------------------- 5. Claude Desktop config merge ------
Write-Step "Merging WaspMCP entry into Claude Desktop config"

# Build the new entry (paths derived from this script's location).
$entry = [pscustomobject]@{
    command = $uvPath
    args    = @("--directory", $ServerDir, "run", "wasp-mcp-server")
}
$envBlock = [ordered]@{}
if ($Port -gt 0)  { $envBlock["WASP_MCP_PORT"]  = "$Port" }
if ($Token -ne "") { $envBlock["WASP_MCP_TOKEN"] = $Token }
if ($envBlock.Count -gt 0) {
    $entry | Add-Member -MemberType NoteProperty -Name env -Value ([pscustomobject]$envBlock)
}

# Load (or initialize) the config. ConvertFrom-Json gives a PSCustomObject in
# PS 5.1, so all membership tests/edits go through PSObject.Properties.
$config = $null
if (Test-Path $ConfigPath) {
    $raw = Get-Content $ConfigPath -Raw
    if ($raw -and $raw.Trim().Length -gt 0) {
        try { $config = $raw | ConvertFrom-Json }
        catch { throw "Existing config at $ConfigPath is not valid JSON -- fix or remove it, then re-run. Nothing was modified." }
    }
}
if ($null -eq $config) { $config = [pscustomobject]@{} }
if (-not $config.PSObject.Properties['mcpServers']) {
    $config | Add-Member -MemberType NoteProperty -Name mcpServers -Value ([pscustomobject]@{})
} elseif ($null -eq $config.mcpServers) {
    $config.mcpServers = [pscustomobject]@{}
}

$otherServers = @($config.mcpServers.PSObject.Properties | Where-Object { $_.Name -ne "WaspMCP" } | ForEach-Object { $_.Name })

# Idempotence: skip the write when the existing entry is already identical.
$identical = $false
if ($config.mcpServers.PSObject.Properties['WaspMCP']) {
    $existingJson = $config.mcpServers.WaspMCP | ConvertTo-Json -Depth 16 -Compress
    $newJson      = $entry | ConvertTo-Json -Depth 16 -Compress
    if ($existingJson -eq $newJson) { $identical = $true }
}

if ($identical) {
    Write-Skip "WaspMCP entry already present and identical -- config untouched"
} else {
    $config.mcpServers | Add-Member -MemberType NoteProperty -Name WaspMCP -Value $entry -Force
    $outJson = $config | ConvertTo-Json -Depth 32

    if (Test-Path $ConfigPath) {
        $backup = "$ConfigPath.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Write-Act "back up config -> $backup"
        if (-not $DryRun) { Copy-Item $ConfigPath $backup -Force }
    }
    Write-Act "write WaspMCP entry to $ConfigPath (preserving: $(if ($otherServers.Count) { $otherServers -join ', ' } else { 'no other servers' }))"
    if ($DryRun) {
        Write-Host "    [dry-run] entry that would be written:" -ForegroundColor Magenta
        ($entry | ConvertTo-Json -Depth 16) -split "`n" | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
    } else {
        $configDir = Split-Path -Parent $ConfigPath
        if (-not (Test-Path $configDir)) { New-Item -ItemType Directory -Force -Path $configDir | Out-Null }
        # PS 5.1 Out-File defaults to UTF-16; write UTF-8 without BOM explicitly.
        [System.IO.File]::WriteAllText($ConfigPath, $outJson, (New-Object System.Text.UTF8Encoding($false)))
        Write-Ok "Config written ($ConfigPath)"
    }
}

# ------------------------------------------------------------ summary --------
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " Install $(if ($DryRun) { 'dry run ' })complete" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
if ($script:Warnings.Count -gt 0) {
    Write-Host " Warnings ($($script:Warnings.Count)):" -ForegroundColor Yellow
    $script:Warnings | ForEach-Object { Write-Host "   - $_" -ForegroundColor Yellow }
    Write-Host ""
}
Write-Host " Next steps:"
Write-Host "   1. Restart the Claude desktop app (it reads the config at startup)."
Write-Host "   2. Start Rhino 8, open Grasshopper."
Write-Host "   3. Drop the 'Wasp MCP Bridge (WaspMCP)' component (Params > Util)"
Write-Host "      on the canvas and set its Enabled input to true."
if ($Port -gt 0) {
    Write-Host "   4. Set the component's Port input to $Port (you passed -Port $Port)."
}
if ($Token -ne "") {
    Write-Host "   *  Set the component's Token input to the same value you passed via -Token."
}
Write-Host "   -> Ask Claude to 'list wasp components' to smoke-test the chain."
Write-Host ""
Write-Host " Bridge listens on 127.0.0.1:$(if ($Port -gt 0) { $Port } else { 8090 }) (default 8090; see README 'Ports & auth')."
