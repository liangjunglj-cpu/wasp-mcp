"""Offline tests for the v0.5 surface: template-expansion engine
(expander.py + list_templates/expand_template tools), zone-scoped canvas
lookups, capture passthroughs returning MCP image content, and
WASP_MCP_TOKEN injection.

No Grasshopper (and no TCP except private fake sockets) required:
FakeV05Client implements capture_viewport/capture_canvas in-memory on top
of the v0.4 fake.
"""

import base64
import json
import socket
import threading

import pytest

import expander
import macros
from expander import ExpansionError, expand_template, parse_wire
from gh_client import BridgeError, GHClient
from macros import ZoneTracker, find_wired_extractor, zone_contains
from test_offline import (  # noqa: F401  (fake_registry is a fixture)
    FAKE_DESCRIPTORS,
    FakeClient,
    fake_registry,
)
from test_v02 import FakeV01Client, FakeV02Client  # noqa: F401
from test_v03 import (  # noqa: F401
    AGG_ID,
    EXTRACTOR_ID,
    FakeV03Client,
    _canvas_with_extractor,
)
from test_v04 import FakeV04Client

FAKE_PNG = b"\x89PNG\r\n\x1a\nfake-png-bytes"
FAKE_PNG_B64 = base64.b64encode(FAKE_PNG).decode("ascii")

SQUARE_GUID = "717a1e25-a075-4530-bc80-d43ecc2500d9"
DISTANCE_GUID = "93b8e93d-f932-402c-b435-84be04d87666"
MULTIPLICATION_GUID = "ce46b74e-00c9-43c4-805a-193b69ea4a11"
CENTER_BOX_GUID = "28061aae-04fb-4cb5-ac45-16f3b66bc0a4"
POINT_PARAM_GUID = "fbac3e32-f100-4292-8692-77240a42fd1a"


class FakeV05Client(FakeV04Client):
    """FakeClient that also speaks the v0.5 capture commands, reports 0.5.0."""

    def __init__(self, canvas_state=None, **kwargs):
        if canvas_state is None:
            canvas_state = {"components": [], "connections": [],
                            "solutionState": "idle", "version": "0.5.0"}
        super().__init__(canvas_state=canvas_state, **kwargs)

    def call(self, command_type, parameters=None):
        parameters = parameters or {}
        if command_type == "capture_viewport":
            self.commands.append((command_type, parameters))
            return {"imageBase64": FAKE_PNG_B64,
                    "viewport": parameters.get("viewport", "Perspective"),
                    "width": 1280, "height": 720}
        if command_type == "capture_canvas":
            self.commands.append((command_type, parameters))
            return {"imageBase64": FAKE_PNG_B64, "width": 800, "height": 600}
        return super().call(command_type, parameters)


MUTATING_COMMANDS = {
    "add_component", "add_user_object", "connect_by_name",
    "connect_components", "set_slider", "set_panel", "set_geometry_ref",
    "set_plane_values", "set_toggle", "set_component_value",
    "expire_solution", "add_group", "add_scribble", "set_nickname",
}


def _assert_no_mutation(client):
    sent = [c for c, _ in client.commands if c in MUTATING_COMMANDS]
    assert sent == [], f"canvas was mutated before validation: {sent}"


# ── wire grammar ───────────────────────────────────────────────────────────


def test_parse_wire_forms():
    assert parse_wire("slot:cell_size -> grid.Size") == {
        "slot": "cell_size", "target_ref": "grid", "target_param": "Size"}
    assert parse_wire("grid.Points -> dist.Point A") == {
        "source_ref": "grid", "source_param": "Points",
        "target_ref": "dist", "target_param": "Point A"}
    # Param names keep exact recorded spellings (spaces, digits, dashes).
    assert parse_wire("cull.List -> weave.Stream 0")["target_param"] == \
        "Stream 0"
    assert parse_wire("depl.Z-Axis -> offs.A")["source_param"] == "Z-Axis"


def test_parse_wire_rejects_prose():
    for prose in (
        "grid.Points -> dist.Point A  (or slot:grid_points -> dist.Point A)"
        .replace("  ", " "),  # trailing parenthetical => target ref invalid
        "axis chain -> base_arch / top_left",
        "Split List(top nodes, 1) x Split List -> chord.Start",
        "just words",
        "slot: -> a.B",
    ):
        assert parse_wire(prose) is None, prose


