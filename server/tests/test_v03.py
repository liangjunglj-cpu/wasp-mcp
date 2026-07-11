"""Offline tests for the v0.3 surface: bridge version probing, solve-flag
batching, wait_for_idle, set_panel split_lines gating, component
introspection tools, JSON-string tolerance for list/dict tool params,
run_aggregation RESET pulses, define_rules panel fan-out and
get_aggregation extractor reuse.

No Grasshopper (and no TCP) required: FakeV03Client implements the v0.3
commands in-memory; the v0.1/v0.2 fakes come from the earlier suites.
"""

import json

import pytest

import macros
from gh_client import BridgeError
from macros import (
    bridge_version,
    finalize_solution,
    find_wired_extractor,
    parse_version,
    supports_set_toggle,
    supports_solve_batching,
)
from test_offline import (  # noqa: F401  (fake_registry is a fixture)
    FAKE_DESCRIPTORS,
    FakeClient,
    fake_registry,
)
from test_v02 import (  # noqa: F401  (registry_with_conn is a fixture)
    PLANE_DICT,
    PLANE_FLAT,
    FakeV01Client,
    FakeV02Client,
    registry_with_conn,
)

# Commands that accept the v0.3 "solve" flag (PROTOCOL.md "Batch solves").
MUTATING_COMMANDS = {
    "add_component", "add_user_object", "connect_by_name",
    "connect_components", "set_slider", "set_panel", "set_geometry_ref",
    "set_plane_values", "set_toggle", "set_component_value",
}

SCHEMA_MESH_BOX = {
    "name": "Mesh Box", "nickname": "MBox", "guid": "guid-mesh-box",
    "category": "Mesh", "subCategory": "Primitive",
    "description": "Create a mesh box.",
    "inputs": [
        {"name": "Base", "nickname": "B", "index": 0, "typeName": "Box",
         "description": "Base box", "optional": False},
        {"name": "X Count", "nickname": "X", "index": 1, "typeName": "Integer",
         "description": "Face count in x", "optional": False,
         "defaultValue": 10},
    ],
    "outputs": [
        {"name": "Mesh", "nickname": "M", "index": 0, "typeName": "Mesh",
         "description": "Resulting mesh"},
    ],
}


class FakeV03Client(FakeV02Client):
    """FakeClient that also speaks the v0.3 commands and reports 0.3.0."""

    def __init__(self, canvas_state=None, **kwargs):
        if canvas_state is None:
            canvas_state = {"components": [], "connections": [],
                            "solutionState": "idle", "version": "0.3.0"}
        super().__init__(canvas_state=canvas_state, **kwargs)

    def call(self, command_type, parameters=None):
        parameters = parameters or {}
        if command_type == "wait_for_idle":
            self.commands.append((command_type, parameters))
            return {"idle": True, "waitedMs": 7}
        if command_type == "list_component_types":
            self.commands.append((command_type, parameters))
            return {"components": [{k: SCHEMA_MESH_BOX[k] for k in
                                    ("name", "nickname", "category",
                                     "subCategory", "guid", "description")}],
                    "total": 1}
        if command_type == "get_component_schema":
            self.commands.append((command_type, parameters))
            return dict(SCHEMA_MESH_BOX)
        return super().call(command_type, parameters)


# ── version probing ────────────────────────────────────────────────────────


def test_parse_version():
    assert parse_version(None) == (0, 1, 0)
    assert parse_version("") == (0, 1, 0)
    assert parse_version("garbage") == (0, 1, 0)
    assert parse_version("0.3.0") == (0, 3, 0)
    assert parse_version("0.2") == (0, 2, 0)
    assert parse_version("1.10.2") == (1, 10, 2)
    assert parse_version("0.10.0") > parse_version("0.3.0")  # numeric, not lexical


def test_bridge_version_per_generation():
    assert bridge_version(FakeClient()) == (0, 1, 0)       # no version field
    assert bridge_version(FakeV02Client()) == (0, 2, 0)
    assert bridge_version(FakeV03Client()) == (0, 3, 0)


