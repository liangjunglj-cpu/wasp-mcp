<#
.SYNOPSIS
    Uninstalls wasp-mcp: removes the bridge .gha from Grasshopper Libraries
    and the "WaspMCP" entry from Claude Desktop's config.

.DESCRIPTION
    Leaves everything else alone: other MCP servers in the config, the Wasp
    plugin UserObjects, uv, and this repo. The config is backed up before it
    is modified. Idempotent -- safe to re-run.

.PARAMETER ConfigPath
    Claude Desktop config file. Default:
    %APPDATA%\Claude\claude_desktop_config.json. Override for testing.

.PARAMETER DryRun
    Print every action without writing anything.
#>
[CmdletBinding()]
param(
    [string]$ConfigPath = "$env:APPDATA\Claude\claude_desktop_config.json",
    [switch]$DryRun
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Write-Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text)   { Write-Host "    OK  $Text" -ForegroundColor Green }
function Write-Skip([string]$Text) { Write-Host "    --  $Text" -ForegroundColor DarkGray }
function Write-Warn2([string]$Text){ Write-Host "    !!  $Text" -ForegroundColor Yellow }
function Write-Act([string]$Text) {
    if ($DryRun) { Write-Host "    [dry-run] would: $Text" -ForegroundColor Magenta }
    else         { Write-Host "    ->  $Text" }
}

if ($DryRun) { Write-Host "DRY RUN -- nothing will be written.`n" -ForegroundColor Magenta }

# --------------------------------------------------- 1. remove the .gha ------
Write-Step "Removing GH_MCP_Wasp.gha from Grasshopper Libraries"
$ghaDest = Join-Path $env:APPDATA "Grasshopper\Libraries\GH_MCP_Wasp.gha"
if (Test-Path $ghaDest) {
    Write-Act "delete $ghaDest"
    if (-not $DryRun) {
        try {
            Remove-Item $ghaDest -Force -Confirm:$false
            Write-Ok "Removed"
        } catch [System.IO.IOException] {
            Write-Warn2 "Could not delete $ghaDest -- Rhino is probably running and has the assembly locked. Close Rhino fully and re-run."
        } catch [System.UnauthorizedAccessException] {
            Write-Warn2 "Could not delete $ghaDest -- Rhino is probably running and has the assembly locked. Close Rhino fully and re-run."
        }
    }
} else {
    Write-Skip "Not installed ($ghaDest)"
}

# --------------------------------- 2. remove the WaspMCP config entry --------
Write-Step "Removing WaspMCP entry from Claude Desktop config"
if (-not (Test-Path $ConfigPath)) {
    Write-Skip "No config at $ConfigPath"
} else {
    $raw = Get-Content $ConfigPath -Raw
    $config = $null
    if ($raw -and $raw.Trim().Length -gt 0) {
        try { $config = $raw | ConvertFrom-Json }
        catch { Write-Warn2 "Config at $ConfigPath is not valid JSON -- not touching it."; $config = $null }
    }
    $hasEntry = $false
    if ($null -ne $config -and $config.PSObject.Properties['mcpServers'] -and $null -ne $config.mcpServers) {
        if ($config.mcpServers.PSObject.Properties['WaspMCP']) { $hasEntry = $true }
    }
    if (-not $hasEntry) {
        Write-Skip "No WaspMCP entry present -- config untouched"
    } else {
        $others = @($config.mcpServers.PSObject.Properties | Where-Object { $_.Name -ne "WaspMCP" } | ForEach-Object { $_.Name })
        $backup = "$ConfigPath.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Write-Act "back up config -> $backup"
        Write-Act "remove mcpServers.WaspMCP (preserving: $(if ($others.Count) { $others -join ', ' } else { 'no other servers' }))"
        if (-not $DryRun) {
            Copy-Item $ConfigPath $backup -Force
            $config.mcpServers.PSObject.Properties.Remove('WaspMCP')
            $outJson = $config | ConvertTo-Json -Depth 32
            [System.IO.File]::WriteAllText($ConfigPath, $outJson, (New-Object System.Text.UTF8Encoding($false)))
            Write-Ok "Config written ($ConfigPath)"
        }
    }
}

# ------------------------------------------------------------ summary --------
Write-Host ""
Write-Host "Uninstall $(if ($DryRun) { 'dry run ' })complete." -ForegroundColor Cyan
Write-Host "Left untouched on purpose:"
Write-Host "  - Wasp UserObjects (%APPDATA%\Grasshopper\UserObjects\Wasp_*.ghuser)"
Write-Host "  - uv and this repo checkout"
Write-Host "  - every other server in the Claude config"
Write-Host "Restart the Claude desktop app and Rhino for the removal to take effect."
