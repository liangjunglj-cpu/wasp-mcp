# wasp-mcp

Claude places and wires **Wasp** components on a live Grasshopper canvas via MCP.

```
Claude ── MCP (stdio) ── server/ (Python FastMCP, uv)
                            │  TCP 127.0.0.1:8090 (JSON, see PROTOCOL.md)
                      GH_MCP_Wasp.gha — "WaspMCP" component on the GH canvas
                            │  GH_Document API, UI-thread marshalled
                      Grasshopper canvas ← Wasp .ghuser components (63 installed)
```

## Install (about 5 minutes)

Prerequisites: Windows, **Rhino 8** (Grasshopper included), the **Wasp** plugin
([Food4Rhino](https://www.food4rhino.com/en/app/wasp)), the Claude desktop app,
and [uv](https://docs.astral.sh/uv/) (the installer offers the install command
if it's missing).

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File tools\install\install.ps1
```

The installer is idempotent (safe to re-run) and:

- verifies Rhino 8 / Grasshopper / uv / Wasp UserObjects (warns, never blocks),
- copies `build\GH_MCP_Wasp.gha` to `%APPDATA%\Grasshopper\Libraries\`
  (with `Unblock-File`),
- merges a `WaspMCP` entry into `%APPDATA%\Claude\claude_desktop_config.json`
  using paths derived from wherever this repo lives — other MCP servers are
  preserved and the config is backed up first.

Options: `-Port <n>` / `-Token <secret>` (see "Ports & auth" below),
`-DryRun` (print everything, write nothing). `tools\install\uninstall.ps1`
reverses both steps.

Then: restart the Claude desktop app, open Rhino 8 + Grasshopper, drop the
**Wasp MCP Bridge (WaspMCP)** component (Params > Util) on the canvas, and set
its `Enabled` input to true. It listens on `127.0.0.1:8090`.

### Manual fallback (one line each)

1. Copy the bridge (then unblock via Explorer > Properties if quarantined):
   `copy build\GH_MCP_Wasp.gha %APPDATA%\Grasshopper\Libraries\`
2. Add this entry under `mcpServers` in
   `%APPDATA%\Claude\claude_desktop_config.json` (adjust to where you cloned
   the repo; uv's default install path shown):

```json
"WaspMCP": {
  "command": "%USERPROFILE%\\.local\\bin\\uv.exe",
  "args": ["--directory", "%USERPROFILE%\\path\\to\\wasp-mcp\\server", "run", "wasp-mcp-server"]
}
```

(Expand the `%USERPROFILE%` placeholders to real absolute paths — Claude
Desktop does not expand environment variables in `command`/`args`.)

3. Restart the Claude desktop app.

### Yak package (alternative bridge install)

`tools\yak\build-yak.ps1` stages and builds `wasp-mcp-bridge-0.5.0-rh8-win.yak`
from `build\GH_MCP_Wasp.gha` using Rhino 8's bundled Yak CLI. Install a built
package with Rhino's `_PackageManager` (it covers only the .gha — the MCP
server config entry still comes from the installer or the manual step above).

## Ports & auth (PROTOCOL v0.5)

- The bridge listens on **localhost TCP, default port 8090**. To change it,
  set the component's `Port` input **and** `WASP_MCP_PORT` in the config
  entry's `env` block to the same value (`install.ps1 -Port <n>` writes the
  latter for you).
- Optional shared-secret auth: set the component's `Token` input and
  `WASP_MCP_TOKEN` in the config entry's `env` block to the same value
  (`install.ps1 -Token <secret>`). Empty/absent token = open access
  (localhost only either way).

## Every session

Rhino 8 + Grasshopper open, WaspMCP component on the canvas, enabled. Everything
else is automatic.

## Tool surface

- `list_wasp_components` / `refresh_registry` — discover installed Wasp components
- `gh_add_wasp_component`, `gh_add_component`, `gh_connect`, `gh_set_slider`,
  `gh_set_panel`, `gh_set_geometry_ref`, `gh_get_output`, `gh_canvas_state`,
  `gh_expire`, `gh_bake`, `gh_clear`, `gh_save` — low-level canvas control
- `create_wasp_part`, `define_rules`, `run_aggregation`, `get_aggregation` —
  high-level Wasp macros (one call = a wired subgraph)

## Docs

- [docs/architecture.md](docs/architecture.md) — processes, threading, design decisions
- [docs/tool-reference.md](docs/tool-reference.md) — all 18 tools: params, return shapes, errors
- [docs/cookbook.md](docs/cookbook.md) — copy-paste Wasp workflow prompts + rule-grammar primer
- [docs/troubleshooting.md](docs/troubleshooting.md) — expanded fixes (ports, timeouts, .gha upgrades)
- [docs/development.md](docs/development.md) — extending the system; PROTOCOL.md stays the binding spec

## Layout

| Path | What | Owner |
|---|---|---|
| `PROTOCOL.md` | binding wire spec | orchestrator |
| `server/` | Python MCP server | Agent A |
| `GH_MCP_Wasp/` | C# bridge source (net48) | Agent B |
| `build/` | compiled `.gha` | Agent B |
| `tools/install/` | install.ps1 / uninstall.ps1 | Agent C |
| `tools/yak/` | Yak package manifest + build script | Agent C |
| `vendor/grasshopper-mcp/` | upstream reference (read-only) | — |

## Rebuild the bridge

```powershell
cd GH_MCP_Wasp
dotnet build -c Release
```

## Troubleshooting

- `bridge_unreachable` — WaspMCP component not on canvas / not enabled / GH not open.
- Port conflict — set `WASP_MCP_PORT` env var for the server AND the component's
  port input to a matching value (default 8090; Almond Rhino bridge uses 5000).
- Stale registry after installing new Wasp version — call `refresh_registry`.