def test_bridge_version_cached_per_client():
    client = FakeV03Client()
    assert bridge_version(client) == (0, 3, 0)
    assert bridge_version(client) == (0, 3, 0)
    assert len(client.sent("get_document_info")) == 1


def test_bridge_version_command_error_not_cached():
    class NoDocClient(FakeClient):
        def call(self, command_type, parameters=None):
            if command_type == "get_document_info":
                self.commands.append((command_type, parameters or {}))
                raise BridgeError("bridge_command_failed",
                                  "No active Grasshopper document")
            return super().call(command_type, parameters)

    client = NoDocClient()
    assert bridge_version(client) == (0, 1, 0)
    assert getattr(client, macros._VERSION_CACHE_ATTR, None) is None
    assert bridge_version(client) == (0, 1, 0)  # probed again, still not cached
    assert len(client.sent("get_document_info")) == 2


def test_capability_helpers():
    assert supports_solve_batching(FakeV03Client()) is True
    assert supports_solve_batching(FakeV02Client()) is False
    assert supports_solve_batching(FakeClient()) is False
    assert supports_set_toggle(FakeV03Client()) is True
    assert supports_set_toggle(FakeV02Client()) is True
    assert supports_set_toggle(FakeClient()) is False


# ── finalize_solution ──────────────────────────────────────────────────────


def test_finalize_solution_v03_expires_then_waits():
    client = FakeV03Client()
    result = finalize_solution(client, ["agg-1"], timeout_ms=5000)
    assert result == {"idle": True, "waitedMs": 7}
    assert client.sent("expire_solution") == [{"ids": ["agg-1"]}]
    assert client.sent("wait_for_idle") == [{"timeoutMs": 5000}]


def test_finalize_solution_pre_v03_skips_wait():
    client = FakeV02Client()
    assert finalize_solution(client, ["agg-1"]) is None
    assert client.sent("expire_solution") == [{"ids": ["agg-1"]}]
    assert client.sent("wait_for_idle") == []


def test_finalize_solution_without_ids_expires_document():
    client = FakeV03Client()
    finalize_solution(client)
    assert client.sent("expire_solution") == [{}]


# ── solve-flag pass-through ────────────────────────────────────────────────


def _assert_all_mutations_batched(client, skip_probe=True):
    seen = 0
    for command_type, params in client.commands:
        if command_type not in MUTATING_COMMANDS:
            continue
        if skip_probe and command_type == "set_plane_values" \
                and params.get("planes") == []:
            continue  # the capability probe is deliberately minimal
        assert params.get("solve") is False, \
            f"{command_type} was sent without solve:false ({params})"
        seen += 1
    assert seen > 0


def test_run_aggregation_all_mutations_carry_solve_false(fake_registry):
    client = FakeV03Client()
    macros.run_aggregation(client, fake_registry, ["part-A"], "rules-1", 50,
                           seed=3, x=400, y=100)
    _assert_all_mutations_batched(client)


def test_define_rules_all_mutations_carry_solve_false(fake_registry):
    client = FakeV03Client()
    macros.define_rules(client, fake_registry, "P|1_P|0\nP|2_P|0", ["part-A"])
    _assert_all_mutations_batched(client)


def test_create_wasp_part_all_mutations_carry_solve_false(registry_with_conn):
    client = FakeV03Client()
    macros.create_wasp_part(client, registry_with_conn, "HEX",
                            geometry_object_ids=["rhino-1"],
                            connection_planes=[PLANE_DICT])
    _assert_all_mutations_batched(client)


def test_create_wasp_part_v03_ends_with_expire_and_wait(registry_with_conn):
    client = FakeV03Client()
    result = macros.create_wasp_part(client, registry_with_conn, "HEX",
                                     geometry_object_ids=["rhino-1"],
                                     connection_planes=[PLANE_DICT])
    # Ignore read-only probes (get_document_info fires lazily on the first
    # capability check, which happens between the expire and the wait).
    trace = [c for c, _ in client.commands
             if c not in ("get_document_info",)]
    assert trace[-2:] == ["expire_solution", "wait_for_idle"]
    assert client.sent("expire_solution") == [{"ids": [result["part_id"]]}]


