# Tool reference

Every MCP tool exposed by `server/server.py`. Core v0.1 surface: 12 low-level
passthroughs, 2 discovery tools, 4 macros. v0.2 additions are listed at the end
(marked **in development** when written; since shipped), followed by the
**v0.5 additions**: `gh_capture_viewport` / `gh_capture_canvas` (MCP image
content), `list_templates` / `expand_template` (template-expansion engine),
zone addressing on every macro result, and `WASP_MCP_TOKEN` auth.

## Conventions

**Success envelope.** Low-level tools and macros return:

```json
{"success": true, "result": { ... }}
```

Discovery tools (`list_wasp_components`, `refresh_registry`) return a flat
`{"success": true, ...}` object without a `result` wrapper — noted per tool.

**Error envelope.** All failures are returned as data (never raised to MCP):

```json
{"success": false, "error": "<code>", "message": "<detail>", "hint": "<optional>"}
```

**Error codes** (defined in `gh_client.py`, `server.py`, `macros.py`):

| Code | Source | Meaning / what to do |
|---|---|---|
| `bridge_unreachable` | transport | TCP connect to `127.0.0.1:8090` failed. Rhino/GH not open, WaspMCP component missing or disabled, or port mismatch. `hint` explains the fix. |
| `bridge_timeout` | transport | No complete response within 60 s (`READ_TIMEOUT`). Usually a long Grasshopper solve; check `gh_canvas_state` for `solutionState`. |
| `bridge_protocol` | transport | Unparseable response, connection closed without data, or invalid `WASP_MCP_PORT` value. |
| `bridge_command_failed` | bridge | Bridge answered `{"success": false, "error": "..."}`. The bridge's message is in `message`. **`solution_running` arrives here**: `{"error": "bridge_command_failed", "message": "solution_running"}` — retry after a moment. |
| `component_not_found` | registry | Name did not resolve to an installed Wasp `.ghuser`; response includes `suggestions`. |
| `param_not_found` | macros | Expected param (e.g. a part's GEO input) not found among the component's real params, or all connect candidates were rejected. |
| `invalid_mode` | macros | Bad `mode`/`out` argument. |
| `invalid_arguments` | macros | Other bad input (e.g. malformed plane list). |
| `bridge_too_old` | server (v0.5) | The connected bridge predates the command (capture tools need v0.5; multi-line panel constants in templates need v0.3 `split_lines`). Rebuild/reinstall GH_MCP_Wasp.gha. |
| `template_not_found` | expander (v0.5) | Unknown template id; message lists close matches, `list_templates` has the full set. |
| `template_blocked` | expander (v0.5) | Template is marked `expansion_blocked` in the knowledge base (e.g. `arch.terrain_from_image`: Image Sampler state is not settable); `details` carries the reason. |
| `template_not_expandable` | expander (v0.5) | Template body is data-only (prose wires / stock components without GUID evidence); `details` lists every structural issue. |
| `invalid_bindings` | expander (v0.5) | One or more binding problems — unknown slots, unbound required slots, kind mismatches — ALL listed in `details`. Raised before anything is placed. |

**`solution_running` retry semantics.** The bridge refuses to read output while
the GH solution is computing (or a scheduled solve has not fired yet), returning
the exact string `solution_running`. Low-level tools surface this as
`bridge_command_failed`; **you** retry. The macros retry internally
(`get_output_when_idle`: up to 20 attempts, 0.5 s apart), also treating a 30 s
UI-thread timeout ("timed out after") and an empty-items first response
(2 extra retries) as retryable.

---

## Low-level tools

### gh_add_component

Add a stock Grasshopper component. Wire command: `add_component`.

| Param | Type | Default | Notes |
|---|---|---|---|
| `component_type` | str | — | e.g. `"Number Slider"`, `"Panel"`, `"Mesh"`, `"Geometry"`, `"Construct Plane"`. Fuzzy-matched, GUIDs and component-server names also accepted. |
| `x`, `y` | float | — | Canvas position. |

```json
{"success": true, "result": {"id": "a1b2c3d4-…", "type": "Panel", "name": "Panel", "x": 100.0, "y": 200.0}}
```

Errors: unknown type → `bridge_command_failed` with up to 10 possible matches in the message.

### gh_add_wasp_component

Resolve a Wasp component name against the registry, then place the `.ghuser`.
Wire command: `add_user_object` (after local registry lookup).

| Param | Type | Default | Notes |
|---|---|---|---|
| `name` | str | — | Fuzzy: `"Basic Part"`, `"basic_part"`, `"stochastic"` all work. |
| `x`, `y` | float | — | Canvas position. |

```json
{"success": true, "result": {
  "id": "instance-guid",
  "name": "Basic Part", "nickname": "Basic Part",
  "inputs":  [{"name": "Name", "nickname": "NAME", "index": 0, "typeName": "Text"},
              {"name": "Geometry", "nickname": "GEO", "index": 1, "typeName": "Mesh"},
              {"name": "Connections", "nickname": "CONN", "index": 2, "typeName": "Connection"}],
  "outputs": [{"name": "Part", "nickname": "PART", "index": 0, "typeName": "Part"}],
  "registryKey": "basic_part"
}}
```

Use the returned `inputs`/`outputs` names for `gh_connect` — never assume
indices. Errors: `component_not_found` (with `suggestions`), or bridge errors if
the `.ghuser` file fails to instantiate.

### gh_connect

Connect a source output to a target input. Wire command: `connect_by_name`.
**Appends** to existing sources (never replaces) — Wasp inputs routinely take
multiple sources.

| Param | Type | Default | Notes |
|---|---|---|---|
| `source_id` | str | — | Instance GUID. |
| `source_param` | str \| null | — | Output name/nickname (case-insensitive; exact then substring match). |
| `target_id` | str | — | Instance GUID. |
| `target_param` | str \| null | — | Input name/nickname. |
| `source_index` | int \| null | `null` | Explicit index; overrides name. For implicit outputs (Panel, Number Slider) pass `source_param=null, source_index=0`. |
| `target_index` | int \| null | `null` | Explicit index; overrides name. |

```json
{"success": true, "result": {"connected": true}}
```

Errors: unresolvable param → `bridge_command_failed`, message lists the
available params as `[i] Name (Nickname)`.

### gh_set_slider

Set a Number Slider's value and optionally its range. Wire command: `set_slider`.

| Param | Type | Default |
|---|---|---|
| `component_id` | str | — |
| `value` | float | — |
| `minimum` | float \| null | `null` (unchanged) |
| `maximum` | float \| null | `null` (unchanged) |

```json
{"success": true, "result": {"id": "guid", "value": 50.0, "min": 0.0, "max": 100.0}}
```

Errors: target is not a `GH_NumberSlider` → `bridge_command_failed`.

### gh_set_panel

Set a Panel's text. Wire command: `set_panel`. Multi-line content (rule
grammars) uses `\n`.