# ── knowledge base state ───────────────────────────────────────────────────


# arch.twist_tower was retracted in v0.5.2: its core wiring was evidenced by
# an unlicensed corpus repo (see wasp-mcp-lab/retracted/). Re-add once
# re-evidenced from licensed material.
UPGRADED = ["arch.attractor_scale_grid", "arch.spatial_truss",
            "arch.section_contours",
            "wasp.stochastic_aggregation"]


def test_upgraded_templates_are_expandable():
    entries = {e["id"]: e for e in expander.list_templates()}
    for template_id in UPGRADED:
        entry = entries[template_id]
        assert entry["expandable"] is True, entry.get("issues")
        assert entry["source_files"]
    # terrain is deliberately blocked (Image Sampler state, no bridge cmd).
    terrain = entries["arch.terrain_from_image"]
    assert terrain["expandable"] is False
    assert "Image Sampler" in terrain["expansion_blocked"]
    assert "issues" not in terrain  # wires themselves are machine-parseable


def test_stock_body_components_carry_dump_guids():
    templates = expander.load_templates()
    for template_id in UPGRADED:
        for comp in templates[template_id]["body"]["components"]:
            if comp.get("wasp"):
                continue
            if comp.get("type") in expander.PROTOCOL_SAFE_TYPES:
                continue
            assert comp.get("guid"), (template_id, comp)


def test_wasp_template_places_via_registry_not_guid():
    template = expander.load_templates()["wasp.stochastic_aggregation"]
    agg = [c for c in template["body"]["components"]
           if c["ref"] == "agg"][0]
    assert agg["wasp"] == "stochastic_aggregation"
    assert "guid" not in agg


# ── expansion validation: typed errors BEFORE any canvas mutation ─────────


def test_expand_unknown_template(fake_registry):
    client = FakeV05Client()
    with pytest.raises(ExpansionError) as excinfo:
        expand_template(client, fake_registry, "arch.does_not_exist", {})
    assert excinfo.value.code == "template_not_found"
    assert client.commands == []


def test_expand_blocked_template(fake_registry):
    client = FakeV05Client()
    with pytest.raises(ExpansionError) as excinfo:
        expand_template(client, fake_registry, "arch.terrain_from_image",
                        {"extent": 10})
    assert excinfo.value.code == "template_blocked"
    assert any("Image Sampler" in d for d in excinfo.value.details)
    assert client.commands == []


def test_expand_data_only_template_not_expandable(fake_registry):
    client = FakeV05Client()
    with pytest.raises(ExpansionError) as excinfo:
        expand_template(client, fake_registry,
                        "arch.hex_attractor_paneling",
                        {"attractors": "comp-1"})
    assert excinfo.value.code == "template_not_expandable"
    assert excinfo.value.details  # names the prose wires / missing guids
    assert client.commands == []


def test_expand_collects_every_binding_problem(fake_registry):
    client = FakeV05Client()
    with pytest.raises(ExpansionError) as excinfo:
        expand_template(client, fake_registry, "arch.attractor_scale_grid", {
            # attractor (required) missing entirely
            "influence": "very strong",      # kind mismatch: driver_num
            "extent_x": 1.5,                 # kind mismatch: count int
            "no_such_slot": 1,               # unknown slot
        })
    err = excinfo.value
    assert err.code == "invalid_bindings"
    details = "\n".join(err.details)
    assert "attractor" in details          # unbound required slot
    assert "influence" in details          # number expected
    assert "extent_x" in details           # integer expected
    assert "no_such_slot" in details       # unknown slot
    assert len(err.details) == 4
    assert client.commands == []           # nothing placed, nothing probed
    assert "details" in err.to_dict()


def test_expand_rejects_rhino_ids_on_wasp_slots(fake_registry):
    client = FakeV05Client()
    with pytest.raises(ExpansionError) as excinfo:
        expand_template(client, fake_registry,
                        "wasp.stochastic_aggregation",
                        {"parts": {"rhino_ids": ["r-1"]},
                         "rules": "rules-1"})
    assert excinfo.value.code == "invalid_bindings"
    assert any("parts" in d and "Rhino" in d for d in excinfo.value.details)
    _assert_no_mutation(client)