def test_create_wasp_part_v01_never_sends_wait(registry_with_conn):
    client = FakeV01Client()
    macros.create_wasp_part(client, registry_with_conn, "HEX",
                            geometry_object_ids=["rhino-1"],
                            connection_planes=[PLANE_DICT])
    assert client.sent("wait_for_idle") == []


# ── define_rules version gating ────────────────────────────────────────────

GRAMMAR = "P|1_P|0\nP|2_P|0\nP|3_P|0"


def test_define_rules_v03_single_split_panel(fake_registry):
    client = FakeV03Client()
    result = macros.define_rules(client, fake_registry, GRAMMAR, ["part-A"])
    panels = client.sent("set_panel")
    assert len(panels) == 1
    assert panels[0]["text"] == GRAMMAR  # whole grammar in one panel
    # split_lines is the bridge default (true); the macro doesn't override it.
    assert "split_lines" not in panels[0] or panels[0]["split_lines"] is True
    assert result["grammar_panel_id"] == result["rule_panel_ids"][0]
    assert len(result["rule_panel_ids"]) == 1


def test_define_rules_v02_one_panel_per_rule(fake_registry):
    client = FakeV02Client()  # v0.2: has toggles but NOT split_lines
    result = macros.define_rules(client, fake_registry, GRAMMAR, ["part-A"])
    panels = client.sent("set_panel")
    assert [p["text"] for p in panels] == GRAMMAR.split("\n")
    assert len(result["rule_panel_ids"]) == 3


def test_define_rules_single_rule_uses_one_panel_everywhere(fake_registry):
    client = FakeV01Client()
    result = macros.define_rules(client, fake_registry, "P|1_P|0", ["part-A"])
    assert len(client.sent("set_panel")) == 1
    assert len(result["rule_panel_ids"]) == 1


def test_define_rules_blank_grammar_rejected(fake_registry):
    with pytest.raises(ValueError):
        macros.define_rules(FakeV03Client(), fake_registry, "  \n ", ["p"])


# ── run_aggregation RESET pulse ────────────────────────────────────────────


def test_run_aggregation_v03_pulses_toggle_and_waits(fake_registry):
    client = FakeV03Client()
    result = macros.run_aggregation(client, fake_registry, ["part-A"],
                                    "rules-1", 60, x=400, y=100)
    agg_id = result["aggregation_id"]

    added_types = [p["type"] for p in client.sent("add_component")]
    assert "Boolean Toggle" in added_types
    assert result["reset_toggle_id"] in result["all_ids"]

    conns = client.sent("connect_by_name")
    assert any(c["sourceId"] == result["reset_toggle_id"]
               and c["targetParam"] == "RESET" and c["sourceIndex"] == 0
               for c in conns)

    # Pulse true (expire includes the TOGGLE source per validator F1, and the
    # True-state solve gets its own wait), back to false, final expire + wait.
    tid = result["reset_toggle_id"]
    toggles = [(p["id"], p["value"]) for p in client.sent("set_toggle")]
    assert toggles == [(tid, True), (tid, False)]
    assert client.sent("expire_solution") == [{"ids": [tid, agg_id]},
                                              {"ids": [agg_id]}]
    assert len(client.sent("wait_for_idle")) == 2
    assert client.toggle_values[tid] is False


def test_run_aggregation_v01_pulses_panel(fake_registry):
    client = FakeClient()  # v0.1: no set_toggle
    result = macros.run_aggregation(client, fake_registry, ["part-A"],
                                    "rules-1", 60, x=400, y=100)
    assert "reset_toggle_id" not in result
    assert client.sent("set_toggle") == []

    panel_id = result["reset_panel_id"]
    texts = [p["text"] for p in client.sent("set_panel")
             if p["id"] == panel_id]
    assert texts == ["True", "False"]
    conns = client.sent("connect_by_name")
    assert any(c["sourceId"] == panel_id and c["targetParam"] == "RESET"
               for c in conns)
    # Pulse expire includes the panel source (F1) + final expire; no wait on
    # a v0.1 bridge.
    assert client.sent("expire_solution") == [
        {"ids": [panel_id, result["aggregation_id"]]},
        {"ids": [result["aggregation_id"]]},
    ]
    assert client.sent("wait_for_idle") == []