| Param | Type |
|---|---|
| `component_id` | str |
| `text` | str |

```json
{"success": true, "result": {"id": "guid", "text": "A|0_B|1"}}
```

### gh_set_geometry_ref

Point a floating param component at existing Rhino document objects (referenced
geometry, `ReferenceID` preserved). Wire command: `set_geometry_ref`.
Supported targets: Geometry, Mesh, Brep, Curve, Surface, Point, Generic params.
Replaces the param's existing persistent data.

| Param | Type | Notes |
|---|---|---|
| `component_id` | str | Must be a floating param, not a component. |
| `object_ids` | list[str] | Rhino object GUIDs; must be non-empty and all exist. |

```json
{"success": true, "result": {"id": "guid", "count": 2}}
```

Errors: bad GUID, missing Rhino object, no active Rhino doc, unsupported
param/geometry type → `bridge_command_failed`.

### gh_get_output

Read a component output after the solution computed. Wire command:
`get_component_output`.

| Param | Type | Default |
|---|---|---|
| `component_id` | str | — |
| `param` | str | — (output name/nickname) |
| `max_items` | int | 1000 |

```json
{"success": true, "result": {
  "dataType": "Mesh", "branchCount": 3,
  "items": [
    {"vertices": [[0,0,0],[1,0,0],[1,1,0]], "faces": [[0,1,2]]},
    {"origin": [0,0,0], "xAxis": [1,0,0], "yAxis": [0,1,0]},
    [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1],
    42.0, "text", true
  ],
  "truncated": true
}}
```

