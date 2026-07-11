# Architectural corpus report

Agent J, 2026-07-10. Companion to `corpus/ARCH_SOURCES.md` (sources + licenses),
`server/knowledge/arch_patterns.json` (13 stage templates) and
`server/knowledge/arch_component_kb.json` (stock-component usage KB, 276
components from 107 architecturally-relevant dumps).

## What was done

- 5 repos shallow-cloned into `corpus/arch/` and dumped with the existing
  `tools/gh_dump` (no changes needed): **156/156 files parsed OK**.
- 107 architecturally-relevant dumps aggregated into `arch_component_kb.json`
  (developer-tutorial subtrees excluded — C# scripting course, Geometry Gems,
  WebSockets, AI demos).
- 13 stage templates extracted into `arch_patterns.json` following
  `docs/generation-principles.md`: typed slots, body wiring referencing slots,
  explainers written for an architecture student, slider `range_evidence`
  copied from real corpus values.

## Per-pattern evidence strength

| Template | Evidence | Strength |
|---|---|---|
| arch.attractor_scale_grid | E.5.1 + E.5.2 (two files, same idiom; three parallel attractor chains in E.5.2) | **Strong** |
| arch.hex_attractor_paneling | wave-attractor.gh (single file, but complete and clean: grid→distance→remap→scale→cull→surface) | Good |
| arch.voronoi_cell_extrusion | cellular-rockery.gh (rectangle + circle/region-intersection variants in one file) | Good |
| arch.random_panel_facade | E.23 (single file; normalization idiom Random→MassAddition→Division is distinctive) | Good |
| arch.triangulated_paneling | E.19 + E.18 (surface + facade-strip variants) | **Strong** |
| arch.planar_truss | E.15 Vierendeel + E.16 Pratt (verticals-only and diagonal variants) | **Strong** |
| arch.spatial_truss | E.17 (single file, 80 components, fully traced) | Good |
| arch.section_contours | E.20 + E.29 + terrain-mesh + WAFFLE (4 files, Brep\|Plane / Mesh\|Plane / Contour variants) | **Strong** |
| arch.terrain_from_image | E.29 + terrain-mesh (heightfield + Delaunay variants) | Good |
| arch.twist_tower | **RETRACTED (v0.5.2)** — core evidence came from two unlicensed repos; removed from the shipped KB pending re-evidencing from licensed material (the E.9 Series-stack idiom remains valid evidence) | — |
| arch.waffle_ribs | WAFFLE STRUCTURES.gh (complete workflow; body condensed from ~300 components of tree bookkeeping; OpenNest nesting excluded as plugin-dependent) | Good |
| arch.sun_oriented_paneling | E.11 + E.12 (openings + tilted-panel siblings) | **Strong** |
| arch.grid_box_field | E.7 + AM_001 p1–p3 (minimal + full live-stream build with random tilt/cull perturbation) | **Strong** |

Cross-cutting idioms the corpus repeats (worth macro-level reuse):

- **Bounds → Remap Numbers** with a panel target domain ("0.85 To 0.1",
  "2 To 10") is *the* normalization idiom — it appears in attractor, voronoi and
  terrain files. Generated graphs should prefer it over hand-computed division.
- **Series → Unit X/Y/Z → Move** is the universal array/stack idiom (E.9, E.19,
  E.20, E.23, E.29).
- **Graph Mapper** after Remap for response-curve shaping (wave-attractor).
- Drivers live in panels/sliders at canvas left with UPPERCASE nicknames in the
  ParametricCamp files ("SPANS", "DEPTH FACTOR", "# SECTIONS") — matches the
  v0.4 INPUTS-group convention nicely.

## Gaps (no corpus evidence — candidates for hand-authoring)

1. **Twist tower** — the template was retracted (v0.5.2, unlicensed evidence);
   re-author a twist-tower definition from licensed idioms (E.9 Series stack +
   Rotate/Pi/Loft, all evidenced in ParametricCamp files), validate it live,
   and re-mine. Floor slabs (Contour on the loft) remain unevidenced too.
2. **Diagrid on a closed tower surface** (wrap-around paneling with seam
   handling) — E.19 is an open surface; closed/periodic UV handling unevidenced.
3. **Voronoi 3D / cellular volumes** (Populate 3D + Voronoi 3D) — users will ask
   for voronoi towers/facades; only 2D voronoi is evidenced.
4. **Form-finding** — E.6 Hanging Cloth uses the stock **Catenary** component
   (real evidence, small); a catenary-vault template is half-evidenced and worth
   hand-finishing. Kangaroo-based relaxation is out of scope (plugin).
5. **Facade from image/pattern sampling** (E.28 Image-based Pattern exists but
   was not template-ized this pass — cheap follow-up).
6. **Brick/masonry wall patterns** (E.24 Exploding Brick Wall exists in corpus,
   unmined this pass).
