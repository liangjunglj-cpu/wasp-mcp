"""Template-expansion engine (PROTOCOL.md v0.5, generation-principles §3b).

Expands the DATA-ONLY stage templates in ``server/knowledge/*.json``
(``arch_patterns.json``, ``wasp_patterns.json`` ``templates`` sections) into
live canvas subgraphs:

- **Binding validation first**: unbound required slots, unknown slots and
  kind mismatches are typed errors raised BEFORE any canvas mutation.
- **Stock components are placed BY GUID** recorded in the template body from
  corpus dump evidence (regression finding #1: names collide — "Square");
  only PROTOCOL-guaranteed type names (Panel, Number Slider, Boolean Toggle,
  Mesh, Geometry, Construct Plane, Plane) may be placed by name. Wasp
  components go through the registry / ``add_user_object`` path.
- **Wiring uses the exact recorded param names** from the template body
  (regression finding #2 — never prose guesses);
  ``macros.connect_with_candidates`` is used only as a fallback for slot
  sources whose output name we do not hold.
- All mutations are batched (``solve: false``) and finished with ONE
  ``expire_solution`` + ``wait_for_idle`` (``macros.finalize_solution``),
  version-gated like every macro.
- v0.4 organization is applied automatically: INPUTS group with role
  nicknames, stage group named from ``stage_name``, wrapped explainer
  scribble from the template's own ``explainer``.
- The result is a **zone manifest** (PROTOCOL v0.5 "Zone addressing"):
  ``{"zone": {x,y,width,height}, "all_ids": [...], per-stage breakdown}``.

Template wire grammar (machine-parseable, validated up front):
  ``slot:<name> -> <ref>.<Param>``    slot binding edge
  ``<ref>.<OutParam> -> <ref>.<InParam>``    internal edge
Component entry fields: ``ref``, ``type``/``guid`` (stock) or ``wasp``
(registry key), optional ``panel_text``, ``skip_when_bound`` (internal
default source, skipped when the slot is bound; its outgoing wires re-source
from the binding) and ``when_bound`` (optional sub-chain, placed only when
the gating slot is bound).
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import macros
from gh_client import BridgeError, GHClient
from registry import WaspRegistry

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"

# Knowledge files whose "templates" section feeds the expander.
TEMPLATE_FILES = ("arch_patterns.json", "wasp_patterns.json")

# add_component type names the PROTOCOL guarantees the bridge resolves
# unambiguously (v0.1 addendum 5 + v0.2); everything else needs a GUID.
PROTOCOL_SAFE_TYPES = {
    "Panel", "Number Slider", "Boolean Toggle",
    "Mesh", "Geometry", "Construct Plane", "Plane",
}

# Components whose single implicit output is wired as sourceParam=None,
# sourceIndex=0 (PROTOCOL v0.1 addendum 1) regardless of the recorded name.
IMPLICIT_OUTPUT_TYPES = {"Panel", "Number Slider", "Boolean Toggle"}

SLIDER_KINDS = {"driver_num", "driver_int", "count"}
DRIVER_KINDS = SLIDER_KINDS | {"driver_domain"}
SOURCE_KINDS = {"geometry", "wasp_part", "wasp_rules"}

# Fallback output-name candidates per slot kind, used only when a bound
# source component's exact output param is unknown AND the recorded wire
# cannot connect (macros.connect_with_candidates path).
_KIND_SOURCE_CANDIDATES: Dict[str, Sequence[str]] = {
    "wasp_part": macros.PART_OUT,
    "wasp_rules": macros.RULE_OUT,
}

# Layout constants: drivers/ref-params in a left column at the zone origin,
# body components in dependency-depth columns to the right (left-to-right
# dataflow, generation-principles §2).
DRIVER_DY = 70.0
BODY_X_OFFSET = 320.0
BODY_COL_DX = 220.0
BODY_ROW_DY = 90.0

_DOMAIN_RE = re.compile(
    r"^\s*[-+]?\d+(?:\.\d+)?\s+to\s+[-+]?\d+(?:\.\d+)?\s*$", re.IGNORECASE)


class ExpansionError(BridgeError):
    """Typed template-expansion failure (raised BEFORE any canvas mutation
    for validation codes). ``details`` lists every individual problem."""

    def __init__(self, code: str, message: str,
                 details: Optional[Sequence[str]] = None,
                 hint: Optional[str] = None):
        super().__init__(code, message, hint)
        self.details = list(details or [])

    def to_dict(self) -> Dict[str, Any]:
        out = super().to_dict()
        if self.details:
            out["details"] = self.details
        return out


# ── knowledge loading ──────────────────────────────────────────────────────

_templates_cache: Optional[Dict[str, Dict[str, Any]]] = None
_param_components_cache: Optional[Dict[str, Any]] = None


def load_templates(refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """All stage templates across the knowledge files, keyed by id."""
    global _templates_cache
    if _templates_cache is not None and not refresh:
        return _templates_cache
    merged: Dict[str, Dict[str, Any]] = {}
    for filename in TEMPLATE_FILES:
        try:
            with open(KNOWLEDGE_DIR / filename, encoding="utf-8") as fh:
                section = json.load(fh).get("templates") or {}
        except (OSError, ValueError):
            continue
        if not isinstance(section, dict):
            continue
        for template_id, template in section.items():
            if template_id.startswith("_") or not isinstance(template, dict):
                continue  # _provenance and other annotations
            entry = dict(template)
            entry.setdefault("id", template_id)
            entry["_knowledge_file"] = filename
            merged[template_id] = entry
    _templates_cache = merged
    return merged


def load_param_components() -> Dict[str, Dict[str, Any]]:
    """Floating-param realizations for geometry slots (guids from dumps)."""
    global _param_components_cache
    if _param_components_cache is None:
        try:
            with open(KNOWLEDGE_DIR / "arch_patterns.json",
                      encoding="utf-8") as fh:
                loaded = json.load(fh).get("param_components") or {}
        except (OSError, ValueError):
            loaded = {}
        _param_components_cache = {
            k: v for k, v in loaded.items()
            if not k.startswith("_") and isinstance(v, dict)}
    return _param_components_cache


def _reset_caches() -> None:
    """Test hook: drop the knowledge caches."""
    global _templates_cache, _param_components_cache
    _templates_cache = None
    _param_components_cache = None


# ── template body parsing ──────────────────────────────────────────────────


def parse_wire(wire: str) -> Optional[Dict[str, Any]]:
    """Parse one body wire; None when it is not machine-parseable.

    ``slot:<name> -> <ref>.<Param>`` or ``<ref>.<Out> -> <ref>.<In>``.
    Refs contain no dots; param names may contain spaces/digits (exact
    recorded names like "Extent X", "Stream 0", "Z-Axis").
    """
    left, sep, right = str(wire).partition("->")
    if not sep or "->" in right:
        return None  # multiple arrows = prose, not a recorded edge
    left, right = left.strip(), right.strip()
    tref, tsep, tparam = right.partition(".")
    tref, tparam = tref.strip(), tparam.strip()
    if not tsep or not tref or not tparam or " " in tref \
            or any(ch in tparam for ch in "()/"):
        return None  # parentheticals/alternatives are prose annotations
    parsed: Dict[str, Any] = {"target_ref": tref, "target_param": tparam}
    if left.lower().startswith("slot:"):
        slot = left[5:].strip()
        if not slot or not re.fullmatch(r"[A-Za-z0-9_]+", slot):
            return None
        parsed["slot"] = slot
        return parsed
    sref, ssep, sparam = left.partition(".")
    sref, sparam = sref.strip(), sparam.strip()
    if not ssep or not sref or not sparam or " " in sref \
            or any(ch in sparam for ch in "()/"):
        return None
    parsed["source_ref"] = sref
    parsed["source_param"] = sparam
    return parsed


def template_issues(template: Dict[str, Any]) -> List[str]:
    """Why a template body cannot be expanded (empty list = expandable).

    Does NOT include ``expansion_blocked`` (that is a deliberate flag,
    reported separately); this lists structural gaps: prose wires, stock
    components without GUID evidence, unknown refs.
    """
    issues: List[str] = []
    body = template.get("body")
    if not isinstance(body, dict):
        return [f"body is not a component/wire dict "
                f"(got {type(body).__name__})"]
    components = body.get("components") or []
    refs: Dict[str, Dict[str, Any]] = {}
    for comp in components:
        if not isinstance(comp, dict) or not comp.get("ref"):
            issues.append(f"component entry without a ref: {comp!r}")
            continue
        ref = str(comp["ref"])
        if ref in refs:
            issues.append(f"duplicate component ref {ref!r}")
        refs[ref] = comp
        if comp.get("wasp"):
            continue  # registry-resolved, no GUID needed
        if not comp.get("guid") and \
                str(comp.get("type")) not in PROTOCOL_SAFE_TYPES:
            issues.append(
                f"component {ref!r} ({comp.get('type')!r}) has no "
                "componentGuid evidence and is not a PROTOCOL-guaranteed "
                "type name (regression finding #1: place stock components "
                "by GUID)")
    slots = template.get("slots") or {}
    for wire in body.get("wires") or []:
        parsed = parse_wire(wire)
        if parsed is None:
            issues.append(f"wire is not machine-parseable: {wire!r}")
            continue
        if parsed["target_ref"] not in refs:
            issues.append(f"wire targets unknown ref: {wire!r}")
        if "slot" in parsed and parsed["slot"] not in slots:
            issues.append(f"wire references undeclared slot: {wire!r}")
        if "source_ref" in parsed and parsed["source_ref"] not in refs:
            issues.append(f"wire sources unknown ref: {wire!r}")
    return issues


def list_templates() -> List[Dict[str, Any]]:
    """Enumerate stage templates across knowledge files (PROTOCOL v0.5).

    Per template: id, stage_name, slots (kind/default/optional/
    range_evidence/arity), source files + evidence strength, and whether the
    expander can expand it (with the blocking reason / structural issues).
    """
    entries: List[Dict[str, Any]] = []
    for template_id, template in sorted(load_templates().items()):
        source_files = list(template.get("source_files") or [])
        slots_out: Dict[str, Any] = {}
        for name, spec in (template.get("slots") or {}).items():
            spec = spec if isinstance(spec, dict) else {}
            slot_summary = {"kind": spec.get("kind")}
            for key in ("default", "optional", "range_evidence", "arity",
                        "note", "ref_param"):
                if key in spec:
                    slot_summary[key] = spec[key]
            slots_out[name] = slot_summary
        blocked = template.get("expansion_blocked")
        issues = template_issues(template)
        entry: Dict[str, Any] = {
            "id": template_id,
            "stage_name": template.get("stage_name"),
            "knowledge_file": template.get("_knowledge_file"),
            "slots": slots_out,
            "outputs": template.get("outputs") or {},
            "source_files": source_files,
            "evidence_strength": (
                f"corroborated ({len(source_files)} files)"
                if len(source_files) > 1 else "single-file"),
            "expandable": not blocked and not issues,
        }
        if blocked:
            entry["expansion_blocked"] = blocked
        if issues:
            entry["issues"] = issues
        entries.append(entry)
    return entries


# ── binding validation (all typed errors BEFORE any canvas mutation) ──────


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_integerish(value: Any) -> bool:
    return _is_number(value) and float(value) == int(value)


def _normalize_domain(value: Any) -> Optional[str]:
    """Normalize a driver_domain binding to corpus panel text 'a To b'."""
    if isinstance(value, str) and _DOMAIN_RE.match(value):
        return value.strip()
    if isinstance(value, (list, tuple)) and len(value) == 2 and \
            all(_is_number(v) for v in value):
        return f"{value[0]} To {value[1]}"
    return None


def _normalize_source_binding(value: Any) -> Optional[List[Dict[str, Any]]]:
    """Normalize a geometry/wasp slot binding to a list of source specs.

    Accepted forms (each list item):
      "component-guid"                         -> upstream component, output
                                                  resolved by index 0 / fallback
      {"component_id": "...", "param": "..."}  -> upstream output by name
      {"rhino_ids": ["...", ...]}              -> referenced Rhino geometry
                                                  (geometry slots only)
    Returns None when the shape is not recognized.
    """
    items = value if isinstance(value, (list, tuple)) else [value]
    if not items:
        return None
    normalized: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, str) and item.strip():
            normalized.append({"component_id": item.strip()})
        elif isinstance(item, dict):
            component_id = item.get("component_id") or item.get("id")
            rhino_ids = item.get("rhino_ids") or item.get("object_ids")
            if component_id and not rhino_ids:
                spec: Dict[str, Any] = {"component_id": str(component_id)}
                if item.get("param"):
                    spec["param"] = str(item["param"])
                normalized.append(spec)
            elif rhino_ids and not component_id and \
                    isinstance(rhino_ids, (list, tuple)) and \
                    all(isinstance(r, str) and r.strip() for r in rhino_ids):
                normalized.append({"rhino_ids": [str(r) for r in rhino_ids]})
            else:
                return None
        else:
            return None
    return normalized


def _validate_bindings(template: Dict[str, Any],
                       bindings: Dict[str, Any],
                       skip_when_bound_slots: Sequence[str],
                       ) -> Dict[str, Dict[str, Any]]:
    """Validate every binding against its slot; returns the resolved plan.

    Raises ExpansionError("invalid_bindings") listing EVERY problem —
    unknown slot names, unbound required slots and kind mismatches — so the
    caller can fix them in one round trip. Nothing has touched the canvas
    yet when this raises.
    """
    slots: Dict[str, Any] = template.get("slots") or {}
    problems: List[str] = []
    resolved: Dict[str, Dict[str, Any]] = {}

    for name in bindings:
        if name not in slots:
            problems.append(
                f"unknown slot {name!r} (template slots: "
                f"{sorted(slots)})")

    for name, spec in slots.items():
        spec = spec if isinstance(spec, dict) else {}
        kind = str(spec.get("kind") or "")
        bound = name in bindings and bindings[name] is not None
        value = bindings.get(name)
        optional = bool(spec.get("optional")) or name in skip_when_bound_slots
        entry: Dict[str, Any] = {"kind": kind, "bound": bound,
                                 "spec": spec}

        if kind in SLIDER_KINDS:
            if bound:
                if kind == "driver_num" and not _is_number(value):
                    problems.append(
                        f"slot {name!r} ({kind}) expects a number, got "
                        f"{value!r} ({type(value).__name__})")
                elif kind in ("driver_int", "count") and \
                        not _is_integerish(value):
                    problems.append(
                        f"slot {name!r} ({kind}) expects an integer, got "
                        f"{value!r} ({type(value).__name__})")
                else:
                    entry["value"] = float(value)
            elif "default" in spec:
                entry["value"] = float(spec["default"])
            elif not optional:
                problems.append(
                    f"required slot {name!r} ({kind}) is unbound and has "
                    "no default")
        elif kind == "driver_domain":
            raw = value if bound else spec.get("default")
            if raw is None:
                if not optional:
                    problems.append(
                        f"required slot {name!r} (driver_domain) is unbound "
                        "and has no default")
            else:
                domain = _normalize_domain(raw)
                if domain is None:
                    problems.append(
                        f"slot {name!r} (driver_domain) expects 'a To b' "
                        f"text or [lo, hi], got {raw!r}")
                else:
                    entry["value"] = domain
        elif kind in SOURCE_KINDS:
            if bound:
                sources = _normalize_source_binding(value)
                if sources is None:
                    problems.append(
                        f"slot {name!r} ({kind}) expects a component id, "
                        "{'component_id', 'param'?} or {'rhino_ids': [...]}"
                        f" (list allowed for arity 1..n), got {value!r}")
                else:
                    arity = str(spec.get("arity") or "1")
                    if arity == "1" and len(sources) > 1:
                        problems.append(
                            f"slot {name!r} has arity 1 but got "
                            f"{len(sources)} sources")
                    if kind != "geometry" and any(
                            "rhino_ids" in s for s in sources):
                        problems.append(
                            f"slot {name!r} ({kind}) cannot be bound to "
                            "raw Rhino geometry — pass the Wasp component "
                            "id instead")
                    entry["sources"] = sources
            elif not optional:
                problems.append(
                    f"required slot {name!r} ({kind}) is unbound")
        elif kind == "driver_image":
            if bound:
                problems.append(
                    f"slot {name!r} (driver_image) cannot be bound: the "
                    "bridge has no command for Image Sampler state")
        else:
            if bound:
                problems.append(
                    f"slot {name!r} has unknown kind {kind!r}; refusing "
                    "to guess")
        resolved[name] = entry

    if problems:
        raise ExpansionError(
            "invalid_bindings",
            f"{len(problems)} binding problem(s) for template "
            f"{template.get('id')!r}; nothing was placed",
            details=problems)
    return resolved


# ── expansion ──────────────────────────────────────────────────────────────


def _component_depths(active: Dict[str, Dict[str, Any]],
                      wires: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Longest-path depth per ref over internal wires (layout columns)."""
    incoming: Dict[str, List[str]] = {ref: [] for ref in active}
    for wire in wires:
        sref = wire.get("source_ref")
        if sref and sref in active and wire["target_ref"] in active:
            incoming[wire["target_ref"]].append(sref)
    depths: Dict[str, int] = {}

    def depth(ref: str, trail: frozenset) -> int:
        if ref in depths:
            return depths[ref]
        if ref in trail:  # defensive: templates are DAGs
            return 0
        sources = incoming.get(ref) or []
        value = 0 if not sources else 1 + max(
            depth(s, trail | {ref}) for s in sources)
        depths[ref] = value
        return value

    for ref in active:
        depth(ref, frozenset())
    return depths


