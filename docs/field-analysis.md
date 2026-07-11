# Field-driven aggregation analysis — 2026-07-10

> **Scope: validation exercise, not method.** This run (like the tetris
> stochastic demo) is a test case for the tool surface. It is not the main
> method or operating model Wasp workflows should follow, and its canvases
> are never mined into the knowledge base (see corpus/self-generated/README.md).
> Only the codified findings below are binding.

First live exercise of `run_aggregation(mode="field")`. Same three tetromino
parts (I/L/T) and the same 10-rule grammar as the stochastic tetris run;
the only variable is a Wasp Field steering placement choice.

## Setup (corpus-evidenced chain, pattern `field_driven_aggregation`)

Boundary Center Box (300×300×120) → **Field Points** (RES 10 → 12,493
voxels) → per-voxel value = distance to an attractor point, remapped and
INVERTED (1.0 at the attractor, 0.0 at the far corner) → **Wasp Field** →
`FIELD` input of **Field-driven Aggregation** (N=40, no seed — field mode
has none). Attractor A = (100, 80, 40); attractor B = (−100, −80, 40).

## Measurements (40-part runs; positions from Deconstruct Part transforms)

| Run | Centroid | min dist → A | min dist → B | within 80 of A | within 80 of B |
|---|---|---|---|---|---|
| Stochastic baseline (n=32) | (33, 17, 43) | 50.0 | — | 9 | — |
| Field → A | (34, 23, 20) | **14.1** | — | 9 | — |
| Field → B (verified field) | (−4, −31, 4) | 89.7 | **18.4** | **0** | 7 |

- **Steering is causal and bidirectional**: wherever the attractor sits, the
  growth reaches it (min dist 14–18 vs 50 for unsteered), and the far side
  is abandoned entirely (0 parts within 80 of the opposite attractor).
- **Mean distance is the wrong metric for chain growth**: it stays ~130 in
  all runs because the aggregation is a connected chain from the origin — the
  tail must span origin→attractor. Arrival (min dist) and occupancy
  (within-radius counts, centroid quadrant) are the meaningful signals.
- Field mode placed all 40/40 parts in every run; the stochastic baseline's
  n=32 transform count on its final state reflects collision-pruned regrowth.

## Findings (knowledge-base-worthy)

1. **Wasp Field names must avoid spaces and `_ | >`** — reserved characters.
   The bridge surfaced Wasp's own error verbatim
   ("Field name attractor_field contains a space or one of the reserved
   characters: _|> "). Underscore-free names only (e.g. "attractorfield").
2. **Verify the instrument before trusting the measurement**: the first
   attractor-move run was invalid because the panel lookup matched a `Point B`
   connection in a DIFFERENT canvas zone (the A1 demo's attractor). Probing
   the field (arg-max of VAL vs expected attractor position) caught it.
   Lesson for the expansion engine: id lookups must always be zone-scoped,
   and field workflows should include a self-check probe.
3. Field mode has genuine run-to-run variation (no SEED input): two runs on
   the identical field differed substantially in shape while both reaching
   the attractor. Reproducibility in field mode requires saving/loading the
   aggregation itself (Wasp_Save/Load Aggregation), not a seed.

## Artifacts

- Canvas archived: `corpus/self-generated/tetris_field_analysis.gh` (+ dump).
- Baked results: Rhino layers `WASP::TETRIS_FIELD` (attractor A run) and
  `WASP::TETRIS_FIELD_B` (attractor B run).
- Canvas state at archive time: zero errors; attractor restored to A.
