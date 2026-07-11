# wasp-mcp

Claude (or any MCP client) places and wires **Wasp** discrete-aggregation
components — and general Grasshopper definitions — on a live Grasshopper
canvas, with evidence-backed component knowledge, legible auto-organized
output, and viewport capture so the model can see what it made.

```
Claude ── MCP (stdio) ── server/ (Python FastMCP, uv)
                            │  TCP 127.0.0.1:8090 (JSON, see PROTOCOL.md)
                      GH_MCP_Wasp.gha — "WaspMCP" component on the GH canvas
                            │  GH_Document API, UI-thread marshalled
                      Grasshopper canvas ← Wasp .ghuser components
```

Two halves, installed separately: a **Grasshopper plugin** (the bridge) and a
**Python MCP server** (what Claude talks to). Both are covered below.

## What you need first

| Requirement | Needed for | How to get it |
|---|---|---|
| Windows + **Rhino 8** | the canvas (Grasshopper is included in Rhino) | [rhino3d.com](https://www.rhino3d.com/download/) — 90-day trial works |
| **Claude Desktop** | the AI driving the canvas (any MCP client works; instructions below assume Claude Desktop) | [claude.ai/download](https://claude.ai/download) — free tier is fine |
| **uv** | running the Python server | in PowerShell: `irm https://astral.sh/uv/install.ps1 \| iex` (the installer in Step 2 checks this and prints the command if missing) |
| **Wasp** *(optional)* | the aggregation workflows (`create_wasp_part`, `run_aggregation`, …). General Grasshopper control and the architectural templates work without it | [Food4Rhino](https://www.food4rhino.com/en/app/wasp) (free account) → download → drag the installer onto Rhino |

## Step 1 — Install the bridge plugin (Grasshopper side)

In Rhino 8, type `_PackageManager`, search for **`wasp-mcp-bridge`**, click
**Install**, restart Rhino. Done.

<details>
<summary>Manual alternative (no Package Manager)</summary>

Download `GH_MCP_Wasp.gha` from the
[latest release](https://github.com/liangjunglj-cpu/wasp-mcp/releases/latest),
copy it to `%APPDATA%\Grasshopper\Libraries\`, right-click it in Explorer →
Properties → **Unblock**, restart Rhino.
</details>

## Step 2 — Install the MCP server (Claude side)

Clone this repo (or download and extract the release source zip), then from
the repo root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File tools\install\install.ps1
```

The installer is idempotent (safe to re-run) and:

- verifies Rhino 8 / Grasshopper / uv / Wasp (warns, never blocks),
- installs the bridge `.gha` if Step 1 was skipped,
- adds a `WaspMCP` entry to `%APPDATA%\Claude\claude_desktop_config.json`,
  pointing at wherever this repo lives — your other MCP servers are preserved
  and the config is backed up first.

**Don't move or delete the repo folder afterwards** — the server runs from it.

Options: `-Port <n>` / `-Token <secret>` (see "Ports & auth"), `-DryRun`
(print everything, write nothing). `tools\install\uninstall.ps1` reverses
everything.

Finally, **restart the Claude desktop app** (fully quit from the system tray —
closing the window is not enough) so it picks up the new server.

<details>
<summary>Manual alternative (edit the config yourself)</summary>

Add this entry under `mcpServers` in
`%APPDATA%\Claude\claude_desktop_config.json`, with both paths expanded to
real absolute paths (Claude Desktop does not expand environment variables):

```json
"WaspMCP": {
  "command": "C:\\Users\\<you>\\.local\\bin\\uv.exe",
  "args": ["--directory", "C:\\path\\to\\wasp-mcp\\server", "run", "wasp-mcp-server"]
}
```

Then restart the Claude desktop app.
</details>

## Step 3 — Put the bridge on the canvas and switch it on

The bridge only runs while its component sits on a Grasshopper canvas with
`Enabled` set to true:

1. Open **Rhino 8**, type `Grasshopper` to open the canvas.
2. Double-click any empty canvas space, type **`WaspMCP`**, and click
   **Wasp MCP Bridge** to drop it. (It also lives in the component panel
   under **Params → Util**.)
3. Add a toggle for its on/off switch: double-click empty canvas again, type
   **`toggle`**, pick **Boolean Toggle** (Params → Input) and drop it left of
   the bridge component.
4. Wire the toggle's output into the bridge's **`Enabled`** input (drag from
   the toggle's right-side nub to the input's left-side nub).
5. Double-click the toggle's **False** label so it flips to **True**. The
   bridge component now reports that it is listening on `127.0.0.1:8090`.

**Verify end-to-end**: in Claude Desktop, ask *"check the wasp-mcp canvas
state"* — you should get back a component list and a version string. If Wasp
is installed, try *"list the wasp components on this machine"*, or go
straight to *"build a stochastic aggregation from a simple box part"*.

## Every session after that

Rhino 8 + Grasshopper open, the WaspMCP component on the canvas with the
toggle at True (save it in a template file so it's one double-click).
Everything else is automatic.

## Ports & auth (PROTOCOL v0.5)

- The bridge listens on **localhost TCP, default port 8090**. To change it,
  set the component's `Port` input **and** `WASP_MCP_PORT` in the config
  entry's `env` block to the same value (`install.ps1 -Port <n>` writes the
  latter for you).
- Optional shared-secret auth: set the component's `Token` input and
  `WASP_MCP_TOKEN` in the config entry's `env` block to the same value
  (`install.ps1 -Token <secret>`). Empty/absent token = open access
  (localhost only either way).

## Tool surface

- `list_wasp_components` / `refresh_registry` — discover installed Wasp components
- `gh_add_wasp_component`, `gh_add_component`, `gh_connect`, `gh_set_slider`,
  `gh_set_panel`, `gh_set_geometry_ref`, `gh_set_plane_values`, `gh_set_toggle`,
  `gh_get_output`, `gh_canvas_state`, `gh_expire`, `gh_wait_idle`, `gh_bake`,
  `gh_delete`, `gh_clear`, `gh_save`, `gh_group`, `gh_scribble`,
  `gh_set_nickname`, `gh_workflow_note`, `gh_list_component_types`,
  `gh_component_schema` — canvas control and introspection
- `create_wasp_part`, `define_rules`, `run_aggregation`, `get_aggregation`,
  `reset_aggregation` — high-level Wasp macros (one call = a wired subgraph)
- `list_templates`, `expand_template` — evidence-backed architectural stage
  templates (attractor grids, trusses, contours, …)
- `gh_capture_viewport`, `gh_capture_canvas` — let the model see the result

## Docs

- [docs/architecture.md](docs/architecture.md) — processes, threading, design decisions
- [docs/tool-reference.md](docs/tool-reference.md) — every tool: params, return shapes, errors
- [docs/cookbook.md](docs/cookbook.md) — copy-paste Wasp workflow prompts + rule-grammar primer
- [docs/troubleshooting.md](docs/troubleshooting.md) — expanded fixes (ports, timeouts, .gha upgrades)
- [docs/development.md](docs/development.md) — extending the system; PROTOCOL.md stays the binding spec

## Layout

| Path | What |
|---|---|
| `PROTOCOL.md` | binding wire spec |
| `server/` | Python MCP server |
| `GH_MCP_Wasp/` | C# bridge source (net48) |
| `build/` | compiled `.gha` |
| `tools/install/` | install.ps1 / uninstall.ps1 |
| `tools/yak/` | Yak package manifest + build script |

## Rebuild the bridge

```powershell
cd GH_MCP_Wasp
dotnet build -c Release
```

(`tools\yak\build-yak.ps1` stages and builds the Yak package from
`build\GH_MCP_Wasp.gha` — only needed if you're publishing your own build;
the released package is already on the Rhino package server.)

## Troubleshooting

- `bridge_unreachable` — WaspMCP component not on canvas / toggle not True /
  Grasshopper not open.
- Nothing in `_PackageManager` search — the package requires Rhino 8 on
  Windows; update Rhino if you're on an early service release.
- Port conflict — set `WASP_MCP_PORT` env var for the server AND the
  component's Port input to a matching value (default 8090).
- Stale registry after installing a new Wasp version — call `refresh_registry`.

## Licensing

Code is [MIT](LICENSE). The knowledge-base data files under
`server/knowledge/` are free to use with wasp-mcp but not redistributable —
see [server/knowledge/LICENSE-KNOWLEDGE.md](server/knowledge/LICENSE-KNOWLEDGE.md).
Third-party attributions: [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
