# Architecture

wasp-mcp lets Claude place and wire [Wasp](https://github.com/ar0551/Wasp) discrete-aggregation
components on a live Grasshopper canvas. Three processes cooperate; PROTOCOL.md is the
binding contract between the two halves this repo owns.

## System diagram

```
┌────────────────────┐  MCP (stdio, JSON-RPC)  ┌─────────────────────────────┐
│  Claude Desktop    │◄───────────────────────►│  server/  (Python, FastMCP) │
│  (MCP client)      │                         │  server.py   18 tools       │
└────────────────────┘                         │  registry.py .ghuser index  │
                                               │  macros.py   workflows      │
                                               │  gh_client.py TCP transport │
                                               └──────────────┬──────────────┘
                                                              │ TCP 127.0.0.1:8090
                                                              │ one JSON command per
                                                              │ connection (PROTOCOL.md)
┌─────────────────────────────────────────────────────────────┴──────────────┐
│  Rhino 8 process                                                           │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │ Grasshopper                                                           │ │
│  │  ┌──────────────────────────┐      ┌────────────────────────────────┐ │ │
│  │  │ GH_MCP_Wasp.gha          │ UI-  │ GH canvas                      │ │ │
│  │  │ "WaspMCP" component      │thread│  Wasp .ghuser components       │ │ │
│  │  │  TCP listener (8090)     │─────►│  (63 installed), panels,       │ │ │
│  │  │  command registry        │calls │  sliders, params, wires        │ │ │
│  │  └──────────────────────────┘      └────────────────────────────────┘ │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│  Rhino document (referenced geometry in, baked geometry out)               │
└─────────────────────────────────────────────────────────────────────────────┘
```

## The three processes

| Process | Role | Talks to |
|---|---|---|
| Claude Desktop | MCP client; decides which tools to call | Python server via stdio |
| `server/` (Python, launched by Claude Desktop via `uv run server.py`) | Exposes 18 MCP tools; resolves Wasp names to `.ghuser` paths; composes multi-step macros; translates tool calls into wire commands | Bridge via one-shot TCP connections to `127.0.0.1:8090` |
| Rhino 8 + Grasshopper hosting `GH_MCP_Wasp.gha` | The "WaspMCP" canvas component runs a TCP listener; command handlers mutate/read the `GH_Document` and the Rhino document | Grasshopper/Rhino APIs on the UI thread |

The Python server holds no persistent socket: `gh_client.GHClient` opens a fresh
connection per command, sends one newline-terminated JSON object, reads one JSON
response, and closes. This keeps the bridge stateless per request and means a
Rhino restart never leaves the server holding a dead socket.

## Threading model (C# side)

Grasshopper's `GH_Document` is not thread-safe and must only be touched from the
Rhino UI thread. The bridge enforces a strict two-layer model
(`WaspMCPComponent.cs`, `Utils/UiSync.cs`):

1. **TCP layer (thread pool).** `Start()` launches `ListenerLoop` as a `Task`;
   each accepted client is handled on its own thread-pool task
   (`HandleClient`). These threads parse JSON and dispatch through
   `GrasshopperCommandRegistry.ExecuteCommand`, but **never** touch
   `GH_Document` directly.
2. **UI layer.** Every handler wraps its canvas work in `UiSync.OnUi(func)`,
   which posts the closure to the Rhino UI thread via
   `RhinoApp.InvokeOnUiThread` and blocks the *worker* thread on a
   `TaskCompletionSource` until the result (or exception) is marshalled back.
   A **30 s timeout** (`UiSync.DefaultTimeoutMs`) turns a stuck UI thread into a
   `TimeoutException` → error response, so the bridge can never hang a client
   indefinitely.

Consequence worth knowing: while a long Grasshopper solve occupies the UI
thread, *any* command's `OnUi` call waits behind it. A read issued mid-solve
therefore surfaces either as the explicit `solution_running` error (if the
handler got onto the UI thread and observed the state) or as a
"timed out after 30 s" error (if it never got on). The Python macro layer
treats both as retryable (`macros.get_output_when_idle`).

Serialization is pinned: the component uses a private
`JsonSerializerSettings` instance so another plugin mutating
`JsonConvert.DefaultSettings` in the shared Rhino process cannot change the
wire format, and responses are written with `UTF8Encoding(false)` — no BOM,
newline-terminated.

## Why the registry exists

Wasp ships as ~63 `.ghuser` UserObject files, not as a compiled `.gha`. That has
two consequences:

- **No stable component GUIDs.** Compiled Grasshopper components can be
  instantiated by their `ComponentGuid` via the component server. UserObjects
  are GhPython scripts wrapped in a file; the reliable way to place one is
  `new GH_UserObject(path).InstantiateObject()` — which needs the *file path*.
- **Names are messy.** Filenames mix spaces, hyphens and casing
  (`Wasp_Field-driven Aggregation.ghuser`), and Claude will ask for
  "stochastic" or "Basic Part" rather than exact filenames.

`registry.py` bridges the gap: it scans `%APPDATA%\Grasshopper\UserObjects` for
`Wasp_*.ghuser`, derives a deterministic key per file (lowercase, strip
`Wasp_`/`.ghuser`, spaces/hyphens → underscores: `basic_part`,
`stochastic_aggregation`, ...), guesses a category
(part/connection/rule/aggregation/field/disco/util) from keywords, and resolves
lookups with layered fuzzy matching (exact key → substring → token subset →
difflib). Failed lookups return typed `component_not_found` errors with
suggestions instead of guessing. After a component is placed once, its real
input/output param descriptors are cached on the registry entry so
`list_wasp_components` can document them.

## Design decisions and why

| Decision | Reason |
|---|---|
| **Port 8090** | 8080 is the stock grasshopper-mcp default — avoid a clash if the user runs both; 5000 is taken by the Almond Rhino bridge on this machine (48884 by Revit MCP). Overridable via `WASP_MCP_PORT` env var + the component's Port input. |
| **Append, don't replace, on connect** (`connect_by_name` calls `target.AddSource(source)`) | Wasp workflows routinely merge many sources into one input — several part outputs into an aggregation's PART input, several rules into RULES. Replace semantics would silently drop previously wired parts. |
| **`solution_running` contract** | `get_component_output` and `bake_component_output` must never return stale or half-computed data. The handler refuses with the exact error string `"solution_running"` when (a) the document's `SolutionDepth > 0` / `SolutionState == Process`, or (b) the target param's phase is `Blank` (expired, scheduled solve not fired yet — an empty "success" here would be stale data disguised as an answer). The Python client substring-matches this string and retries with delay. `expire_solution` correspondingly returns `{"scheduled": true}` immediately rather than blocking until the solve finishes. |
| **UserObject instantiation via `add_user_object` (path-based) instead of GUID components** | See "Why the registry exists": Wasp components are `.ghuser` UserObjects without stable component-server GUIDs. `add_user_object` takes an absolute file path and returns the instance GUID plus full `inputs`/`outputs` descriptors so callers wire by real param names, never by assumed indices. |
| **Param resolution by name *or* nickname, case-insensitive, index override** | Wasp param nicknames differ across versions ("PART" vs "Parts"). Macros read the descriptors returned by `add_user_object` and match against candidate lists (`macros.match_param`); when the source component wasn't placed by us, `connect_with_candidates` simply tries candidates until the bridge accepts one. |
| **One command per TCP connection** | Inherited from the upstream baseline; keeps both ends trivially stateless and immune to framing bugs. Cost (a localhost TCP handshake per call) is negligible against Grasshopper solve times. |
| **`clear_document` preserves the bridge** | Clearing the canvas must not sever the MCP connection, so the handler skips the WaspMCP component and (heuristically) objects whose nickname/type mentions MCP/Claude/Toggle/Status. |
| **Explicit registry of wire commands** | `GrasshopperCommandRegistry` maps command-name strings to handlers; handlers may return a plain object (wrapped in `{"success": true, "result": ...}`) or a pre-built `Response` (passed through verbatim — how `solution_running` keeps its exact wire shape). Unknown commands return a typed error, which v0.2's probe-and-fallback strategy relies on. |

## Lineage

`GH_MCP_Wasp/` is a fork of the `GH_MCP` component from
[grasshopper-mcp](https://github.com/alfredatnycu/grasshopper-mcp), vendored
read-only under `vendor/grasshopper-mcp/`. The fork keeps the upstream baseline
commands (`add_component`, `connect_components`, document commands, the
intent/pattern system) and adds the Wasp command set, a hardened threading model
(`UiSync` replaces direct document access), real `save_document`/`load_document`
implementations, and the port move to 8090. Credit to the upstream authors for
the original bridge design; nothing in `vendor/` is modified or documented here.

## v0.2 (in development)

PROTOCOL.md defines a v0.2 command set — `set_plane_values`, `set_toggle`,
`delete_components`, plus `add_component` support for `"Plane"` and
`"Boolean Toggle"` — currently being implemented by another agent. Everything in
this document describes v0.1 as shipped. See PROTOCOL.md "v0.2 commands" for the
binding spec and docs/tool-reference.md for what it adds to the tool surface.
