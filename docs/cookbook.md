# Cookbook — Wasp workflows via Claude

Copy-paste-able prompts to give Claude Desktop, plus the Wasp concepts you need
to read the results. Prerequisite for all of them: Rhino 8 + Grasshopper open,
WaspMCP component on the canvas with `Enabled = true` (see README).

## Wasp in 60 seconds

Wasp (Andrea Rossi) does **discrete aggregation**: it assembles many copies of a
few modular parts into larger structures, the way bricks or growth systems
work.

- **Part** — a named unit of geometry (a mesh) plus a set of **connections**.
- **Connection** — an oriented plane on the part where another part may attach.
  Connections are numbered `0, 1, 2, ...` per part in the order supplied.
- **Rule** — a permitted pairing: *this connection of part A may mate with that
  connection of part B*.
- **Aggregation** — the solver. Starting from one part it repeatedly picks a
  rule (stochastically, field-driven, or by graph grammar) and attaches new
  parts until it reaches N parts or runs out of collision-free moves.

### Rule grammar (Rules From Text)

One rule per line. The canonical Wasp text form is:

```
PARTNAME|CONN_PARTNAME|CONN
```

`A|0_B|1` reads: connection `0` of part `A` pairs with connection `1` of part
`B` — during aggregation a new part is attached by mating those two connection
planes. With a single self-similar part `P`, the grammar

```
P|0_P|1
```

means: connection 0 of an **existing** `P` hosts connection 1 of a **new** `P`
— the first half of the rule is the part already placed, the second half is
the incoming part (Wasp `Rule(part1, conn1, part2, conn2)` semantics; rules
are directional — write both directions if you want both).
Part names in the grammar must match the `name` you gave `create_wasp_part`
exactly (case-sensitive). More lines = more permitted attachments = richer,
less predictable growth. `define_rules` lints the grammar and returns
non-fatal `warnings` for missing inverse rules and case-colliding names.
For deeper authoring guidance (connection orientation, constraints, fields,
geometry proxies) see docs/wasp-practices.md.

> Note: the separator syntax (`|` between part and connection, `_` between the
> two halves) belongs to Wasp's "Rules From Text" component, not to this
> bridge — the bridge passes the text through verbatim. If your Wasp version
> rejects a grammar, open the placed panel in GH and check against the syntax
> the component's help reports. Beware: `>` never appears in Rule From Text
> grammars — it belongs to the Rules Generator (`TYPE>TYPE`) and Graph-Grammar
> (`rule>node_node`) languages, and `define_rules` rejects it with a pointer.

---

## (a) First canvas contact / health check

> Using the WaspMCP tools: call `gh_canvas_state` and tell me what's on my
> Grasshopper canvas and whether the solution is idle. Then call
> `list_wasp_components` and summarize how many Wasp components are installed,
> grouped by category.

Expected: a component list including "Wasp MCP Bridge", `solutionState:
"idle"`, and 63 registry entries. If you get `bridge_unreachable`, see
docs/troubleshooting.md.

## (b) Place and inspect a Wasp component

> Place a Wasp Stochastic Aggregation component at canvas position (600, 300)
> with `gh_add_wasp_component`, and report its real input and output parameter
> names, nicknames, and indices. Don't wire anything yet.

Expected: an `inputs` list (PART / RULES / N / SEED / RESET or similar —
nicknames vary by Wasp version, which is exactly why you inspect instead of
assuming) and a PART-ish output. The component will sit orange/red until wired;
that is normal.

## (c) Build a part from Rhino geometry with connection planes

Select or note the GUID of a closed mesh in Rhino first (Rhino command `What`
or `SelID` shows object ids; or ask Claude to find it via your Rhino MCP if you
run one).

> Create a Wasp part named `HEX` from the Rhino mesh with GUID
> `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` using `create_wasp_part`, with two
> connection planes:
> 1. origin (0,0,0), x-axis (1,0,0), y-axis (0,1,0)
> 2. origin (0,0,10), x-axis (-1,0,0), y-axis (0,1,0)
> Place it around (0, 0) on the canvas. Then call `gh_canvas_state` and confirm
> the part component has no runtime errors.