Serialization per item: meshes → `{vertices, faces}` (faces are 3- or 4-index);
planes → `{origin, xAxis, yAxis}`; transforms → 16-float row-major array;
points/vectors → `[x,y,z]`; numbers/ints/bools/strings/guids as-is; anything
else (Breps, Wasp Python objects) → `{"type": "...", "text": "..."}`.
`truncated` present only when the `max_items` cap was hit.

Errors: `solution_running` (as `bridge_command_failed`; retry), unknown
component/param.

### gh_canvas_state

Full canvas snapshot. Wire command: `get_canvas_state`. No parameters.

```json
{"success": true, "result": {
  "components": [{
    "id": "guid", "name": "Stochastic Aggregation", "nickname": "StochAggr",
    "position": [400.0, 100.0],
    "runtimeMessages": [{"level": "warning", "text": "..."}]
  }],
  "connections": [{"sourceId": "guid", "sourceParam": "Part",
                   "targetId": "guid", "targetParam": "Parts"}],
  "solutionState": "idle"
}}
```

`runtimeMessages.level` ∈ `error | warning | remark`. `solutionState` ∈
`idle | running`. Use to drift-check after edits and to poll before reads.
Note: `connections` reports param **names** (not nicknames).

### gh_expire

Expire components and schedule a recompute. Wire command: `expire_solution`.
Returns immediately — poll `gh_canvas_state` for `solutionState: "idle"` before
reading outputs.

| Param | Type | Default |
|---|---|---|
| `component_ids` | list[str] \| null | `null` = recompute whole document |

```json
{"success": true, "result": {"scheduled": true}}
```

Errors: any listed id not found → `bridge_command_failed` (ids validated up
front, nothing is expired).

### gh_bake

Bake a component output's geometry into the Rhino document. Wire command:
`bake_component_output`. Nested layer paths use `::` and are created on demand.

| Param | Type | Default |
|---|---|---|
| `component_id` | str | — |
| `param` | str | — |
| `layer` | str \| null | `null` = current layer |

```json
{"success": true, "result": {"bakedIds": ["rhino-guid", "rhino-guid"]}}
```

Errors: `solution_running` (retry), no active Rhino doc.

### gh_clear

Clear the Grasshopper document. Wire command: `clear_document`. No parameters.
Preserves the WaspMCP bridge component and (heuristically) any object whose
nickname/type mentions MCP, Claude, Toggle, or Status.

```json
{"success": true, "result": {"message": "Document cleared", "removedCount": 12}}
```

### gh_save

Save the current definition to a `.gh` file. Wire command: `save_document`.
Parent directories are created if missing.

| Param | Type |
|---|---|
| `path` | str (absolute) |

```json
{"success": true, "result": {"message": "Document saved", "path": "C:\\...\\agg.gh"}}
```

(The bridge also implements `load_document`, `get_document_info` and the
upstream baseline commands, but v0.1 exposes no MCP tools for them.)

---

## Discovery tools

### list_wasp_components

List installed Wasp components from the local registry. No bridge round-trip.
Flat envelope (no `result` wrapper).

| Param | Type | Default |
|---|---|---|
| `category` | str \| null | `null`; one of `part`, `connection`, `rule`, `aggregation`, `field`, `disco`, `util` |

```json
{"success": true,
 "directory": "C:\\Users\\liang\\AppData\\Roaming\\Grasshopper\\UserObjects",
 "count": 63,
 "components": [{
   "key": "basic_part",
   "filename": "Wasp_Basic Part.ghuser",
   "path": "C:\\...\\Wasp_Basic Part.ghuser",
   "category": "part",
   "inputs": [ ... ], "outputs": [ ... ]
 }]}
```

`inputs`/`outputs` appear only for components placed at least once this session
(cached from `add_user_object`).

### refresh_registry

Rescan `%APPDATA%\Grasshopper\UserObjects` for `Wasp_*.ghuser`. Use after
installing/updating Wasp while the server is running. Flat envelope.

```json
{"success": true, "directory": "C:\\...\\UserObjects", "count": 63,
 "keys": ["advanced_part", "aggregation_graph", "basic_part", "..."]}
```

---

## Macros

Each macro composes several wire commands and returns the id of every component
it placed (`all_ids` collects them). Wire commands used are listed per macro.
All macro errors use the codes table above; a mid-macro bridge failure leaves
already-placed components on the canvas (see troubleshooting).

