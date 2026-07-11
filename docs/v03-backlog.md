# v0.3 backlog — findings from the first live end-to-end aggregation (2026-07-10)

The demo (60-part stochastic aggregation, box module, 3 connections, 2 rules,
baked to `WASP::AGG_DEMO`) succeeded, but only after working around all of the
following. Ordered by impact.

## 1. MCP tool schemas: untyped optional params arrive as strings
`create_wasp_part(connection_planes=...)`, `gh_expire(component_ids=...)`,
`gh_connect(source_param=...)` have optional params without JSON-schema types
(FastMCP emits no `"type"` for them), so MCP clients send them as raw strings
and pydantic rejects the call (`Input should be a valid list`). The demo had to
fall back to low-level tools for part assembly.
**Fix:** annotate every optional tool param with concrete types
(`Optional[List[dict]]` etc.) so the generated schema declares `array`/`object`,
and additionally accept JSON-encoded strings (json.loads on str input) for
client compatibility. Also make `gh_connect(source_param)` truly optional
(currently requires passing the literal string "null").

## 2. Wasp aggregation statefulness vs per-connect solves
The bridge schedules a solution after EVERY `connect_by_name`, so an
aggregation component initializes with partial inputs (e.g. before RULES is
wired) and caches a broken internal aggregation object
(`'NoneType' object has no attribute 'part1'`), or silently stays at size 1.
**Fix options:** (a) batch mode — a `begin_batch`/`end_batch` command pair (or
a `solve: false` flag on mutating commands) suppressing intermediate solves;
(b) `run_aggregation` macro should wire RESET (v0.2 `set_toggle` + Boolean
Toggle) and pulse it after wiring — v0.2's `reset_aggregation` exists, fold it
into `run_aggregation` automatically.

## 3. Panels don't split multiline text into items
Programmatically created `GH_Panel` feeds its text as ONE item; the macro
plane-injection design (3 lines per panel) and multi-line rule grammars both
silently fail (Construct Plane: "Data conversion failed from Text to Point";
Rule From Text: "not formatted correctly").
**Fix:** in C# `set_panel`, set the panel's multiline/stream behavior so each
line is a separate item (GH_Panel.Properties), or v0.2 `set_plane_values` path
(already built) + one-panel-per-rule in `define_rules`. Rule grammars with
multiple rules currently require one panel per rule wired appended into TXT.

## 4. Wasp rule syntax
Correct Wasp "Rule From Text" syntax: `P|1_P|0` (pipe part|connection,
underscore between halves). The `>` form in the define_rules docstring and the
`P1>0_P2>1` form in PROTOCOL.md line ~50 are both wrong and parse-fail.
**Fix:** correct macro docstring + PROTOCOL example + cookbook already has the
right form. Rule direction note: `A|cA_B|cB` = connection cA of existing part A
hosts connection cB of new part B.

## 5. Connection plane orientation convention
Wasp expects connection-plane Z (x-axis × y-axis) pointing OUTWARD from the
part volume; an inward normal makes every placement collide with the host
(aggregation stays at size 1, only warning is "Could not place N parts").
**Fix:** document prominently (cookbook), and consider a `validate_part` macro
that checks each connection plane normal against the mesh centroid and warns.

## 6. get_aggregation is not idempotent
Every call places a fresh Get Part Geometry / Deconstruct Part component and
rewires, triggering new solves (which then make the next read return
solution_running). Two failed calls = two orphan components.
**Fix:** macro should reuse an existing extractor component already wired to
the same aggregation output (find via get_canvas_state connections), and use
v0.2 delete_components to clean up on failure.

## 7. Solution-settling race after panel/slider edits
A mutation immediately followed by a macro that places+reads often lands in
the expire-solve window; the retry loop handles it but burns its budget when
multiple mutations queue up.
**Fix:** a `wait_for_idle` wire command (block server-side until
SolutionState == idle or timeout) would replace client-side sleep loops.

## Cleanup owed on the demo canvas
Stale components from the debugging session (safe to delete once v0.2 bridge
is installed, via gh_delete): first stochastic aggregation `44bbc805…` (stale
state) + its smoke-test sibling `4e5b7473…`, orphan Get Part Geometry
`0c39a9dd…` and one of `e1f512ca…`/`d3ced76a…`.
