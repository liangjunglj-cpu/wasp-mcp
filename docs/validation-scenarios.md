# Validation scenarios — live regression harness for wasp-mcp

Derived from the parsed official Wasp example corpus (`corpus/dumps/`, see
`corpus/INVENTORY.md`). Every expected value below is traceable to a dump file;
citations are given per scenario. Scenarios are ordered so the earliest failures
are the cheapest to diagnose. All interaction goes through the wasp-mcp MCP
tools — never raw TCP to port 8090.

Conventions:

- **Prerequisite for all scenarios**: Rhino 8 + Grasshopper open, WaspMCP bridge
  component on canvas, `Enabled = true`. Scenario V3 onward additionally needs a
  closed box mesh in the Rhino document (10 x 10 x 10, corner at origin), its
  GUID recorded as `<BOX>`.
- Ids returned by tool calls are referred to as `<part_id>`, `<rules_id>`,
  `<agg_id>` etc.
- "No runtime errors" means: `gh_canvas_state` → the component's
  `runtimeMessages` contains no entries with `level == "error"` (warnings are
  reported but do not fail the scenario unless stated).
- Each scenario ends with cleanup so scenarios can run in any order.

---

## V1 — Bridge health and registry contents

**Goal**: bridge reachable, solution idle, registry complete.

Steps:
1. `gh_clear` (keeps the bridge component).
2. `gh_canvas_state`
3. `list_wasp_components`

Expected:
- Step 2: `solutionState == "idle"`; component list contains exactly one
  component (the WaspMCP bridge), zero error-level runtime messages.
- Step 3: 63 registry entries (count of `Wasp_*.ghuser` on this machine).
  Must include keys: `basic_part`, `advanced_part`, `connection_from_plane`,
  `connection_from_direction`, `rule`, `rule_from_text`, `rules_generator`,
  `stochastic_aggregation`, `field-driven_aggregation` or
  `field_driven_aggregation` (filename is `Wasp_Field-driven Aggregation.ghuser`
  — hyphen normalization per registry rules), `graph-grammar_aggregation` or
  `graph_grammar_aggregation`, `get_part_geometry`, `deconstruct_part`,
  `aggregation_graph`.

Evidence: component names from `corpus/dumps/devFiles/Wasp_ComponentsRep_260704.json`
(the newest upstream component-repository sheet; 65 distinct `Wasp_*` names).

Cleanup: none (canvas already clean).

---

## V2 — Placed-component param names match the corpus

**Goal**: the exact input/output param names Claude will wire against are the
ones the corpus (and `server/knowledge/wasp_patterns.json` → `param_aliases`)
says exist. This is the cheapest catch-all for a Wasp version drift.

Steps:
1. `gh_add_wasp_component(name="stochastic_aggregation", x=600, y=300)`
2. `gh_add_wasp_component(name="basic_part", x=200, y=300)`
3. `gh_add_wasp_component(name="rule_from_text", x=200, y=500)`
4. `gh_clear`

Expected (order-sensitive, from `param_aliases` in wasp_patterns.json):
- Step 1 inputs: `PART, PREV, N, RULES, SEED, CAT, MODE, GC, ID, RESET`;
  outputs: `AGGR, PART_OUT`.
- Step 2 inputs: `NAME, GEO, CONN, COLL, ATTR`; outputs: `PART`.
- Step 3 inputs: `TXT`; outputs: `R`.

Evidence: `corpus/dumps/ExampleFiles/0.Basics/0_01_Basic_Aggregation.json`
(Stochastic Aggregation, Basic Part) and
`corpus/dumps/ExampleFiles/0.Basics/0_02_MultiPart_Aggregation.json`
(Rule From Text); identical in `Wasp_ComponentsRep_260704.json`.

Cleanup: step 4.

---

## V3 — Minimal single-part aggregation (0_01 replica)

**Goal**: end-to-end 0_01_Basic_Aggregation: one part, two connections, rule
grammar, stochastic aggregation of N parts, geometry extraction.

Steps:
1. `gh_clear`
2. `create_wasp_part(name="BOX", geometry_object_ids=["<BOX>"],
   connection_planes=[
     {"origin": [5,5,10], "xAxis": [1,0,0], "yAxis": [0,1,0]},   # top, +Z out
     {"origin": [5,5,0],  "xAxis": [1,0,0], "yAxis": [0,-1,0]}   # bottom, -Z out
   ], x=0, y=0)` → `<part_id>` (key `part_id` in the result)
3. `gh_canvas_state` — part component has no error-level messages.
4. `define_rules(grammar_text="BOX|0_BOX|1", parts_component_ids=["<part_id>"],
   x=0, y=300)` → `<rules_id>` (`rules_component_id`)
   (single rule only — multi-line panels are item-split only from bridge v0.3
   `split_lines`; see V4)