def test_expand_multiline_panels_need_v03_bridge(fake_registry):
    # arch.spatial_truss carries True/False + 1/0 pattern panels which rely
    # on set_panel split_lines (v0.3). A v0.2 bridge gets a typed error and
    # an untouched canvas (the version probe is read-only).
    client = FakeV02Client()
    with pytest.raises(ExpansionError) as excinfo:
        expand_template(client, fake_registry, "arch.spatial_truss", {
            "start_support": {"rhino_ids": ["pt-a"]},
            "end_support": {"rhino_ids": ["pt-b"]},
        })
    assert excinfo.value.code == "bridge_too_old"
    _assert_no_mutation(client)


# ── full expansion command stream: arch.attractor_scale_grid ───────────────


@pytest.fixture
def attractor_expansion(fake_registry):
    client = FakeV05Client()
    result = expand_template(
        client, fake_registry, "arch.attractor_scale_grid",
        {"attractor": {"rhino_ids": ["rhino-pt-1"]}},
        x=1000.0, y=500.0)
    return client, result


def test_attractor_places_stock_components_by_guid(attractor_expansion):
    client, result = attractor_expansion
    types = [p["type"] for p in client.sent("add_component")]
    # Body components placed by componentGuid from the E.5.2 dump —
    # regression finding #1: the NAME "Square" collides with Maths>Sqr.
    for guid in (SQUARE_GUID, DISTANCE_GUID, MULTIPLICATION_GUID,
                 CENTER_BOX_GUID):
        assert guid in types
    assert "Square" not in types
    # The attractor Rhino point is referenced through a Point param placed
    # by its dump guid and fed via set_geometry_ref.
    assert POINT_PARAM_GUID in types
    georefs = client.sent("set_geometry_ref")
    assert georefs == [{"id": result["referenced_params"]["attractor"],
                        "objectIds": ["rhino-pt-1"], "solve": False}]
    assert client.sent("add_user_object") == []  # no Wasp components here


def test_attractor_wires_exact_recorded_param_names(attractor_expansion):
    client, result = attractor_expansion
    comps = result["components"]
    conns = client.sent("connect_by_name")

    def has(source_id, source_param, target_id, target_param):
        return any(c["sourceId"] == source_id
                   and c["sourceParam"] == source_param
                   and c["targetId"] == target_id
                   and c["targetParam"] == target_param for c in conns)

    drivers = result["drivers"]
    # Driver sliders wire by implicit output (None + index 0), targets by
    # the exact dump-recorded names incl. "Extent X"/"Extent Y".
    assert has(drivers["cell_size"]["id"], None, comps["grid"], "Size")
    assert has(drivers["extent_x"]["id"], None, comps["grid"], "Extent X")
    assert has(drivers["extent_y"]["id"], None, comps["grid"], "Extent Y")
    assert has(drivers["influence"]["id"], None, comps["scale"], "B")
    # Internal edges use the recorded source AND target names.
    assert has(comps["grid"], "Points", comps["dist"], "Point A")
    assert has(comps["dist"], "Distance", comps["scale"], "A")
    assert has(comps["grid"], "Points", comps["cell"], "Base")
    for axis in ("X", "Y", "Z"):
        assert has(comps["scale"], "Result", comps["cell"], axis)
    # Referenced attractor point -> Distance.Point B.
    assert has(result["referenced_params"]["attractor"], None,
               comps["dist"], "Point B")


def test_attractor_sliders_use_range_evidence(attractor_expansion):
    client, result = attractor_expansion
    sliders = {s["id"]: s for s in client.sent("set_slider")}
    drivers = result["drivers"]
    influence = sliders[drivers["influence"]["id"]]
    assert influence["value"] == 0.05 and influence["min"] == 0 \
        and influence["max"] == 1
    cell_size = sliders[drivers["cell_size"]["id"]]
    assert cell_size["value"] == 10 and cell_size["max"] == 10
    extent_x = sliders[drivers["extent_x"]["id"]]
    assert extent_x["value"] == 10 and extent_x["max"] == 100