def test_run_aggregation_without_reset_input_skips_pulse(fake_registry):
    original = FAKE_DESCRIPTORS["stochastic aggregation"]
    without_reset = dict(original)
    without_reset["inputs"] = [p for p in original["inputs"]
                               if p["nickname"] != "RESET"]
    FAKE_DESCRIPTORS["stochastic aggregation"] = without_reset
    try:
        client = FakeV03Client()
        result = macros.run_aggregation(client, fake_registry, ["part-A"],
                                        "rules-1", 60)
    finally:
        FAKE_DESCRIPTORS["stochastic aggregation"] = original

    assert "reset_toggle_id" not in result
    assert "reset_panel_id" not in result
    assert client.sent("set_toggle") == []
    # Single final expire only.
    assert client.sent("expire_solution") == [
        {"ids": [result["aggregation_id"]]}]


# ── corpus corrections: PART_OUT vs AGGR, mode signatures, rule syntaxes ──

GRAPH_AGG_DESCRIPTOR = {
    "name": "Graph-Grammar Aggregation", "nickname": "GraphAggr",
    # Authoritative signature: NO N and NO SEED inputs.
    "inputs": [
        {"name": "PART", "nickname": "PART", "index": 0, "typeName": "Part"},
        {"name": "PREV", "nickname": "PREV", "index": 1, "typeName": "Part"},
        {"name": "RULES", "nickname": "RULES", "index": 2, "typeName": "Text"},
        {"name": "ID", "nickname": "ID", "index": 3, "typeName": "Text"},
        {"name": "RESET", "nickname": "RESET", "index": 4,
         "typeName": "Boolean"},
    ],
    "outputs": [
        {"name": "AGGR", "nickname": "AGGR", "index": 0,
         "typeName": "Aggregation"},
        {"name": "PART_OUT", "nickname": "PART_OUT", "index": 1,
         "typeName": "Part"},
    ],
}

FIELD_AGG_DESCRIPTOR = {
    "name": "Field-driven Aggregation", "nickname": "FieldAggregation",
    # Authoritative signature: N present, SEED replaced by FIELD.
    "inputs": [
        {"name": "PART", "nickname": "PART", "index": 0, "typeName": "Part"},
        {"name": "PREV", "nickname": "PREV", "index": 1, "typeName": "Part"},
        {"name": "N", "nickname": "N", "index": 2, "typeName": "Integer"},
        {"name": "RULES", "nickname": "RULES", "index": 3, "typeName": "Rule"},
        {"name": "FIELD", "nickname": "FIELD", "index": 4,
         "typeName": "Field"},
        {"name": "CAT", "nickname": "CAT", "index": 5, "typeName": "Text"},
        {"name": "MODE", "nickname": "MODE", "index": 6,
         "typeName": "Integer"},
        {"name": "GC", "nickname": "GC", "index": 7, "typeName": "Boolean"},
        {"name": "ID", "nickname": "ID", "index": 8, "typeName": "Text"},
        {"name": "RESET", "nickname": "RESET", "index": 9,
         "typeName": "Boolean"},
    ],
    "outputs": [
        {"name": "AGGR", "nickname": "AGGR", "index": 0,
         "typeName": "Aggregation"},
        {"name": "PART_OUT", "nickname": "PART_OUT", "index": 1,
         "typeName": "Part"},
    ],
}


@pytest.fixture
def registry_all_aggregations(fake_registry):
    for filename in ("Wasp_Graph-Grammar Aggregation.ghuser",
                     "Wasp_Field-driven Aggregation.ghuser"):
        (fake_registry.directory / filename).write_bytes(b"")
    fake_registry.scan()
    FAKE_DESCRIPTORS["graph-grammar aggregation"] = GRAPH_AGG_DESCRIPTOR
    FAKE_DESCRIPTORS["field-driven aggregation"] = FIELD_AGG_DESCRIPTOR
    yield fake_registry
    del FAKE_DESCRIPTORS["graph-grammar aggregation"]
    del FAKE_DESCRIPTORS["field-driven aggregation"]


