# Troubleshooting

Expanded from README's short list. Ordered roughly by how often you'll hit each.

## Component-ID-conflict popup when drag-dropping the .gha

**Symptom:** dropping `GH_MCP_Wasp.gha` onto the Grasshopper canvas raises a
"component ID conflict" dialog.

**Cause:** the assembly is already loaded from
`%APPDATA%\Grasshopper\Libraries\` and the drag-drop tries to load a second
copy — every component GUID in it collides with itself.

**Fix:** click **Skip All**. Nothing is lost; the Libraries copy stays active.
Long-term, pick one install path: keep the file in Libraries and stop
drag-dropping (drag-drop is only useful for a first run before the file is in
Libraries).

## bridge_unreachable

**Symptom:** every tool returns
`{"success": false, "error": "bridge_unreachable", ...}`.

Checklist, in order:

1. **Rhino + Grasshopper actually open?** The bridge lives inside the Rhino
   process.
2. **WaspMCP component on the canvas?** Search for "Wasp MCP Bridge"
   (Params > Util). It must be on the *active* document.
3. **Enabled input true?** The component only starts its TCP listener when
   `Enabled = true`. Its Status output should read `Running on port 8090`.
4. **Port mismatch?** The Python server targets `WASP_MCP_PORT` (default 8090);
   the component listens on its Port input (default 8090). Both must agree.
5. **.gha loaded at all?** Check Grasshopper's component panel; if missing, the
   file may be blocked (Explorer > Properties > Unblock) or GH's COFF loading
   settings interfered. Restart Rhino after fixing.
6. **Firewall** rarely matters (loopback only) but a very aggressive endpoint
   product can still kill localhost listeners.

## Port conflicts on this machine

Three local MCP bridges run here — keep them apart:

| Port | Owner |
|---|---|
| 5000 | Almond Rhino bridge |
| 8090 | **wasp-mcp** (this project) |
| 48884 | Revit MCP |

If 8090 is taken (Status shows an error, or the listener dies immediately):
pick another port, set the component's Port input to it, and set
`WASP_MCP_PORT` to the same value in the WaspMCP server entry in
`claude_desktop_config.json` (env block), then restart Claude Desktop.
`netstat -ano | findstr :8090` shows who holds the port.

## solution_running and timeouts on long aggregations

Two distinct behaviors, both by design:

- **`solution_running`** (surfaced as `bridge_command_failed` with message
  `solution_running`): the bridge refuses to read output while the GH solution
  is computing, or while the target param is expired-but-not-yet-solved
  (a scheduled solve that hasn't fired). This is the no-stale-data contract —
  retry after a moment.
- **`timed out after 30 s`** / **`bridge_timeout`**: a long solve occupies the
  Rhino UI thread, so the bridge can't even get on it to answer. The UI-thread
  marshal gives up at 30 s (per command); the Python socket read gives up at
  60 s.

What to do:

- The **macros already retry** both cases (up to 20 × 0.5 s in
  `get_output_when_idle`). For very long aggregations (high N, heavy meshes)
  that budget (~10 s of retrying plus per-attempt waits) can still run out —
  poll `gh_canvas_state` until `solutionState: "idle"`, then read again.
- Rhino is **not frozen** — Grasshopper solves block its UI by nature. Watch
  the GH window; when the profiler/cursor settles, read again.
- Prefer `out="bake"` over pulling thousands of meshes through the wire.

## Empty-items result right after expiring

**Symptom:** `gh_get_output` succeeds but `items` is `[]` immediately after
`gh_expire` / a macro run, then a later read has data.

**Cause:** a narrow window where an expired param slips through as an empty
success before the scheduled solve fires. The bridge guards the common case
(param phase `Blank` → `solution_running`), and the macro layer additionally
retries an empty first response twice. If you drive low-level tools yourself,
copy that habit: empty items right after an expire → wait 0.5 s and re-read
before trusting the emptiness.

## Registry staleness

**Symptom:** `component_not_found` for a component you just installed, or
`gh_add_wasp_component` places an old version.

**Cause:** the registry scans `%APPDATA%\Grasshopper\UserObjects` once at
server start; `.ghuser` files added/updated afterwards aren't indexed.

**Fix:** call `refresh_registry`. Note the registry only indexes files matching
`Wasp_*.ghuser` — renamed or differently prefixed files are invisible by
design. Also note: Grasshopper itself must know the UserObject too if you want
to interact with it manually, but the bridge instantiates directly from the
file path, so a refresh + placement works without restarting GH.

## Upgrading the .gha (bridge versions)

Windows/. NET keeps a loaded assembly locked and resident for the life of the
process — replacing `GH_MCP_Wasp.gha` while Rhino runs does **not** hot-swap
the code (and the file may be locked against overwriting).

Procedure:

1. Close Rhino (fully — check no `Rhino.exe` lingers in Task Manager).
2. Build: `dotnet build -c Release` in `GH_MCP_Wasp\` (output lands in
   `build\`).
3. Copy `build\GH_MCP_Wasp.gha` over the copy in
   `%APPDATA%\Grasshopper\Libraries\`.
4. Start Rhino + Grasshopper; the new version loads at startup. Re-place or
   re-enable the WaspMCP component.

The Python side has no such constraint — restarting Claude Desktop restarts the
server with the current code.

## gh_clear kept some components / removed one I wanted

`clear_document` deliberately preserves the bridge component and, heuristically,
anything whose nickname or type contains `MCP`, `Claude`, `Toggle`, or
`Status`. Side effects: your own panel nicknamed "Status" survives a clear, and
a Boolean Toggle you placed manually survives too. Delete such objects manually
in GH (v0.2's `delete_components` will make this scriptable).

## Component placed but orange/red

Not a bridge fault — the component is missing inputs (normal mid-macro or after
step (b) in the cookbook). `gh_canvas_state` returns each component's
`runtimeMessages`; `level: "error"` entries tell you which input is unhappy.
Wasp GhPython components also go red if the Wasp Python modules are missing —
verify plain-GH Wasp works by hand if errors mention imports.

## Aggregation stops well short of N parts

Not a bridge fault — the rule grammar ran out of legal moves. Wasp rules are
directional (`A|0_B|1` never implies `B|1_A|0`); a grammar without inverse
rules can strand growth in small clusters once every open connection lacks a
compatible rule ("closed loop" trap). `define_rules` returns a `warnings`
list naming the missing inverses — add them if growth should continue both
ways. Collisions also consume moves: densely self-intersecting parts
legitimately stall early. See docs/wasp-practices.md §2.

## Constrained aggregation ignores constraints, or places nothing

Two distinct failures (docs/wasp-practices.md §3):

- **Constraints ignored:** constraints wired into GC only compute when the
  aggregation MODE input is 2 (global) or 3 (local+global); the default
  mode 0 skips them silently. `run_aggregation` with `global_constraint_ids`
  wires GC *and* places a MODE slider at 2 — if you wired GC by hand with the
  low-level tools, check the MODE input.
- **Nothing places at all:** the seed part sits outside the allowed zone, so
  the aggregation cannot initialize. Move the seed into the valid region with
  Wasp Transform Part (or move/flip the constraint) and reset.

## Multi-field aggregation: everything follows one field / field-name error

Wasp matches parts to fields **by name** (docs/wasp-practices.md §4). With
several fields merged into FIELD:

- A part with an empty FIELD input silently defaults to the **first** field
  in the list — so "my second field does nothing" usually means no part
  names it.
- A part naming a field that isn't supplied is a hard component error
  ("does not have a valid field name assigned").

Fix: give every Field component a NAME, and put that name into each part's
FIELD input — which only **Advanced Part** exposes (Basic Part has no FIELD
input; that alone forces the Advanced Part switch for multi-channel work).

## Part proportions don't match my catalog numbers

Expected behavior, mostly (docs/wasp-practices.md §6): with LIM=False the
NUM values are probabilities, and parts with more valid rules still win more
placements; in field mode the field outranks the ratios entirely. Options:
LIM=True makes NUM a hard stock (the aggregation then stops early when the
catalog empties — that's the trade), or AD=True re-balances probabilities
adaptively (experimental, and only works with LIM=False).

## Macro failed halfway

Macros place several components then wire them; a failure mid-way (e.g.
`param_not_found` on an unexpected Wasp version) leaves the already-placed
components on the canvas. They're harmless but noisy: check the error's
`message` for what was expected, then either wire the remainder manually with
`gh_connect` (the message lists the real params) or `gh_clear` and retry.