def test_attractor_batches_and_finalizes(attractor_expansion):
    client, result = attractor_expansion
    for command_type, params in client.commands:
        if command_type in ("add_component", "add_user_object",
                            "connect_by_name", "set_slider", "set_panel",
                            "set_geometry_ref"):
            assert params.get("solve") is False, (command_type, params)
    expires = client.sent("expire_solution")
    assert len(expires) == 1
    assert set(expires[0]["ids"]) == set(result["all_ids"])
    assert len(client.sent("wait_for_idle")) == 1
    assert result["wait"] == {"idle": True, "waitedMs": 7}


def test_attractor_applies_v04_organization(attractor_expansion):
    client, result = attractor_expansion
    groups = {g["name"]: g for g in client.sent("add_group")}
    assert set(groups) == {"ATTRACTOR FIELD",
                           "INPUTS — attractor field drivers"}
    stage = groups["ATTRACTOR FIELD"]
    assert set(stage["ids"]) == set(result["components"].values())
    assert stage["color"] == macros.ORG_STAGE_COLOR
    inputs = groups["INPUTS — attractor field drivers"]
    expected_inputs = {d["id"] for d in result["drivers"].values()} | \
        set(result["referenced_params"].values())
    assert set(inputs["ids"]) == expected_inputs
    assert inputs["color"] == macros.ORG_INPUTS_COLOR
    # Explainer scribble: the template's own explainer text, wrapped.
    template = expander.load_templates()["arch.attractor_scale_grid"]
    texts = [s["text"] for s in client.sent("add_scribble")]
    assert macros.wrap_scribble_text(template["explainer"]) in texts
    # Sliders nicknamed by role (slot name), never left as "Number Slider".
    assert client.nicknames[result["drivers"]["cell_size"]["id"]] == \
        "cell size"
    assert client.nicknames[result["referenced_params"]["attractor"]] == \
        "attractor"


def test_attractor_zone_manifest(attractor_expansion):
    client, result = attractor_expansion
    zone = result["zone"]
    assert set(zone) == {"x", "y", "width", "height"}
    # Zone covers the drivers column at the requested origin...
    assert zone["x"] <= 1000.0 <= zone["x"] + zone["width"]
    assert zone["y"] <= 500.0 <= zone["y"] + zone["height"]
    # ...and every add_component anchor the expansion placed.
    for _, params in client.commands:
        if "x" in params and "y" in params:
            assert zone_contains(zone, [params["x"], params["y"]])
    assert set(result["all_ids"]) == (
        set(result["components"].values())
        | {d["id"] for d in result["drivers"].values()}
        | set(result["referenced_params"].values()))
    # Per-stage breakdown + outputs by exact recorded param name.
    stages = {s["name"]: s["ids"] for s in result["stages"]}
    assert set(stages["ATTRACTOR FIELD"]) == \
        set(result["components"].values())
    assert result["outputs"]["sizes"] == {
        "component_id": result["components"]["scale"], "param": "Result"}
    assert result["outputs"]["cells"] == {
        "component_id": result["components"]["cell"], "param": "Box"}


def test_attractor_bound_grid_points_skips_internal_grid(fake_registry):
    client = FakeV05Client()
    result = expand_template(
        client, fake_registry, "arch.attractor_scale_grid",
        {"attractor": "attr-comp",
         "grid_points": {"component_id": "upstream-1", "param": "Points"}})
    types = [p["type"] for p in client.sent("add_component")]
    assert SQUARE_GUID not in types            # internal default skipped
    assert "grid" not in result["components"]
    # Wires that read grid.Points re-source from the binding.
    conns = client.sent("connect_by_name")
    assert any(c["sourceId"] == "upstream-1"
               and c["sourceParam"] == "Points"
               and c["targetParam"] == "Point A" for c in conns)
    assert any(c["sourceId"] == "upstream-1"
               and c["targetParam"] == "Base" for c in conns)
    # Drivers that only fed the skipped grid are not realized.
    assert "cell_size" not in result["drivers"]
    assert "extent_x" not in result["drivers"]
    assert "influence" in result["drivers"]
    # Bare-string geometry binding wires by implicit output index 0.
    assert any(c["sourceId"] == "attr-comp" and c["sourceIndex"] == 0
               and c["targetParam"] == "Point B" for c in conns)