def test_extraction_candidates_prefer_part_out(monkeypatch):
    # Knowledge base present (this repo ships server/knowledge): PART_OUT
    # first, and AGGR EXCLUDED from wiring candidates entirely (validator F3
    # — AGGR always connects, so its presence anywhere would mask a renamed
    # parts output).
    monkeypatch.setattr(macros, "_param_aliases_cache", None)
    candidates = macros.aggregation_parts_out_candidates()
    assert candidates[0] == "PART_OUT"
    assert "AGGR" not in candidates

    # Knowledge base missing: fallback list, same guarantees.
    monkeypatch.setattr(macros, "_param_aliases_cache", {})
    fallback = macros.aggregation_parts_out_candidates()
    assert fallback == list(macros.AGG_PARTS_OUT_FALLBACK)
    assert fallback[0] == "PART_OUT"
    assert "AGGR" not in fallback


def test_run_aggregation_reports_part_out_not_aggr(fake_registry):
    client = FakeV03Client()
    result = macros.run_aggregation(client, fake_registry, ["part-A"],
                                    "rules-1", 50)
    assert result["aggregation_output_param"] == "PART_OUT"


def test_get_aggregation_wires_extractor_from_part_out(fake_registry):
    client = FakeV03Client()
    result = macros.get_aggregation(client, fake_registry, AGG_ID,
                                    out="meshes")
    agg_conns = [c for c in client.sent("connect_by_name")
                 if c["sourceId"] == AGG_ID]
    assert agg_conns and agg_conns[0]["sourceParam"] == "PART_OUT"
    assert result["reused_extractor"] is False


def test_run_aggregation_graph_mode_skips_n_and_seed(registry_all_aggregations):
    client = FakeV03Client()
    result = macros.run_aggregation(client, registry_all_aggregations,
                                    ["part-A"], "graph-rules-panel-1",
                                    count=999, seed=42, mode="graph")
    # No N slider, no seed slider (the component has neither input).
    assert client.sent("set_slider") == []
    assert "count_slider_id" not in result
    assert "seed_slider_id" not in result
    conns = client.sent("connect_by_name")
    assert not any(c["targetParam"] in ("N", "ID") for c in conns)
    # The rules panel wires directly into RULES.
    assert any(c["sourceId"] == "graph-rules-panel-1"
               and c["targetParam"] == "RULES" for c in conns)
    # RESET pulse still runs.
    assert result["reset_toggle_id"]
    assert result["aggregation_output_param"] == "PART_OUT"


def test_run_aggregation_field_mode_requires_field(registry_all_aggregations):
    with pytest.raises(ValueError, match="field_component_id"):
        macros.run_aggregation(FakeV03Client(), registry_all_aggregations,
                               ["part-A"], "rules-1", 50, mode="field")


def test_run_aggregation_field_mode_wires_field_no_seed(
        registry_all_aggregations):
    client = FakeV03Client()
    result = macros.run_aggregation(client, registry_all_aggregations,
                                    ["part-A"], "rules-1", 50, seed=7,
                                    mode="field",
                                    field_component_id="field-1")
    # N slider yes, seed slider no (FIELD replaces SEED on this component).
    sliders = client.sent("set_slider")
    assert len(sliders) == 1 and sliders[0]["value"] == 50.0
    assert "seed_slider_id" not in result
    conns = client.sent("connect_by_name")
    assert any(c["sourceId"] == "field-1" and c["targetParam"] == "FIELD"
               for c in conns)
    assert result["field_source"] == "field-1"
    assert "field-1" not in result["all_ids"]  # not placed by the macro


def test_define_rules_rejects_non_rule_from_text_syntax(fake_registry):
    client = FakeV03Client()
    # Connection-type grammar (Rules Generator language).
    with pytest.raises(ValueError, match="Rules Generator"):
        macros.define_rules(client, fake_registry, "END>END", ["part-A"])
    # Graph-grammar rule (Graph-Grammar Aggregation language).
    with pytest.raises(ValueError, match="Graph-Grammar"):
        macros.define_rules(client, fake_registry,
                            "HEXA|0_HEXA|0>a_b", ["part-A"])
    # Nothing was placed before validation failed.
    assert client.sent("add_user_object") == []


