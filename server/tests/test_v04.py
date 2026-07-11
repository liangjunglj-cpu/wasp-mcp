"""Offline tests for the v0.4 surface: canvas organization.

Covers the three new tools (gh_group / gh_scribble / gh_set_nickname wire
shapes + JSON-string tolerance), the organize_stage helper, the
stage_explainers knowledge file, and the macro Generation conventions
(PROTOCOL.md v0.4): stage groups, INPUTS group, explainer scribbles and
role nicknames — applied on a v0.4 bridge, skipped SILENTLY on v0.1-v0.3.

No Grasshopper (and no TCP) required: FakeV04Client implements add_group /
add_scribble / set_nickname in-memory on top of the v0.3 fake.
"""

import json

import pytest

import macros
from gh_client import BridgeError
from macros import (
    ORG_INPUTS_COLOR,
    ORG_SCRIBBLE_SIZE,
    ORG_STAGE_COLOR,
    STAGE_AGGREGATION,
    STAGE_INPUTS_AGGREGATION,
    STAGE_OUTPUT,
    STAGE_PART_DEFINITION,
    STAGE_RULES,
    load_stage_explainers,
    organize_stage,
    supports_organization,
)
from test_offline import (  # noqa: F401  (fake_registry is a fixture)
    FAKE_DESCRIPTORS,
    FakeClient,
    fake_registry,
)
from test_v02 import (  # noqa: F401  (registry_with_conn is a fixture)
    PLANE_DICT,
    FakeV01Client,
    FakeV02Client,
    registry_with_conn,
)
from test_v03 import (  # noqa: F401  (registry_all_aggregations is a fixture)
    AGG_ID,
    EXTRACTOR_ID,
    FakeV03Client,
    _canvas_with_extractor,
    registry_all_aggregations,
)

EXPLAINERS = load_stage_explainers()


class FakeV04Client(FakeV03Client):
    """FakeClient that also speaks the v0.4 commands and reports 0.4.0."""

    def __init__(self, canvas_state=None, **kwargs):
        if canvas_state is None:
            canvas_state = {"components": [], "connections": [],
                            "solutionState": "idle", "version": "0.4.0"}
        super().__init__(canvas_state=canvas_state, **kwargs)
        self.nicknames = {}

    def call(self, command_type, parameters=None):
        parameters = parameters or {}
        if command_type == "add_group":
            self.commands.append((command_type, parameters))
            ids = parameters.get("ids") or []
            return {"groupId": self._new_id("group"),
                    "name": parameters.get("name"),
                    "grouped": len(ids), "colorOrder": "RGBA",
                    "results": [{"id": i, "grouped": True} for i in ids]}
        if command_type == "add_scribble":
            self.commands.append((command_type, parameters))
            return {"id": self._new_id("scribble"),
                    "text": parameters.get("text"),
                    "size": parameters.get("size", 14.0)}
        if command_type == "set_nickname":
            self.commands.append((command_type, parameters))
            self.nicknames[parameters["id"]] = parameters["nickname"]
            return {"id": parameters["id"],
                    "nickname": parameters["nickname"]}
        return super().call(command_type, parameters)


# ── capability gating ──────────────────────────────────────────────────────


def test_supports_organization_per_generation():
    assert supports_organization(FakeV04Client()) is True
    assert supports_organization(FakeV03Client()) is False
    assert supports_organization(FakeV02Client()) is False
    assert supports_organization(FakeClient()) is False


ORG_COMMANDS = ("add_group", "add_scribble", "set_nickname")


def _assert_no_organization(client):
    for cmd in ORG_COMMANDS:
        assert client.sent(cmd) == [], f"{cmd} sent on a pre-v0.4 bridge"


# ── stage_explainers knowledge file ────────────────────────────────────────


REQUIRED_EXPLAINER_KEYS = {
    "part_definition", "rules",
    "aggregation_stochastic", "aggregation_field", "aggregation_graph",
    "inputs", "output_geometry", "output_transforms",
}


def test_stage_explainers_file_has_all_macro_keys():
    assert REQUIRED_EXPLAINER_KEYS <= set(EXPLAINERS)
    for key in REQUIRED_EXPLAINER_KEYS:
        text = EXPLAINERS[key]
        assert text.strip(), f"explainer {key} is empty"
        # 1-3 lines, canvas-note sized (generation-principles section 2).
        assert len(text) < 400, f"explainer {key} too long for a scribble"


def test_load_stage_explainers_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(macros, "_stage_explainers_cache", None)
    monkeypatch.setattr(macros, "_KNOWLEDGE_DIR", tmp_path)
    assert load_stage_explainers() == {}
    monkeypatch.setattr(macros, "_stage_explainers_cache", None)


# ── organize_stage helper ──────────────────────────────────────────────────