MINIMAL_BINDINGS = {
    "arch.attractor_scale_grid": {"attractor": {"rhino_ids": ["p-1"]}},
    "arch.spatial_truss": {"start_support": {"rhino_ids": ["p-1"]},
                           "end_support": {"rhino_ids": ["p-2"]}},
    "arch.section_contours": {"solid": {"rhino_ids": ["brep-1"]}},
}


@pytest.mark.parametrize("template_id", sorted(MINIMAL_BINDINGS))
def test_every_upgraded_arch_template_expands(template_id, fake_registry):
    client = FakeV05Client()
    result = expand_template(client, fake_registry, template_id,
                             MINIMAL_BINDINGS[template_id], x=0, y=0)
    template = expander.load_templates()[template_id]
    # Every non-optional body component landed; ids are all real.
    assert result["zone"]
    assert result["all_ids"]
    assert set(result["all_ids"]) >= set(result["components"].values())
    # Stock placements only ever by GUID or PROTOCOL-safe name.
    safe = expander.PROTOCOL_SAFE_TYPES
    for params in client.sent("add_component"):
        assert params["type"] in safe or "-" in params["type"], params
    # One batch: exactly one expire + one wait, everything solve:false.
    assert len(client.sent("expire_solution")) == 1
    assert len(client.sent("wait_for_idle")) == 1
    # Both organization groups present.
    names = {g["name"] for g in client.sent("add_group")}
    assert template["stage_name"] in names
    assert any(n.startswith("INPUTS") for n in names)


def test_section_contours_optional_tails(fake_registry):
    # Without bindings: no Contour, no layout chain.
    client = FakeV05Client()
    result = expand_template(client, fake_registry, "arch.section_contours",
                             {"solid": {"rhino_ids": ["brep-1"]}})
    assert "contour" not in result["components"]
    assert "flatten" not in result["components"]
    assert "even_contours" not in result["outputs"]
    # Binding interval/layout_spacing pulls the evidenced tails in.
    client2 = FakeV05Client()
    result2 = expand_template(
        client2, fake_registry, "arch.section_contours",
        {"solid": {"rhino_ids": ["brep-1"]}, "interval": 1.0,
         "layout_spacing": 5.98})
    assert "contour" in result2["components"]
    assert "flatten" in result2["components"]
    conns = client2.sent("connect_by_name")
    assert any(c["targetParam"] == "Distance" for c in conns)
    assert any(c["targetParam"] == "Target" for c in conns)
    assert result2["outputs"]["even_contours"]["param"] == "Contours"


# ── full expansion command stream: wasp.stochastic_aggregation ────────────


@pytest.fixture
def wasp_expansion(fake_registry):
    client = FakeV05Client()
    result = expand_template(
        client, fake_registry, "wasp.stochastic_aggregation",
        {"parts": ["part-A", "part-B"], "rules": "rules-1", "count": 120},
        x=0.0, y=0.0)
    return client, result


def test_wasp_expansion_places_via_registry(wasp_expansion):
    client, result = wasp_expansion
    user_objects = client.sent("add_user_object")
    assert len(user_objects) == 1
    assert "stochastic aggregation" in user_objects[0]["path"].lower()
    assert user_objects[0]["solve"] is False
    types = [p["type"] for p in client.sent("add_component")]
    assert types.count("Number Slider") == 2   # count + seed(default)
    assert types.count("Boolean Toggle") == 1


