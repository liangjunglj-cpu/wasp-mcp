# Generation principles — flexible, legible Grasshopper workflows

Why this document: the first-generation macros replayed fixed component
chains. That produces working but rigid graphs — copy-paste generation. From
v0.4 the goal is **composition**: workflows assembled from parameterized stage
templates, organized and annotated like a competent human author would.

## 1. Template, not transcript

A **stage template** is a mined-and-abstracted subgraph with declared SLOTS:

```json
{
  "id": "wasp.stochastic_aggregation",
  "stage_name": "AGGREGATION",
  "explainer": "Grows the structure: places N copies of the part(s) one by one, each placement chosen randomly among rule-legal, collision-free options.",
  "slots": {
    "parts":  {"kind": "wasp_part", "arity": "1..n"},
    "rules":  {"kind": "wasp_rules", "arity": "1"},
    "count":  {"kind": "driver_int", "default": 100, "range_evidence": [10, 500]},
    "seed":   {"kind": "driver_int", "default": 1, "optional": true}
  },
  "body": [ "... component + wiring spec referencing slots ..." ],
  "outputs": {"parts_out": "Stochastic Aggregation.PART_OUT"},
  "source_files": ["0_01_Basic_Aggregation.gh", "..."]
}
```

- **Slots are typed by role**, not by component: a `geometry` slot accepts a
  referenced Rhino mesh, a Mesh Box chain, or another stage's output. That is
  what makes a workflow function-agnostic.
- `range_evidence` comes from real slider values in the corpus — generated
  sliders get sensible ranges, not 0..1 defaults.
- Templates chain: `OUTPUT of stage A satisfies slot X of stage B` when kinds
  match. A workflow = a small plan of stages + slot bindings.

## 2. Canvas legibility (v0.4 conventions, enforced by macros)

- **INPUTS group** at canvas left: all drivers, sliders nicknamed by role
  ("part count", "random seed"), grouped with a consistent color.
- **One group per stage**, labeled with the stage name.
- **Explainer scribbles** above complex stages: 1-3 lines, WHAT the stage
  does + WHY it exists, from the template's `explainer`. Written for an
  architecture student reading the canvas cold.
- **Left-to-right dataflow**, stages spaced consistently (x += ~450 per
  stage), drivers above/left of their consumers.
- Nicknames for placed components where the default is cryptic.

## 3. Corpus discipline (applies to the architectural corpus too)

- Every template's `body` and every `explainer` claim must be traceable to
  `source_files` in a corpus. No invented idioms.
- Wasp corpus: corpus/wasp-upstream (ar0551/Wasp, LGPL-3).
- Architectural corpus: corpus/arch/<repo>/ — each repo recorded in
  corpus/ARCH_SOURCES.md with URL, license, and what patterns it evidences.
- Slider ranges, panel formats, and grouping habits observed in corpus files
  are evidence; when corpora disagree, prefer the more canonical source and
  record the conflict.

## 3b. Template-expansion engine — **IMPLEMENTED (v0.5, server/expander.py)**

`expand_template(template_id, bindings, x, y)` + `list_templates()` are live
MCP tools (offline coverage: server/tests/test_v05.py). What shipped:
1. The four prose-slot templates were upgraded to the machine-parseable
   `slot:<name> -> <ref>.<Param>` wire syntax with GUIDs/param names taken
   from the corpus dumps: `arch.spatial_truss` (E.17, fully traced),
   `arch.section_contours` (E.20 core + optional Contour/layout tails),
   `arch.twist_tower` (ibrahimxxs core; Series stack stays a FLAGGED
   abstraction), plus `arch.attractor_scale_grid` (E.5.2).
   `arch.terrain_from_image` is marked **`expansion_blocked`** instead: the
   E.29 dump stores the heightmap as Image Sampler component state
   (values.FilePath), not a wire, and no bridge command can set it —
   blocked rather than invented.
2. Validation is all-up-front: unknown/unbound/kind-mismatched bindings are
   ONE typed `invalid_bindings` error (per-problem `details`) raised before
   any canvas mutation; data-only templates answer `template_not_expandable`
   listing their prose wires.
3. Stock components place BY componentGuid recorded in the body (regression
   finding #1), Wasp components via the registry; wiring uses the exact
   recorded param names (finding #2) with `connect_with_candidates` only as
   the fallback for unnamed slot sources; everything batches `solve:false`
   with one final expire + wait; v0.4 organization (stage group from
   `stage_name`, INPUTS group with role nicknames, wrapped explainer
   scribble) is applied automatically; results are v0.5 zone manifests.

Remaining gaps: the other 8 arch templates are still data-only (bodies keep
prose wires and un-GUIDed components — `list_templates` reports the exact
issues per template); Expression/Graph-Mapper/Image-Sampler component STATE
is not settable over the bridge (worked around with panel-constant
arithmetic where evidenced, blocking terrain_from_image); scenario A5 in
docs/arch-corpus-report.md is now executable but has not yet been run live.

## 4. Regression tie-in

Every new template gets: (a) an offline test asserting its expansion (slots →
commands), and (b) a live scenario in docs/validation-scenarios.md asserting
the built canvas solves without errors and produces the declared outputs.
