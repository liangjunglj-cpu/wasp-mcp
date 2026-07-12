# Wasp practices — operational heuristics for generation

**Provenance:** distilled 2026-07-12 from Liang's tutorial-note summaries
(7 MD files) of Andrea Rossi's *Wasp for Grasshopper #101* tutorial series
and the *Strategic Discrete Aggregation* masterclass. Prose sources, so per
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
  values to get natural blended transitions. [tutorial]
- Multi-channel setups can steer each part type by its own field (per-part
  field assignment). [verified — corpus pattern multichannel_field]

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

## 6. Scale, persistence, stock

- **Save to File stores transformation matrices + part IDs, not geometry** —
  the JSON says *where* to place meshes, not *what* they are; that's why it
  stays lightweight at thousands of parts. The **PREV input** loads an
  existing aggregation as the base for iterative growth. [verified — corpus
  pattern save_load_aggregation; PREV in param_aliases]
- **Part Catalog** manages stock: *limited* (stop when stock runs out),
  *proportional* (percentage probabilities), and an experimental *adaptive*
  toggle that deprioritizes over-placed parts (rule-frequency bias
  feedback). Feeds the aggregation CAT input. [verified — corpus pattern
  parts_catalog; adaptive semantics tutorial]
- **Hierarchical aggregation requires Advanced Part** — Basic Part can't
  hold the multi-level (level 0 / level 1) data. [tutorial]

## Integration status

Codified into behavior (2026-07-12): `run_aggregation
global_constraint_ids` + automatic MODE=2 slider; `define_rules` inverse-rule
and case-collision warnings; graph-mode constraint rejection; stage
explainers `global_constraints` + graph-mode collision note. The rest of
this file is guidance for whoever (human or agent) drives the tools —
field-building and attribute macros don't exist yet, so §4–§5 are
prompt-level knowledge for now.