def test_organize_stage_skipped_on_pre_v04_bridges():
    for client in (FakeClient(), FakeV02Client(), FakeV03Client()):
        result = organize_stage(client, ["a", "b"], "STAGE", 0, 0,
                                explainer_key="rules",
                                nicknames={"a": "thing"})
        assert result is None
        _assert_no_organization(client)


def test_organize_stage_v04_groups_scribbles_and_nicknames():
    client = FakeV04Client()
    result = organize_stage(client, ["a", "b", None, ""], "MY STAGE",
                            x=100, y=-50, explainer_key="rules",
                            nicknames={"a": "part count"})
    groups = client.sent("add_group")
    assert groups == [{"ids": ["a", "b"], "name": "MY STAGE",
                       "color": ORG_STAGE_COLOR}]
    scribbles = client.sent("add_scribble")
    assert len(scribbles) == 1
    # Text is wrapped to a column and the block is lifted fully above the
    # anchor so long explainers never overlap the group's components.
    wrapped = macros.wrap_scribble_text(EXPLAINERS["rules"])
    assert scribbles[0]["text"] == wrapped
    assert max(len(l) for l in wrapped.split("\n")) <= macros.SCRIBBLE_WRAP_WIDTH
    assert scribbles[0]["x"] == 100
    assert scribbles[0]["y"] == -50 - macros.scribble_block_height(wrapped)
    assert scribbles[0]["size"] == ORG_SCRIBBLE_SIZE
    assert client.sent("set_nickname") == [{"id": "a",
                                            "nickname": "part count"}]
    assert result["group_id"]
    assert result["group_name"] == "MY STAGE"
    assert result["scribble_id"]
    assert result["nicknames"] == {"a": "part count"}
    # Visual-only commands: never a solve flag.
    for cmd in ORG_COMMANDS:
        for params in client.sent(cmd):
            assert "solve" not in params


def test_organize_stage_custom_color_and_no_explainer():
    client = FakeV04Client()
    result = organize_stage(client, ["a"], "INPUTS", 0, 0,
                            color=ORG_INPUTS_COLOR)
    assert client.sent("add_group")[0]["color"] == ORG_INPUTS_COLOR
    assert client.sent("add_scribble") == []
    assert "scribble_id" not in result


def test_organize_stage_unknown_explainer_key_skips_scribble():
    client = FakeV04Client()
    result = organize_stage(client, ["a"], "X", 0, 0,
                            explainer_key="no_such_stage")
    assert client.sent("add_scribble") == []
    assert "scribble_id" not in result


def test_organize_stage_empty_ids_is_noop():
    client = FakeV04Client()
    assert organize_stage(client, [], "X", 0, 0) is None
    assert organize_stage(client, [None, ""], "X", 0, 0) is None
    _assert_no_organization(client)


# ── macro organization: create_wasp_part ───────────────────────────────────


def test_create_wasp_part_v04_organizes(fake_registry):
    client = FakeV04Client()
    result = macros.create_wasp_part(client, fake_registry, "HEX",
                                     geometry_object_ids=["rhino-1"],
                                     x=0, y=0)
    groups = client.sent("add_group")
    assert len(groups) == 1
    assert groups[0]["name"] == STAGE_PART_DEFINITION
    assert set(groups[0]["ids"]) == {result["part_id"],
                                     result["geometry_param_id"],
                                     result["name_panel_id"]}
    scribbles = client.sent("add_scribble")
    assert [s["text"] for s in scribbles] == [macros.wrap_scribble_text(EXPLAINERS["part_definition"])]
    assert client.nicknames[result["geometry_param_id"]] == "part geometry"
    assert client.nicknames[result["name_panel_id"]] == "part name"

    org = result["organization"]["stage"]
    assert org["group_id"] and org["scribble_id"]
    # Group/scribble ids are annotations, not workflow components.
    assert org["group_id"] not in result["all_ids"]
    assert org["scribble_id"] not in result["all_ids"]


def test_create_wasp_part_v04_with_planes_nicknames_plane_param(
        registry_with_conn):
    client = FakeV04Client()
    result = macros.create_wasp_part(client, registry_with_conn, "HEX",
                                     geometry_object_ids=["rhino-1"],
                                     connection_planes=[PLANE_DICT])
    # v0.4 bridge speaks v0.2: the Plane-param fast path ran and got named.
    assert client.nicknames[result["plane_param_id"]] == "connection planes"
    group_ids = set(client.sent("add_group")[0]["ids"])
    assert result["plane_param_id"] in group_ids
    assert result["connection_component_id"] in group_ids


def test_create_wasp_part_skips_organization_pre_v04(fake_registry):
    for client in (FakeClient(), FakeV03Client()):
        result = macros.create_wasp_part(client, fake_registry, "HEX",
                                         geometry_object_ids=["rhino-1"])
        _assert_no_organization(client)
        assert "organization" not in result