def test_wasp_expansion_wires_recorded_names(wasp_expansion):
    client, result = wasp_expansion
    agg_id = result["components"]["agg"]
    conns = client.sent("connect_by_name")
    # Parts by knowledge-base candidates (PART, never index 0 — an
    # aggregation source's index 0 would be AGGR).
    part_conns = [c for c in conns if c["targetParam"] == "PART"]
    assert {c["sourceId"] for c in part_conns} == {"part-A", "part-B"}
    assert all(c["sourceParam"] == "PART" for c in part_conns)
    assert all(c["targetId"] == agg_id for c in part_conns)
    assert any(c["sourceId"] == "rules-1" and c["targetParam"] == "RULES"
               and c["sourceParam"] == "R" for c in conns)
    # Drivers/toggle by implicit output into the exact recorded inputs.
    assert any(c["targetParam"] == "N" and c["sourceIndex"] == 0
               for c in conns)
    assert any(c["targetParam"] == "SEED" for c in conns)
    toggle_conn = [c for c in conns if c["targetParam"] == "RESET"]
    assert len(toggle_conn) == 1 and toggle_conn[0]["sourceIndex"] == 0

    sliders = client.sent("set_slider")
    count = [s for s in sliders if s["value"] == 120.0][0]
    assert (count["min"], count["max"]) == (0.0, 1000.0)  # range_evidence
    assert any(s["value"] == 1.0 for s in sliders)  # seed default

    expires = client.sent("expire_solution")
    assert len(expires) == 1 and agg_id in expires[0]["ids"]
    assert len(client.sent("wait_for_idle")) == 1


def test_wasp_expansion_reset_toggle_is_an_inputs_driver(wasp_expansion):
    client, result = wasp_expansion
    groups = {g["name"]: g for g in client.sent("add_group")}
    stage = groups["AGGREGATION"]
    inputs = groups["INPUTS — aggregation drivers"]
    reset_id = result["components"]["reset"]
    assert stage["ids"] == [result["components"]["agg"]]
    assert reset_id in inputs["ids"]
    assert client.nicknames[reset_id] == "reset"
    assert result["outputs"]["parts_out"] == {
        "component_id": result["components"]["agg"], "param": "PART_OUT"}


def test_expansion_skips_organization_pre_v04(fake_registry):
    client = FakeV03Client()
    result = expand_template(
        client, fake_registry, "wasp.stochastic_aggregation",
        {"parts": "part-A", "rules": "rules-1"})
    assert client.sent("add_group") == []
    assert client.sent("add_scribble") == []
    assert "organization" not in result
    assert result["zone"]  # zone manifest present on every bridge


# ── zone-scoped canvas lookups ─────────────────────────────────────────────


def test_zone_tracker_and_contains():
    tracker = ZoneTracker()
    assert tracker.rect() is None
    tracker.add(100, 50)
    tracker.add(400, 200)
    zone = tracker.rect()
    assert zone["x"] <= 100 and zone["y"] <= 50
    assert zone["x"] + zone["width"] >= 400
    assert zone["y"] + zone["height"] >= 200
    assert zone_contains(zone, [250, 100])
    assert not zone_contains(zone, [5000, 100])
    # None zone / missing position: cannot verify -> include (compat).
    assert zone_contains(None, [5000, 5000])
    assert zone_contains(zone, None)
    assert zone_contains(zone, [])


def _far_extractor_canvas():
    state = _canvas_with_extractor()
    state["components"][1]["position"] = [5000.0, 5000.0]
    return state


def test_find_wired_extractor_zone_filter():
    client = FakeV03Client(canvas_state=_canvas_with_extractor())
    zone = {"x": 300, "y": 0, "width": 500, "height": 300}
    assert find_wired_extractor(client, AGG_ID, ("get part geometry",),
                                zone=zone) == EXTRACTOR_ID
    far = {"x": -1000, "y": -1000, "width": 100, "height": 100}
    assert find_wired_extractor(client, AGG_ID, ("get part geometry",),
                                zone=far) is None


def test_get_aggregation_ignores_cross_zone_extractor(fake_registry):
    # A same-typed extractor wired to the aggregation but sitting in a far
    # canvas zone (another workflow) is NOT reused — finding #6.
    client = FakeV03Client(canvas_state=_far_extractor_canvas())
    result = macros.get_aggregation(client, fake_registry, AGG_ID,
                                    out="meshes", x=400, y=0)
    assert result["reused_extractor"] is False
    assert result["extractor_id"] != EXTRACTOR_ID
    assert len(client.sent("add_user_object")) == 1
    # The macro result now declares its zone (additive field).
    zone = result["zone"]
    assert zone_contains(zone, [400, 100])     # aggregation position
    assert not zone_contains(zone, [5000, 5000])


