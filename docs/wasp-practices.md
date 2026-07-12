# Wasp practices — operational heuristics for generation

**Provenance:** distilled 2026-07-12 from Liang's tutorial-note summaries
(15 MD files, two batches) of Andrea Rossi's *Wasp for Grasshopper #101*
tutorial series and the *Strategic Discrete Aggregation* masterclass. Prose sources, so per
corpus discipline (PROTOCOL.md, generation-principles §3) **nothing here is
wiring evidence** — param names, GUIDs, and template bodies still come only
from corpus dumps. What this file carries is the *operational* knowledge the
dumps can't: why a wire exists, what value to set, which trap you're walking
into.

Each claim is tagged:
- **[verified]** — cross-checked against the Wasp source
  (`src/wasp/core/*.py`) or the mined corpus (`knowledge/wasp_patterns.json`).
- **[tutorial]** — from the tutorial notes only; plausible but not
  independently confirmed. Verify before promoting into macro behavior.

## 1. Part & connection authoring

- **Connection direction lines point from the face center OUTWARD.**
  Drawing the line toward the center rotates the connection plane 180°,
  producing overlapping/recursive placements. Same rule for explicit planes:
  the implied Z (x-axis × y-axis) is the mating direction and must point out
  of the part volume. [verified — create_wasp_part docstring codified this
  from live regression; tutorials explain the *why*]
- **Points and direction lines must be supplied in the same order** — Wasp
  pairs them by index. Connections are then numbered 0, 1, 2… in that order,
  and those indices are what rules reference. [verified — corpus connection
  idioms; Point List used in examples to check ordering]
- **Names are case-sensitive everywhere** (part NAME, rule text, connection
  types). "Square" ≠ "square". `define_rules` lints grammars for
  case-colliding part names. [verified — cookbook + corpus]
- When subdividing a prism with IsoTrim/Divide Domain to add connections,
  **isolate the quad side-faces first** — subdividing the polygonal caps
  yields non-orthogonal connection planes and erratic assemblies. [tutorial]

## 2. Rules

- **Rules are directional.** `A|0_B|1` = connection 0 of an *existing* A
  hosts connection 1 of a *new* B; the reverse move needs its own rule
  `B|1_A|0`. Without inverses an aggregation can exhaust its legal
  connections and stop far short of N — the "closed loop" trap (growth
  locked in A-B/B-A clusters). `define_rules` warns about missing inverses;
  deliberate one-way hierarchies (§ rule grammars below) are the legitimate
  exception. [verified — corpus scribble "NB: Rules are directional!"]
- **Three rule languages, never interchangeable** (see PROTOCOL corpus
  addendum 1): `P|0_P|1` → Rule From Text; `TYPE>TYPE` → Rules Generator GR;
  `P|c_P|c>node_node` → Graph-Grammar Aggregation RULES. [verified]
- **Rules Generator control inputs** — `SELF_P` (may a part connect to
  another instance of itself?), `SELF_C` (may a connection ID mate with the
  same ID?), `TYP` (only generate rules between connections sharing a type
  string). SELF_P=false forces part-type alternation; types prevent
  "illegal" pairings like a square face mating a hexagonal one. Type names
  are case-sensitive. [verified — param_aliases SELF_P/SELF_C/TYP; semantics
  from tutorials]
- **Rule grammars (`TYPE>TYPE`) are the sweet spot** between hand-writing
  every rule and the Rules Generator's all-combinations chaos. Architectural
  idiom from the tutorials (Maison-Domino-style towers):
  `slab_top>column_bottom`, `column_top>slab_bottom` (the vertical loop needs
  BOTH), `slab_side>step_bottom`, `step_top>step_bottom`,
  `step_top>slab_side` (stairs branch off and terminate into new slabs).
  [tutorial — grammar syntax verified, the specific grammar is not in the
  corpus]