### create_wasp_part

Place a wired Wasp **Basic Part**: Mesh param referencing Rhino geometry + NAME
panel + optional connections. Wire commands: `add_user_object`,
`add_component`, `set_panel`, `set_geometry_ref`, `connect_by_name`,
`expire_solution`.

| Param | Type | Default | Notes |
|---|---|---|---|
| `name` | str | — | Fed into the part's NAME input; also the token you use in rule grammars. |
| `geometry_object_ids` | list[str] | — | Rhino GUIDs of the part's mesh geometry. |
| `connection_planes` | list \| null | `null` | Each `{"origin":[x,y,z],"xAxis":[x,y,z],"yAxis":[x,y,z]}` **or** a flat 9-float list `[ox,oy,oz, xx,xy,xz, yx,yy,yz]`. Realized as three panels → Construct Plane → Connection From Plane (v0.1 workaround; v0.2 replaces this with `set_plane_values`). |
| `connection_object_ids` | list[str] \| null | `null` | Alternative: Rhino GUIDs of planar geometry, referenced into a Geometry param → Connection From Plane. |
| `x`, `y` | float | 0.0, 0.0 | Canvas position of the part. Feeders are placed to its left. |

```json
{"success": true, "result": {
  "part_id": "guid",
  "name_panel_id": "guid",
  "geometry_param_id": "guid",
  "construct_plane_id": "guid",
  "plane_origin_panel_id": "guid", "plane_xaxis_panel_id": "guid", "plane_yaxis_panel_id": "guid",
  "connection_component_id": "guid",
  "part_output_param": "PART",
  "all_ids": ["guid", "..."]
}}
```

Pass `part_id` into `define_rules` / `run_aggregation`.

### define_rules

Place **Rule From Text** fed by a grammar panel, wired to the given parts.
Wire commands: `add_user_object`, `add_component`, `set_panel`,
`connect_by_name`, `expire_solution`.

| Param | Type | Default |
|---|---|---|
| `grammar_text` | str | — (one rule per line, `\n`-separated) |
| `parts_component_ids` | list[str] | — (`part_id` values) |
| `x`, `y` | float | 0.0, 200.0 |

```json
{"success": true, "result": {
  "rules_component_id": "guid",
  "grammar_panel_id": "guid",
  "rules_output_param": "R",
  "warnings": ["Rules are directional; no inverse rule present for: ..."],
  "all_ids": ["guid", "guid"]
}}
```

`warnings` (only present when non-empty) is a non-fatal lint: missing
inverse rules (rules are directional — one-way grammars can stop short of N)
and part names differing only by case (Wasp is case-sensitive). Relay them
to the user; deliberate one-way hierarchies can ignore the inverse warning.

Pass `rules_component_id` as `rule_id` to `run_aggregation`.

### run_aggregation

Place an aggregation component, wire parts + rules + N slider (+ seed slider),
and expire to start computing. Wire commands: `add_user_object`,
`add_component`, `set_slider`, `connect_by_name`, `expire_solution`.

| Param | Type | Default | Notes |
|---|---|---|---|
| `part_ids` | list[str] | — | `part_id` values. |
| `rule_id` | str | — | `rules_component_id` from define_rules. |
| `count` | int | — | N slider value (slider range 0..max(2×count, 100)). |
| `seed` | int \| null | `null` | Seed slider, stochastic mode only. |
| `mode` | str | `"stochastic"` | `"stochastic"` → `stochastic_aggregation`, `"field"` → `field_driven_aggregation`, `"graph"` → `graph_grammar_aggregation`. |
| `x`, `y` | float | 400.0, 100.0 | |
| `field_component_id` | str \| null | `null` | FIELD source, required when `mode="field"`. |
| `global_constraint_ids` | list[str] \| null | `null` | Plane/Mesh Constraint component ids. Wired into GC + a MODE slider set to 2 is placed (constraints are ignored at the default mode 0). Rejected for `mode="graph"` (no GC/MODE inputs; graph mode does no collision/constraint checking). |