def test_get_aggregation_still_reuses_in_zone_extractor(fake_registry):
    client = FakeV03Client(canvas_state=_canvas_with_extractor())
    result = macros.get_aggregation(client, fake_registry, AGG_ID,
                                    out="meshes")
    assert result["reused_extractor"] is True
    assert result["extractor_id"] == EXTRACTOR_ID
    assert "zone" in result


def test_reset_aggregation_ignores_cross_zone_toggle():
    from test_v02 import _canvas
    state = _canvas(with_toggle=True)
    state["components"][1]["position"] = [5000.0, 5000.0]  # far toggle
    client = FakeV02Client(canvas_state=state)
    result = macros.reset_aggregation(client, AGG_ID)
    assert result["created_toggle"] is True   # far toggle not reused
    assert result["toggle_id"] != "toggle-1"
    assert "zone" in result


def test_macro_results_carry_zone(fake_registry):
    client = FakeV05Client()
    result = macros.run_aggregation(client, fake_registry, ["part-A"],
                                    "rules-1", 50, seed=7, x=400, y=100)
    zone = result["zone"]
    # Covers the aggregation anchor and the driver column to its left.
    assert zone_contains(zone, [400, 100])
    assert zone_contains(zone, [150, 280])    # reset toggle spot
    rules = macros.define_rules(client, fake_registry, "P|1_P|0",
                                ["part-A"], x=0, y=200)
    assert zone_contains(rules["zone"], [-250, 200])  # grammar panel
    part = macros.create_wasp_part(client, fake_registry, "HEX",
                                   geometry_object_ids=["rhino-1"],
                                   x=0, y=0)
    assert zone_contains(part["zone"], [-250, 0])     # geometry param


# ── MCP tool layer (server.py) ─────────────────────────────────────────────


@pytest.fixture
def server_v05(monkeypatch, fake_registry):
    import server
    client = FakeV05Client()
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_registry", fake_registry)
    monkeypatch.setattr(server, "_make_wait_client", lambda: client)
    return server, client


def test_list_templates_tool(server_v05):
    server, client = server_v05
    out = server.list_templates()
    assert out["success"] is True
    entries = {e["id"]: e for e in out["templates"]}
    assert entries["arch.attractor_scale_grid"]["expandable"] is True
    assert entries["arch.terrain_from_image"]["expansion_blocked"]
    assert entries["wasp.stochastic_aggregation"]["slots"]["count"]["kind"] \
        == "driver_int"
    assert out["count"] == len(out["templates"])
    assert client.commands == []  # discovery is local, no bridge traffic


def test_expand_template_tool_accepts_json_string_bindings(server_v05):
    server, client = server_v05
    out = server.expand_template(
        "wasp.stochastic_aggregation",
        bindings='{"parts": "part-A", "rules": "rules-1", "count": 60}')
    assert out["success"] is True
    assert out["result"]["zone"]
    assert out["result"]["components"]["agg"]

    bad = server.expand_template("wasp.stochastic_aggregation",
                                 bindings="{not json")
    assert bad["error"] == "invalid_arguments"


def test_expand_template_tool_surfaces_typed_errors(server_v05):
    server, client = server_v05
    out = server.expand_template("arch.attractor_scale_grid",
                                 bindings={"influence": "loud"})
    assert out["success"] is False
    assert out["error"] == "invalid_bindings"
    assert any("influence" in d for d in out["details"])
    assert any("attractor" in d for d in out["details"])

    missing = server.expand_template("nope.nothing")
    assert missing["error"] == "template_not_found"


# ── v0.5 capture passthroughs ──────────────────────────────────────────────


def test_gh_capture_viewport_returns_image_content(server_v05):
    server, client = server_v05
    out = server.gh_capture_viewport(viewport="Top", width=640, height=480,
                                     zoom_extents=True)
    from fastmcp.utilities.types import Image
    assert isinstance(out, Image)             # MCP image content, not text
    assert out.data == FAKE_PNG
    assert client.sent("capture_viewport") == [{
        "viewport": "Top", "width": 640, "height": 480,
        "zoomExtents": True}]
    # Defaults: only zoomExtents on the wire.
    server.gh_capture_viewport()
    assert client.sent("capture_viewport")[1] == {"zoomExtents": False}