- **Graph-grammar rules address parts by their assigned IDs.** The rule
  `HEXA|0_CUBE|1>a_b` names part TYPES and assigns IDs `a`/`b`; every
  SUBSEQUENT rule's left half references an already-assigned ID, not a type
  (`a|1_HEXA|2>a_c` goes BACK to part `a` and hangs a new hexagon off its
  connection 1). That is what makes hand-crafted sequences possible: any
  earlier part stays addressable. [verified — aggregate_sequence looks the
  left half up by id among aggregated_parts after the first rule]
- **Graph-grammar practicalities:** use Advanced Part (current experimental
  bugs give Basic Part display issues here), and reset the aggregation after
  every rule edit — the component is explicitly experimental. A strong idiom:
  build a small composite module under graph-grammar control (micro-scale),
  Solid Union it, feed the merged brep into a NEW Basic Part (remapping
  which sub-part connections stay active, via Tree Item on the connection
  tree), then aggregate those composite parts stochastically (macro-scale).
  [tutorial]

## 3. Aggregation modes & constraints

- **The MODE input gates constraint computation** — 0 none (default),
  1 local constraints only, 2 global only, 3 local+global. Constraints wired
  into GC while MODE=0 are silently ignored. `run_aggregation` sets MODE=2
  automatically when `global_constraint_ids` is given.
  [verified — wasp core aggregation.py; corpus MODE slider value 2]
- **Plane Constraint** (output PC): infinite plane, POS picks the allowed
  side; planes can be rotated for inclined boundaries or harvested from
  geometry faces (e.g. Voronoi cells). **Mesh Constraint** (output GC):
  closed mesh, IN toggles inside/outside growth. [verified — param_aliases;
  semantics from tutorials]
- **Multiple global constraints intersect (AND):** a part must satisfy all
  of them. Openings/voids = one mesh set to inside + an intersecting mesh
  set to outside. Newer Wasp exposes REQ to make a constraint optional
  (OR-ish logic). [verified for REQ input existing; AND semantics tutorial]
- **Soft vs hard:** SOFT=true checks only the part's center point — fast,
  parts may bleed past the boundary; SOFT=false runs full mesh-intersection —
  precise, expensive. Prototype soft, finalize hard. [tutorial]
- **Constrained aggregation places nothing?** The seed part sits outside the
  valid zone; the aggregation can't initialize. Move the seed into the zone
  with **Transform Part** (inputs PART/TR) before aggregating.
  [tutorial — Transform Part params verified in param_aliases]
- **Graph-grammar mode does NO collision or constraint checking** —
  `aggregate_sequence` never calls `collision_check` (the additional-collider
  check is commented out in the source). The grammar author owns overlap
  avoidance; `run_aggregation` rejects `global_constraint_ids` in graph mode.
  [verified — wasp core aggregation.py]

## 4. Field-driven aggregation

- **Remap distances so CLOSE = 1, FAR = 0.** Attraction fields from a
  curve/surface need the raw distances inverted; forgetting this repels
  parts from the target. [tutorial]
- **Sharpen transitions with a Graph Mapper (Bezier).** A linear remap gives
  a blurred low-density cloud; a sharpened curve makes parts "snap" to the
  target geometry. [tutorial — Graph Mapper appears in corpus field files,
  the Bezier-sharpening intent is tutorial prose]
- **Combine fields by multiplication:** `field_a × field_b × field_c` —
  any 0 zone vetoes growth there (built-in AND). [tutorial]
- **Field choice is deterministic** — the solver always takes the field
  optimum, which draws an unnaturally straight boundary where two part
  populations meet. Add small **stochastic noise (±0.15)** to the field
  values to get natural blended transitions: more noise = wider blend zone,
  less = sharper boundary. [tutorial]
