# wasp-mcp Protocol Specification (v0.1) — BINDING

This document is the single source of truth for the Wasp MCP implementation.
Both the Python MCP server (`server/`) and the C# Grasshopper bridge
(`GH_MCP_Wasp/`) MUST conform to it exactly. Any deviation must be raised to
the orchestrator, not silently implemented.

## Transport

- TCP, localhost only. Default port **8090** (NOT 8080 — avoid clash with the
  stock grasshopper-mcp if user runs both; NOT 5000 — Almond Rhino bridge).
- Request: single UTF-8 JSON object `{"type": "<command>", "parameters": {...}}`,
  connection closed by client after response (same as baseline GH_MCP).
- Response: single JSON object `{"success": true, "result": {...}}` or
  `{"success": false, "error": "<message>"}`.

## Existing baseline commands (keep, do not rename)

`add_component`, `connect_components`, `set_component_value`,
`get_component_info`, `get_all_components`, `get_connections`,
`get_document_info`, `clear_document`, `save_document`, `load_document`,
`search_components`, `get_component_parameters`, `validate_connection`.

## New commands (C# must implement; Python must call with these exact shapes)

### add_user_object
Instantiate a `.ghuser` UserObject (Wasp component) on the canvas.
```json
{"type": "add_user_object",
 "parameters": {"path": "C:\\...\\Wasp_Basic Part.ghuser", "x": 100.0, "y": 200.0}}
```
Result: `{"id": "<instance-guid>", "name": "...", "nickname": "...",
"inputs": [{"name": "...", "nickname": "...", "index": 0, "typeName": "..."}],
"outputs": [same shape]}`

### connect_by_name
Connect source output to target input, resolved by param **name or nickname**
(case-insensitive; exact index still accepted via optional `sourceIndex`/`targetIndex`).
```json
{"type": "connect_by_name",
 "parameters": {"sourceId": "guid", "sourceParam": "PART",
                "targetId": "guid", "targetParam": "PART",
                "sourceIndex": null, "targetIndex": null}}
```
Result: `{"connected": true}`