def _slot_role(name: str) -> str:
    return name.replace("_", " ")


def expand_template(
    client: GHClient,
    registry: WaspRegistry,
    template_id: str,
    bindings: Optional[Dict[str, Any]] = None,
    x: float = 0.0,
    y: float = 0.0,
) -> Dict[str, Any]:
    """Expand a stage template into a live canvas subgraph; zone manifest back.

    Validation (template lookup, expansion_blocked flag, machine-parseable
    body, EVERY binding problem) happens before the first canvas mutation.
    Placement batches all mutations with ``solve: false``, ends with one
    ``expire_solution`` + ``wait_for_idle`` (``macros.finalize_solution``),
    then applies v0.4 organization (INPUTS group, stage group, wrapped
    explainer scribble, role nicknames) — skipped silently on pre-v0.4
    bridges, like every macro.
    """
    bindings = dict(bindings or {})
    templates = load_templates()
    template = templates.get(template_id)
    if template is None:
        close = difflib.get_close_matches(str(template_id), list(templates),
                                          n=5, cutoff=0.3)
        raise ExpansionError(
            "template_not_found",
            f"No template {template_id!r}"
            + (f"; closest: {', '.join(close)}" if close else "")
            + " (see list_templates)")

    blocked = template.get("expansion_blocked")
    if blocked:
        raise ExpansionError(
            "template_blocked",
            f"Template {template_id!r} is marked expansion_blocked",
            details=[str(blocked)])

    issues = template_issues(template)
    if issues:
        raise ExpansionError(
            "template_not_expandable",
            f"Template {template_id!r} body is not machine-parseable "
            f"({len(issues)} issue(s)); it is data-only until upgraded",
            details=issues)

    body = template["body"]
    specs: Dict[str, Dict[str, Any]] = {
        str(c["ref"]): c for c in body.get("components") or []}
    parsed_wires = [parse_wire(w) for w in body.get("wires") or []]

    skip_when_bound_slots = [str(c["skip_when_bound"]) for c in specs.values()
                             if c.get("skip_when_bound")]
    plan = _validate_bindings(template, bindings, skip_when_bound_slots)

    def slot_bound(name: Optional[str]) -> bool:
        entry = plan.get(name or "")
        return bool(entry and (entry.get("bound")
                               or "sources" in entry))

    # Active components: drop internal defaults whose slot is bound, and
    # optional sub-chains whose gating slot is unbound.
    active: Dict[str, Dict[str, Any]] = {}
    alias_to_slot: Dict[str, str] = {}
    for ref, spec in specs.items():
        gate = spec.get("skip_when_bound")
        if gate and slot_bound(str(gate)):
            alias_to_slot[ref] = str(gate)  # wires re-source from the slot
            continue
        gate = spec.get("when_bound")
        if gate and not slot_bound(str(gate)):
            continue
        active[ref] = spec

    # Resolve wires against the active set.
    resolved_wires: List[Dict[str, Any]] = []
    live_slot_targets: Dict[str, List[Tuple[str, str]]] = {}
    for wire in parsed_wires:
        tref = wire["target_ref"]
        if tref not in active:
            continue  # optional sub-chain not requested
        if "slot" in wire:
            slot = wire["slot"]
            resolved_wires.append(wire)
            live_slot_targets.setdefault(slot, []).append(
                (tref, wire["target_param"]))
        else:
            sref = wire["source_ref"]
            if sref in alias_to_slot:
                slot = alias_to_slot[sref]
                rewired = {"slot": slot, "target_ref": tref,
                           "target_param": wire["target_param"]}
                resolved_wires.append(rewired)
                live_slot_targets.setdefault(slot, []).append(
                    (tref, wire["target_param"]))
            elif sref in active:
                resolved_wires.append(wire)
            # else: source belongs to a skipped optional chain — drop.

    # Drivers/ref-params to realize: only slots with live targets.
    driver_slots: List[str] = []
    ref_param_slots: List[str] = []
    for name, entry in plan.items():
        if not live_slot_targets.get(name):
            continue
        kind = entry["kind"]
        if kind in DRIVER_KINDS and "value" in entry:
            driver_slots.append(name)
        elif kind in SOURCE_KINDS and any(
                "rhino_ids" in s for s in entry.get("sources") or []):
            ref_param_slots.append(name)

    # Version gates that need no mutation: multi-line fixed panels rely on
    # set_panel split_lines (v0.3+) to emit one item per line.
    multiline_panels = [ref for ref, spec in active.items()
                        if "\n" in str(spec.get("panel_text") or "")]
    if multiline_panels and not macros.supports_solve_batching(client):
        raise ExpansionError(
            "bridge_too_old",
            f"Template {template_id!r} uses multi-line panel constants "
            f"({', '.join(multiline_panels)}) which need set_panel "
            "split_lines — a v0.3+ GH_MCP_Wasp bridge")

    # ── placement (batched: every mutation carries solve:false) ──────────
    zone_tracker = macros.ZoneTracker()
    placed: Dict[str, str] = {}          # ref -> instance id
    driver_ids: Dict[str, str] = {}      # slot -> instance id
    ref_param_ids: Dict[str, str] = {}   # slot -> instance id
    param_components = load_param_components()

    # Left column: drivers, then referenced-geometry params.
    row = 0
    for name in driver_slots:
        entry = plan[name]
        px, py = x, y + row * DRIVER_DY
        row += 1
        if entry["kind"] == "driver_domain":
            comp = macros.call_no_solve(client, "add_component", {
                "type": "Panel", "x": px, "y": py})
            macros.call_no_solve(client, "set_panel", {
                "id": comp["id"], "text": entry["value"],
                "split_lines": False})
        else:
            comp = macros.call_no_solve(client, "add_component", {
                "type": "Number Slider", "x": px, "y": py})
            value = entry["value"]
            evidence = entry["spec"].get("range_evidence")
            if isinstance(evidence, (list, tuple)) and len(evidence) == 2:
                lo, hi = float(evidence[0]), float(evidence[1])
            else:
                lo, hi = 0.0, max(2.0 * abs(value), 10.0)
            lo, hi = min(lo, value), max(hi, value)
            macros.call_no_solve(client, "set_slider", {
                "id": comp["id"], "value": value, "min": lo, "max": hi})
        zone_tracker.add(px, py)
        driver_ids[name] = comp["id"]

    for name in ref_param_slots:
        entry = plan[name]
        rhino_ids: List[str] = []
        for source in entry.get("sources") or []:
            rhino_ids.extend(source.get("rhino_ids") or [])
        param_type = str(entry["spec"].get("ref_param") or "Geometry")
        info = param_components.get(param_type) or {}
        type_query = info.get("guid") or param_type
        if not info.get("guid") and param_type not in PROTOCOL_SAFE_TYPES:
            # Validation guarantees should prevent this; stay loud if a
            # template names an unevidenced param type.
            raise ExpansionError(
                "template_not_expandable",
                f"slot {name!r} names ref_param {param_type!r} with no "
                "GUID evidence in param_components")
        px, py = x, y + row * DRIVER_DY
        row += 1
        comp = macros.call_no_solve(client, "add_component", {
            "type": type_query, "x": px, "y": py})
        macros.call_no_solve(client, "set_geometry_ref", {
            "id": comp["id"], "objectIds": rhino_ids})
        zone_tracker.add(px, py)
        ref_param_ids[name] = comp["id"]

    # Body columns by dependency depth (left-to-right dataflow).
    depths = _component_depths(active, resolved_wires)
    col_rows: Dict[int, int] = {}
    body_positions: Dict[str, Tuple[float, float]] = {}
    for ref in active:  # declaration order within a column
        col = depths.get(ref, 0)
        row_in_col = col_rows.get(col, 0)
        col_rows[col] = row_in_col + 1
        px = x + BODY_X_OFFSET + col * BODY_COL_DX
        py = y + row_in_col * BODY_ROW_DY
        body_positions[ref] = (px, py)

    for ref, spec in active.items():
        px, py = body_positions[ref]
        if spec.get("wasp"):
            comp = macros.add_wasp(client, registry, str(spec["wasp"]),
                                   px, py)
        else:
            type_query = spec.get("guid") or spec.get("type")
            comp = macros.call_no_solve(client, "add_component", {
                "type": type_query, "x": px, "y": py})
            if spec.get("panel_text") is not None:
                macros.call_no_solve(client, "set_panel", {
                    "id": comp["id"], "text": str(spec["panel_text"])})
        zone_tracker.add(px, py)
        placed[ref] = comp["id"]

    # ── wiring (exact recorded param names; candidates only as fallback) ──
    def _spec_type(ref: str) -> str:
        return str((specs.get(ref) or {}).get("type") or "")

    def _connect_slot_source(source: Dict[str, Any], slot_name: str,
                             target_id: str, target_param: str) -> None:
        kind = plan[slot_name]["kind"]
        source_id = source["component_id"]
        explicit = source.get("param")
        if explicit:
            # Caller named the output — exact name, loud failure.
            macros.connect(client, source_id, explicit, target_id,
                           target_param)
            return
        candidates = _KIND_SOURCE_CANDIDATES.get(kind)
        if candidates:
            # Wasp sources without an explicit param: NEVER index 0 (an
            # aggregation's index 0 is AGGR, not the parts). Resolve by the
            # knowledge-base candidate names (connect_with_candidates is
            # exactly the sanctioned fallback here — PROTOCOL v0.5).
            macros.connect_with_candidates(client, source_id,
                                           list(candidates),
                                           target_id, target_param)
            return
        # Geometry sources: single implicit/primary output by index.
        macros.connect(client, source_id, None, target_id, target_param,
                       source_index=0)

    for wire in resolved_wires:
        target_id = placed[wire["target_ref"]]
        target_param = wire["target_param"]
        if "slot" in wire:
            slot_name = wire["slot"]
            entry = plan[slot_name]
            if slot_name in driver_ids:
                macros.connect(client, driver_ids[slot_name], None,
                               target_id, target_param, source_index=0)
                continue
            for source in entry.get("sources") or []:
                if "rhino_ids" in source:
                    macros.connect(client, ref_param_ids[slot_name], None,
                                   target_id, target_param, source_index=0)
                else:
                    _connect_slot_source(source, slot_name, target_id,
                                         target_param)
        else:
            source_ref = wire["source_ref"]
            source_id = placed[source_ref]
            if _spec_type(source_ref) in IMPLICIT_OUTPUT_TYPES:
                # Panels/sliders/toggles expose one implicit output.
                macros.connect(client, source_id, None, target_id,
                               target_param, source_index=0)
            else:
                macros.connect(client, source_id, wire["source_param"],
                               target_id, target_param)

    # ── one recompute for the whole batch ─────────────────────────────────
    all_ids = (list(driver_ids.values()) + list(ref_param_ids.values())
               + list(placed.values()))
    wait = macros.finalize_solution(client, all_ids)

    # ── v0.4 organization (skipped silently on pre-v0.4 bridges) ─────────
    stage_name = str(template.get("stage_name") or template_id)
    inputs_name = f"INPUTS — {stage_name.lower()} drivers"
    organization: Dict[str, Any] = {}

    # Body toggles (e.g. a Wasp RESET feeder) are user-tweakable drivers:
    # they belong in the INPUTS group with a role nickname, not in the
    # stage group (generation conventions #1).
    toggle_refs = [ref for ref, spec in active.items()
                   if str(spec.get("type")) == "Boolean Toggle"]
    stage_ids = [placed[ref] for ref in placed if ref not in toggle_refs]

    body_xs = [body_positions[r][0] for r in placed] or [x]
    body_ys = [body_positions[r][1] for r in placed] or [y]
    explainer = str(template.get("explainer") or "") or None
    if explainer:
        # The wrapped explainer scribble sits fully ABOVE the stage anchor;
        # extend the zone so it covers the annotation too.
        wrapped = macros.wrap_scribble_text(explainer)
        zone_tracker.add(
            min(body_xs),
            (min(body_ys) - 30) - macros.scribble_block_height(wrapped))
    stage_org = macros._organize_quietly(
        client,
        ids=stage_ids,
        stage_name=stage_name,
        x=min(body_xs), y=min(body_ys) - 30,
        explainer_text=explainer,
    )
    if stage_org:
        organization["stage"] = stage_org

    input_ids = (list(driver_ids.values()) + list(ref_param_ids.values())
                 + [placed[ref] for ref in toggle_refs])
    if input_ids:
        nicknames = {driver_ids[s]: _slot_role(s) for s in driver_ids}
        nicknames.update(
            {ref_param_ids[s]: _slot_role(s) for s in ref_param_ids})
        nicknames.update(
            {placed[ref]: _slot_role(ref) for ref in toggle_refs})
        inputs_org = macros._organize_quietly(
            client,
            ids=input_ids,
            stage_name=inputs_name,
            x=x, y=y - 30,
            color=macros.ORG_INPUTS_COLOR,
            nicknames=nicknames,
        )
        if inputs_org:
            organization["inputs"] = inputs_org

    # ── zone manifest (PROTOCOL v0.5 "Zone addressing") ───────────────────
    outputs: Dict[str, Any] = {}
    for name, spec_text in (template.get("outputs") or {}).items():
        oref, osep, oparam = str(spec_text).partition(".")
        if osep and oref in placed:
            outputs[name] = {"component_id": placed[oref], "param": oparam}

    drivers_manifest = {
        s: {"id": driver_ids[s], "role": _slot_role(s),
            "kind": plan[s]["kind"], "value": plan[s].get("value")}
        for s in driver_ids}

    manifest: Dict[str, Any] = {
        "template_id": template_id,
        "stage_name": stage_name,
        "zone": zone_tracker.rect(),
        "all_ids": all_ids,
        "components": dict(placed),
        "drivers": drivers_manifest,
        "referenced_params": dict(ref_param_ids),
        "outputs": outputs,
        "stages": [
            {"name": stage_name, "ids": stage_ids},
            {"name": inputs_name, "ids": input_ids},
        ],
    }
    if organization:
        manifest["organization"] = organization
    if wait is not None:
        manifest["wait"] = wait
    return manifest