Notes:
- Connection planes are in Rhino world coordinates on the part's geometry.
  The z-axis (implied by x×y) should point *outward* — that's the mating
  direction.
- In v0.1 each plane becomes three panels feeding a Construct Plane component;
  expect a small cluster of feeders left of the part.

## (d) Rules from grammar text

> Using `define_rules`, create rules for my parts with this grammar (one rule
> per line):
> ```
> HEX|0_HEX|1
> HEX|1_HEX|0
> ```
> Wire in the part component `<part_id from step c>`. Report the
> rules_component_id.

## (e) Run a stochastic aggregation and bake to Rhino layers

> Run a stochastic aggregation with `run_aggregation`: parts
> `[<part_id>]`, rules `<rules_component_id>`, 100 parts, seed 42. Then poll
> `gh_canvas_state` until solutionState is "idle" (wait a few seconds between
> polls), and once idle call `get_aggregation` with out="bake" and layer
> "WASP::AGG_100". Tell me how many objects were baked.

Notes:
- Aggregations of a few hundred parts can take tens of seconds; a poll during
  the solve returning `solution_running` or a timeout is expected — keep
  polling (see troubleshooting).
- Baked objects land on the nested Rhino layer `WASP > AGG_100` (`::` separates
  layer levels; layers are created automatically).
- Re-runs: bump the seed slider (`gh_set_slider` on the returned
  `seed_slider_id`) and `gh_expire` the aggregation to get a new variant; bake
  each variant to its own layer to compare.

## (f) Reading back meshes / transforms

For meshes (geometry of every placed part):

> Call `get_aggregation` on `<aggregation_id>` with out="meshes" and
> max_items=50, and summarize: how many items, and the vertex/face counts of
> the first mesh.

For transforms (lighter — one 4×4 matrix per placed part, useful if I want to
instance the base geometry myself):

> Call `get_aggregation` on `<aggregation_id>` with out="transforms" and give
> me the first three transforms.

Notes:
- Meshes come back as `{"vertices": [[x,y,z],...], "faces": [[a,b,c(,d)],...]}`,
  transforms as 16-float row-major arrays.
- If the result says `"truncated": true`, raise `max_items` — or don't pull
  the data through the wire at all and use out="bake" instead.
- `out="transforms"` requires the `deconstruct_part` UserObject (present in
  the standard Wasp install).

## (g) Constrain the aggregation to a volume

Global constraints crop growth to a buildable zone. Place the constraint
component first, then hand its id to `run_aggregation`:

> Place a Wasp Mesh Constraint with `gh_add_wasp_component` at (100, 500),
> reference my closed Rhino mesh `<guid>` into a Geometry param with
> `gh_set_geometry_ref`, and wire it into the constraint's GEO input. Then
> run a stochastic aggregation with `run_aggregation`: parts `[<part_id>]`,
> rules `<rules_component_id>`, 200 parts, and
> `global_constraint_ids: ["<constraint_component_id>"]`.

Notes:
- `run_aggregation` wires the constraint output (Mesh Constraint `GC` /
  Plane Constraint `PC`) into the aggregation's GC input **and sets the MODE
  slider to 2 automatically** — constraints are silently ignored at the
  default mode 0.
- Multiple constraints intersect (a part must satisfy all of them). A void =
  one mesh constraint set to inside + an intersecting one set to outside.
- If zero parts place, the seed part is outside the allowed zone — move it
  with Wasp Transform Part, or move/flip the constraint. More in
  docs/wasp-practices.md §3 and troubleshooting.

## Bonus: save your work

> Save the current Grasshopper definition to
> `C:\Users\liang\OneDrive\Documents\Almond\wasp-mcp\out\aggregation.gh` with
> `gh_save`.

And when the canvas gets messy:

> Call `gh_clear` to wipe the canvas — it keeps the WaspMCP bridge component
> alive.