def test_gh_capture_canvas_wire_shape_and_region(server_v05):
    server, client = server_v05
    out = server.gh_capture_canvas(zoom=0.5, region=[0, 0, 800, 600])
    from fastmcp.utilities.types import Image
    assert isinstance(out, Image)
    assert client.sent("capture_canvas") == [{
        "zoom": 0.5, "region": [0.0, 0.0, 800.0, 600.0]}]

    bad = server.gh_capture_canvas(region=[1, 2])
    assert bad["error"] == "invalid_arguments"
    bad = server.gh_capture_canvas(region="not json")
    assert bad["error"] == "invalid_arguments"


def test_capture_on_old_bridge_is_bridge_too_old(monkeypatch, fake_registry):
    import server
    client = FakeV01Client()

    def reject(command_type, parameters=None):
        client.commands.append((command_type, parameters or {}))
        raise BridgeError("bridge_command_failed",
                          f"Unknown command type '{command_type}'")

    monkeypatch.setattr(client, "call", reject)
    monkeypatch.setattr(server, "_client", client)
    out = server.gh_capture_viewport()
    assert out["success"] is False
    assert out["error"] == "bridge_too_old"
    assert "v0.5" in out["hint"]
    # v0.1-wording bridges get the same typed error.
    def reject_v01(command_type, parameters=None):
        raise BridgeError("bridge_command_failed",
                          "No handler registered for command type 'x'")
    monkeypatch.setattr(client, "call", reject_v01)
    assert server.gh_capture_canvas()["error"] == "bridge_too_old"


def test_capture_bad_image_payload_is_protocol_error(monkeypatch,
                                                     server_v05):
    server, client = server_v05

    def no_image(command_type, parameters=None):
        return {}
    monkeypatch.setattr(client, "call", no_image)
    out = server.gh_capture_viewport()
    assert out["error"] == "bridge_protocol"


# ── WASP_MCP_TOKEN injection (gh_client) ───────────────────────────────────


def _capture_request_once(response_obj):
    """Fake bridge that records the raw request and answers response_obj."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]
    captured = {}

    def run():
        conn, _ = server_sock.accept()
        captured["raw"] = conn.recv(65536)
        conn.sendall((json.dumps(response_obj) + "\n").encode("utf-8"))
        conn.close()
        server_sock.close()

    threading.Thread(target=run, daemon=True).start()
    return port, captured


def test_token_added_to_every_request_when_set(monkeypatch):
    monkeypatch.setenv("WASP_MCP_TOKEN", "hunter2")
    port, captured = _capture_request_once({"success": True, "result": {}})
    client = GHClient(port=port, read_timeout=5.0)
    client.call("get_canvas_state")
    request = json.loads(captured["raw"].decode("utf-8"))
    assert request["token"] == "hunter2"       # top-level field
    assert request["type"] == "get_canvas_state"
    assert "token" not in request["parameters"]


def test_token_absent_when_env_unset_or_blank(monkeypatch):
    monkeypatch.delenv("WASP_MCP_TOKEN", raising=False)
    port, captured = _capture_request_once({"success": True, "result": {}})
    GHClient(port=port, read_timeout=5.0).call("ping")
    assert "token" not in json.loads(captured["raw"].decode("utf-8"))

    monkeypatch.setenv("WASP_MCP_TOKEN", "   ")
    port, captured = _capture_request_once({"success": True, "result": {}})
    GHClient(port=port, read_timeout=5.0).call("ping")
    assert "token" not in json.loads(captured["raw"].decode("utf-8"))


def test_token_never_appears_in_errors(monkeypatch):
    monkeypatch.setenv("WASP_MCP_TOKEN", "sup3r-secret")
    port, _ = _capture_request_once({"success": False,
                                     "error": "auth_failed"})
    client = GHClient(port=port, read_timeout=5.0)
    with pytest.raises(BridgeError) as excinfo:
        client.call("get_canvas_state")
    err = excinfo.value
    assert "auth_failed" in err.message
    assert "sup3r-secret" not in str(err)
    assert "sup3r-secret" not in json.dumps(err.to_dict())