7. **Wasp × arch bridging** — nothing yet connects arch stages to Wasp stages
   (e.g. voronoi cells as Wasp part regions, attractor field as Wasp Field).
   That composition is where this corpus meets the existing one; needs design,
   not just mining.

## Contradictions with existing knowledge files

None found. `arch_component_kb.json` overlaps `component_kb.json` on stock
components (Panel, Number Slider, Series, Move…) but records different
`typical_feeds` because the Wasp corpus feeds Wasp params; the files are
complementary, keyed by different corpora, and were deliberately kept separate.
One convention difference: feed keys here are `TypeName.ParamName` (full param
name), while component_kb.json inherits Wasp's `Wasp_X.NICK` style for Wasp
targets — documented in both provenance strings.

## Proposed live validation scenarios (arch workflows)

Same conventions as `docs/validation-scenarios.md` (not appended there —
proposals only). All stock components go through `gh_add_component`;
"no runtime errors" as defined in that doc.

---

### A1 — Attractor grid stage solves and grades sizes

**Goal**: `arch.attractor_scale_grid` expansion produces a working graded field.

Steps:
1. `gh_clear`.
2. Expand `arch.attractor_scale_grid` with defaults (Square grid 10×10, internal
   attractor point at grid corner, influence 0.05).
3. Solve; `gh_get_output` on the Multiplication (sizes) and Center Box outputs.

Expected:
- No runtime errors; sizes output count = (extent_x+1) × (extent_y+1) = 121.
- Sizes strictly increase with distance from the attractor (spot-check min ≠ max).
- Evidence: E.5.2 dump (Square.Points → Distance.A, attractor → Distance.B,
  Distance → Multiplication → Center Box X/Y/Z).

Cleanup: `gh_clear`.

---

### A2 — Voronoi cell extrusion respects count and height range

**Goal**: `arch.voronoi_cell_extrusion` end-to-end with slot bindings.

Steps:
1. `gh_clear`.
2. Expand template with count=100, seed=0, height_range="2 To 10" (corpus defaults).
3. Solve; `gh_get_output` on Voronoi.Cells and Extrude.Extrusion.

Expected:
- No runtime errors; 100 cells, 100 closed extrusions.
- Remap.Mapped values all within [2,10].
- Re-run with seed=1: cell geometry changes, count stays 100 (seed slot works).
- Evidence: cellular-rockery dump (Populate 2D count/seed sliders 100/0, panel "2 To 10").

Cleanup: `gh_clear`.

---

### A3 — Planar truss node counts scale with spans

**Goal**: `arch.planar_truss` slot arithmetic (spans drives every list length).

Steps:
1. `gh_clear`.
2. Expand with start=(0,0,0), end=(30,0,0), spans=8, depth_factor=8.58.
3. Solve; count verticals (Line output) and pipe breps.
4. `gh_set_slider` spans → 12; re-solve; recount.

Expected:
- spans=8: 9 verticals (nodes = spans+1); spans=12: 13 verticals. No errors
  after the slider change (regression guard for stale-solution handling).
- Truss depth ≈ 30/8.58 ≈ 3.5 units (bottom nodes at z ≈ −3.5).
- Evidence: E.15 dump (Divide Curve.Count=spans slider 8 [0,25]; Expression '-len/factor').

Cleanup: `gh_clear`.

---

### A4 — Section stage on a referenced solid

**Goal**: `arch.section_contours` against real Rhino geometry via
`gh_set_geometry_ref` (the geometry-slot contract: referenced brep, not internal).

Steps:
1. `gh_clear`; reference the standard `<BOX>` mesh/brep (10×10×10 at origin).
2. Expand `arch.section_contours` with solid ← `<BOX>`, n_sections=5, axis=Z.
3. Solve; `gh_get_output` on section curves.

Expected:
- No runtime errors; 5 branches of closed curves; each branch's curves are
  planar and horizontal (constant Z per branch).
- Evidence: E.20 dump (Brep|Plane fed by XZ planes at Divide Curve points,
  Expression 'x−1' on # SECTIONS).

Cleanup: delete referenced geometry component, `gh_clear`.

---

### A5 — Canvas legibility conventions on an arch template (v0.4)

**Goal**: expansion honors generation conventions: INPUTS group, stage group
named from `stage_name`, explainer scribble present.

Steps:
1. `gh_clear`.
2. Expand `arch.hex_attractor_paneling` via the composing macro (not raw adds).
3. `gh_canvas_state`.

Expected:
- Two+ groups: one named like "INPUTS…", one named "ATTRACTOR PANELING".
- Sliders nicknamed by role (cell size, threshold — not "Number Slider").
- One scribble whose text equals the template's `explainer` (first line at minimum).
- Slider ranges match `range_evidence` (threshold 0..1, not 0..100).
- Evidence: `arch_patterns.json` stage_name/explainer fields; PROTOCOL.md v0.4
  add_group/add_scribble/set_nickname.

Cleanup: `gh_clear`.