# ── macro organization: define_rules ───────────────────────────────────────


def test_define_rules_v04_organizes(fake_registry):
    client = FakeV04Client()
    result = macros.define_rules(client, fake_registry, "P|1_P|0\nP|0_P|1",
                                 ["part-A"], x=0, y=200)
    groups = client.sent("add_group")
    assert len(groups) == 1
    assert groups[0]["name"] == STAGE_RULES
    assert set(groups[0]["ids"]) == {result["rules_component_id"],
                                     result["grammar_panel_id"]}
    assert [s["text"] for s in client.sent("add_scribble")] == \
        [macros.wrap_scribble_text(EXPLAINERS["rules"])]
    # v0.4 >= v0.3: single split panel, nicknamed for its role.
    assert client.nicknames == {result["grammar_panel_id"]: "rule grammar"}
    assert result["organization"]["stage"]["group_name"] == STAGE_RULES


def test_define_rules_skips_organization_pre_v04(fake_registry):
    for client in (FakeClient(), FakeV03Client()):
        result = macros.define_rules(client, fake_registry, "P|1_P|0",
                                     ["part-A"])
        _assert_no_organization(client)
        assert "organization" not in result


# ── macro organization: run_aggregation ────────────────────────────────────


def test_run_aggregation_v04_stage_and_inputs_groups(fake_registry):
    client = FakeV04Client()
    result = macros.run_aggregation(client, fake_registry, ["part-A"],
                                    "rules-1", 50, seed=7, x=400, y=100)
    groups = {g["name"]: g for g in client.sent("add_group")}
    assert set(groups) == {STAGE_AGGREGATION, STAGE_INPUTS_AGGREGATION}

    # Solver alone in the stage group; every driver in the INPUTS group.
    assert groups[STAGE_AGGREGATION]["ids"] == [result["aggregation_id"]]
    assert set(groups[STAGE_INPUTS_AGGREGATION]["ids"]) == {
        result["count_slider_id"], result["seed_slider_id"],
        result["reset_toggle_id"]}
    assert groups[STAGE_INPUTS_AGGREGATION]["color"] == ORG_INPUTS_COLOR
    assert groups[STAGE_AGGREGATION]["color"] == ORG_STAGE_COLOR

    # Sliders nicknamed by role (PROTOCOL Generation conventions #1).
    assert client.nicknames[result["count_slider_id"]] == "part count"
    assert client.nicknames[result["seed_slider_id"]] == "random seed"
    assert client.nicknames[result["reset_toggle_id"]] == "reset"

    texts = [s["text"] for s in client.sent("add_scribble")]
    assert texts == [macros.wrap_scribble_text(EXPLAINERS["aggregation_stochastic"]),
                     macros.wrap_scribble_text(EXPLAINERS["inputs"])]

    org = result["organization"]
    assert org["stage"]["group_name"] == STAGE_AGGREGATION
    assert org["inputs"]["group_name"] == STAGE_INPUTS_AGGREGATION
    assert org["inputs"]["nicknames"] == {
        result["count_slider_id"]: "part count",
        result["seed_slider_id"]: "random seed",
        result["reset_toggle_id"]: "reset",
    }


def test_run_aggregation_v04_graph_mode_explainer_and_inputs(
        registry_all_aggregations):
    client = FakeV04Client()
    result = macros.run_aggregation(client, registry_all_aggregations,
                                    ["part-A"], "graph-rules-panel-1",
                                    count=999, seed=42, mode="graph")
    # Graph mode has no N/SEED sliders: only the reset toggle is a driver.
    groups = {g["name"]: g for g in client.sent("add_group")}
    assert groups[STAGE_INPUTS_AGGREGATION]["ids"] == \
        [result["reset_toggle_id"]]
    texts = [s["text"] for s in client.sent("add_scribble")]
    assert texts[0] == macros.wrap_scribble_text(EXPLAINERS["aggregation_graph"])


def test_run_aggregation_skips_organization_pre_v04(fake_registry):
    for client in (FakeClient(), FakeV03Client()):
        result = macros.run_aggregation(client, fake_registry, ["part-A"],
                                        "rules-1", 50, seed=3)
        _assert_no_organization(client)
        assert "organization" not in result


def test_run_aggregation_organization_failure_does_not_break_macro(
        fake_registry):
    class GroupFailClient(FakeV04Client):
        def call(self, command_type, parameters=None):
            if command_type == "add_group":
                self.commands.append((command_type, parameters or {}))
                raise BridgeError("bridge_command_failed", "boom")
            return super().call(command_type, parameters)

    client = GroupFailClient()
    result = macros.run_aggregation(client, fake_registry, ["part-A"],
                                    "rules-1", 50)
    # The workflow itself succeeded; the failures are reported, not raised.
    assert result["aggregation_id"]
    assert "boom" in result["organization"]["stage"]["error"]
    assert "boom" in result["organization"]["inputs"]["error"]


