# Development guide

How to extend wasp-mcp without breaking the v0.1 contract.

## Rule zero: the orchestrator owns PROTOCOL.md

PROTOCOL.md is the **binding wire spec**. The workflow for any wire-level change
is:

1. Propose the change to the orchestrator; the spec is updated first
   (command name, exact parameter keys and casing, result shape, error
   strings).
2. Only then implement it — on **both** sides, C# and Python, against the
   updated spec.

Never "just add a field" on one side. Both `server/` and `GH_MCP_Wasp/` MUST
conform to PROTOCOL.md exactly; deviations are raised to the orchestrator, not
silently implemented. Exact strings matter: the client substring-matches
`solution_running`, and v0.2's feature probe relies on the unknown-command
error text.

## Repo layout

| Path | What | Notes |
|---|---|---|
| `PROTOCOL.md` | Binding wire spec (v0.1 + Addenda v0.1.1 + v0.2-in-development) | Orchestrator-owned |
| `README.md` | Short entry point: install, tool list, quick troubleshooting | Keep short; deep docs live in `docs/` |
| `docs/` | Architecture, tool reference, cookbook, troubleshooting, this file | |
| `server/server.py` | FastMCP stdio server; the 18 `@mcp.tool` definitions | Tool docstrings are what Claude reads |
| `server/gh_client.py` | One-shot TCP transport; typed `BridgeError` codes | |
| `server/registry.py` | `.ghuser` scan/index/fuzzy lookup | |
| `server/macros.py` | Multi-step workflows; candidate-name param matching | |
| `server/tests/` | Offline pytest suite (no Grasshopper needed) | |
| `server/pyproject.toml` | uv project; `wasp-mcp` console script | |
| `GH_MCP_Wasp/` | C# bridge source (net48 class library → `.gha`) | Fork of vendor GH_MCP |
| `GH_MCP_Wasp/Commands/` | One handler class per command family; `GrasshopperCommandRegistry` maps wire names → handlers | Wasp v0.1 commands live in `WaspCommandHandler.cs` |
| `GH_MCP_Wasp/Utils/UiSync.cs` | UI-thread marshalling (TCS + 30 s timeout) | Every canvas touch goes through this |
| `GH_MCP_Wasp/Utils/CanvasUtils.cs` | Document/object/param resolution, goo serialization, layer creation | |
| `build/` | Compiled `GH_MCP_Wasp.gha` | Copy to `%APPDATA%\Grasshopper\Libraries\` |
| `vendor/grasshopper-mcp/` | Upstream reference | **Read-only**, never modified |

## Adding a wire command end-to-end

Worked order (using a hypothetical `set_toggle` as the example — which is in
fact specced for v0.2):

1. **Spec** — add the command to PROTOCOL.md: request shape
   (`{"type": "set_toggle", "parameters": {"id": "guid", "value": true}}`),
   result shape (`{"id": "guid", "value": true}`), error behavior. Get it
   blessed.
2. **C# handler** — add a static method to
   `GH_MCP_Wasp/Commands/WaspCommandHandler.cs` (or a new handler class):
   - Extract parameters via `command.GetParameter<T>("key")` /
     `command.HasParameter("key")` on the worker thread.
   - Wrap all canvas work in `UiSync.OnUi<object>(() => { ... })`.
   - Resolve objects with `CanvasUtils.RequireDocument()` /
     `RequireObject(doc, id)`; throw `ArgumentException` with helpful text on
     bad input (the registry converts exceptions to error envelopes).
   - After mutations, `obj.ExpireSolution(false)` + `doc.ScheduleSolution(10)`.
   - Return a `Dictionary<string, object>` matching the spec'd result shape
     exactly (key casing included). Return a `Response` instance directly only
     when you need a verbatim error envelope (see `solution_running`).
3. **C# registration** — one line in
   `GrasshopperCommandRegistry.Initialize()`:
   `RegisterCommand("set_toggle", WaspCommandHandler.SetToggle);`
4. **Python tool** — add an `@mcp.tool` function in `server/server.py` that
   calls `_call("set_toggle", {...})`. Write the docstring for Claude:
   purpose, args, return shape, error modes. If the tool needs registry or
   composition logic, put that in `registry.py` / `macros.py` and keep
   `server.py` thin.
5. **Tests** — extend `server/tests/`:
   - Transport/envelope behavior against a fake socket bridge
     (see `_serve_once` in `test_offline.py`).
   - Macro wiring logic against `FakeClient` (records every command; asserts
     what got wired where, by param name not index).
   - Registry behavior in `test_registry.py` if lookup rules changed.
6. **Build + install** — rebuild the `.gha`, close Rhino fully, replace the
   copy in Libraries, restart Rhino (the assembly stays loaded for the process
   lifetime — see docs/troubleshooting.md "Upgrading the .gha").
7. **Live validation** — run the checklist below against a real canvas.

## Build and test commands

```powershell
# C# bridge (net48; output copied to ..\build\)
cd GH_MCP_Wasp
dotnet build -c Release

# Python server tests (offline; no Rhino/GH required)
cd server
uv run pytest

# Run the server manually (normally Claude Desktop launches it)
uv run server.py
```

The pytest suite runs entirely offline: fake TCP bridges for transport tests,
a `FakeClient` for macro tests. Two `test_registry.py` tests additionally
validate against the real `%APPDATA%\Grasshopper\UserObjects` when present
(≥40 entries; all macro-dependency keys exist) and auto-skip elsewhere.

## v0.1 validation checklist

Used to reach the v0.1 SHIP verdict; rerun the relevant rows after any change.

| Check | How |
|---|---|
| Wire command names match PROTOCOL exactly | Diff `GrasshopperCommandRegistry.Initialize()` registrations and `server.py` `_call(...)` strings against PROTOCOL.md |
| Parameter keys and casing exact (`sourceId`, `objectIds`, `maxItems`, ...) | Grep both sides; JSON keys are case-sensitive |
| Response envelope | Always `{"success": true, "result": ...}` or `{"success": false, "error": ...}`; newline-terminated, UTF-8, no BOM |
| `solution_running` exact string | Bridge returns it verbatim; Python substring-matches it |
| Threading | No `GH_Document` access outside `UiSync.OnUi`; every handler that mutates schedules a solution; `expire_solution` returns immediately |
| Ports | 8090 default on both sides; `WASP_MCP_PORT` env honored by Python; component Port input honored by C# |
| Connect semantics | `AddSource` (append), name-or-nickname case-insensitive, explicit index wins |
| Registry keys | `key_from_filename` matches PROTOCOL's derivation; macro-dependency keys exist on the target machine |
| Offline tests green | `uv run pytest` |
| Live smoke | canvas state → place basic_part → wire → slider → expire → read output → bake |

## Conventions

- **Python:** every tool returns a dict, never raises to MCP; typed error codes
  (`BridgeError.code`, `component_not_found`, `param_not_found`, ...); no
  hardcoded param indices — match names from `add_user_object` descriptors.
- **C#:** handlers are static, stateless; input validation before `OnUi`;
  errors as exceptions with actionable messages (they become the `error`
  string); enumerate available params in resolution errors.
- **Docs:** wire-visible behavior changes update PROTOCOL.md first,
  then docs/tool-reference.md; keep README the short entry point.
- **v0.2 compat rule:** new Python features that need new bridge commands must
  probe and degrade gracefully against a v0.1 bridge (unknown command → typed
  error → fallback path), because the .gha upgrade requires a Rhino restart and
  the two sides can be out of step.