# ── get_aggregation extractor reuse ────────────────────────────────────────

AGG_ID = "agg-1"
EXTRACTOR_ID = "ext-1"


def _canvas_with_extractor(extractor_name="Get Part Geometry"):
    return {
        "components": [
            {"id": AGG_ID, "name": "Stochastic Aggregation",
             "nickname": "StochAggr", "position": [400.0, 100.0],
             "runtimeMessages": []},
            {"id": EXTRACTOR_ID, "name": extractor_name,
             "nickname": extractor_name, "position": [650.0, 100.0],
             "runtimeMessages": []},
        ],
        "connections": [
            {"sourceId": AGG_ID, "sourceParam": "PART_OUT",
             "targetId": EXTRACTOR_ID, "targetParam": "PART"},
        ],
        "solutionState": "idle",
        "version": "0.3.0",
    }


def test_find_wired_extractor():
    client = FakeV03Client(canvas_state=_canvas_with_extractor())
    assert find_wired_extractor(client, AGG_ID,
                                ("get part geometry",)) == EXTRACTOR_ID
    assert find_wired_extractor(client, AGG_ID, ("deconstruct part",)) is None
    assert find_wired_extractor(client, "other-agg",
                                ("get part geometry",)) is None


def test_get_aggregation_reuses_wired_extractor(fake_registry):
    client = FakeV03Client(canvas_state=_canvas_with_extractor())
    result = macros.get_aggregation(client, fake_registry, AGG_ID,
                                    out="meshes")
    assert result["extractor_id"] == EXTRACTOR_ID
    assert result["reused_extractor"] is True
    assert client.sent("add_user_object") == []  # no duplicate placed
    assert client.sent("connect_by_name") == []
    # Reused extractor still recomputed before the read.
    assert client.sent("expire_solution") == [{"ids": [EXTRACTOR_ID]}]
    # Output param resolved by candidate (we never held its outputs list).
    assert result["output_param"] == "GEO"
    reads = client.sent("get_component_output")
    assert reads and reads[0]["id"] == EXTRACTOR_ID


def test_get_aggregation_places_extractor_when_none_wired(fake_registry):
    client = FakeV03Client()  # empty canvas
    result = macros.get_aggregation(client, fake_registry, AGG_ID,
                                    out="meshes")
    assert result["reused_extractor"] is False
    assert len(client.sent("add_user_object")) == 1
    conns = client.sent("connect_by_name")
    assert any(c["sourceId"] == AGG_ID for c in conns)


def test_get_aggregation_transforms_ignores_geometry_extractor(fake_registry):
    # A wired Get Part Geometry must NOT be reused for out="transforms".
    (fake_registry.directory / "Wasp_Deconstruct Part.ghuser").write_bytes(b"")
    fake_registry.scan()
    FAKE_DESCRIPTORS["deconstruct part"] = {
        "name": "Deconstruct Part", "nickname": "DePart",
        "inputs": [
            {"name": "Part", "nickname": "PART", "index": 0,
             "typeName": "Part"},
        ],
        "outputs": [
            {"name": "Transform", "nickname": "TR", "index": 0,
             "typeName": "Transform"},
        ],
    }
    try:
        client = FakeV03Client(canvas_state=_canvas_with_extractor())
        result = macros.get_aggregation(client, fake_registry, AGG_ID,
                                        out="transforms")
    finally:
        del FAKE_DESCRIPTORS["deconstruct part"]

    assert result["reused_extractor"] is False
    assert len(client.sent("add_user_object")) == 1
    assert result["extractor_id"] != EXTRACTOR_ID


def test_get_aggregation_cleans_up_placed_extractor_on_failure(fake_registry):
    class FailingReadClient(FakeV03Client):
        def call(self, command_type, parameters=None):
            if command_type == "get_component_output":
                self.commands.append((command_type, parameters or {}))
                raise BridgeError("bridge_command_failed", "boom")
            return super().call(command_type, parameters)

    client = FailingReadClient()
    with pytest.raises(BridgeError):
        macros.get_aggregation(client, fake_registry, AGG_ID, out="meshes")

    deletes = client.sent("delete_components")
    assert len(deletes) == 1
    assert len(deletes[0]["ids"]) == 1  # exactly the extractor we placed


