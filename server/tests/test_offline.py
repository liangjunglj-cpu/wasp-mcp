"""Offline tests: transport error handling + macro param matching.

No Grasshopper required. The fake bridge servers are plain sockets; the
fake client records commands so macro wiring logic can be asserted.
"""

import json
import socket
import threading

import pytest

import macros
from gh_client import BridgeError, GHClient, bridge_port
from macros import (
    connect_with_candidates,
    match_param,
    param_ref,
    require_param,
)
from registry import WaspRegistry


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ── transport ──────────────────────────────────────────────────────────────


def test_bridge_unreachable_is_typed():
    client = GHClient(port=_free_port(), connect_timeout=1.0)
    with pytest.raises(BridgeError) as excinfo:
        client.send_raw("get_canvas_state")
    err = excinfo.value
    assert err.code == "bridge_unreachable"
    assert err.hint and "Grasshopper" in err.hint
    assert "WaspMCP" in err.hint
    payload = err.to_dict()
    assert payload["success"] is False
    assert payload["error"] == "bridge_unreachable"


def test_port_env_override(monkeypatch):
    monkeypatch.setenv("WASP_MCP_PORT", "9123")
    assert bridge_port() == 9123
    assert GHClient().port == 9123
    monkeypatch.delenv("WASP_MCP_PORT")
    assert bridge_port() == 8090


def test_port_env_invalid(monkeypatch):
    monkeypatch.setenv("WASP_MCP_PORT", "not-a-port")
    with pytest.raises(BridgeError) as excinfo:
        bridge_port()
    assert excinfo.value.code == "bridge_protocol"