```json
{"success": true, "result": {
  "aggregation_id": "guid",
  "count_slider_id": "guid",
  "seed_slider_id": "guid",
  "mode_slider_id": "guid",
  "global_constraint_sources": ["guid"],
  "aggregation_output_param": "PART",
  "all_ids": ["guid", "guid", "guid"]
}}
```

`mode_slider_id` / `global_constraint_sources` appear only when
`global_constraint_ids` was given. If a constrained aggregation places
nothing, the seed part sits outside the allowed zone — move it with Wasp
Transform Part (see docs/wasp-practices.md §3).

Note: this *starts* the solve; it does not wait. Long aggregations keep
`solutionState: "running"` — see `get_aggregation` and troubleshooting.

### get_aggregation

Extract results from a computed aggregation. Wire commands: `add_user_object`,
`connect_by_name`, `expire_solution`, then `get_component_output` (with retry)
or `bake_component_output`.

| Param | Type | Default | Notes |
|---|---|---|---|
| `aggregation_id` | str | — | From run_aggregation. |
| `out` | str | `"meshes"` | `"meshes"` → places Get Part Geometry, returns serialized meshes; `"transforms"` → places Deconstruct Part, returns TR transforms; `"bake"` → Get Part Geometry + bake. |
| `layer` | str \| null | `null` | Bake layer; defaults to `"WASP::AGG"`. |
| `max_items` | int | 1000 | Truncation for meshes/transforms. |

```json
{"success": true, "result": {
  "extractor_id": "guid",
  "output_param": "GEO",
  "data": {"dataType": "Mesh", "branchCount": 50, "items": [ ... ]},
  "all_ids": ["guid"]
}}
```

For `out="bake"` the `data` key is replaced by `"bakedIds": ["rhino-guid", ...]`.

---

## v0.2 additions (in development)

Defined in PROTOCOL.md "v0.2 commands"; being implemented by another agent.
Binding once GH_MCP_Wasp v0.2 ships — shapes below are the spec, not shipped
behavior.

| Wire command | Purpose | Result |
|---|---|---|
| `set_plane_values` | Set persistent planes directly on a floating `Param_Plane` (replaces the three-Panels + Construct Plane workaround for connection planes). | `{"count": n}` |
| `set_toggle` | Set a `GH_BooleanToggle` value (enables driving Wasp RESET inputs, left untouched in v0.1). | `{"id": "guid", "value": true}` |
| `delete_components` | Remove canvas objects by id (macro cleanup/retry). Refuses per-id (error entry, not exception) to delete the WaspMCP bridge itself. | `{"deleted": n}` |

Also in v0.2: `add_component` accepts `"Plane"` and `"Boolean Toggle"`; Python
gains a `reset_aggregation(aggregation_id)` macro (places/wires a toggle on
RESET, pulses false→true→false with expiry between); and `create_wasp_part`
switches to Param_Plane + `set_plane_values` when the bridge supports it,
probing by sending `set_plane_values` and falling back to the Construct Plane
path on an "Unknown command type"-style error, keeping v0.1 bridge
compatibility.

---

## v0.5 additions (shipped in server.py)

### Zone addressing (all macros)

Every macro result now carries an additive `"zone"` field — the canvas
rectangle implied by what the macro placed:

```json
"zone": {"x": -110.0, "y": -60.0, "width": 770.0, "height": 500.0}
```