def test_get_aggregation_reused_extractor_not_deleted_on_failure(fake_registry):
    class FailingReadClient(FakeV03Client):
        def call(self, command_type, parameters=None):
            if command_type == "get_component_output":
                self.commands.append((command_type, parameters or {}))
                raise BridgeError("bridge_command_failed", "boom")
            return super().call(command_type, parameters)

    client = FailingReadClient(canvas_state=_canvas_with_extractor())
    with pytest.raises(BridgeError):
        macros.get_aggregation(client, fake_registry, AGG_ID, out="meshes")
    assert client.sent("delete_components") == []  # pre-existing: keep it


# ── MCP tool layer (server.py) ─────────────────────────────────────────────


@pytest.fixture
def server_v03(monkeypatch, fake_registry):
    import server
    client = FakeV03Client()
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_registry", fake_registry)
    # gh_wait_idle uses a dedicated client (validator F6); route it to the
    # same fake so tests observe the wait_for_idle calls.
    monkeypatch.setattr(server, "_make_wait_client", lambda: client)
    return server, client


def test_gh_wait_idle_wire_shape(server_v03):
    server, client = server_v03
    out = server.gh_wait_idle()
    assert out == {"success": True, "result": {"idle": True, "waitedMs": 7}}
    assert client.sent("wait_for_idle") == [{"timeoutMs": 30000}]

    server.gh_wait_idle(timeout_ms=90000)
    assert client.sent("wait_for_idle")[1] == {"timeoutMs": 90000}


def test_gh_list_component_types_wire_shape(server_v03):
    server, client = server_v03
    out = server.gh_list_component_types(filter="mesh", category="Mesh",
                                         limit=25)
    assert out["success"] is True
    assert out["result"]["total"] == 1
    assert client.sent("list_component_types") == [
        {"filter": "mesh", "category": "Mesh", "limit": 25}]

    server.gh_list_component_types()
    assert client.sent("list_component_types")[1] == {"limit": 100}


def test_gh_component_schema_wire_shape(server_v03):
    server, client = server_v03
    out = server.gh_component_schema("Mesh Box")
    assert out["success"] is True
    assert out["result"]["name"] == "Mesh Box"
    assert out["result"]["inputs"][1]["defaultValue"] == 10
    assert client.sent("get_component_schema") == [{"name": "Mesh Box"}]


def test_gh_connect_params_truly_optional(server_v03):
    server, client = server_v03
    out = server.gh_connect("src-1", "tgt-1", target_param="PART",
                            source_index=0)
    assert out["success"] is True
    sent = client.sent("connect_by_name")[0]
    assert sent["sourceParam"] is None
    assert sent["targetParam"] == "PART"
    assert sent["sourceIndex"] == 0
    # Literal "null"/"none" strings behave like omission (backlog #1).
    server.gh_connect("src-1", "tgt-1", source_param="null",
                      target_param="None", source_index=0, target_index=0)
    sent = client.sent("connect_by_name")[1]
    assert sent["sourceParam"] is None
    assert sent["targetParam"] is None


def test_low_level_solve_passthrough(server_v03):
    server, client = server_v03
    server.gh_add_component("Panel", 0, 0)
    assert "solve" not in client.sent("add_component")[0]
    server.gh_add_component("Panel", 0, 0, solve=False)
    assert client.sent("add_component")[1]["solve"] is False
    server.gh_connect("a", "b", source_index=0, target_index=0, solve=False)
    assert client.sent("connect_by_name")[0]["solve"] is False
    server.gh_set_slider("s", 5.0, solve=False)
    assert client.sent("set_slider")[0]["solve"] is False
    server.gh_set_toggle("t", True, solve=False)
    assert client.sent("set_toggle")[0]["solve"] is False