def _serve_once(response_bytes: bytes, close_after: bool = True) -> int:
    """One-shot fake bridge on a private port; returns the port."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def run():
        conn, _ = server.accept()
        conn.recv(65536)  # consume the request
        conn.sendall(response_bytes)
        if close_after:
            conn.close()
        else:
            # Hold the connection open; client must return on complete JSON.
            threading.Event().wait(2.0)
            conn.close()
        server.close()

    threading.Thread(target=run, daemon=True).start()
    return port


def test_reads_complete_json_without_close():
    body = json.dumps({"success": True, "result": {"ok": 1}}) + "\n"
    port = _serve_once(body.encode("utf-8"), close_after=False)
    client = GHClient(port=port, read_timeout=5.0)
    assert client.call("get_canvas_state") == {"ok": 1}


def test_reads_until_close_without_newline():
    body = json.dumps({"success": True, "result": {"ok": 2}})  # no newline
    port = _serve_once(body.encode("utf-8"), close_after=True)
    client = GHClient(port=port, read_timeout=5.0)
    assert client.call("get_canvas_state") == {"ok": 2}


def test_bridge_failure_envelope_raises_command_failed():
    body = json.dumps({"success": False, "error": "solution_running"}) + "\n"
    port = _serve_once(body.encode("utf-8"))
    client = GHClient(port=port, read_timeout=5.0)
    with pytest.raises(BridgeError) as excinfo:
        client.call("get_component_output", {"id": "x", "param": "GEO"})
    assert excinfo.value.code == "bridge_command_failed"
    assert "solution_running" in excinfo.value.message


def test_utf8_bom_response_parses():
    body = b"\xef\xbb\xbf" + json.dumps({"success": True, "result": {}}).encode() + b"\n"
    port = _serve_once(body)
    client = GHClient(port=port, read_timeout=5.0)
    assert client.call("ping") == {}


# ── param matching ─────────────────────────────────────────────────────────

STOCHASTIC_INPUTS = [
    {"name": "Parts", "nickname": "PART", "index": 0, "typeName": "Part"},
    {"name": "Rules", "nickname": "RULES", "index": 1, "typeName": "Rule"},
    {"name": "Number of Parts", "nickname": "N", "index": 2, "typeName": "Integer"},
    {"name": "Random Seed", "nickname": "SEED", "index": 3, "typeName": "Integer"},
    {"name": "Aggregation Mode", "nickname": "MODE", "index": 4, "typeName": "Integer"},
    {"name": "Global Constraints", "nickname": "GC", "index": 5, "typeName": "Constraint"},
    {"name": "Parts Catalog", "nickname": "CAT", "index": 6, "typeName": "Catalog"},
    {"name": "Reset", "nickname": "RESET", "index": 7, "typeName": "Boolean"},
]


def test_match_param_by_nickname_case_insensitive():
    assert match_param(STOCHASTIC_INPUTS, ["part"])["index"] == 0
    assert match_param(STOCHASTIC_INPUTS, ["RULES"])["index"] == 1
    assert match_param(STOCHASTIC_INPUTS, ["n"])["index"] == 2


def test_match_param_by_full_name():
    assert match_param(STOCHASTIC_INPUTS, ["random seed"])["index"] == 3


def test_match_param_candidate_priority():
    # First candidate that hits wins, even if a later one also matches.
    hit = match_param(STOCHASTIC_INPUTS, ["SEED", "PART"])
    assert hit["index"] == 3


def test_match_param_prefix_fallback():
    # Candidate "PARTS" vs nickname "PART": prefix fallback catches it.
    assert match_param(STOCHASTIC_INPUTS, ["PARTS"])["index"] == 0


def test_match_param_no_match_and_empty():
    assert match_param(STOCHASTIC_INPUTS, ["FIELD"]) is None
    assert match_param([], ["PART"]) is None
    assert match_param(None, ["PART"]) is None


def test_require_param_raises_typed_error():
    with pytest.raises(BridgeError) as excinfo:
        require_param(STOCHASTIC_INPUTS, ["FIELD"], "field input")
    assert excinfo.value.code == "param_not_found"
    assert "field input" in excinfo.value.message


def test_param_ref_prefers_nickname():
    assert param_ref({"name": "Parts", "nickname": "PART"}) == "PART"
    assert param_ref({"name": "Parts"}) == "Parts"


# ── fake bridge client for macro logic ─────────────────────────────────────


FAKE_DESCRIPTORS = {
    "basic part": {
        "name": "Basic Part", "nickname": "Basic Part",
        "inputs": [
            {"name": "Name", "nickname": "NAME", "index": 0, "typeName": "Text"},
            {"name": "Geometry", "nickname": "GEO", "index": 1, "typeName": "Mesh"},
            {"name": "Connections", "nickname": "CONN", "index": 2, "typeName": "Connection"},
        ],
        "outputs": [
            {"name": "Part", "nickname": "PART", "index": 0, "typeName": "Part"},
        ],
    },
    "rule from text": {
        "name": "Rule From Text", "nickname": "Rule Txt",
        "inputs": [
            {"name": "Rules Text", "nickname": "R", "index": 0, "typeName": "Text"},
            {"name": "Parts", "nickname": "PART", "index": 1, "typeName": "Part"},
        ],
        "outputs": [
            {"name": "Rules", "nickname": "R", "index": 0, "typeName": "Rule"},
        ],
    },
    "stochastic aggregation": {
        "name": "Stochastic Aggregation", "nickname": "StochAggr",
        "inputs": STOCHASTIC_INPUTS,
        # Authoritative output order (Wasp component repository): AGGR (the
        # aggregation object) FIRST, then PART_OUT (the parts) — extraction
        # must bind PART_OUT, never AGGR.
        "outputs": [
            {"name": "AGGR", "nickname": "AGGR", "index": 0,
             "typeName": "Aggregation"},
            {"name": "PART_OUT", "nickname": "PART_OUT", "index": 1,
             "typeName": "Part"},
        ],
    },
    "get part geometry": {
        "name": "Get Part Geometry", "nickname": "PartGeo",
        "inputs": [
            {"name": "Parts", "nickname": "PART", "index": 0, "typeName": "Part"},
        ],
        "outputs": [
            {"name": "Geometry", "nickname": "GEO", "index": 0, "typeName": "Mesh"},
        ],
    },
}


class FakeClient:
    """Records bridge commands; answers add_user_object from descriptors.

    Models a v0.1 bridge: the v0.2 commands (set_plane_values, set_toggle,
    delete_components) are rejected as unknown, so v0.1-era macro tests keep
    exercising the fallback paths. tests/test_v02.py subclasses this with
    v0.2-capable fakes.
    """

    V02_COMMANDS = ("set_plane_values", "set_toggle", "delete_components")

    def __init__(self, valid_connections=None):
        self.commands = []
        self._counter = 0
        # Optional set of (sourceParam, targetParam) pairs that "exist";
        # None means every connection succeeds.
        self.valid_connections = valid_connections

    def _new_id(self, prefix):
        self._counter += 1
        return f"{prefix}-{self._counter}"

    def call(self, command_type, parameters=None):
        parameters = parameters or {}
        self.commands.append((command_type, parameters))
        if command_type in self.V02_COMMANDS:
            raise BridgeError("bridge_command_failed",
                              f"Unknown command type '{command_type}'")
        if command_type == "add_user_object":
            path = parameters["path"].lower()
            for marker, desc in FAKE_DESCRIPTORS.items():
                if marker in path:
                    return {"id": self._new_id(marker.split()[0]), **desc}
            raise AssertionError(f"unexpected user object: {path}")
        if command_type == "add_component":
            return {"id": self._new_id(parameters["type"].lower().replace(" ", "-"))}
        if command_type == "connect_by_name":
            if self.valid_connections is not None:
                pair = (parameters.get("sourceParam"), parameters.get("targetParam"))
                if pair not in self.valid_connections:
                    raise BridgeError("bridge_command_failed",
                                      f"no matching params {pair}")
            return {"connected": True}
        if command_type == "get_component_output":
            return {"dataType": "Mesh", "branchCount": 1,
                    "items": [{"vertices": [], "faces": []}]}
        return {}

    def sent(self, command_type):
        return [p for t, p in self.commands if t == command_type]


@pytest.fixture
def fake_registry(tmp_path):
    for n in ("Wasp_Basic Part.ghuser", "Wasp_Rule From Text.ghuser",
              "Wasp_Stochastic Aggregation.ghuser",
              "Wasp_Get Part Geometry.ghuser"):
        (tmp_path / n).write_bytes(b"")
    reg = WaspRegistry(tmp_path)
    reg.scan()
    return reg


def test_connect_with_candidates_tries_in_order():
    client = FakeClient(valid_connections={("R", "RULES")})
    used = connect_with_candidates(client, "src-1", ["RULES", "RULE", "R"],
                                   "tgt-1", "RULES")
    assert used == "R"
    assert len(client.sent("connect_by_name")) == 3  # two failures + success


def test_connect_with_candidates_exhaustion():
    client = FakeClient(valid_connections=set())
    with pytest.raises(BridgeError) as excinfo:
        connect_with_candidates(client, "src-1", ["A", "B"], "tgt-1", "X")
    assert excinfo.value.code == "param_not_found"


def test_run_aggregation_wiring(fake_registry):
    client = FakeClient()
    result = macros.run_aggregation(
        client, fake_registry,
        part_ids=["part-A", "part-B"], rule_id="rules-1",
        count=120, seed=7, mode="stochastic", x=400, y=100,
    )
    assert result["aggregation_id"].startswith("stochastic")
    # PART_OUT (the parts output), never AGGR (the aggregation object).
    assert result["aggregation_output_param"] == "PART_OUT"

    conns = client.sent("connect_by_name")
    # Two parts wired to PART, rules wired to RULES (nicknames matched from
    # the descriptor, not hardcoded indices).
    part_conns = [c for c in conns if c["targetParam"] == "PART"]
    assert {c["sourceId"] for c in part_conns} == {"part-A", "part-B"}
    assert any(c["targetParam"] == "RULES" and c["sourceId"] == "rules-1"
               for c in conns)
    # N slider created, set to count, wired to N.
    sliders = client.sent("set_slider")
    assert any(s["value"] == 120.0 for s in sliders)
    assert any(s["value"] == 7.0 for s in sliders)  # seed slider
    assert any(c["targetParam"] == "N" for c in conns)
    assert any(c["targetParam"] == "SEED" for c in conns)
    # RESET pulse expiries include the SOURCE (toggle/panel) so its stale
    # VolatileData can't be re-read (validator F1); the aggregation id is
    # always present.
    first_expire = client.sent("expire_solution")[0]["ids"]
    assert result["aggregation_id"] in first_expire
    if len(first_expire) > 1:
        source_ids = {result.get("reset_toggle_id"),
                      result.get("reset_panel_id")}
        assert set(first_expire) - {result["aggregation_id"]} <= source_ids


def test_run_aggregation_rejects_unknown_mode(fake_registry):
    with pytest.raises(BridgeError) as excinfo:
        macros.run_aggregation(FakeClient(), fake_registry,
                               ["p"], "r", 10, mode="quantum")
    assert excinfo.value.code == "invalid_mode"


# ── global constraints (MODE gating — wasp core: mode 2/3 computes GC) ────


def test_run_aggregation_global_constraints_wire_gc_and_mode(fake_registry):
    client = FakeClient()
    result = macros.run_aggregation(
        client, fake_registry, ["part-A"], "rules-1", 50,
        mode="stochastic",
        global_constraint_ids=["mesh-const-1", "plane-const-1"],
    )
    conns = client.sent("connect_by_name")
    # Every constraint id wired into GC (first output candidate is GC).
    gc_conns = [c for c in conns if c["targetParam"] == "GC"]
    assert {c["sourceId"] for c in gc_conns} == {"mesh-const-1",
                                                 "plane-const-1"}
    # MODE slider placed, set to 2 (constraints are IGNORED at mode 0),
    # range covering the source-defined modes 0..3.
    assert any(c["targetParam"] == "MODE" for c in conns)
    mode_sets = [s for s in client.sent("set_slider")
                 if s["id"] == result["mode_slider_id"]]
    assert mode_sets and mode_sets[0]["value"] == 2.0
    assert mode_sets[0]["max"] == 3.0
    assert result["global_constraint_sources"] == ["mesh-const-1",
                                                   "plane-const-1"]
    # The slider we placed belongs to the macro's id manifest.
    assert result["mode_slider_id"] in result["all_ids"]


def test_run_aggregation_no_constraints_no_mode_slider(fake_registry):
    client = FakeClient()
    result = macros.run_aggregation(client, fake_registry,
                                    ["part-A"], "rules-1", 50)
    assert "mode_slider_id" not in result
    assert not any(c["targetParam"] == "MODE"
                   for c in client.sent("connect_by_name"))


def test_run_aggregation_graph_mode_rejects_global_constraints(fake_registry):
    with pytest.raises(ValueError) as excinfo:
        macros.run_aggregation(FakeClient(), fake_registry,
                               ["p"], "r", 10, mode="graph",
                               global_constraint_ids=["c-1"])
    assert "graph" in str(excinfo.value)


# ── parts catalog (stock/proportion control via the CAT input) ────────────


def test_run_aggregation_wires_catalog_into_cat(fake_registry):
    client = FakeClient()
    result = macros.run_aggregation(
        client, fake_registry, ["part-A"], "rules-1", 50,
        catalog_component_id="catalog-1",
    )
    conns = client.sent("connect_by_name")
    assert any(c["targetParam"] == "CAT" and c["sourceId"] == "catalog-1"
               for c in conns)
    assert result["catalog_source"] == "catalog-1"


def test_run_aggregation_no_catalog_no_cat_wire(fake_registry):
    client = FakeClient()
    result = macros.run_aggregation(client, fake_registry,
                                    ["part-A"], "rules-1", 50)
    assert "catalog_source" not in result
    assert not any(c["targetParam"] == "CAT"
                   for c in client.sent("connect_by_name"))


def test_run_aggregation_graph_mode_rejects_catalog(fake_registry):
    with pytest.raises(ValueError) as excinfo:
        macros.run_aggregation(FakeClient(), fake_registry,
                               ["p"], "r", 10, mode="graph",
                               catalog_component_id="catalog-1")
    assert "CAT" in str(excinfo.value)


# ── rule-grammar lints (directional-rule + case-sensitivity traps) ─────────


def test_analyze_rule_grammar_warns_on_missing_inverse():
    warnings = macros.analyze_rule_grammar(["HEX|0_CUBE|1"])
    assert len(warnings) == 1
    assert "CUBE|1_HEX|0" in warnings[0]
    assert "directional" in warnings[0]


def test_analyze_rule_grammar_quiet_when_both_directions_present():
    assert macros.analyze_rule_grammar(["HEX|0_CUBE|1",
                                        "CUBE|1_HEX|0"]) == []


def test_analyze_rule_grammar_symmetric_self_rule_is_its_own_inverse():
    assert macros.analyze_rule_grammar(["P|0_P|0"]) == []


def test_analyze_rule_grammar_warns_on_case_collision():
    warnings = macros.analyze_rule_grammar(["HEX|0_hex|1", "hex|1_HEX|0"])
    assert len(warnings) == 1
    assert "case-sensitive" in warnings[0]


def test_analyze_rule_grammar_ignores_unparseable_lines():
    # Malformed lines are Wasp's to reject; the lint stays quiet.
    assert macros.analyze_rule_grammar(["not a rule", ""]) == []


def test_define_rules_surfaces_warnings(fake_registry):
    client = FakeClient()
    result = macros.define_rules(client, fake_registry,
                                 "HEX|0_HEX|1", ["part-A"])
    assert any("HEX|1_HEX|0" in w for w in result["warnings"])


def test_define_rules_no_warnings_key_when_clean(fake_registry):
    result = macros.define_rules(FakeClient(), fake_registry,
                                 "HEX|0_HEX|1\nHEX|1_HEX|0", ["part-A"])
    assert "warnings" not in result


def test_create_wasp_part_with_planes(fake_registry):
    # Need connection_from_plane in the registry for this path.
    (fake_registry.directory / "Wasp_Connection From Plane.ghuser").write_bytes(b"")
    fake_registry.scan()
    FAKE_DESCRIPTORS["connection from plane"] = {
        "name": "Connection From Plane", "nickname": "ConnPln",
        "inputs": [
            {"name": "Planes", "nickname": "PLN", "index": 0, "typeName": "Plane"},
        ],
        "outputs": [
            {"name": "Connections", "nickname": "CONN", "index": 0, "typeName": "Connection"},
        ],
    }
    try:
        client = FakeClient()
        result = macros.create_wasp_part(
            client, fake_registry, "HEX",
            geometry_object_ids=["rhino-guid-1"],
            connection_planes=[
                {"origin": [0, 0, 0], "xAxis": [1, 0, 0], "yAxis": [0, 1, 0]},
                [5, 0, 0, 0, 1, 0, 0, 0, 1],  # flat 9-float form
            ],
            x=0, y=0,
        )
    finally:
        del FAKE_DESCRIPTORS["connection from plane"]

    assert result["part_output_param"] == "PART"
    # Geometry referenced into the Mesh param.
    georefs = client.sent("set_geometry_ref")
    assert georefs[0]["objectIds"] == ["rhino-guid-1"]
    # Name panel + three plane panels (origins, x-axes, y-axes).
    panels = client.sent("set_panel")
    assert panels[0]["text"] == "HEX"
    assert len(panels) == 4
    origins_panel = panels[1]["text"].splitlines()
    assert len(origins_panel) == 2  # one line per plane
    # Part GEO and CONN inputs wired by matched nickname.
    conns = client.sent("connect_by_name")
    assert any(c["targetParam"] == "GEO" for c in conns)
    assert any(c["targetParam"] == "CONN" for c in conns)


def test_define_rules_wiring_v01_fans_out_panels(fake_registry):
    # v0.1 bridge (FakeClient): panels emit their text as ONE item, so a
    # multi-rule grammar becomes one panel per rule, all wired into R.
    client = FakeClient()
    result = macros.define_rules(
        client, fake_registry, "P|1_P|0\nP|2_P|0",
        parts_component_ids=["part-A"], x=0, y=200,
    )
    assert result["rules_output_param"] == "R"
    panels = client.sent("set_panel")
    assert [p["text"] for p in panels] == ["P|1_P|0", "P|2_P|0"]
    assert len(result["rule_panel_ids"]) == 2
    assert set(result["rule_panel_ids"]) <= set(result["all_ids"])
    conns = client.sent("connect_by_name")
    # Each rule panel wired to the R text input by index-0 source.
    panel_conns = [c for c in conns
                   if c["targetParam"] == "R" and c["sourceIndex"] == 0]
    assert {c["sourceId"] for c in panel_conns} == set(result["rule_panel_ids"])
    # Part component wired into the rules PART input.
    assert any(c["sourceId"] == "part-A" and c["targetParam"] == "PART"
               for c in conns)


def test_get_aggregation_meshes(fake_registry):
    client = FakeClient()
    result = macros.get_aggregation(client, fake_registry, "agg-1",
                                    out="meshes")
    assert result["output_param"] == "GEO"
    assert result["data"]["dataType"] == "Mesh"
    reads = client.sent("get_component_output")
    assert reads[0]["param"] == "GEO"
    assert reads[0]["id"] == result["extractor_id"]


def test_get_aggregation_bake(fake_registry):
    client = FakeClient()
    result = macros.get_aggregation(client, fake_registry, "agg-1",
                                    out="bake", layer="WASP::TEST")
    bakes = client.sent("bake_component_output")
    assert bakes[0]["layer"] == "WASP::TEST"
    assert bakes[0]["param"] == "GEO"
    assert "bakedIds" in result