Any canvas-state lookup a macro performs is scoped to its zone:
`get_aggregation` never reuses a same-typed extractor sitting in another
workflow's zone, and `reset_aggregation` never reuses a cross-zone RESET
feeder (both place a fresh component instead — regression finding #6).
Feed a zone rect to `gh_capture_canvas`'s `region` to frame one workflow,
or use it to `gh_delete` a whole workflow cleanly.

### Shared-secret auth (transport)

Set the `WASP_MCP_TOKEN` environment variable to match the WaspMCP
component's Token input: every bridge request then carries a top-level
`"token"` field. Wrong/missing token → `bridge_command_failed` with message
`auth_failed`. The token value is never logged and never appears in error
payloads. Unset/empty = open access (backward compatible).

### gh_capture_viewport

Capture a Rhino viewport to a PNG, returned as **MCP image content** (not
base64 text) so any MCP client renders it inline. Wire command:
`capture_viewport` (v0.5 bridge; older bridges → `bridge_too_old`).

| Param | Type | Default | Notes |
|---|---|---|---|
| `viewport` | str \| null | active viewport | e.g. `"Perspective"`, `"Top"`. |
| `width`, `height` | int \| null | viewport size | Bridge clamps to 1920×1080. |
| `zoom_extents` | bool | `false` | ZoomExtents before capture; the camera is NOT restored. |

### gh_capture_canvas

Snapshot the Grasshopper canvas as MCP image content. Wire command:
`capture_canvas` (v0.5 bridge; older bridges → `bridge_too_old`).

| Param | Type | Default | Notes |
|---|---|---|---|
| `zoom` | float \| null | bridge default | Output scale; total pixels clamped to 4 MP. |
| `region` | list \| null | full document bounds | `[x, y, w, h]` in canvas coordinates — pass a macro/expansion `zone` rect. |

### list_templates

Enumerate the stage templates the expansion engine can build (from
`server/knowledge/arch_patterns.json` + `wasp_patterns.json` `templates`
sections). Local — no bridge round-trip. Flat envelope.

```json
{"success": true, "count": 14, "templates": [{
  "id": "arch.attractor_scale_grid",
  "stage_name": "ATTRACTOR FIELD",
  "knowledge_file": "arch_patterns.json",
  "slots": {"attractor": {"kind": "geometry", "arity": "1", "ref_param": "Point"},
            "influence": {"kind": "driver_num", "default": 0.05, "range_evidence": [0, 1]}},
  "outputs": {"sizes": "scale.Result", "cells": "cell.Box"},
  "source_files": ["..."],
  "evidence_strength": "corroborated (2 files)",
  "expandable": true
}]}
```

`expandable: false` entries carry either `expansion_blocked` (deliberate —
e.g. `arch.terrain_from_image`, Image Sampler state) or `issues` (data-only
body: prose wires, stock components without GUID evidence).

### expand_template

The template-expansion engine (generation-principles §3b). Binds slots,
places the body (stock components **by componentGuid** from corpus dump
evidence, Wasp components via the registry), wires the exact recorded param
names, batches everything with `solve:false` + one final
`expire_solution` + `wait_for_idle`, applies the v0.4 organization
conventions automatically (INPUTS group with role-nicknamed sliders, stage
group named from `stage_name`, wrapped explainer scribble), and returns a
zone manifest. ALL binding problems are one `invalid_bindings` error
(`details` list) raised **before** anything is placed.

| Param | Type | Default | Notes |
|---|---|---|---|
| `template_id` | str | — | From `list_templates`. |
| `bindings` | dict \| null | `{}` | Slot → value. Drivers: numbers (or `"2 To 10"` domain text). Geometry/wasp slots: component id string, `{"component_id", "param"?}` for a named upstream output, or `{"rhino_ids": ["..."]}` (geometry only). Lists for `arity: 1..n`. Driver slots with defaults may be omitted — they still get an evidence-ranged slider. |
| `x`, `y` | float | 0.0, 0.0 | Zone origin (drivers column; body columns grow rightward by dependency depth). |

```json
{"success": true, "result": {
  "template_id": "arch.attractor_scale_grid",
  "stage_name": "ATTRACTOR FIELD",
  "zone": {"x": 940.0, "y": 296.0, "width": 1300.0, "height": 644.0},
  "all_ids": ["guid", "..."],
  "components": {"grid": "guid", "dist": "guid", "scale": "guid", "cell": "guid"},
  "drivers": {"influence": {"id": "guid", "role": "influence", "kind": "driver_num", "value": 0.05}},
  "referenced_params": {"attractor": "guid"},
  "outputs": {"sizes": {"component_id": "guid", "param": "Result"}},
  "stages": [{"name": "ATTRACTOR FIELD", "ids": ["..."]},
             {"name": "INPUTS — attractor field drivers", "ids": ["..."]}],
  "organization": {"stage": {"group_id": "..."}, "inputs": {"group_id": "..."}}
}}
```

Read results with `gh_get_output(outputs.<name>.component_id,
outputs.<name>.param)`. For `wasp.stochastic_aggregation` expansions, pulse
RESET afterwards (`reset_aggregation` on `components.agg`) before reading
`PART_OUT` — the expander wires the toggle but does not pulse it (the
full-service path remains the `run_aggregation` macro).