5. `run_aggregation(part_ids=["<part_id>"], rule_id="<rules_id>", count=50,
   seed=42, mode="stochastic", x=400, y=0)` → `<agg_id>` (`aggregation_id`)
6. Poll `gh_canvas_state` until `solutionState == "idle"` (max 60 s, 2 s
   interval).
7. `gh_canvas_state` — aggregation component has no error-level messages.
8. `get_aggregation(aggregation_id="<agg_id>", out="meshes", max_items=100)`

Expected:
- Step 8 returns `data.items` with **exactly 50 items** (slider N = 50; the
  grammar `BOX|0_BOX|1` + top/bottom outward planes stack parts vertically —
  every placement is collision-free, so the aggregation reaches N. Corpus
  reference: 0_01 uses N slider value 100, max 1000). Each item is a mesh
  `{vertices, faces}` with ≥ 8 vertices.
- The rule syntax is the corpus `PART|CONN_PART|CONN` form — a parse failure on
  `BOX|0_BOX|1` (Rule From Text "not formatted correctly") is a regression.
- Warning "Could not place N parts" at step 7 = FAIL here (means connection
  plane normals point inward; see docs/v03-backlog.md #5).

Evidence: chain in wasp_patterns.json → `patterns.basic_aggregation`
(from `0_01_Basic_Aggregation.gh`): Part.PART → StochasticAggregation.PART,
slider → N, rules → RULES; grammar strings verbatim in `grammars[]`
(e.g. `P|2_P|6` from 0_02, `HEXA|0_HEXA|0` from 0_10).

Cleanup: `gh_clear`.

---

## V4 — Multi-rule grammar (panel line splitting)

**Goal**: grammars with one rule per line reach Rule From Text as separate
items. On a v0.1/v0.2 bridge this is a **known expected failure**
(docs/v03-backlog.md #3); it becomes a hard pass requirement once v0.3
`set_panel split_lines` ships.

Steps:
1. `gh_clear`, then V3 steps 2–3 (part `BOX`).
2. `define_rules(grammar_text="BOX|0_BOX|1\nBOX|1_BOX|0",
   parts_component_ids=["<part_id>"], x=0, y=300)`
3. `gh_canvas_state` — inspect the Rule From Text component's messages.
4. `gh_get_output(component_id="<rules_id>", param="R", max_items=10)`

Expected:
- Bridge ≥ v0.3: no errors, step 4 returns **2 items** (two rules).
- Bridge < v0.3: Rule From Text error containing "not formatted correctly" —
  record as KNOWN-LIMITATION, not regression.

Evidence: two-directional rule pairs are the corpus norm — `A|0_A|1` +
`A|1_A|0` (`0_03_Vertex_Edge_Connections.gh`), `OCTA|0_OCTA|6` +
`OCTA|6_OCTA|0` (`2_01_Field_Basics.gh`); the 0_01 scribble: "Rules are
directional! ... you need to write two separate rules."

Cleanup: `gh_clear`.

---

## V5 — Seed reproducibility (0_08 replica)

**Goal**: same seed ⇒ identical aggregation; different seed ⇒ different.

Steps:
1. Build V3 steps 1–6 with `count=30, seed=7`.
2. `get_aggregation(aggregation_id="<agg_id>", out="transforms", max_items=50)`
   → save as `T1` (uses Deconstruct Part, output TR).
3. `gh_set_slider(component_id="<seed_slider_id>", value=7)` (re-set same value),
   `gh_expire(component_ids=["<agg_id>"])`, wait idle,
   re-read transforms → `T2`.
4. `gh_set_slider(component_id="<seed_slider_id>", value=8)`,
   `gh_expire(component_ids=["<agg_id>"])`, wait idle,
   re-read transforms → `T3`.

Expected:
- `len(T1) == 30`; `T1 == T2` (element-wise, 16-float rows, tolerance 1e-9);
  `T3 != T2`.
- NOTE: Wasp aggregations are stateful/additive; if `T2` comes back with more
  than 30 items the RESET pulse in `run_aggregation`/`reset_aggregation` is not
  working (v0.3 macro requirement) — record which.

Evidence: `0_08_Aggregation_w_Fixed_Seed.gh` (SEED input wired from slider;
Stochastic Aggregation exposes SEED per param_aliases). Deconstruct Part TR
output per `Wasp_ComponentsRep_260704.json` (outputs `NAME, ID, GEO, CENTER,
CONN, COLL, TR, PARENT, CHILD, ADD_COLL, ATTR`).

Cleanup: `gh_clear`.

---

## V6 — Geometry extraction uses PART_OUT, not AGGR

**Goal**: encode the corpus wiring contract for reading results: the parts
stream for Get Part Geometry / Deconstruct Part is the aggregation's
**PART_OUT** output; **AGGR** is the aggregation object (consumed by
Aggregation Graph, Save Aggregation to File, Rules from Aggregation).

Steps:
1. Build V3 steps 1–6 (`count=20, seed=1`).
2. `get_aggregation(aggregation_id="<agg_id>", out="meshes", max_items=30)`
3. `gh_canvas_state` — find the connection whose target is the extractor
   (`Get Part Geometry`) placed by step 2.

Expected:
- The connection's `sourceParam` is `PART_OUT` (exact string).
  [Contradiction RESOLVED in v0.3: extraction is PART_OUT-first and AGGR was
  removed from wiring candidates entirely (validator F3). This scenario stays
  as the live regression guard for that fix.]
- Step 2 still returns 20 mesh items.

Evidence: wire in `0_01_Basic_Aggregation.json`:
`Wasp_Stochastic Aggregation.PART_OUT -> Wasp_Get Part Geometry.PART`;
same pattern in 0_02, 0_04, 2_01, 4_05 dumps. AGGR feeds
`Wasp_Aggregation Graph.AGGR` (0_10) and `Wasp_Save Aggregation to File`
(0_07) only.

Cleanup: `gh_clear`.

---

## V7 — Bake to Rhino layer

**Goal**: `get_aggregation(out="bake")` bakes one Rhino object per placed part
onto the requested layer.

Steps:
1. Build V3 steps 1–6 (`count=25, seed=3`).
2. `get_aggregation(aggregation_id="<agg_id>", out="bake",
   layer="WASP::REGRESSION")`

Expected:
- Result `bakedIds` has length 25; each id is a valid GUID string.
- (If a Rhino-side check is available: the objects are on nested layer
  `WASP > REGRESSION`.)

Evidence: mesh-per-part extraction chain as V6; bake contract from
PROTOCOL.md `bake_component_output`.

Cleanup: `gh_clear`; delete the `WASP::REGRESSION` layer contents in Rhino
manually or via the Rhino-side bridge (the GH bridge has no Rhino-object
delete command — leaving the layer is acceptable but note it).

---

## V8 — Save definition to disk

**Goal**: `gh_save` round-trip; the saved file is a readable GH archive whose
component census matches the canvas.

Steps:
1. Build V3 steps 1–5 (`count=10, seed=2`).
2. `gh_save(path="C:\\Users\\liang\\OneDrive\\Documents\\Almond\\wasp-mcp\\out\\regression_v8.gh")`
3. Offline: run `tools\gh_dump\bin\Release\gh_dump.exe out\regression_v8.gh <tempdir>`
   and compare the dump's component census to `gh_canvas_state`.

Expected:
- Step 2 succeeds and the file exists, size > 10 KB.
- Step 3: dump parses (`parseGaps` absent), contains exactly one
  `Wasp_Basic Part`, one `Wasp_Rule From Text`, one
  `Wasp_Stochastic Aggregation`, plus the feeders and the bridge component;
  wire `Wasp_Basic Part.PART -> Wasp_Stochastic Aggregation.PART` present.

Evidence: dump/census method identical to how the corpus itself was parsed
(39/39 ExampleFiles OK); wire shape from `patterns.basic_aggregation`.

Cleanup: `gh_clear`; delete `out\regression_v8.gh`.

---

## Known corpus-vs-implementation contradictions the harness must watch

(also reported to the orchestrator; sources in parentheses)

1. **[RESOLVED v0.3]** `AGG_OUT` candidate order: extraction now uses
   `aggregation_parts_out_candidates()` — PART_OUT-first, AGGR excluded from
   wiring candidates (validator F3). V6 remains the live guard.
   (0_01/0_02/0_10 dumps.)
2. **[RESOLVED v0.3]** Graph-Grammar Aggregation (inputs
   `PART, PREV, RULES, ID, RESET`): `run_aggregation(mode="graph")` no longer
   places N/seed sliders and wires the grammar panel directly into RULES
   (`HEXA|0_HEXA|0>a_b` syntax). (4_05 dump; ComponentsRep_260704.)
3. **Field-driven Aggregation has `FIELD` instead of `SEED`** (inputs:
   `PART, PREV, N, RULES, FIELD, CAT, MODE, GC, ID, RESET`) — seed wiring is
   silently skipped (acceptable), but a field must be provided for meaningful
   runs. (2_01 dump.)
4. **[RESOLVED]** PROTOCOL.md's set_panel example now reads `P|0_P|1`.
   Retained nuance: `>` **is** valid syntax but only in the *other two*
   grammars — `TYPE>TYPE` for Rules Generator `GR`, and `rule>node_node` for
   Graph-Grammar `RULES`. Never in Rule From Text.
5. **RESET in corpus examples is a Button, not a Boolean Toggle** (all 39
   ExampleFiles). `reset_aggregation`'s toggle-pulse (false→true→false) mimics
   a button press and remains valid; noted for fidelity only.
