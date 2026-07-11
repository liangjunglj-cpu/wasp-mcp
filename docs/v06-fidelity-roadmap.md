# v0.6 — general Grasshopper generation fidelity

Goal: move general (non-Wasp) generation from "places plausible components that
often don't cohere" to "produces graphs that solve, type-check, and match
intent." This doc sets the engineering direction; it is grounded in a scan of
the field (industry tools + academic work, July 2026) recorded in the private
lab (`wasp-mcp-lab/research/gh-generation-landscape.md`).

## The core problem, precisely

A Grasshopper definition is a **typed, directed dataflow graph with tree-shaped
data**. Incoherence in LLM-generated graphs comes from four distinct failure
classes, in rough order of how often they break a graph:

1. **Wrong component identity** — the name the model picks resolves to the
   wrong proxy ("Square" → Maths>Square, not Vector>SquareGrid), or a
   component that doesn't exist. (We already log this: REGRESSION_LOG finding
   #1; v0.5 added nickname+ambiguity resolution.)
2. **Type mismatch at the wire** — output is a Surface, the target input wants
   a Curve; or a number feeds a plane. The connect succeeds structurally but
   the solve errors or coerces silently.
3. **Data-tree / graph-structure mismatch** — the single biggest source of
   *silently wrong* output. A list where a tree is needed, unflattened
   branches multiplying into millions of items, a graft missing so two lists
   pair 1:1 instead of cross-referencing. The graph "works" but the geometry
   is nonsense.
4. **Missing intermediate logic** — the model jumps from A to D and omits the
   remap/normalize/reparameterize step a competent author always inserts.

Our current evidence layer addresses (1) well and (2) partially. (3) and (4)
are where "coherent" is won or lost, and neither is solved by better prompting
alone — they need **structural knowledge encoded in the tool layer**, which is
exactly our moat's shape.

## What the field does (and where the ceiling is)

- **Prompt-to-graph plugins** (GHPT and successors): the LLM emits a
  JSON-ish list of components + connections; the plugin instantiates it. No
  type checking, no tree reasoning — coherence is whatever the base model
  happened to learn. Fine for small canonical graphs, degrades fast with size.
- **Canvas-context copilots** (Ant, GH Pilot, Planaria, Smarthopper): the
  advance that's winning the market — they **serialize the user's existing
  canvas** (component names, wires, input access mode Item/List/Tree, data
  types) into the prompt so the model edits *in context* rather than
  generating blind. Ant explicitly "translates the actual logic of your
  components and wires into a structured format the LLM can understand."
  Planaria advertises "self-corrects" (solve → read errors → repair loop).
- **Multi-agent decomposition** (LLMto3D, PromptMorph, academic): one agent
  parses intent into design elements + spatial relations, another realizes
  geometry. Better on complex prompts; slower.

The ceiling every one of these hits: **none publishes a way to guarantee tree
coherence**, and the closed ones carry no auditable evidence for their choices.
That gap is our opening.

## Five upgrades for v0.6 (in priority order)

### 1. Round-trip validation loop (highest leverage, we're closest)
We uniquely already have the eyes and the state reads. Formalize a
**generate → solve → read runtime messages → repair** cycle as a first-class
macro (`build_and_verify`): after `expand`/placement, call `gh_canvas_state`,
collect per-component `runtimeMessages` (errors/warnings we already surface),
and feed them back for a bounded repair pass. Planaria/Ant do a weaker version
of this; we can do it rigorously because our bridge already refuses stale data
and reports blank-phase. **This is the single biggest coherence win per unit
effort** and reuses shipped infrastructure.

### 2. A type + tree layer in the knowledge base
Extend the component KB from "who feeds whom" (frequency) to **typed ports**:
per component, each input/output's `typeName` and default **access mode**
(Item/List/Tree). Then a pre-placement checker can reject or auto-insert:
- **type adapters** where a wire crosses types the corpus never connects
  directly (evidence: if `A.out → B.in` never appears but
  `A.out → X → B.in` does, X is the missing adapter);
- **tree ops** (Graft/Flatten/Simplify) where access modes mismatch — encode
  the corpus's actual Graft/Flatten placement as evidence, not heuristics.
The dump already records access mode; we're mining data we already have.

### 3. Idiom templates for the "missing logic" class
The arch corpus already surfaced the repeated idioms (Bounds→Remap Numbers for
normalization; Series→Unit→Move for arrays; Graph Mapper after Remap for
response curves — see arch-corpus-report.md). Promote these from prose notes to
**expandable micro-templates** the planner inserts automatically, so generated
graphs get the normalize/remap steps a human always adds. This is template
expansion (already shipped) applied at finer grain.

### 4. Canvas-context editing (match the market's table stakes)
`gh_canvas_state` already serializes components + wires. Add access-mode and
type to that payload (needs a small bridge addition to read
`IGH_Param.Access` and the resolved data type) so the model can **edit an
existing user canvas** coherently, not just build new. This is what every
context-copilot ships; we're one bridge field away and it unlocks the "add a
slider to control the radius / divide this surface into panels" workflows
users now expect.

### 5. An evaluation harness (our credibility differentiator)
No competitor publishes coherence metrics. Turn our validation-scenarios
discipline into a scored benchmark: a set of intent→expected-structure cases,
scored on (a) solves-without-error, (b) output type matches intent, (c) tree
structure matches expected, (d) component count sanity. Run it per model and
per KB version. This makes "more coherent" a number we can show, gates KB
releases against regressions, and is the artifact that substantiates the
model-agnostic claim (same harness, many models).

## Corpus expansion needed to feed the above

Current general/arch corpus is ~156 files; typed-port + tree-idiom mining wants
more breadth. Clean, minable candidates identified (licenses verified):
- **mcneel/rhino-developer-samples** — MIT, first-party, canonical component
  usage. Best single source; safe commercially.
- **ladybug-tools/lbt-grasshopper-samples** — GPL-3: minable for *facts*
  (param names, tree ops) with the same facts-not-expression position as Wasp,
  but keep derived artifacts clearly separated and documented; when in doubt,
  use for validation not shipped templates.
- **jhorikawa/GrasshopperHowtos** — 100+ files but **no license file**
  (all-rights-reserved): usable privately for research/validation only, never
  as shipped evidence. Same rule as the two purged arch repos.
- **Hydra** (chriswmackey/hydra_2) — community example-sharing platform;
  per-file provenance varies, treat case by case.

Discipline unchanged: mine only into the private lab; ship only baked,
license-clean knowledge; every claim traceable to a licensed source.

## Sequence

1. `build_and_verify` repair loop (reuses shipped tools; biggest win).
2. Access-mode + type in `gh_canvas_state` (one bridge field) → unlocks both
   context-editing (#4) and the type/tree checker's live inputs.
3. Typed-port KB mining from rhino-developer-samples (MIT) → checker + adapters.
4. Tree-idiom micro-templates.
5. Evaluation harness, run per model + KB version; gate releases on it.
