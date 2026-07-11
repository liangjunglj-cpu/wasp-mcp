"""High-level Wasp workflow macros (PROTOCOL.md "Macros").

Each macro composes low-level bridge calls (via gh_client.GHClient) and
returns the ids of every component it placed. Wasp param nicknames are NOT
hardcoded by index: after ``add_user_object`` we read the returned
``inputs``/``outputs`` lists and match case-insensitively against candidate
name lists (``match_param``).

Registry keys these macros depend on (verified against the .ghuser files
installed in %APPDATA%\\Grasshopper\\UserObjects on this machine):
  basic_part, connection_from_plane, rule_from_text,
  stochastic_aggregation, field_driven_aggregation,
  graph_grammar_aggregation, get_part_geometry, deconstruct_part
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from gh_client import BridgeError, GHClient
from registry import WaspRegistry

# Candidate param names (name OR nickname, case-insensitive). Order = priority.
PART_GEO_IN = ["GEO", "GEOMETRY", "G", "MESH", "M"]
PART_NAME_IN = ["NAME", "N", "ID"]
PART_CONN_IN = ["CONN", "CONNECTIONS", "C"]
PART_OUT = ["PART", "P"]
CONN_PLANE_IN = ["PLN", "PLANE", "PLANES", "PL"]
CONN_OUT = ["CONN", "CONNECTIONS", "C"]
RULE_TEXT_IN = ["R", "RULES", "RULE", "TXT", "TEXT", "GR", "GRAMMAR"]
RULE_PART_IN = ["PART", "PARTS", "P"]
RULE_OUT = ["R", "RULES", "RULE"]
AGG_PART_IN = ["PART", "PARTS", "P"]
AGG_RULES_IN = ["RULES", "RULE", "R", "GR"]
AGG_COUNT_IN = ["N", "NUM", "COUNT", "ITERATIONS"]
AGG_SEED_IN = ["SEED", "S"]
AGG_FIELD_IN = ["FIELD", "F"]
AGG_RESET_IN = ["RESET", "RES"]
# Aggregation outputs are AGGR (the aggregation object) then PART_OUT (the
# parts). ALL corpus geometry/transform extraction reads PART_OUT; AGGR only
# feeds Aggregation Graph / Save Aggregation / Rules From Aggregation — so
# extraction candidates put PART_OUT first and AGGR last-resort.
# AGGR is deliberately EXCLUDED from wiring candidates (validator F3): it
# always connects successfully, so having it anywhere in the retry list means
# a renamed parts output would silently bind the aggregation object instead
# of failing loudly. It remains valid only for output-name *reporting*.
AGG_PARTS_OUT_FALLBACK = ["PART_OUT", "PART", "PARTS"]
FIELD_OUT = ["FIELD", "F"]
GETGEO_PART_IN = ["PART", "PARTS", "P"]
GETGEO_OUT = ["GEO", "GEOMETRY", "G", "M", "MESH"]
DECON_PART_IN = ["PART", "P"]
DECON_TR_OUT = ["TR", "TRANSFORM", "TRANSFORMS", "T"]

AGGREGATION_KEYS = {
    "stochastic": "stochastic_aggregation",
    "field": "field_driven_aggregation",
    "graph": "graph_grammar_aggregation",
}

# ── knowledge base (server/knowledge, built from the Wasp example corpus) ──

_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"
_param_aliases_cache: Optional[Dict[str, Any]] = None

_AGG_ALIAS_KEYS = (
    "Wasp_Stochastic Aggregation",
    "Wasp_Field-driven Aggregation",
    "Wasp_Graph-Grammar Aggregation",
)


def load_param_aliases() -> Dict[str, Any]:
    """Lazily load param_aliases from knowledge/wasp_patterns.json.

    Authoritative input/output names for all Wasp components (mined from
    Wasp's own component-repository sheet). Returns {} when the knowledge
    base is absent — callers must keep their candidate-list fallbacks.
    """
    global _param_aliases_cache
    if _param_aliases_cache is None:
        try:
            with open(_KNOWLEDGE_DIR / "wasp_patterns.json",
                      encoding="utf-8") as fh:
                loaded = json.load(fh).get("param_aliases") or {}
            # F4: a non-dict shape (e.g. a list) would crash consumers with
            # AttributeError, which escapes the tool-layer error handling.
            _param_aliases_cache = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            _param_aliases_cache = {}
    return _param_aliases_cache


def aggregation_parts_out_candidates() -> List[str]:
    """Output-param candidates for extracting PARTS from an aggregation.

    Built from the knowledge base when present, reordered so PART_OUT-like
    names come before AGGR (corpus evidence: extraction always reads
    PART_OUT; AGGR is the aggregation object for graph/save components).
    """
    aliases = load_param_aliases()
    names: List[str] = []
    for key in _AGG_ALIAS_KEYS:
        for param in (aliases.get(key) or {}).get("outputs") or []:
            name = str(param.get("name") or "").strip()
            if name and name not in names:
                names.append(name)
    if not names:
        return list(AGG_PARTS_OUT_FALLBACK)
    # Wiring candidates only — drop AGGR entirely (F3: it always connects, so
    # it would mask a renamed parts output instead of failing loudly).
    ordered = [n for n in names if "PART" in n.upper() and n.upper() != "AGGR"]
    for fallback in AGG_PARTS_OUT_FALLBACK:
        if fallback not in ordered:
            ordered.append(fallback)
    return ordered

# ── v0.2 capability probing ────────────────────────────────────────────────

# Error-text markers that mean "the bridge does not know this command".
# PROTOCOL.md specifies "Unknown command type" (bridge >= 0.2 wording); the
# shipped v0.1 bridge answers "No handler registered for command type", so
# both are accepted for v0.1 compatibility.
UNKNOWN_COMMAND_MARKERS = (
    "unknown command type",
    "no handler registered for command type",
)

# Deliberately-invalid id used to probe set_plane_values support without
# mutating the canvas: a v0.2 bridge rejects the arguments (any error text
# except an unknown-command marker), a v0.1 bridge rejects the command itself.
_PROBE_ID = "00000000-0000-0000-0000-000000000000"

_PROBE_CACHE_ATTR = "_wasp_supports_set_plane_values"


def is_unknown_command_error(message: str) -> bool:
    """True when a bridge error message means 'command not implemented'."""
    lowered = str(message or "").lower()
    return any(marker in lowered for marker in UNKNOWN_COMMAND_MARKERS)


def supports_set_plane_values(client: GHClient) -> bool:
    """Probe (once per client instance) whether the bridge speaks v0.2.

    Sends a set_plane_values with a null id and no planes: a v0.2 bridge
    answers with an argument error, a v0.1 bridge with an unknown-command
    error. The verdict is cached on the client instance; transport errors
    (bridge unreachable/timeout) propagate and are NOT cached.
    """
    cached = getattr(client, _PROBE_CACHE_ATTR, None)
    if cached is not None:
        return cached

    try:
        client.call("set_plane_values", {"id": _PROBE_ID, "planes": []})
        supported = True  # unexpected success still proves the command exists
    except BridgeError as exc:
        if exc.code != "bridge_command_failed":
            raise  # transport problem: leave the cache unset
        supported = not is_unknown_command_error(exc.message)

    setattr(client, _PROBE_CACHE_ATTR, supported)
    return supported


# ── v0.3 version probing ───────────────────────────────────────────────────

_VERSION_CACHE_ATTR = "_wasp_bridge_version"

# Default assumed for bridges that predate the "version" field
# (get_document_info gained it in v0.2).
_V01 = (0, 1, 0)


def parse_version(text: Any) -> Tuple[int, int, int]:
    """Parse a bridge version string ("0.3.0") into a comparable 3-tuple.

    Missing/unparseable input means a v0.1 bridge (the "version" field was
    added to get_document_info/get_canvas_state in v0.2).
    """
    if not text:
        return _V01
    numbers = re.findall(r"\d+", str(text))
    if not numbers:
        return _V01
    parts = [int(n) for n in numbers[:3]]
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])


def bridge_version(client: GHClient) -> Tuple[int, int, int]:
    """Probe (once per client instance) the bridge version.

    Reads the "version" field of get_document_info: absent on a v0.1 bridge,
    "0.2.0"/"0.3.0"/... afterwards. A bridge_command_failed answer (e.g. no
    active GH document) is treated as v0.1 for this call but NOT cached, so
    a later probe can still detect the real version. Transport errors
    propagate and are never cached.
    """
    cached = getattr(client, _VERSION_CACHE_ATTR, None)
    if cached is not None:
        return cached

    try:
        info = client.call("get_document_info")
    except BridgeError as exc:
        if exc.code != "bridge_command_failed":
            raise  # transport problem: leave the cache unset
        return _V01  # not cached: the failure may be transient (no doc open)

    version = parse_version((info or {}).get("version"))
    setattr(client, _VERSION_CACHE_ATTR, version)
    return version


def supports_solve_batching(client: GHClient) -> bool:
    """v0.3+: solve flag honored, wait_for_idle + set_panel split_lines exist."""
    return bridge_version(client) >= (0, 3, 0)


def supports_set_toggle(client: GHClient) -> bool:
    """v0.2+: set_toggle / delete_components exist."""
    return bridge_version(client) >= (0, 2, 0)


def supports_organization(client: GHClient) -> bool:
    """v0.4+: add_group / add_scribble / set_nickname exist."""
    return bridge_version(client) >= (0, 4, 0)


def finalize_solution(client: GHClient, ids: Optional[Sequence[str]] = None,
                      timeout_ms: int = 30000) -> Optional[Dict[str, Any]]:
    """End a mutating batch: one expire_solution, then wait_for_idle (v0.3+).

    On pre-v0.3 bridges the wait is skipped (the command does not exist);
    those bridges also solved after every mutation anyway, so there is far
    less to wait for. Returns the wait_for_idle result, or None when skipped.
    """
    params: Dict[str, Any] = {}
    if ids:
        params["ids"] = list(ids)
    client.call("expire_solution", params)
    if supports_solve_batching(client):
        return client.call("wait_for_idle", {"timeoutMs": timeout_ms})
    return None


# ── param matching ─────────────────────────────────────────────────────────


def match_param(params: Optional[Iterable[Dict[str, Any]]],
                candidates: Sequence[str]) -> Optional[Dict[str, Any]]:
    """Match a component param descriptor against candidate names.

    ``params`` is the ``inputs`` or ``outputs`` list returned by
    ``add_user_object``: ``[{"name","nickname","index","typeName"}, ...]``.
    Matching is case-insensitive on both ``name`` and ``nickname``; earlier
    candidates win over later ones; exact matches win over prefix matches.
    Returns the matched descriptor dict, or None.
    """
    if not params:
        return None
    params = list(params)

    def names(p: Dict[str, Any]) -> List[str]:
        return [str(p.get(k, "")).strip().upper()
                for k in ("name", "nickname") if p.get(k)]

    for cand in candidates:
        c = cand.strip().upper()
        for p in params:
            if c in names(p):
                return p
    # Prefix fallback (e.g. candidate "PART" vs param "PARTS").
    for cand in candidates:
        c = cand.strip().upper()
        for p in params:
            if any(n.startswith(c) or c.startswith(n) for n in names(p) if n):
                return p
    return None


def param_ref(param: Dict[str, Any]) -> str:
    """Preferred wire name for connect_by_name: nickname, else name."""
    return str(param.get("nickname") or param.get("name") or "")


def require_param(params: Optional[Iterable[Dict[str, Any]]],
                  candidates: Sequence[str], what: str) -> Dict[str, Any]:
    found = match_param(params, candidates)
    if found is None:
        available = [
            f"{p.get('name')}({p.get('nickname')})" for p in (params or [])
        ]
        raise BridgeError(
            "param_not_found",
            f"Could not find {what} among params {available}; "
            f"tried candidates {list(candidates)}",
        )
    return found


# ── bridge helpers ─────────────────────────────────────────────────────────


def call_no_solve(client: GHClient, command_type: str,
                  params: Dict[str, Any]) -> Dict[str, Any]:
    """Send a mutating command with "solve": false (v0.3 batch mode).

    Pre-v0.3 bridges ignore the extra parameter and solve after every
    mutation as before — more solves, identical results — so macros always
    request batching and rely on finalize_solution for the single recompute.
    """
    merged = dict(params)
    merged["solve"] = False
    return client.call(command_type, merged)


def add_wasp(client: GHClient, registry: WaspRegistry, key: str,
             x: float, y: float) -> Dict[str, Any]:
    """Place a Wasp UserObject by registry key; returns add_user_object result."""
    comp = registry.lookup(key)
    result = call_no_solve(client, "add_user_object",
                           {"path": comp.path, "x": x, "y": y})
    result.setdefault("registryKey", comp.key)
    return result


def connect(client: GHClient, source_id: str, source_param: Optional[str],
            target_id: str, target_param: Optional[str],
            source_index: Optional[int] = None,
            target_index: Optional[int] = None) -> Dict[str, Any]:
    return call_no_solve(client, "connect_by_name", {
        "sourceId": source_id,
        "sourceParam": source_param,
        "targetId": target_id,
        "targetParam": target_param,
        "sourceIndex": source_index,
        "targetIndex": target_index,
    })


def connect_with_candidates(client: GHClient, source_id: str,
                            source_candidates: Sequence[str],
                            target_id: str, target_param: str) -> str:
    """Try each source param candidate until connect_by_name succeeds.

    Used when we did not place the source component ourselves and therefore
    do not hold its outputs list. Returns the candidate that worked.
    """
    last: Optional[BridgeError] = None
    for cand in source_candidates:
        try:
            connect(client, source_id, cand, target_id, target_param)
            return cand
        except BridgeError as exc:
            if exc.code != "bridge_command_failed":
                raise  # transport problem: no point retrying candidates
            last = exc
    raise BridgeError(
        "param_not_found",
        f"None of source params {list(source_candidates)} on {source_id} "
        f"could connect to {target_param!r} on {target_id}"
        + (f" (last error: {last.message})" if last else ""),
    )


def get_output_when_idle(client: GHClient, component_id: str, param: str,
                         max_items: int = 1000, retries: int = 20,
                         delay: float = 0.5) -> Dict[str, Any]:
    """get_component_output with retry while the GH solution is running.

    Retryable states: the bridge's explicit "solution_running" error, a UI-thread
    timeout ("timed out after" — a long solve keeps the UI thread busy, so the
    read itself times out rather than observing solution_running), and an
    empty-items first response (an expired param whose scheduled solve hasn't
    fired yet can slip through as an empty success).
    """
    last: Optional[BridgeError] = None
    empty_retries = 2
    for _ in range(max(1, retries)):
        try:
            result = client.call("get_component_output", {
                "id": component_id, "param": param, "maxItems": max_items,
            })
            if not result.get("items") and empty_retries > 0:
                empty_retries -= 1
                time.sleep(delay)
                continue
            return result
        except BridgeError as exc:
            retryable = exc.code == "bridge_command_failed" and (
                "solution_running" in exc.message or "timed out after" in exc.message
            )
            if retryable:
                last = exc
                time.sleep(delay)
                continue
            raise
    raise last or BridgeError("bridge_timeout", "solution never became idle")


def _fmt_vec(v: Sequence[float]) -> str:
    return "{" + ",".join(repr(float(c)) for c in v) + "}"


def _plane_component(plane: Any, key: str) -> List[float]:
    """Extract origin/xAxis/yAxis from a plane dict or 9-float list."""
    if isinstance(plane, dict):
        val = plane.get(key)
        if val is None:
            raise ValueError(f"plane dict missing {key!r}: {plane}")
        vec = [float(c) for c in val]
        if len(vec) != 3:
            raise ValueError(f"plane {key!r} must be 3 floats [x,y,z]: {val}")
        return vec
    flat = [float(c) for c in plane]
    if len(flat) != 9:
        raise ValueError(
            "plane list must be 9 floats [ox,oy,oz, xx,xy,xz, yx,yy,yz]")
    idx = {"origin": 0, "xAxis": 3, "yAxis": 6}[key]
    return flat[idx:idx + 3]


def normalize_plane(plane: Any) -> Dict[str, List[float]]:
    """Normalize one plane (dict or flat 9-float list) to the wire shape
    {"origin": [x,y,z], "xAxis": [x,y,z], "yAxis": [x,y,z]} (set_plane_values)."""
    return {key: _plane_component(plane, key)
            for key in ("origin", "xAxis", "yAxis")}


def normalize_planes(planes: Sequence[Any]) -> List[Dict[str, List[float]]]:
    """Normalize a list of planes for the set_plane_values command."""
    return [normalize_plane(p) for p in planes]


# ── v0.5 zone addressing (PROTOCOL.md "Zone addressing") ──────────────────

# Padding around the anchor points a macro used, so the zone rectangle covers
# the full component bodies (anchors are top-left-ish pivots) plus the
# organization artifacts (group border, explainer scribble above the group).
ZONE_PAD_LEFT = 60.0
ZONE_PAD_TOP = 60.0
ZONE_PAD_RIGHT = 260.0
ZONE_PAD_BOTTOM = 160.0


class ZoneTracker:
    """Collects the canvas anchor points a macro places at; yields the zone.

    Every macro/expansion declares a canvas zone (PROTOCOL v0.5 "Zone
    addressing"): the rectangle implied by what it placed, padded so whole
    component bodies fit. Macro results carry the rect under "zone"; any
    canvas-state lookup the macro performs filters candidates to it
    (closes live-regression finding #6, the cross-zone Point B match).
    """

    def __init__(self) -> None:
        self._xs: List[float] = []
        self._ys: List[float] = []

    def add(self, x: Any, y: Any) -> None:
        try:
            self._xs.append(float(x))
            self._ys.append(float(y))
        except (TypeError, ValueError):
            pass  # untrackable anchor: zone stays conservative

    def add_position(self, position: Any) -> None:
        """Track a get_canvas_state ``position`` ([x, y] or None)."""
        if isinstance(position, (list, tuple)) and len(position) >= 2:
            self.add(position[0], position[1])

    def rect(self) -> Optional[Dict[str, float]]:
        """Padded zone rectangle {"x","y","width","height"}, or None."""
        if not self._xs:
            return None
        min_x, max_x = min(self._xs), max(self._xs)
        min_y, max_y = min(self._ys), max(self._ys)
        return {
            "x": min_x - ZONE_PAD_LEFT,
            "y": min_y - ZONE_PAD_TOP,
            "width": (max_x - min_x) + ZONE_PAD_LEFT + ZONE_PAD_RIGHT,
            "height": (max_y - min_y) + ZONE_PAD_TOP + ZONE_PAD_BOTTOM,
        }


def zone_contains(zone: Optional[Dict[str, Any]], position: Any) -> bool:
    """True when ``position`` ([x, y] from get_canvas_state) is inside ``zone``.

    A None zone means "no zone declared" and a missing/malformed position
    means "cannot verify" — both answer True so zone filtering only ever
    EXCLUDES components that verifiably sit outside the rectangle (a v0.1
    bridge without positions keeps the pre-v0.5 behavior).
    """
    if not zone:
        return True
    if not isinstance(position, (list, tuple)) or len(position) < 2:
        return True
    try:
        px, py = float(position[0]), float(position[1])
        zx, zy = float(zone["x"]), float(zone["y"])
        zw, zh = float(zone["width"]), float(zone["height"])
    except (TypeError, ValueError, KeyError):
        return True
    return zx <= px <= zx + zw and zy <= py <= zy + zh


# ── v0.4 canvas organization (PROTOCOL.md "Generation conventions") ───────

# Group colors, channel order RGBA (alpha last — the bridge documents the
# order in its add_group result). Stage groups get a quiet cool tint; the
# INPUTS group gets the soft green from the PROTOCOL example so drivers are
# recognizable at a glance across workflows.
ORG_STAGE_COLOR = [200, 205, 215, 100]
ORG_INPUTS_COLOR = [190, 220, 190, 120]

# Stage names (generation-principles: one group per functional stage).
STAGE_PART_DEFINITION = "PART DEFINITION"
STAGE_RULES = "RULES"
STAGE_AGGREGATION = "AGGREGATION"
STAGE_OUTPUT = "OUTPUT"
STAGE_INPUTS_AGGREGATION = "INPUTS — aggregation drivers"

# Explainer scribbles are annotations, slightly smaller than the default
# scribble size so they read as notes, not titles.
ORG_SCRIBBLE_SIZE = 12.0

# Wrapping: long unwrapped scribbles sprawl across the canvas and overlap
# neighboring stages. ~54 chars at size 12 spans roughly one stage column.
SCRIBBLE_WRAP_WIDTH = 54
SCRIBBLE_LINE_HEIGHT = 18.0  # canvas px per line at size 12


def wrap_scribble_text(text: str, width: int = SCRIBBLE_WRAP_WIDTH) -> str:
    """Wrap scribble text to a column, preserving explicit paragraph breaks.

    Explicit newlines in the source are kept as paragraph boundaries; each
    paragraph is re-wrapped to ``width`` chars. Long explainers stay tidy
    instead of sprawling across neighboring stages.
    """
    import textwrap
    wrapped: List[str] = []
    for para in str(text).split("\n"):
        para = para.strip()
        if not para:
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(para, width=width) or [""])
    return "\n".join(wrapped)


def scribble_block_height(text: str) -> float:
    """Canvas height a wrapped scribble occupies (for overlap-free layout)."""
    return (text.count("\n") + 1) * SCRIBBLE_LINE_HEIGHT


_stage_explainers_cache: Optional[Dict[str, str]] = None


def load_stage_explainers() -> Dict[str, str]:
    """Lazily load the "explainers" section of knowledge/stage_explainers.json.

    Texts are written for an architecture student reading the canvas cold
    (WHAT the stage does + WHY it exists, 1-3 lines). Returns {} when the
    file is absent/malformed — organization then happens without scribbles.
    """
    global _stage_explainers_cache
    if _stage_explainers_cache is None:
        try:
            with open(_KNOWLEDGE_DIR / "stage_explainers.json",
                      encoding="utf-8") as fh:
                loaded = json.load(fh).get("explainers") or {}
            _stage_explainers_cache = (
                {str(k): str(v) for k, v in loaded.items()}
                if isinstance(loaded, dict) else {})
        except (OSError, ValueError):
            _stage_explainers_cache = {}
    return _stage_explainers_cache


def organize_stage(
    client: GHClient,
    ids: Sequence[str],
    stage_name: str,
    x: float,
    y: float,
    explainer_key: Optional[str] = None,
    color: Optional[Sequence[int]] = None,
    nicknames: Optional[Dict[str, str]] = None,
    explainer_text: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Group a placed subgraph, nickname its members, add an explainer.

    The shared v0.4 organization helper: sets the given nicknames
    (component id -> role name), wraps ``ids`` in a GH_Group labeled
    ``stage_name`` (color RGBA, default ORG_STAGE_COLOR), and places the
    ``explainer_key`` text from knowledge/stage_explainers.json as a
    scribble at (x, y) — callers pass a point ABOVE the group.
    ``explainer_text`` supplies the scribble text directly instead (used by
    the template expander, whose explainers live in the template bodies);
    when both are given the explicit text wins.

    Version-gated: returns None without sending anything on pre-v0.4
    bridges (organization commands don't exist there). All three commands
    are visual-only on the bridge — no solve flags, no solution expiry.
    """
    if not supports_organization(client):
        return None
    member_ids = [str(i) for i in ids if i]
    if not member_ids:
        return None

    org: Dict[str, Any] = {}

    applied: Dict[str, str] = {}
    for component_id, nickname in (nicknames or {}).items():
        if component_id and nickname:
            client.call("set_nickname",
                        {"id": component_id, "nickname": nickname})
            applied[component_id] = nickname
    if applied:
        org["nicknames"] = applied

    group = client.call("add_group", {
        "ids": member_ids,
        "name": stage_name,
        "color": list(color if color is not None else ORG_STAGE_COLOR),
    })
    org["group_id"] = (group or {}).get("groupId")
    org["group_name"] = stage_name

    text = explainer_text
    if not text and explainer_key:
        text = load_stage_explainers().get(explainer_key)
    if text:
        # Wrap to a column and lift the scribble so its whole block sits
        # ABOVE (x, y) — callers pass the group's top-left; unwrapped text
        # used to sprawl over neighboring stages.
        wrapped = wrap_scribble_text(text)
        scribble = client.call("add_scribble", {
            "text": wrapped,
            "x": x,
            "y": y - scribble_block_height(wrapped),
            "size": ORG_SCRIBBLE_SIZE,
        })
        org["scribble_id"] = (scribble or {}).get("id")

    return org


def add_workflow_note(client: GHClient, title: str, text: str,
                      x: float, y: float,
                      width: int = 64) -> Optional[Dict[str, Any]]:
    """Place a workflow-level overview note (title + wrapped paragraphs).

    One scribble at the top-left of the workflow's canvas zone: an UPPERCASE
    title line, a separator, then the body wrapped to ``width``. Use for the
    'what is this whole graph doing' paragraph that individual stage
    explainers don't cover. Version-gated like all organization.
    """
    if not supports_organization(client):
        return None
    body = wrap_scribble_text(text, width=width)
    title_line = str(title).strip().upper()
    full = f"{title_line}\n{'-' * min(len(title_line), width)}\n{body}"
    result = client.call("add_scribble", {
        "text": full, "x": x, "y": y, "size": 14.0,
    })
    return {"id": (result or {}).get("id"), "lines": full.count("\n") + 1}


def _organize_quietly(client: GHClient, **kwargs: Any) -> Optional[Dict[str, Any]]:
    """organize_stage that never raises.

    Organization is cosmetic: a bridge hiccup while grouping must not
    discard a workflow that already built and solved. Failures come back as
    {"error": ...} in the macro result instead.
    """
    try:
        return organize_stage(client, **kwargs)
    except BridgeError as exc:
        return {"error": f"{exc.code}: {exc.message}"}


# ── macros ─────────────────────────────────────────────────────────────────


def create_wasp_part(
    client: GHClient,
    registry: WaspRegistry,
    name: str,
    geometry_object_ids: Sequence[str],
    connection_planes: Optional[Sequence[Any]] = None,
    connection_object_ids: Optional[Sequence[str]] = None,
    x: float = 0.0,
    y: float = 0.0,
) -> Dict[str, Any]:
    """Place and wire a Wasp Basic Part.

    Layout: geometry/name/connection feeders to the left of the part at (x, y).
    ``connection_planes``: list of planes as {"origin","xAxis","yAxis"} dicts
    or 9-float lists — realized via a floating Plane param + set_plane_values
    on a v0.2 bridge, falling back to panels + Construct Plane when the bridge
    answers the capability probe with an unknown-command error (v0.1).
    ``connection_object_ids``: alternative — Rhino GUIDs of planar geometry
    referenced into a Geometry param and fed to Connection From Plane.
    """
    placed: Dict[str, Any] = {}
    zone_tracker = ZoneTracker()

    part = add_wasp(client, registry, "basic_part", x, y)
    zone_tracker.add(x, y)
    part_id = part["id"]
    placed["part_id"] = part_id

    geo_in = require_param(part.get("inputs"), PART_GEO_IN, "part GEO input")
    name_in = match_param(part.get("inputs"), PART_NAME_IN)
    conn_in = match_param(part.get("inputs"), PART_CONN_IN)
    part_out = match_param(part.get("outputs"), PART_OUT)

    # NAME panel
    if name_in is not None:
        name_panel = call_no_solve(client, "add_component", {
            "type": "Panel", "x": x - 250, "y": y - 90,
        })
        zone_tracker.add(x - 250, y - 90)
        placed["name_panel_id"] = name_panel["id"]
        call_no_solve(client, "set_panel",
                      {"id": name_panel["id"], "text": name})
        connect(client, name_panel["id"], None, part_id, param_ref(name_in),
                source_index=0)

    # Geometry param referencing Rhino objects
    geo_param = call_no_solve(client, "add_component", {
        "type": "Mesh", "x": x - 250, "y": y,
    })
    zone_tracker.add(x - 250, y)
    placed["geometry_param_id"] = geo_param["id"]
    call_no_solve(client, "set_geometry_ref", {
        "id": geo_param["id"], "objectIds": list(geometry_object_ids),
    })
    connect(client, geo_param["id"], None, part_id, param_ref(geo_in),
            source_index=0)

    # Connections
    if (connection_planes or connection_object_ids) and conn_in is None:
        raise BridgeError("param_not_found",
                          "Basic Part exposes no connections input (CONN)")

    if connection_planes:
        planes = normalize_planes(connection_planes)

        if supports_set_plane_values(client):
            # v0.2 fast path: one floating Plane param with persistent plane
            # data (set_plane_values), no panel/Construct-Plane scaffolding.
            plane_param = call_no_solve(client, "add_component", {
                "type": "Plane", "x": x - 400, "y": y + 120,
            })
            zone_tracker.add(x - 400, y + 120)
            placed["plane_param_id"] = plane_param["id"]
            call_no_solve(client, "set_plane_values", {
                "id": plane_param["id"], "planes": planes,
            })
            plane_feeder_id = plane_param["id"]
        else:
            # v0.1 fallback: origin/x-axis/y-axis panels into Construct Plane.
            origins = "\n".join(_fmt_vec(p["origin"]) for p in planes)
            xaxes = "\n".join(_fmt_vec(p["xAxis"]) for p in planes)
            yaxes = "\n".join(_fmt_vec(p["yAxis"]) for p in planes)

            cp = call_no_solve(client, "add_component", {
                "type": "Construct Plane", "x": x - 400, "y": y + 120,
            })
            zone_tracker.add(x - 400, y + 120)
            placed["construct_plane_id"] = cp["id"]
            for text, dy, target, key in (
                (origins, 60, "O", "plane_origin_panel_id"),
                (xaxes, 130, "X", "plane_xaxis_panel_id"),
                (yaxes, 200, "Y", "plane_yaxis_panel_id"),
            ):
                panel = call_no_solve(client, "add_component", {
                    "type": "Panel", "x": x - 560, "y": y + dy,
                })
                zone_tracker.add(x - 560, y + dy)
                placed[key] = panel["id"]
                call_no_solve(client, "set_panel",
                              {"id": panel["id"], "text": text})
                connect(client, panel["id"], None, cp["id"], target, source_index=0)
            plane_feeder_id = cp["id"]

        conn_comp = add_wasp(client, registry, "connection_from_plane",
                             x - 250, y + 120)
        zone_tracker.add(x - 250, y + 120)
        placed["connection_component_id"] = conn_comp["id"]
        pln_in = require_param(conn_comp.get("inputs"), CONN_PLANE_IN,
                               "connection PLN input")
        conn_out = require_param(conn_comp.get("outputs"), CONN_OUT,
                                 "connection CONN output")
        # Plane param / Construct Plane single output — index 0 for safety.
        connect(client, plane_feeder_id, None, conn_comp["id"],
                param_ref(pln_in), source_index=0)
        connect(client, conn_comp["id"], param_ref(conn_out),
                part_id, param_ref(conn_in))

    elif connection_object_ids:
        conn_geo = call_no_solve(client, "add_component", {
            "type": "Geometry", "x": x - 400, "y": y + 120,
        })
        zone_tracker.add(x - 400, y + 120)
        placed["connection_geometry_param_id"] = conn_geo["id"]
        call_no_solve(client, "set_geometry_ref", {
            "id": conn_geo["id"], "objectIds": list(connection_object_ids),
        })
        conn_comp = add_wasp(client, registry, "connection_from_plane",
                             x - 250, y + 120)
        zone_tracker.add(x - 250, y + 120)
        placed["connection_component_id"] = conn_comp["id"]
        pln_in = require_param(conn_comp.get("inputs"), CONN_PLANE_IN,
                               "connection PLN input")
        conn_out = require_param(conn_comp.get("outputs"), CONN_OUT,
                                 "connection CONN output")
        connect(client, conn_geo["id"], None, conn_comp["id"],
                param_ref(pln_in), source_index=0)
        connect(client, conn_comp["id"], param_ref(conn_out),
                part_id, param_ref(conn_in))

    finalize_solution(client, [part_id])

    # v0.4 organization (skipped silently on older bridges): group the
    # part-definition subgraph, nickname the cryptic feeders, and place the
    # explainer scribble above the group.
    nicknames: Dict[str, str] = {placed["geometry_param_id"]: "part geometry"}
    if "name_panel_id" in placed:
        nicknames[placed["name_panel_id"]] = "part name"
    if "plane_param_id" in placed:
        nicknames[placed["plane_param_id"]] = "connection planes"
    org = _organize_quietly(
        client,
        ids=[v for k, v in placed.items() if k.endswith("_id")],
        stage_name=STAGE_PART_DEFINITION,
        x=x - 250, y=y - 160,
        explainer_key="part_definition",
        nicknames=nicknames,
    )
    if org:
        placed["organization"] = {"stage": org}

    placed["part_output_param"] = param_ref(part_out) if part_out else "PART"
    placed["zone"] = zone_tracker.rect()
    placed["all_ids"] = [v for k, v in placed.items() if k.endswith("_id")]
    return placed


def define_rules(
    client: GHClient,
    registry: WaspRegistry,
    grammar_text: str,
    parts_component_ids: Sequence[str],
    x: float = 0.0,
    y: float = 0.0,
) -> Dict[str, Any]:
    """Place Rule From Text fed by the grammar (Wasp syntax: "P|1_P|0").

    Wasp has THREE distinct rule languages; this macro only speaks the
    first:
      1. "PART|CONN_PART|CONN" (e.g. "P|0_P|1") → Rule From Text TXT input
         (this macro). Rules are directional.
      2. "TYPE>TYPE" connection-type grammars (e.g. "END>END") → Rules
         Generator GR input.
      3. "P|c_P|c>node_node" graph-grammar rules → a panel wired DIRECTLY
         into Graph-Grammar Aggregation RULES (no Rule From Text).

    Panel strategy is version-gated: a v0.3+ bridge gets ONE panel holding
    the whole grammar (set_panel split_lines default true → one item per
    line); older bridges feed a panel's text as a single item, so each rule
    line gets its own panel, all appended into the rule text input.
    """
    placed: Dict[str, Any] = {}

    rule_lines = [ln.strip() for ln in str(grammar_text).splitlines()
                  if ln.strip()]
    if not rule_lines:
        raise ValueError("grammar_text contains no rules")
    bad = [ln for ln in rule_lines if ">" in ln]
    if bad:
        raise ValueError(
            f"grammar line {bad[0]!r} contains '>' — not Rule From Text "
            "syntax. Rule From Text takes \"PART|CONN_PART|CONN\" rules "
            "(e.g. \"P|1_P|0\"). Use Rules Generator (GR input) for "
            "connection-TYPE grammars like \"END>END\", or wire a panel "
            "directly into Graph-Grammar Aggregation RULES for "
            "\"P|c_P|c>node_node\" graph rules (run_aggregation "
            "mode=\"graph\").")

    zone_tracker = ZoneTracker()
    rules = add_wasp(client, registry, "rule_from_text", x, y)
    zone_tracker.add(x, y)
    placed["rules_component_id"] = rules["id"]
    text_in = require_param(rules.get("inputs"), RULE_TEXT_IN,
                            "rule text input")
    parts_in = match_param(rules.get("inputs"), RULE_PART_IN)
    rules_out = match_param(rules.get("outputs"), RULE_OUT)

    if supports_solve_batching(client) or len(rule_lines) == 1:
        # v0.3+ (or single rule): one panel; split_lines (bridge default
        # true) makes each line a separate item.
        panel = call_no_solve(client, "add_component", {
            "type": "Panel", "x": x - 250, "y": y,
        })
        zone_tracker.add(x - 250, y)
        placed["grammar_panel_id"] = panel["id"]
        call_no_solve(client, "set_panel", {
            "id": panel["id"], "text": "\n".join(rule_lines),
        })
        connect(client, panel["id"], None, rules["id"], param_ref(text_in),
                source_index=0)
        placed["rule_panel_ids"] = [panel["id"]]
    else:
        # Pre-v0.3 bridges emit a panel's text as ONE item: fan out to one
        # panel per rule, all appended into the rule text input.
        panel_ids: List[str] = []
        for i, line in enumerate(rule_lines):
            panel = call_no_solve(client, "add_component", {
                "type": "Panel", "x": x - 250, "y": y + i * 60,
            })
            zone_tracker.add(x - 250, y + i * 60)
            panel_ids.append(panel["id"])
            call_no_solve(client, "set_panel",
                          {"id": panel["id"], "text": line})
            connect(client, panel["id"], None, rules["id"],
                    param_ref(text_in), source_index=0)
        placed["rule_panel_ids"] = panel_ids

    if parts_in is not None:
        for pid in parts_component_ids:
            connect_with_candidates(client, pid, PART_OUT,
                                    rules["id"], param_ref(parts_in))

    finalize_solution(client, [rules["id"]])

    # v0.4 organization (skipped silently on older bridges). On a v0.4
    # bridge the single-split-panel path always ran (v0.4 >= v0.3), so
    # "rule grammar" normally names exactly one panel.
    stage_ids = sorted(
        {v for k, v in placed.items() if k.endswith("_id")}
        | set(placed["rule_panel_ids"]))
    org = _organize_quietly(
        client,
        ids=stage_ids,
        stage_name=STAGE_RULES,
        x=x - 250, y=y - 90,
        explainer_key="rules",
        nicknames={pid: "rule grammar" for pid in placed["rule_panel_ids"]},
    )
    if org:
        placed["organization"] = {"stage": org}

    placed["rules_output_param"] = param_ref(rules_out) if rules_out else "R"
    placed["zone"] = zone_tracker.rect()
    placed["all_ids"] = sorted(
        {v for k, v in placed.items() if k.endswith("_id")}
        | set(placed["rule_panel_ids"]))
    return placed


def run_aggregation(
    client: GHClient,
    registry: WaspRegistry,
    part_ids: Sequence[str],
    rule_id: str,
    count: int,
    seed: Optional[int] = None,
    mode: str = "stochastic",
    x: float = 0.0,
    y: float = 0.0,
    field_component_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Place a Wasp aggregation, wire it mode-appropriately, pulse RESET, solve.

    Mode differences (from the corpus component maps):
      - "stochastic": PART/PREV/N/RULES/SEED/... — N slider + optional seed.
      - "field": PART/PREV/N/RULES/FIELD/... — N slider, NO seed; requires
        ``field_component_id`` wired into FIELD.
      - "graph": PART/PREV/RULES/ID/RESET — NO N and NO seed (``count`` and
        ``seed`` are ignored); ``rule_id`` should be a PANEL carrying
        "P|c_P|c>node_node" graph rules wired directly into RULES (no Rule
        From Text component in this language).

    All wiring is sent with solve:false so the (stateful) aggregation never
    initializes from partial inputs; RESET is then pulsed automatically
    (v0.2+ set_toggle when available, else a "True"/"False" panel as in the
    live demo — corpus files use a Button, our toggle produces the same
    False→True→False edge) and one final expire + wait_for_idle computes
    the result.
    """
    key = AGGREGATION_KEYS.get(mode)
    if key is None:
        raise BridgeError(
            "invalid_mode",
            f"Unknown aggregation mode {mode!r}; "
            f"expected one of {sorted(AGGREGATION_KEYS)}",
        )
    if mode == "field" and field_component_id is None:
        raise ValueError(
            "mode=\"field\" requires field_component_id (a component whose "
            "FIELD output feeds Field-driven Aggregation); build one with "
            "the Wasp field components first")

    placed: Dict[str, Any] = {}
    zone_tracker = ZoneTracker()

    agg = add_wasp(client, registry, key, x, y)
    zone_tracker.add(x, y)
    placed["aggregation_id"] = agg["id"]
    part_in = require_param(agg.get("inputs"), AGG_PART_IN, "aggregation PART input")
    rules_in = require_param(agg.get("inputs"), AGG_RULES_IN, "aggregation RULES input")
    reset_in = match_param(agg.get("inputs"), AGG_RESET_IN)
    agg_out = match_param(agg.get("outputs"), aggregation_parts_out_candidates())

    for pid in part_ids:
        connect_with_candidates(client, pid, PART_OUT, agg["id"],
                                param_ref(part_in))
    connect_with_candidates(client, rule_id, RULE_OUT, agg["id"],
                            param_ref(rules_in))

    if mode != "graph":
        # Graph-Grammar Aggregation has no N input (and prefix-matching
        # against it would grab ID) — only stochastic/field get a slider.
        count_in = require_param(agg.get("inputs"), AGG_COUNT_IN,
                                 "aggregation N input")
        slider = call_no_solve(client, "add_component", {
            "type": "Number Slider", "x": x - 250, "y": y + 60,
        })
        zone_tracker.add(x - 250, y + 60)
        placed["count_slider_id"] = slider["id"]
        call_no_solve(client, "set_slider", {
            "id": slider["id"], "value": float(count),
            "min": 0.0, "max": float(max(count * 2, 100)),
        })
        connect(client, slider["id"], None, agg["id"], param_ref(count_in),
                source_index=0)

    if mode == "stochastic" and seed is not None:
        seed_in = match_param(agg.get("inputs"), AGG_SEED_IN)
        if seed_in is not None:
            seed_slider = call_no_solve(client, "add_component", {
                "type": "Number Slider", "x": x - 250, "y": y + 120,
            })
            zone_tracker.add(x - 250, y + 120)
            placed["seed_slider_id"] = seed_slider["id"]
            call_no_solve(client, "set_slider", {
                "id": seed_slider["id"], "value": float(seed),
                "min": 0.0, "max": float(max(seed * 2, 1000)),
            })
            connect(client, seed_slider["id"], None, agg["id"],
                    param_ref(seed_in), source_index=0)

    if mode == "field":
        field_in = require_param(agg.get("inputs"), AGG_FIELD_IN,
                                 "aggregation FIELD input")
        connect_with_candidates(client, field_component_id, FIELD_OUT,
                                agg["id"], param_ref(field_in))
        placed["field_source"] = field_component_id  # not placed by us

    # Automatic RESET pulse (backlog #2): the aggregation caches its internal
    # state on first solve, so drive RESET high for one solve and low again
    # before the final recompute.
    if reset_in is not None:
        if supports_set_toggle(client):
            toggle = call_no_solve(client, "add_component", {
                "type": "Boolean Toggle", "x": x - 250, "y": y + 180,
            })
            zone_tracker.add(x - 250, y + 180)
            placed["reset_toggle_id"] = toggle["id"]
            connect(client, toggle["id"], None, agg["id"],
                    param_ref(reset_in), source_index=0)
            call_no_solve(client, "set_toggle",
                          {"id": toggle["id"], "value": True})
            # Expire the TOGGLE too (F1: an unexpired source feeds its stale
            # value downstream) and let the True-state solve run on v0.3
            # before flipping back.
            client.call("expire_solution", {"ids": [toggle["id"], agg["id"]]})
            if supports_solve_batching(client):
                client.call("wait_for_idle", {"timeoutMs": 30000})
            call_no_solve(client, "set_toggle",
                          {"id": toggle["id"], "value": False})
        else:
            # v0.1 bridge: no set_toggle — pulse via a "True"/"False" panel
            # (Grasshopper converts the text to a boolean), as the live demo
            # did by hand.
            panel = call_no_solve(client, "add_component", {
                "type": "Panel", "x": x - 250, "y": y + 180,
            })
            zone_tracker.add(x - 250, y + 180)
            placed["reset_panel_id"] = panel["id"]
            call_no_solve(client, "set_panel",
                          {"id": panel["id"], "text": "True"})
            connect(client, panel["id"], None, agg["id"],
                    param_ref(reset_in), source_index=0)
            client.call("expire_solution", {"ids": [panel["id"], agg["id"]]})
            call_no_solve(client, "set_panel",
                          {"id": panel["id"], "text": "False"})

    finalize_solution(client, [agg["id"]])

    # v0.4 organization (skipped silently on older bridges): the solver gets
    # its own stage group with a mode-specific explainer, and every
    # user-tweakable driver (sliders, reset) goes into a SEPARATE INPUTS
    # group with role nicknames — never magic values buried mid-graph.
    organization: Dict[str, Any] = {}
    stage_org = _organize_quietly(
        client,
        ids=[agg["id"]],
        stage_name=STAGE_AGGREGATION,
        x=x, y=y - 110,
        explainer_key=f"aggregation_{mode}",
    )
    if stage_org:
        organization["stage"] = stage_org

    input_keys = ("count_slider_id", "seed_slider_id",
                  "reset_toggle_id", "reset_panel_id")
    input_ids = [placed[k] for k in input_keys if k in placed]
    if input_ids:
        input_nicknames: Dict[str, str] = {}
        if "count_slider_id" in placed:
            input_nicknames[placed["count_slider_id"]] = "part count"
        if "seed_slider_id" in placed:
            input_nicknames[placed["seed_slider_id"]] = "random seed"
        if "reset_toggle_id" in placed:
            input_nicknames[placed["reset_toggle_id"]] = "reset"
        if "reset_panel_id" in placed:
            input_nicknames[placed["reset_panel_id"]] = "reset"
        inputs_org = _organize_quietly(
            client,
            ids=input_ids,
            stage_name=STAGE_INPUTS_AGGREGATION,
            x=x - 250, y=y + 10,
            explainer_key="inputs",
            color=ORG_INPUTS_COLOR,
            nicknames=input_nicknames,
        )
        if inputs_org:
            organization["inputs"] = inputs_org
    if organization:
        placed["organization"] = organization

    # PART_OUT is the parts output every downstream extractor reads;
    # AGGR (the other output) is the aggregation object.
    placed["aggregation_output_param"] = (
        param_ref(agg_out) if agg_out else "PART_OUT")
    placed["zone"] = zone_tracker.rect()
    placed["all_ids"] = [v for k, v in placed.items() if k.endswith("_id")]
    return placed


def get_aggregation(
    client: GHClient,
    registry: WaspRegistry,
    aggregation_id: str,
    out: str = "meshes",
    layer: Optional[str] = None,
    max_items: int = 1000,
    x: float = 400.0,
    y: float = 0.0,
) -> Dict[str, Any]:
    """Extract aggregation results as meshes, transforms, or a bake.

    meshes/bake: uses Get Part Geometry downstream of the aggregation.
    transforms: uses Deconstruct Part and reads its TR output.
    Extractors are wired from the aggregation's PART_OUT output (the parts);
    AGGR (the aggregation object) is never fed into an extractor.

    Idempotent (backlog #6): an extractor of the right type ALREADY wired to
    this aggregation's output is reused (found via get_canvas_state) instead
    of placing a duplicate; a freshly placed extractor is deleted again
    (v0.2+ delete_components, best-effort) when a later step fails.
    """
    if out not in ("meshes", "transforms", "bake"):
        raise BridgeError(
            "invalid_mode",
            f"Unknown output mode {out!r}; expected meshes|transforms|bake",
        )
    placed: Dict[str, Any] = {}

    if out in ("meshes", "bake"):
        extractor_key = "get_part_geometry"
        extractor_names = ("get part geometry",)
        in_candidates, out_candidates = GETGEO_PART_IN, GETGEO_OUT
        what_in, what_out = ("Get Part Geometry PART input",
                             "Get Part Geometry GEO output")
    else:
        extractor_key = "deconstruct_part"
        extractor_names = ("deconstruct part",)
        in_candidates, out_candidates = DECON_PART_IN, DECON_TR_OUT
        what_in, what_out = ("Deconstruct Part PART input",
                             "Deconstruct Part TR output")

    # Zone (PROTOCOL v0.5): the extraction zone spans the aggregation's
    # canvas position and the requested extractor spot. The reuse lookup is
    # scoped to it, so a same-typed extractor in another workflow's zone is
    # never picked up (regression finding #6).
    state = client.call("get_canvas_state")
    zone_tracker = ZoneTracker()
    zone_tracker.add(x, y)
    for comp in state.get("components") or []:
        if comp.get("id") == aggregation_id:
            zone_tracker.add_position(comp.get("position"))
            break
    zone = zone_tracker.rect()

    reused_id = find_wired_extractor(client, aggregation_id, extractor_names,
                                     zone=zone, state=state)

    if reused_id is not None:
        extractor_id = reused_id
        placed["extractor_id"] = extractor_id
        placed["reused_extractor"] = True
        # We did not place this component, so we hold no outputs list;
        # the read below resolves the output param by candidates.
        data_out_ref: Optional[str] = None
    else:
        extractor = add_wasp(client, registry, extractor_key, x, y)
        extractor_id = extractor["id"]
        placed["extractor_id"] = extractor_id
        placed["reused_extractor"] = False
        part_in = require_param(extractor.get("inputs"), in_candidates, what_in)
        data_out = require_param(extractor.get("outputs"), out_candidates,
                                 what_out)
        data_out_ref = param_ref(data_out)
        try:
            # PART_OUT first: wiring AGGR into an extractor binds the
            # aggregation OBJECT, not the parts (corpus backlog finding).
            connect_with_candidates(client, aggregation_id,
                                    aggregation_parts_out_candidates(),
                                    extractor_id, param_ref(part_in))
        except BridgeError:
            _cleanup_components(client, [extractor_id])
            raise

    try:
        finalize_solution(client, [extractor_id])

        if out == "bake":
            used_param, baked = _bake_with_candidates(
                client, extractor_id,
                [data_out_ref] if data_out_ref else list(out_candidates),
                layer or "WASP::AGG")
            placed["bakedIds"] = baked.get("bakedIds", [])
        else:
            used_param, data = _read_with_candidates(
                client, extractor_id,
                [data_out_ref] if data_out_ref else list(out_candidates),
                max_items)
            placed["data"] = data
    except BridgeError:
        if reused_id is None:
            _cleanup_components(client, [extractor_id])
        raise

    # v0.4 organization, only for an extractor WE placed (a reused one may
    # already sit in an OUTPUT group from the run that created it; grouping
    # it again would stack duplicate groups on every read).
    if reused_id is None:
        org = _organize_quietly(
            client,
            ids=[extractor_id],
            stage_name=STAGE_OUTPUT,
            x=x, y=y - 90,
            explainer_key=("output_transforms" if out == "transforms"
                           else "output_geometry"),
        )
        if org:
            placed["organization"] = {"stage": org}

    placed["output_param"] = used_param
    placed["zone"] = zone
    placed["all_ids"] = [v for k, v in placed.items() if k.endswith("_id")]
    return placed


def find_wired_extractor(client: GHClient, aggregation_id: str,
                         extractor_names: Sequence[str],
                         zone: Optional[Dict[str, Any]] = None,
                         state: Optional[Dict[str, Any]] = None,
                         ) -> Optional[str]:
    """Find a component of the given type already fed by the aggregation.

    Looks up get_canvas_state connections whose sourceId is the aggregation
    and whose target component's name/nickname matches one of
    ``extractor_names`` (case-insensitive substring). When ``zone`` is given
    the candidate's canvas position must fall inside it (PROTOCOL v0.5 zone
    addressing — a same-named extractor in ANOTHER workflow's zone is never
    reused; regression finding #6). ``state`` lets callers reuse an already
    fetched get_canvas_state snapshot.
    """
    if state is None:
        state = client.call("get_canvas_state")
    components = {c.get("id"): c for c in state.get("components") or []}
    for conn in state.get("connections") or []:
        if conn.get("sourceId") != aggregation_id:
            continue
        # F3: only reuse extractors fed from a parts output — a user-miswired
        # AGGR -> Get Part Geometry must not be picked up.
        source_param = str(conn.get("sourceParam") or "").upper()
        if source_param and "PART" not in source_param:
            continue
        target = components.get(conn.get("targetId"))
        if target is None:
            continue
        if not zone_contains(zone, target.get("position")):
            continue  # verifiably outside this macro's zone: never reuse
        labels = [str(target.get("name") or "").strip().lower(),
                  str(target.get("nickname") or "").strip().lower()]
        if any(wanted in label for wanted in extractor_names
               for label in labels if label):
            return target.get("id")
    return None


def _read_with_candidates(client: GHClient, component_id: str,
                          candidates: Sequence[str],
                          max_items: int) -> Tuple[str, Dict[str, Any]]:
    """get_output_when_idle over output-param name candidates."""
    last: Optional[BridgeError] = None
    for cand in candidates:
        try:
            return cand, get_output_when_idle(client, component_id, cand,
                                              max_items=max_items)
        except BridgeError as exc:
            if exc.code == "bridge_command_failed" and "not found" in exc.message:
                last = exc
                continue
            raise
    raise last or BridgeError(
        "param_not_found",
        f"No output param among {list(candidates)} on {component_id}")


def _bake_with_candidates(client: GHClient, component_id: str,
                          candidates: Sequence[str],
                          layer: str) -> Tuple[str, Dict[str, Any]]:
    """bake_component_output over output-param name candidates."""
    last: Optional[BridgeError] = None
    for cand in candidates:
        try:
            return cand, client.call("bake_component_output", {
                "id": component_id, "param": cand, "layer": layer,
            })
        except BridgeError as exc:
            if exc.code == "bridge_command_failed" and "not found" in exc.message:
                last = exc
                continue
            raise
    raise last or BridgeError(
        "param_not_found",
        f"No output param among {list(candidates)} on {component_id}")


def _cleanup_components(client: GHClient, ids: Sequence[str]) -> None:
    """Best-effort removal of macro-placed components after a failure.

    Uses v0.2 delete_components when the bridge has it; silently does
    nothing on v0.1 (the orphan is reported to the caller via the raised
    error's component ids instead).
    """
    try:
        if supports_set_toggle(client):  # v0.2+ has delete_components too
            client.call("delete_components", {"ids": list(ids)})
    except BridgeError:
        pass  # cleanup must never mask the original error


def reset_aggregation(
    client: GHClient,
    aggregation_id: str,
) -> Dict[str, Any]:
    """Reset a Wasp aggregation via its RESET input (v0.2 bridge required).

    Places and wires a Boolean Toggle onto the aggregation's RESET input if
    none is connected yet, then pulses it false -> true -> false with a
    solution expiry after each step (Wasp resets while RESET is true and
    re-aggregates when it drops back to false). Wasp's own example files
    use a Button on RESET; the toggle pulse produces the same edge.
    """
    placed: Dict[str, Any] = {"aggregation_id": aggregation_id}

    state = client.call("get_canvas_state")
    components = {c.get("id"): c for c in state.get("components") or []}
    if aggregation_id not in components:
        raise BridgeError(
            "component_not_found",
            f"Aggregation component {aggregation_id} is not on the canvas",
        )

    # Zone (PROTOCOL v0.5): the aggregation's position plus the spot where
    # this macro would place a toggle. The RESET-feeder lookup is scoped to
    # it, so a same-role toggle from another workflow's zone is never reused.
    agg_pos = components[aggregation_id].get("position") or [0.0, 0.0]
    zone_tracker = ZoneTracker()
    zone_tracker.add_position(agg_pos)
    zone_tracker.add(float(agg_pos[0]) - 250, float(agg_pos[1]) + 180)
    zone = zone_tracker.rect()

    def is_reset_name(name: Any) -> bool:
        n = str(name or "").strip().upper()
        return any(n == c or n.startswith(c) for c in AGG_RESET_IN)

    # Reuse a toggle already wired into the RESET input, if any (must sit
    # inside this macro's zone — regression finding #6).
    toggle_id: Optional[str] = None
    for conn in state.get("connections") or []:
        if (conn.get("targetId") == aggregation_id
                and is_reset_name(conn.get("targetParam"))):
            source = components.get(conn.get("sourceId"))
            if source is not None and not zone_contains(
                    zone, source.get("position")):
                continue
            toggle_id = conn.get("sourceId")
            break

    created = False
    if toggle_id is None:
        toggle = client.call("add_component", {
            "type": "Boolean Toggle",
            "x": float(agg_pos[0]) - 250, "y": float(agg_pos[1]) + 180,
        })
        toggle_id = toggle["id"]
        created = True

        last: Optional[BridgeError] = None
        for cand in AGG_RESET_IN:
            try:
                connect(client, toggle_id, None, aggregation_id, cand,
                        source_index=0)
                break
            except BridgeError as exc:
                if exc.code != "bridge_command_failed":
                    raise
                last = exc
        else:
            raise BridgeError(
                "param_not_found",
                f"No RESET input found on {aggregation_id}; tried "
                f"{list(AGG_RESET_IN)}"
                + (f" (last error: {last.message})" if last else ""),
            )

    placed["toggle_id"] = toggle_id
    placed["created_toggle"] = created

    # Pulse false -> true -> false. The TOGGLE id must be in each expire: a
    # non-expired source keeps stale VolatileData, so expiring only the
    # aggregation would make it re-read the toggle's OLD value and the pulse
    # would never happen on the wire (validator finding F1). Expiring the
    # source propagates downstream to the aggregation. On v0.3 bridges we also
    # wait between steps so the True-state solve actually runs before the
    # flip back (ScheduleSolution vs fast localhost round-trips is a race).
    batching = supports_solve_batching(client)
    for value in (False, True, False):
        call_no_solve(client, "set_toggle", {"id": toggle_id, "value": value})
        client.call("expire_solution", {"ids": [toggle_id, aggregation_id]})
        if batching:
            client.call("wait_for_idle", {"timeoutMs": 30000})

    placed["pulse"] = [False, True, False]
    placed["zone"] = zone
    placed["all_ids"] = [v for k, v in placed.items() if k.endswith("_id")]
    return placed