# ── macro organization: get_aggregation ────────────────────────────────────


def test_get_aggregation_v04_groups_new_extractor(fake_registry):
    client = FakeV04Client()
    result = macros.get_aggregation(client, fake_registry, AGG_ID,
                                    out="meshes", x=700, y=100)
    groups = client.sent("add_group")
    assert len(groups) == 1
    assert groups[0]["name"] == STAGE_OUTPUT
    assert groups[0]["ids"] == [result["extractor_id"]]
    assert [s["text"] for s in client.sent("add_scribble")] == \
        [macros.wrap_scribble_text(EXPLAINERS["output_geometry"])]
    assert result["organization"]["stage"]["group_name"] == STAGE_OUTPUT


def test_get_aggregation_v04_reused_extractor_not_regrouped(fake_registry):
    client = FakeV04Client(canvas_state=_canvas_with_extractor())
    result = macros.get_aggregation(client, fake_registry, AGG_ID,
                                    out="meshes")
    assert result["reused_extractor"] is True
    # Re-reading must not stack duplicate OUTPUT groups on every call.
    _assert_no_organization(client)
    assert "organization" not in result


def test_get_aggregation_skips_organization_pre_v04(fake_registry):
    for client in (FakeClient(), FakeV03Client()):
        result = macros.get_aggregation(client, fake_registry, AGG_ID,
                                        out="meshes")
        _assert_no_organization(client)
        assert "organization" not in result


# ── MCP tool layer (server.py) ─────────────────────────────────────────────


@pytest.fixture
def server_v04(monkeypatch, fake_registry):
    import server
    client = FakeV04Client()
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_registry", fake_registry)
    monkeypatch.setattr(server, "_make_wait_client", lambda: client)
    return server, client


def test_gh_group_wire_shape(server_v04):
    server, client = server_v04
    out = server.gh_group(["a", "b"], "AGGREGATION", color=[190, 220, 190, 120])
    assert out["success"] is True
    assert out["result"]["groupId"]
    assert out["result"]["colorOrder"] == "RGBA"
    assert client.sent("add_group") == [{
        "ids": ["a", "b"], "name": "AGGREGATION",
        "color": [190, 220, 190, 120]}]

    # Color optional: omitted from the wire entirely when None.
    server.gh_group(["a"], "X")
    assert "color" not in client.sent("add_group")[1]


def test_gh_group_accepts_json_strings(server_v04):
    server, client = server_v04
    out = server.gh_group('["a", "b"]', "X", color="[10, 20, 30]")
    assert out["success"] is True
    sent = client.sent("add_group")[0]
    assert sent["ids"] == ["a", "b"]
    assert sent["color"] == [10, 20, 30]


def test_gh_group_rejects_bad_input(server_v04):
    server, client = server_v04
    assert server.gh_group("not json", "X")["error"] == "invalid_arguments"
    assert server.gh_group([], "X")["error"] == "invalid_arguments"
    out = server.gh_group(["a"], "X", color=[300, 0, 0])
    assert out["error"] == "invalid_arguments"
    out = server.gh_group(["a"], "X", color=[1, 2])
    assert out["error"] == "invalid_arguments"
    assert client.sent("add_group") == []  # bridge never called


def test_gh_scribble_wire_shape(server_v04):
    server, client = server_v04
    out = server.gh_scribble("Explains the stage", 100.0, -60.0)
    assert out["success"] is True
    assert client.sent("add_scribble") == [{
        "text": "Explains the stage", "x": 100.0, "y": -60.0, "size": 14.0}]

    server.gh_scribble("Small note", 0, 0, size=10.0)
    assert client.sent("add_scribble")[1]["size"] == 10.0


def test_gh_set_nickname_wire_shape(server_v04):
    server, client = server_v04
    out = server.gh_set_nickname("slider-1", "part count")
    assert out == {"success": True,
                   "result": {"id": "slider-1", "nickname": "part count"}}
    assert client.sent("set_nickname") == [{
        "id": "slider-1", "nickname": "part count"}]


def test_v04_tools_error_cleanly_on_old_bridge(monkeypatch):
    import server
    client = FakeV01Client()

    def reject(command_type, parameters=None):
        client.commands.append((command_type, parameters or {}))
        raise BridgeError("bridge_command_failed",
                          f"Unknown command type '{command_type}'")

    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(client, "call", reject)
    out = server.gh_set_nickname("x", "y")
    assert out["success"] is False
    assert "Unknown command type" in out["message"]