### set_slider / set_panel
```json
{"type": "set_slider", "parameters": {"id": "guid", "value": 50.0, "min": 0.0, "max": 100.0}}
{"type": "set_panel",  "parameters": {"id": "guid", "text": "P|0_P|1"}}
```
Multi-line rule grammars use `\n` in `text`. NOTE (from live testing): a
programmatically created Panel feeds its text as ONE item — multi-rule
grammars need one panel per rule (appended into TXT) until v0.3 fixes panel
splitting. Correct Wasp rule syntax: `P|1_P|0` (see docs/v03-backlog.md #4).

### set_geometry_ref
Inject referenced Rhino document geometry (by Rhino object GUID strings) into a
Geometry/Mesh/Brep param component on canvas.
```json
{"type": "set_geometry_ref", "parameters": {"id": "guid", "objectIds": ["rhino-guid", "..."]}}
```

### get_component_output
Read output data of a component after solution.
```json
{"type": "get_component_output", "parameters": {"id": "guid", "param": "PART_OUT", "maxItems": 1000}}
```
Result: `{"dataType": "...", "branchCount": n, "items": [...]}` — meshes
serialized as `{"vertices": [[x,y,z]...], "faces": [[a,b,c(,d)]...]}`, planes as
`{"origin": [..], "xAxis": [..], "yAxis": [..]}`, transforms as 16-float row-major
array, primitives as-is. Truncate at `maxItems`, set `"truncated": true`.

### get_canvas_state
Full canvas snapshot for drift-checking and debugging.
Result: `{"components": [{"id", "name", "nickname", "position": [x,y],
"runtimeMessages": [{"level": "error|warning|remark", "text": "..."}]}],
"connections": [{"sourceId", "sourceParam", "targetId", "targetParam"}],
"solutionState": "idle|running"}`

### expire_solution
```json
{"type": "expire_solution", "parameters": {"ids": ["guid", ...] }}
```
`ids` optional — omit to recompute whole document. MUST schedule via
`GH_Document.ScheduleSolution` on the UI thread and return immediately with
`{"scheduled": true}`.

### bake_component_output
Bake geometry from a component output to the Rhino doc.
```json
{"type": "bake_component_output",
 "parameters": {"id": "guid", "param": "GEO", "layer": "WASP::AGG"}}
```
Result: `{"bakedIds": ["rhino-guid", ...]}`

## Threading rules (C#)

1. TCP listener thread NEVER touches `GH_Document` directly.
2. All canvas mutations and reads via `RhinoApp.InvokeOnUiThread` (or
   `Grasshopper.Instances.DocumentEditor.BeginInvoke`), with results marshalled
   back to the TCP thread through a `TaskCompletionSource`/wait handle,
   timeout 30 s → error response, never a hang.
3. After mutations that require recompute, use `ScheduleSolution(10)`;
   `get_component_output` must check `SolutionState`/`SolutionDepth` and return
   `{"success": false, "error": "solution_running"}` rather than stale data.

## Python MCP tool surface (FastMCP server, stdio)

Low-level (thin passthrough): `gh_add_component`, `gh_add_wasp_component`
(name → registry path → add_user_object), `gh_connect` (connect_by_name),
`gh_set_slider`, `gh_set_panel`, `gh_set_geometry_ref`, `gh_get_output`,
`gh_canvas_state`, `gh_expire`, `gh_bake`, `gh_clear`, `gh_save`.

Discovery: `list_wasp_components()` → registry contents (name, path, category
guessed from name, input/output docs when cached).

Macros (compose the above; each returns the ids of every component it placed):
- `create_wasp_part(name, geometry_object_ids, connection_planes|connection_object_ids, x, y)`
- `define_rules(grammar_text, parts_component_ids, x, y)`
- `run_aggregation(part_ids, rule_id, count, seed, mode="stochastic", x, y)` —
  places Wasp aggregation component, wires, sets N slider, expires, returns ids.
- `get_aggregation(aggregation_id, out="meshes"|"transforms"|"bake", layer=None)`

Wasp component canonical names in registry (from `Wasp_*.ghuser` filenames):
`basic_part`, `advanced_part`, `connection_from_plane`, `connection_from_direction`,
`rule`, `rule_from_text` (a.k.a. "Rules from Text/Grammar" — agent must verify the
exact filename present on this machine), `stochastic_aggregation`
("Wasp_Stochastic Aggregation.ghuser" — verify), `field_driven_aggregation`,
`graph_grammar_aggregation`, `get_part_geometry`, `aggregation_graph`, etc.
Registry key = lowercased filename minus `Wasp_` prefix and `.ghuser` suffix,
spaces/hyphens → underscore.

UserObjects dir: `%APPDATA%\Grasshopper\UserObjects` (63 Wasp_*.ghuser files
present on this machine). Registry must rescan on server start and expose
`refresh_registry` tool.

## Repo layout

```
Almond/wasp-mcp/
  PROTOCOL.md            (this file)
  README.md              (integration + build + install instructions)
  server/                (Python FastMCP server; uv project)
    pyproject.toml
    server.py
    registry.py
    gh_client.py         (TCP transport)
    macros.py
    tests/
  GH_MCP_Wasp/           (C# fork; net48 class library → .gha)
    (forked from vendor/grasshopper-mcp/GH_MCP, renamed assembly GH_MCP_Wasp,
     new component nickname "WaspMCP", port default 8090)
  vendor/grasshopper-mcp (upstream reference, read-only)
  build/                 (compiled GH_MCP_Wasp.gha lands here)
```

## Addenda v0.1.1 (binding — from Agent A's implementation findings)

1. `connect_by_name`: `sourceParam`/`targetParam` may be null/absent when the
   matching `sourceIndex`/`targetIndex` is provided (implicit outputs of Panel /
   Number Slider). Unresolvable param names return `{"success": false, ...}`,
   never crash — Python macros retry with candidate names.
2. `add_user_object` response MUST include full `inputs`/`outputs` arrays with
   `name`, `nickname`, `index` per param.
3. `set_slider`: `min`/`max` optional (value-only update allowed).
4. `expire_solution`: `ids` absent or null ⇒ whole-document recompute.
5. `add_component` must support type names: `Panel`, `Number Slider`, `Mesh`,
   `Geometry`, `Construct Plane`. Connection planes are injected as three Panels
   (origin/x-axis/y-axis lines) wired into Construct Plane — there is no
   `set_plane_values` command in v0.1.
6. `get_component_output` during an active solution returns
   `{"success": false, "error": "solution_running"}` (exact string — client
   substring-matches).
7. Responses newline-terminated JSON preferred; connection-close termination
   acceptable; no BOM.
8. Wasp RESET inputs are left at component defaults in v0.1 (no bool-setting
   command; revisit in v0.2).

## v0.2 commands (in development — binding once GH_MCP_Wasp v0.2 ships)

### set_plane_values
Set persistent plane data directly on a Param_Plane floating param (removes the
three-Panels-into-Construct-Plane workaround for connection planes).
```json
{"type": "set_plane_values",
 "parameters": {"id": "guid", "planes": [
   {"origin": [x,y,z], "xAxis": [x,y,z], "yAxis": [x,y,z]}, ...]}}
```
Result: `{"count": n}`. `add_component` must accept type name `"Plane"`
(Param_Plane) as of v0.2.

### set_toggle
```json
{"type": "set_toggle", "parameters": {"id": "guid", "value": true}}
```
Targets GH_BooleanToggle. Result: `{"id": "guid", "value": true}`.
Python: macros gain `reset_aggregation(aggregation_id)` — places/wires a toggle
on RESET if absent, pulses false→true→false with expiry between.
`add_component` must accept `"Boolean Toggle"` as of v0.2.

### delete_components
```json
{"type": "delete_components", "parameters": {"ids": ["guid", ...]}}
```
Removes objects from the canvas (needed for macro cleanup/retry paths).
Result: `{"deleted": n}`. Must refuse (per-id error entry, not exception) to
delete the WaspMCP bridge component itself.

v0.2 Python side: `create_wasp_part` switches to Param_Plane + set_plane_values
when the bridge reports v0.2 (probe: send set_plane_values, fall back to the
Construct Plane path on "Unknown command type"), keeping v0.1 bridge compat.

## v0.3 commands (in development — reliability + general-Grasshopper introspection)

### Batch solves: `solve` flag
Every mutating command (`add_component`, `add_user_object`, `connect_by_name`,
`connect_components`, `set_slider`, `set_panel`, `set_geometry_ref`,
`set_plane_values`, `set_toggle`, `set_component_value`) accepts optional
`"solve": false` (default true) suppressing its ScheduleSolution. A wiring
batch ends with one explicit `expire_solution`. Fixes the
partial-input-initialization trap in stateful components (Wasp aggregations).

### wait_for_idle
```json
{"type": "wait_for_idle", "parameters": {"timeoutMs": 30000}}
```
Blocks (on the TCP thread — must NOT occupy the UI thread; poll
doc.SolutionState/SolutionDepth read-only) until the solution is idle.
Result: `{"idle": true, "waitedMs": n}`; on timeout
`{"success": false, "error": "wait_timeout"}`. Replaces client sleep loops.

### set_panel line splitting
`set_panel` gains optional `"split_lines": true` (default **true**): the panel
must emit one item per text line (configure GH_Panel properties accordingly).
`false` = single multiline item (v0.1 behavior).

### Component introspection (general-Grasshopper foundation)
```json
{"type": "list_component_types", "parameters": {"filter": "mesh", "category": null, "limit": 100}}
```
Result: `{"components": [{"name", "nickname", "category", "subCategory",
"guid", "description"}], "total": n}` — from Grasshopper's ComponentServer
proxies (all installed plugins included).
```json
{"type": "get_component_schema", "parameters": {"name": "Mesh Box"}}
```
Instantiate the proxy IN MEMORY (never added to the canvas), describe, discard.
Result: `{"name", "guid", "inputs": [{"name","nickname","index","typeName",
"description","optional","defaultValue"?}], "outputs": [...]}`.

### Python v0.3
- All optional tool params get concrete JSON-schema types AND tolerate
  JSON-encoded string input (json.loads fallback) — fixes MCP clients sending
  strings for untyped params.
- `gh_connect(source_param)` becomes truly optional.
- New tools: `gh_wait_idle`, `gh_list_component_types`, `gh_component_schema`.
- Macros: mutating sequences use `solve: false` + single final expire +
  `wait_for_idle`; `run_aggregation` pulses RESET automatically (v0.2
  `set_toggle`) after wiring; `get_aggregation` reuses an existing extractor
  wired to the same output (canvas-state lookup) instead of placing duplicates;
  `define_rules` emits one panel per rule (until split_lines ships, then one
  split panel).
- Knowledge base: `server/knowledge/` JSON files (wasp_patterns.json,
  component_kb.json) consulted by macros; built from the Wasp example corpus
  (`corpus/`) and live introspection.

## Corpus-verified addenda (binding — evidence: server/knowledge/wasp_patterns.json, 120 parsed official examples)

1. **Three distinct rule-grammar syntaxes**, not interchangeable:
   - `PART|CONN_PART|CONN` (e.g. `P|0_P|1`) → **Rule From Text** `TXT` input.
   - `TYPE>TYPE` (connection-type strings from connection `T` inputs) →
     **Rules Generator** `GR` input.
   - `P|c_P|c>node_node` → **Graph-Grammar Aggregation** `RULES` input
     (panel wired directly; no Rule From Text).
2. **Aggregation outputs are `AGGR, PART_OUT` in that order.** Geometry and
   transform extraction MUST bind `PART_OUT` (candidates `["PART_OUT","AGGR"]`);
   `AGGR` feeds only Aggregation Graph / Save Aggregation / Rules From
   Aggregation.
3. **Aggregation input maps by mode**: stochastic
   `PART,PREV,N,RULES,SEED,CAT,MODE,GC,ID,RESET`; field-driven swaps `SEED`→
   `FIELD`; graph-grammar is `PART,PREV,RULES,ID,RESET` (NO `N`, NO `SEED`).
4. Authoritative per-component param names for all 64 Wasp components live in
   `server/knowledge/wasp_patterns.json` `param_aliases`; macros should prefer
   it over candidate guessing when present.
5. Dominant corpus connection idiom is **Connection From Direction**
   (GEO/CEN/UP) at ~10:1 over Connection From Plane; both remain supported.

## Codified from live regression (2026-07-10 — binding)

1. `add_component` `type` accepts a **component GUID string** in addition to a
   name (verified live). Names are matched against proxy NAMES only, not
   nicknames; ambiguous names (two proxies named "Square") resolve
   unpredictably — clients placing stock components programmatically SHOULD
   resolve via `list_component_types` and place by GUID. v0.5: nickname
   matching + explicit ambiguity errors.
2. Template bodies / expanders MUST take param names and component GUIDs from
   corpus dump wires (recorded exactly), never from prose. See
   docs/REGRESSION_LOG.md findings.

## Codified from implementation (v0.3 validation round — binding)

1. **Version gating**: `get_document_info` and `get_canvas_state` results
   carry an additive `"version"` string (`"0.2.0"`, `"0.3.0"`, …); an absent
   field means v0.1. This is the primary capability probe; the
   set_plane_values probe remains a fallback.
2. **Unknown-command markers**: clients accept BOTH `"Unknown command type"`
   (v0.2+) and `"No handler registered for command type"` (v0.1 wording).
3. **wait_for_idle clamps**: `timeoutMs <= 0` → 30000; hard cap 120000. The
   bridge requires two consecutive idle reads 100 ms apart before answering
   idle (a scheduled-but-not-started solve reads as idle on a single sample).
4. **delete_components** result carries an additive per-id `"results"` array
   beyond `{"deleted": n}`.
5. **run_aggregation** macro signature includes `field_component_id`
   (required for mode="field", wired into FIELD).
6. **Blank-phase guard**: `get_component_output`/`bake_component_output`
   return `solution_running` also when the target param's phase is Blank
   (expired but not yet solved) — stale-data-as-success is never allowed.
7. **RESET pulses must expire the SOURCE too**: with `solve:false` batching,
   expiring only the downstream component re-reads the source's stale
   VolatileData; pulse expires are `{"ids": [source_id, target_id]}` with a
   wait_for_idle between steps on v0.3+ (validator F1).

## v0.4 commands (in development — canvas organization + annotation)

### add_group
```json
{"type": "add_group",
 "parameters": {"ids": ["guid", ...], "name": "INPUTS — part geometry",
                "color": [190, 220, 190, 120]}}
```
Creates a GH_Group containing the given objects; `name` becomes the group
label (NickName). `color` is **RGBA, alpha LAST and optional** — `[r,g,b]` or
`[r,g,b,a]`, each 0-255; omitted alpha defaults to 150 (GH's native group
transparency). Result: `{"groupId", "name", "grouped", "colorOrder": "RGBA",
"results": [per-id entries]}` — invalid ids get per-id errors, the group is
still created from the valid ones. Grouping an id already in another group
is allowed (GH supports nesting/overlap).

Macro organization results: errors are reported per unit at
`result["organization"]["stage"]["error"]` and
`result["organization"]["inputs"]["error"]` (never a bare
`organization.error`); a failed organization never discards the built,
solved workflow. `organize_stage`'s pre-v0.4 gate issues no organization
commands, though the (cached) get_document_info version probe may fire once.

### add_scribble
```json
{"type": "add_scribble",
 "parameters": {"text": "Stochastic aggregation:\ngrows N parts from rules",
                "x": 100.0, "y": 80.0, "size": 14.0}}
```
Places a GH_Scribble (canvas text note). Result: `{"id": "guid"}`.

### set_nickname
```json
{"type": "set_nickname", "parameters": {"id": "guid", "nickname": "part count"}}
```
Renames a component/param instance for readability (e.g. sliders named after
their role). Result: `{"id", "nickname"}`.

### create_cluster (EXPLORATORY — may slip)
Wrap given component ids into a GH_Cluster with named inputs/outputs.
Programmatic cluster authoring is significantly harder than grouping; v0.4
ships add_group/add_scribble/set_nickname first, cluster support is
best-effort behind them.

### Generation conventions (binding on macros from v0.4)
Generated workflows MUST be structured, not flat:
1. **INPUTS group** — every user-tweakable driver (sliders, panels, toggles)
   grouped, each slider named for its role (`set_nickname`), ranges taken
   from corpus evidence, never magic values buried mid-graph.
2. **One group per functional stage** (e.g. "PART DEFINITION",
   "RULES", "AGGREGATION", "OUTPUT"), stage names from the pattern library.
3. **Explainer scribbles** on complex stages: what the stage does and why it
   exists (sourced from the pattern's `explainer` field in the knowledge
   base), placed above the group. Text MUST be wrapped (~54 chars/line for
   stage notes) and the whole block lifted above the group anchor so long
   explainers never overlap components — long is fine, sprawling is not.
   Each generated workflow additionally gets ONE overview note
   (`gh_workflow_note` / `add_workflow_note`: UPPERCASE title + separator +
   ~64-char-wrapped paragraphs) at the top-left of its canvas zone: what the
   whole graph produces, what drives it, where to look first.
4. **Template-driven, not literal**: macros compose parameterized stage
   templates (knowledge/*.json `templates` with input SLOTS — geometry slot,
   driver slot, count slot) rather than replaying a fixed component list.
   Slots keep workflows function-agnostic: the same paneling stage accepts a
   box, a loft, or a referenced surface.

## v0.5 commands (in development — vision, hardening, addressing)

### capture_viewport
```json
{"type": "capture_viewport",
 "parameters": {"viewport": "Perspective", "width": 1280, "height": 720,
                "zoomExtents": false}}
```
Captures the named Rhino viewport (`viewport` optional — default the active
one) to PNG. `width`/`height` optional (default viewport size, hard cap
1920×1080 — clamp, don't error). `zoomExtents: true` performs ZoomExtents
before capture and does NOT restore the camera (callers wanting a fixed view
manage the camera themselves). Runs on the UI thread via UiSync like every
other handler. Result: `{"imageBase64": "<png>", "viewport": "...",
"width": n, "height": n}`.

### capture_canvas
```json
{"type": "capture_canvas", "parameters": {"zoom": 0.5, "region": null}}
```
Snapshot of the GH canvas via Grasshopper's hi-res image API. `region`
optional `[x, y, w, h]` in canvas coordinates (null = full document bounds).
`zoom` scales output (clamp total pixels to ≤ 4 MP). Result:
`{"imageBase64": "<png>", "width": n, "height": n}`.

### Optional shared-secret auth
The WaspMCP component gains an optional `Token` input. When set (non-empty),
every request MUST carry a top-level `"token": "<value>"` field; a missing or
wrong token gets `{"success": false, "error": "auth_failed"}` and the
connection is closed. Empty/absent Token input = open access (backward
compatible). Python reads `WASP_MCP_TOKEN` env var and, when set, adds the
field to every request. The token never appears in logs on either side.

### add_component nickname matching + ambiguity errors
Name resolution order: exact GUID → exact name → exact nickname → unique
fuzzy name (all case-insensitive). When more than one proxy matches at the
winning tier, return `{"success": false, "error": "ambiguous_component_type:
<query>", "candidates": [{"name", "nickname", "guid", "category"}]}` (the
additive `candidates` array rides next to `error`). Closes live-regression
finding #1 ("Square").

### Zone addressing (Python-side convention — binding on macros from v0.5)
Every macro/expansion declares a **canvas zone**: an origin `(x, y)` plus the
rectangle implied by what it places. Macro results carry
`"zone": {"x", "y", "width", "height"}` and the full list of placed ids.
Any canvas-state lookup a macro performs (extractor reuse, panel/point
probes, cleanup) MUST filter candidates to its own zone bounds — closes
live-regression finding #6 (cross-zone Point B match). No new wire command:
`get_canvas_state` positions suffice.

### Python v0.5 tool surface
- `gh_capture_viewport`, `gh_capture_canvas` — thin passthrough; return the
  image as MCP image content (not raw base64 text) so any MCP client renders it.
- `list_templates()` — enumerate stage templates across knowledge files
  (id, stage_name, slots with kinds/defaults, evidence strength, source files).
- `expand_template(template_id, bindings, x, y)` — the template-expansion
  engine (generation-principles §3b): binds slots, places the body (stock
  components by GUID from dump evidence, Wasp components via registry), wires
  by recorded param names, applies v0.4 organization automatically, returns
  the zone manifest. Unbound required slots and kind mismatches are typed
  errors BEFORE any canvas mutation. Bridge version gates as elsewhere.

## Codified from tutorial-notes integration (2026-07-12 — binding)

Source: Liang's tutorial-note summaries of the Wasp #101 series /
masterclass, distilled into docs/wasp-practices.md. Prose guidance only —
per corpus discipline it NEVER supplies wiring evidence; every behavioral
change below was verified against the Wasp source or corpus first.

1. **Aggregation MODE gates constraints** (wasp core aggregation.py: mode
   1 = local only, 2 = global only, 3 = local+global, default 0 = none;
   corpus global-constraint examples run MODE=2). `run_aggregation` gains
   optional `global_constraint_ids`: each constraint output (Mesh Constraint
   `GC` / Plane Constraint `PC`) is wired into the aggregation `GC` input
   and a MODE slider (value 2, range 0–3) is placed and joined to the INPUTS
   group as "constraint mode". Rejected with a typed ValueError for
   mode="graph" (no GC/MODE inputs).
2. **Graph-Grammar Aggregation performs NO collision checking**
   (aggregate_sequence never calls collision_check) — codified in the
   aggregation_graph stage explainer; the grammar author owns overlaps.
3. **Rule-grammar lints (non-fatal)**: `define_rules` results may carry
   `warnings` — missing inverse rules (rules are directional; one-way
   grammars can exhaust legal connections and stop short of N) and part
   names differing only by case (Wasp names are case-sensitive). Warnings
   never block placement.

## Non-goals for v0.1

DisCo commands, intent/pattern system from baseline (keep code but don't extend),
multi-document support, remote (non-localhost) access.