- **Multi-channel fields are string-matched by NAME.** Give each Field
  component a name (its NAME input), merge the fields into the aggregation's
  FIELD input, and put the field's name into each part's FIELD input —
  which only **Advanced Part** exposes. A part with NO name silently
  defaults to the FIRST field in the list; a part naming a field that isn't
  supplied is a hard component error. [verified — Field-driven Aggregation
  component source; corpus pattern multichannel_field]
- **Multi-channel recipe** (two-typology blend in one volume): build one
  base field (e.g. distance-from-center remapped 1→0), multiply it by two
  opposite directional gradients (Y-coordinate remapped 0→1 and 1→0) to get
  fields "plus_y" / "minus_y", assign part A to one and part B to the other,
  and bridge the typologies with explicit transition rules between the two
  parts' shared connection types. Add the ±0.15 noise for the blend zone.
  [tutorial — mechanism verified, recipe prose]
- **Attractor recipe** (grow along curves, e.g. roads): project the curves
  onto the terrain, Pull Point from each field point to the curves, remap
  distances 1→0 (close = 1), Graph Mapper to tune the falloff. [tutorial]
- **Slope-repellant recipe** (avoid steep terrain): Evaluate Surface at the
  closest point for the normal, Angle against world Z, remap 1→0 so flat = 1
  and steep ≈ 0 — multiplied in, steep zones veto growth. [tutorial]
- **Surface half-field recipe** (urban growth hugging a terrain): bounding
  box around the surface scaled ~1.5 in Z, field resolution ~2.5–3; pull
  each field point to the surface and compare Z to detect below-terrain
  points; dispatch — below-surface points get value **0**, above-surface
  points get distance remapped 1→0 with a Bezier Graph Mapper; **Weave** the
  two streams back into the original point order (the field expects values
  in field-point order). [tutorial]

## 5. Attributes & geometry proxies (base vs detailed)

- **Aggregate lightweight colliders, carry detail as attributes.** The
  solver only collision-checks the base geometry; high-poly detail rides
  along as a Wasp Attribute and is transformed into place at the end.
  [verified — corpus patterns part_attributes / smart_attributes]
- **Transformable flag:** geometric attribute values → `true` (they must
  move with the part); non-geometric data (labels, metadata) → `false`.
  [tutorial]
- **Mesh-convert detail before attaching** (Mesh Brep component) — keeps
  display of thousands of parts responsive. [tutorial]
- Retrieval idiom: **Filter Parts by Name** to split part types, **Get
  Attribute by Name** (the ID you used, e.g. "detail") to pull the detailed
  geometry; a Stream Filter + Value List makes a base/detailed display
  toggle. Work in base mode, switch to detailed for finals. [tutorial —
  components exist in param_aliases]
- **Rule-testing goes faster on base geometry** — switch to detailed only
  once the grammar behaves. [tutorial]
- **Non-geometric attributes make variation legible.** When parts are
  logically identical but geometrically varied (e.g. built at different
  rotation angles), store the varying parameter as a non-transformable
  attribute (e.g. "angle" = the slider value at creation); after
  aggregation, Get Attribute by Name → remap 0–1 → Gradient → Custom
  Preview color-codes the structure by that parameter. [tutorial]
- Random per-part coloring for schematic urban models: color list → Random
  integers → List Item → Custom Preview. [tutorial]

## 6. Scale, persistence, stock

- **Save to File stores transformation matrices + part IDs, not geometry** —
  the JSON says *where* to place meshes, not *what* they are; that's why it
  stays lightweight at thousands of parts. The **PREV input** loads an
  existing aggregation as the base for iterative growth. [verified — corpus
  pattern save_load_aggregation; PREV in param_aliases]
- **Part Catalog** (inputs PART/NUM/LIM/AD, output CAT → aggregation CAT;
  `run_aggregation catalog_component_id` wires it): with **LIM=False (the
  default)** the NUM values are *proportional probabilities* — approximate,
  because rule counts bias placement; with **LIM=True** they are *hard
  stock* and the aggregation stops early once the catalog empties, whatever
  N says. **AD (adaptive) works ONLY with LIM=False** — it re-boosts
  under-represented parts against rule-frequency bias, and is experimental.
  [verified — Parts Catalog component source + corpus pattern parts_catalog]
