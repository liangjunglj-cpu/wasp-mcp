# Live regression log

## 2026-07-10 — first full pass (bridge 0.4.0, server 0.4.0)

Environment: Rhino 8.32, Grasshopper, Wasp installed, fresh canvas, WaspMCP
component enabled on port 8090. Bridge reported `"version": "0.4.0"` on first
contact (v0.2+v0.3+v0.4 .gha active, sha256 db70a63f…).

| Scenario | Result | Evidence |
|---|---|---|
| V1 bridge + registry health | **PASS** | canvas_state v0.4.0; registry lists aggregations incl. stochastic |
| V2 param-name drift | **PASS** (implicit) | macros matched N/RULES/SEED/RESET live without fallback errors |
| V3 0_01 Basic Aggregation replica | **PASS** | create_wasp_part with typed planes (v0.2 fast path, 1 call vs 19 in v0.1); 20/20 meshes (726v/600f each); worked FIRST TRY — auto-RESET pulse (F1 fix) confirmed on live dataflow |
| V4 multi-rule split panel | **PASS** | one panel → 2 WaspRule items (expected-fail on v0.1; split_lines fixed) |
| V5 seed reproducibility | **PASS** | seed 1 → seed 9 → seed 1: byte-identical transforms on return; seed 9 differs; 20 transforms |
| V6 PART_OUT wiring contract | **PASS** | single aggregation outgoing wire, sourceParam == "PART_OUT"; 27 components, 0 errors |
| V7 bake | **PASS** | 20 bakedIds on WASP::REGRESSION; reused_extractor: true (idempotency) |
| V8 save + offline census | **PASS** | out/regression_v8.gh (24.9 KB); gh_dump: 30 components, 0 parseGaps, exact Wasp census, key wire present |
| A1 attractor-scaled grid | **PASS** (after 2 findings) | 121 circles, radii exactly 2.00–10.00, 26 distinct values, 0 errors; organized (2 groups + scribble + nicknames) |
| A2–A4 voronoi / truss / sections | not run | queued for the template-expansion engine round |
| A5 v0.4 conventions via expander | blocked | expander not built yet (generation-principles §3b) |

Also exercised live for the first time: gh_wait_idle (100 ms double-idle
minimum), gh_delete (3 orphans, per-id results), gh_set_nickname, gh_group,
gh_scribble, list_component_types, add_component-by-GUID, gh_connect with
source_param genuinely omitted.

## Findings from this pass (→ v0.5 backlog)

1. **add_component name collisions**: "Square" resolves to Maths>Square (Sqr),
   not Vector>Grid (SqGrid); nicknames are NOT matched by the fallback, but
   **GUID placement works** (`add_component {"type": "<guid>"}` verified).
   Fix: (a) match nicknames in the exact-proxy fallback with ambiguity
   detection (error listing candidates when >1 proxy shares a name), and/or
   (b) template bodies should carry component GUIDs from the corpus dumps
   (they already record componentGuid) and the expander should place by GUID.
2. **Param-name guessing still bites for stock components**: Bounds' output is
   "Domain" (nick "I"), not "Bounds". The bridge's error DID list available
   params (good design). Fix: expander must take param names from the corpus
   dump wires (they are recorded exactly), never from prose guesses;
   arch_component_kb feed keys already use TypeName.ParamName.
3. Rerun-friendliness: recovery after a mid-build failure worked well via
   canvas-state lookup + gh_delete of a coordinate zone; the expander should
   place each workflow in a declared canvas zone to make cleanup trivial.

## 2026-07-10 — tetris multi-part demo (bridge 0.4.0, standalone tree)

Three tetromino parts (I/L/T, four joined unit cubes each), 10-rule grammar,
40-part stochastic aggregation, baked to WASP::TETRIS. First multi-part run,
first live run of wrapped scribbles + gh_workflow_note (13-line overview).

**New finding (4): composite part geometry must be a clean closed solid.**
Mesh Join on touching boxes leaves internal faces; Wasp then fails with
"Could not compute a valid collider geometry" on Basic Part and the
aggregation dies with 'NoneType' object has no attribute 'copy'. Fix:
Solid Union (breps) -> Mesh Brep -> bake, then set_geometry_ref to the clean
mesh + reset_aggregation. The repair ran live without rebuilding the part
subgraphs — delete/re-add of the mesh chain plus re-reference was enough.
Codify: any part-geometry template that composes multiple primitives MUST
boolean-union them, never join. (Candidate for a create_wasp_part validity
pre-check: closed mesh + no coincident internal faces.)

## 2026-07-10 — field-driven mode first live run (bridge 0.4.0)

run_aggregation(mode="field") exercised live for the first time: 40/40 parts
placed under an attractor-valued field; causal steering verified in both
directions (docs/field-analysis.md has the full analysis). New findings:
Wasp field names reject spaces and `_|>` (5); canvas id lookups must be
zone-scoped — a cross-zone Point B match invalidated a measurement until a
field-value arg-max probe caught it (6). Both runs archived to
corpus/self-generated/.