def test_gh_set_panel_split_lines_passthrough(server_v03):
    server, client = server_v03
    server.gh_set_panel("p", "a\nb")
    assert "split_lines" not in client.sent("set_panel")[0]  # bridge default
    server.gh_set_panel("p", "a\nb", split_lines=False)
    assert client.sent("set_panel")[1]["split_lines"] is False
    server.gh_set_panel("p", "a\nb", split_lines=True, solve=False)
    assert client.sent("set_panel")[2]["split_lines"] is True
    assert client.sent("set_panel")[2]["solve"] is False


# ── JSON-string tolerance for every list/dict tool param ──────────────────


def test_gh_set_geometry_ref_accepts_json_string(server_v03):
    server, client = server_v03
    out = server.gh_set_geometry_ref("comp-1", '["g-1", "g-2"]')
    assert out["success"] is True
    assert client.sent("set_geometry_ref")[0]["objectIds"] == ["g-1", "g-2"]


def test_gh_set_geometry_ref_rejects_bad_string(server_v03):
    server, client = server_v03
    out = server.gh_set_geometry_ref("comp-1", "not json at all")
    assert out["success"] is False
    assert out["error"] == "invalid_arguments"
    assert client.sent("set_geometry_ref") == []  # bridge never called


def test_gh_set_plane_values_accepts_json_string(server_v03):
    server, client = server_v03
    out = server.gh_set_plane_values("comp-1", json.dumps([PLANE_DICT]))
    assert out["success"] is True
    sent = client.sent("set_plane_values")
    assert sent[0]["planes"] == macros.normalize_planes([PLANE_DICT])


def test_gh_delete_accepts_json_string(server_v03):
    server, client = server_v03
    out = server.gh_delete('["a", "b"]')
    assert out["success"] is True
    assert client.sent("delete_components") == [{"ids": ["a", "b"]}]


def test_gh_expire_accepts_json_string_and_null_forms(server_v03):
    server, client = server_v03
    server.gh_expire('["a"]')
    assert client.sent("expire_solution")[0] == {"ids": ["a"]}
    server.gh_expire("null")
    assert client.sent("expire_solution")[1] == {}  # treated as omitted
    server.gh_expire(None)
    assert client.sent("expire_solution")[2] == {}
    out = server.gh_expire("{bad json")
    assert out["error"] == "invalid_arguments"


def test_create_wasp_part_accepts_json_strings(server_v03, registry_with_conn):
    import server as server_module
    server, client = server_v03
    # server_v03 monkeypatched _registry to fake_registry; swap in the one
    # that also has Connection From Plane.
    server_module._registry = registry_with_conn
    out = server.create_wasp_part(
        "HEX",
        geometry_object_ids='["rhino-1"]',
        connection_planes=json.dumps([PLANE_DICT, PLANE_FLAT]),
    )
    assert out["success"] is True
    georefs = client.sent("set_geometry_ref")
    assert georefs[0]["objectIds"] == ["rhino-1"]

    bad = server.create_wasp_part("HEX", geometry_object_ids="oops")
    assert bad["error"] == "invalid_arguments"


def test_define_rules_accepts_json_string(server_v03):
    server, client = server_v03
    out = server.define_rules("P|1_P|0", parts_component_ids='["part-A"]')
    assert out["success"] is True
    conns = client.sent("connect_by_name")
    assert any(c["sourceId"] == "part-A" for c in conns)

    bad = server.define_rules("P|1_P|0", parts_component_ids="[not json")
    assert bad["error"] == "invalid_arguments"


def test_run_aggregation_accepts_json_string(server_v03):
    server, client = server_v03
    out = server.run_aggregation('["part-A", "part-B"]', "rules-1", 40)
    assert out["success"] is True
    conns = client.sent("connect_by_name")
    assert {c["sourceId"] for c in conns if c["targetParam"] == "PART"} == \
        {"part-A", "part-B"}


# ── docstring regression (backlog #4) ──────────────────────────────────────


def test_define_rules_docstring_uses_real_wasp_syntax():
    import server
    doc = server.define_rules.__doc__
    assert "P|1_P|0" in doc
    assert "PART1|0>PART2|1" not in doc  # the old, wrong example