- **Catalog + field mode mix worst:** the field outranks the ratios, so
  proportions drift furthest there — reach for LIM or AD in field-driven
  aggregations. [tutorial]
- **Hierarchical aggregation requires Advanced Part** — Basic Part can't
  hold the multi-level (level 0 / level 1) data. Sub-assemblies are built by
  transforming a base part (Move/Rotate) into an **Assembled Part**
  (experimental), merging geometry (Solid/Mesh Union — Merge Faces cleans
  the internal linework) and aggregating the connections. [tutorial —
  Advanced Part requirement corroborated by masterclass]
- **Hierarchy is free at solve time** — levels are only computed when
  extracted. **Get Parts Hierarchy** (inputs AGGR/LEVEL, output SUB_P) pulls
  level-N sub-parts from a finished aggregation; those sub-parts keep their
  connection logic, so they can seed a NEW aggregation via PREV (recursive
  growth: meta-aggregate large parts, extract the bricks, grow more bricks
  on top). Depth is effectively unlimited; hardware limits only the
  extracted element count. [tutorial — component params verified in
  param_aliases]
- **Rule count explodes with part complexity** — harmless for stochastic
  aggregation, but it measurably slows FIELD-driven aggregation; prune
  grammars before switching a complex part set to field mode. [tutorial]

## 7. Dynamic & staged aggregation (parts as parameters)

- **Connections are parametric, not fixed.** Extract the connection plane,
  rotate it around its Z with a slider, and feed it back through Connection
  From Plane as a new connection type (e.g. `outer_rot`); a `TYPE>TYPE`
  grammar like `outer>outer_rot` then forces every attachment through the
  rotation. The angle is a design dial: 90° = rigid interlock, 88° = subtle
  drift across the whole structure, 75° = chaotic. [tutorial — Connection
  From Plane + rotation corroborated by masterclass §3]
- **Parametric connections update live** — define connection points in
  Grasshopper (quad-face isolation → IsoTrim/Divide Domain² → face
  centroids + a consistent direction vector) instead of static Rhino
  points, and the part's connection count becomes a slider. [tutorial]
- **When rotating part geometry, transform the connection points and
  direction curves through the SAME transformation** — geometry and
  connection data that fall out of sync produce misaligned mating planes.
  [tutorial]
- **Seed methodology / staged growth:** aggregation state persists between
  edits, so you can grow in stages — e.g. 10–20 parts at a chaotic 75°,
  reset the angle to 90°, then keep adding: each new chunk interlocks
  rigidly relative to the irregular seed it attached to. Same trick with
  any parameter (angle sequences 90° → 60° → 0° give multi-tonal
  structures). Track what varied via a non-geometric attribute (§5).
  [tutorial]
- **Save limitation:** Save to File may NOT preserve geometry of parts that
  were edited mid-aggregation (it stores part definitions + transforms, and
  the definition changed under the placed parts). Archive staged/dynamic
  runs by baking, until Wasp ships edited-geometry persistence. [tutorial]

## Integration status

Codified into behavior (2026-07-12): `run_aggregation
global_constraint_ids` + automatic MODE=2 slider; `run_aggregation
catalog_component_id` → CAT wiring (with LIM/AD semantics in the tool doc);
`define_rules` inverse-rule and case-collision warnings; graph-mode
constraint AND catalog rejection; stage explainers `global_constraints`,
graph-mode collision note, and the multi-channel field-naming note. The
rest of this file is guidance for whoever (human or agent) drives the
tools — field-building and attribute macros don't exist yet, so §4–§5 and
§7 are prompt-level knowledge for now (the field recipes in §4 are the spec
for a future `create_field` macro).
