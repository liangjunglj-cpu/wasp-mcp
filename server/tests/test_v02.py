"""Offline tests for the v0.2 surface: set_plane_values / set_toggle /
delete_components tools, the create_wasp_part probe/fallback logic, and the
reset_aggregation pulse sequence.

No Grasshopper (and no TCP) required: FakeV01Client answers v0.2 commands
with unknown-command errors, FakeV02Client implements them in-memory.
"""

import pytest

import macros
from gh_client import BridgeError
from macros import (
    is_unknown_command_error,
    normalize_plane,
    normalize_planes,
    supports_set_plane_values,
)
from test_offline import (  # noqa: F401  (fake_registry is a fixture)
    FAKE_DESCRIPTORS,
    FakeClient,
    fake_registry,
)

PLANE_DICT = {"origin": [0, 0, 0], "xAxis": [1, 0, 0], "yAxis": [0, 1, 0]}
PLANE_FLAT = [5, 0, 0, 0, 1, 0, 0, 0, 1]

CONN_FROM_PLANE_DESCRIPTOR = {
    "name": "Connection From Plane", "nickname": "ConnPln",
    "inputs": [
        {"name": "Planes", "nickname": "PLN", "index": 0, "typeName": "Plane"},
    ],
    "outputs": [
        {"name": "Connections", "nickname": "CONN", "index": 0,
         "typeName": "Connection"},
    ],
}


class FakeV02Client(FakeClient):
    """FakeClient that also speaks the v0.2 commands."""

    def __init__(self, canvas_state=None, **kwargs):
        super().__init__(**kwargs)
        self.canvas_state = canvas_state or {"components": [], "connections": [],
                                             "solutionState": "idle",
                                             "version": "0.2.0"}
        self.toggle_values = {}

    def call(self, command_type, parameters=None):
        parameters = parameters or {}
        if command_type == "get_document_info":
            self.commands.append((command_type, parameters))
            return {"name": "doc", "componentCount": 0,
                    "version": self.canvas_state.get("version", "0.2.0")}
        if command_type == "set_plane_values":
            self.commands.append((command_type, parameters))
            if not parameters.get("planes"):
                # Mirrors the real v0.2 bridge: argument error, not unknown command.
                raise BridgeError(
                    "bridge_command_failed",
                    "Error executing command 'set_plane_values': "
                    "planes is required and must be non-empty",
                )
            return {"count": len(parameters["planes"])}
        if command_type == "set_toggle":
            self.commands.append((command_type, parameters))
            self.toggle_values[parameters["id"]] = parameters["value"]
            return {"id": parameters["id"], "value": parameters["value"]}
        if command_type == "delete_components":
            self.commands.append((command_type, parameters))
            results = [{"id": i, "deleted": True} for i in parameters["ids"]]
            return {"deleted": len(results), "results": results}
        if command_type == "get_canvas_state":
            self.commands.append((command_type, parameters))
            return self.canvas_state
        return super().call(command_type, parameters)


class FakeV01Client(FakeClient):
    """FakeClient that rejects every v0.2 command as unknown."""

    V02_COMMANDS = ("set_plane_values", "set_toggle", "delete_components")

    def __init__(self, unknown_template="Unknown command type '{cmd}'", **kwargs):
        super().__init__(**kwargs)
        self.unknown_template = unknown_template

    def call(self, command_type, parameters=None):
        if command_type in self.V02_COMMANDS:
            self.commands.append((command_type, parameters or {}))
            raise BridgeError("bridge_command_failed",
                              self.unknown_template.format(cmd=command_type))
        return super().call(command_type, parameters)


@pytest.fixture
def registry_with_conn(fake_registry):
    """fake_registry extended with Connection From Plane."""
    (fake_registry.directory / "Wasp_Connection From Plane.ghuser").write_bytes(b"")
    fake_registry.scan()
    FAKE_DESCRIPTORS["connection from plane"] = CONN_FROM_PLANE_DESCRIPTOR
    yield fake_registry
    del FAKE_DESCRIPTORS["connection from plane"]


# ── plane normalization ────────────────────────────────────────────────────


def test_normalize_plane_dict_and_flat_agree():
    from_dict = normalize_plane(PLANE_DICT)
    assert from_dict == {"origin": [0.0, 0.0, 0.0],
                         "xAxis": [1.0, 0.0, 0.0],
                         "yAxis": [0.0, 1.0, 0.0]}
    from_flat = normalize_plane(PLANE_FLAT)
    assert from_flat == {"origin": [5.0, 0.0, 0.0],
                         "xAxis": [0.0, 1.0, 0.0],
                         "yAxis": [0.0, 0.0, 1.0]}


def test_normalize_planes_mixed_forms():
    assert normalize_planes([PLANE_DICT, PLANE_FLAT])[1]["origin"] == [5.0, 0.0, 0.0]


def test_normalize_plane_rejects_bad_input():
    with pytest.raises(ValueError):
        normalize_plane([1, 2, 3])  # not 9 floats
    with pytest.raises(ValueError):
        normalize_plane({"origin": [0, 0, 0], "xAxis": [1, 0, 0]})  # no yAxis
    with pytest.raises(ValueError):
        normalize_plane({"origin": [0, 0], "xAxis": [1, 0, 0],
                         "yAxis": [0, 1, 0]})  # origin not 3 floats


# ── capability probe ───────────────────────────────────────────────────────


def test_unknown_command_markers():
    assert is_unknown_command_error("Unknown command type 'set_plane_values'")
    assert is_unknown_command_error(
        "No handler registered for command type 'set_plane_values'")
    assert not is_unknown_command_error(
        "Error executing command 'set_plane_values': planes is required")
    assert not is_unknown_command_error(None)


def test_probe_detects_v02_and_caches():
    client = FakeV02Client()
    assert supports_set_plane_values(client) is True
    assert supports_set_plane_values(client) is True
    # Only the first call actually probed the bridge.
    assert len(client.sent("set_plane_values")) == 1


def test_probe_detects_v01_and_caches():
    client = FakeV01Client()
    assert supports_set_plane_values(client) is False
    assert supports_set_plane_values(client) is False
    assert len(client.sent("set_plane_values")) == 1


def test_probe_accepts_legacy_v01_error_text():
    # The shipped v0.1 bridge says "No handler registered for command type".
    client = FakeV01Client(
        unknown_template="No handler registered for command type '{cmd}'")
    assert supports_set_plane_values(client) is False


def test_probe_cache_is_per_client_instance():
    assert supports_set_plane_values(FakeV02Client()) is True
    assert supports_set_plane_values(FakeV01Client()) is False  # not cross-cached


def test_probe_transport_error_propagates_and_is_not_cached():
    class DeadClient(FakeClient):
        def call(self, command_type, parameters=None):
            raise BridgeError("bridge_unreachable", "no bridge")

    client = DeadClient()
    with pytest.raises(BridgeError) as excinfo:
        supports_set_plane_values(client)
    assert excinfo.value.code == "bridge_unreachable"
    assert getattr(client, "_wasp_supports_set_plane_values", None) is None


# ── create_wasp_part fast path / fallback ──────────────────────────────────


def _create_part(client, registry):
    return macros.create_wasp_part(
        client, registry, "HEX",
        geometry_object_ids=["rhino-guid-1"],
        connection_planes=[PLANE_DICT, PLANE_FLAT],
        x=0, y=0,
    )


def test_create_wasp_part_v02_fast_path(registry_with_conn):
    client = FakeV02Client()
    result = _create_part(client, registry_with_conn)

    # Plane param placed and filled via set_plane_values (probe + real call).
    added_types = [p["type"] for p in client.sent("add_component")]
    assert "Plane" in added_types
    assert "Construct Plane" not in added_types
    spv = client.sent("set_plane_values")
    assert len(spv) == 2  # capability probe + actual data
    assert spv[0]["planes"] == []
    assert spv[1]["id"] == result["plane_param_id"]
    assert spv[1]["planes"] == normalize_planes([PLANE_DICT, PLANE_FLAT])

    # Only the NAME panel — no origin/x/y plane panels.
    assert len(client.sent("set_panel")) == 1
    assert "construct_plane_id" not in result
    assert result["plane_param_id"] in result["all_ids"]

    # Plane param wired into Connection From Plane, connection into the part.
    conns = client.sent("connect_by_name")
    assert any(c["sourceId"] == result["plane_param_id"]
               and c["targetParam"] == "PLN" and c["sourceIndex"] == 0
               for c in conns)
    assert any(c["targetParam"] == "CONN" for c in conns)


def test_create_wasp_part_v01_fallback(registry_with_conn):
    client = FakeV01Client()
    result = _create_part(client, registry_with_conn)

    # Probe failed -> Construct Plane + three plane panels, no Plane param.
    added_types = [p["type"] for p in client.sent("add_component")]
    assert "Construct Plane" in added_types
    assert "Plane" not in added_types
    assert len(client.sent("set_plane_values")) == 1  # the probe only
    assert len(client.sent("set_panel")) == 4  # NAME + O/X/Y panels
    assert "plane_param_id" not in result
    assert "construct_plane_id" in result


def test_create_wasp_part_probe_cached_across_calls(registry_with_conn):
    client = FakeV02Client()
    r1 = _create_part(client, registry_with_conn)
    r2 = _create_part(client, registry_with_conn)
    spv = client.sent("set_plane_values")
    # One probe total, then one data call per part.
    assert [p["planes"] for p in spv][0] == []
    assert len(spv) == 3
    assert r1["plane_param_id"] != r2["plane_param_id"]

    v01 = FakeV01Client()
    _create_part(v01, registry_with_conn)
    _create_part(v01, registry_with_conn)
    assert len(v01.sent("set_plane_values")) == 1  # probe once, then cached


def test_create_wasp_part_bad_plane_fails_before_any_placement(registry_with_conn):
    client = FakeV02Client()
    with pytest.raises(ValueError):
        macros.create_wasp_part(
            client, registry_with_conn, "HEX",
            geometry_object_ids=["g"],
            connection_planes=[[1, 2, 3]],  # invalid: not 9 floats
        )
    # Validation happens before probing or placing plane components.
    assert client.sent("set_plane_values") == []


# ── reset_aggregation ──────────────────────────────────────────────────────


AGG_ID = "agg-1"
TOGGLE_ID = "toggle-1"


def _canvas(with_toggle: bool):
    components = [
        {"id": AGG_ID, "name": "Stochastic Aggregation", "nickname": "StochAggr",
         "position": [400.0, 100.0], "runtimeMessages": []},
    ]
    connections = []
    if with_toggle:
        components.append(
            {"id": TOGGLE_ID, "name": "Boolean Toggle", "nickname": "Toggle",
             "position": [150.0, 280.0], "runtimeMessages": []})
        connections.append(
            {"sourceId": TOGGLE_ID, "sourceParam": "Boolean",
             "targetId": AGG_ID, "targetParam": "Reset"})
    return {"components": components, "connections": connections,
            "solutionState": "idle", "version": "0.2.0"}


def _pulse_sequence(client, toggle_id, agg_id):
    """The (command, key-fields) trace of set_toggle/expire_solution calls."""
    trace = []
    for cmd, params in client.commands:
        if cmd == "set_toggle":
            trace.append(("set_toggle", params["id"], params["value"]))
        elif cmd == "expire_solution":
            trace.append(("expire", tuple(params.get("ids") or ())))
    return trace


def test_reset_aggregation_reuses_wired_toggle():
    client = FakeV02Client(canvas_state=_canvas(with_toggle=True))
    result = macros.reset_aggregation(client, AGG_ID)

    assert result["toggle_id"] == TOGGLE_ID
    assert result["created_toggle"] is False
    assert result["pulse"] == [False, True, False]
    assert client.sent("add_component") == []  # nothing new placed
    assert client.sent("connect_by_name") == []

    # Exact pulse sequence: each expire includes the TOGGLE (source) so its
    # stale VolatileData can't be re-read by the aggregation (validator F1).
    assert _pulse_sequence(client, TOGGLE_ID, AGG_ID) == [
        ("set_toggle", TOGGLE_ID, False), ("expire", (TOGGLE_ID, AGG_ID)),
        ("set_toggle", TOGGLE_ID, True), ("expire", (TOGGLE_ID, AGG_ID)),
        ("set_toggle", TOGGLE_ID, False), ("expire", (TOGGLE_ID, AGG_ID)),
    ]
    assert client.toggle_values[TOGGLE_ID] is False  # left in run state


def test_reset_aggregation_places_toggle_when_absent():
    client = FakeV02Client(canvas_state=_canvas(with_toggle=False))
    result = macros.reset_aggregation(client, AGG_ID)

    assert result["created_toggle"] is True
    added = client.sent("add_component")
    assert added and added[0]["type"] == "Boolean Toggle"
    # Wired into RESET (first candidate) from the toggle's implicit output.
    conns = client.sent("connect_by_name")
    assert conns[0]["sourceId"] == result["toggle_id"]
    assert conns[0]["targetId"] == AGG_ID
    assert conns[0]["targetParam"] == "RESET"
    assert conns[0]["sourceIndex"] == 0
    # Pulse still runs on the new toggle; expiries include the source (F1).
    tid = result["toggle_id"]
    assert _pulse_sequence(client, tid, AGG_ID) == [
        ("set_toggle", tid, False), ("expire", (tid, AGG_ID)),
        ("set_toggle", tid, True), ("expire", (tid, AGG_ID)),
        ("set_toggle", tid, False), ("expire", (tid, AGG_ID)),
    ]


def test_reset_aggregation_unknown_component_raises():
    client = FakeV02Client(canvas_state=_canvas(with_toggle=False))
    with pytest.raises(BridgeError) as excinfo:
        macros.reset_aggregation(client, "no-such-id")
    assert excinfo.value.code == "component_not_found"
    assert client.sent("set_toggle") == []


def test_reset_aggregation_v01_bridge_fails_cleanly():
    # On a v0.1 bridge set_toggle is unknown; the macro surfaces the bridge
    # error instead of half-completing silently.
    client = FakeV01Client()
    client_canvas = _canvas(with_toggle=True)

    class V01WithCanvas(FakeV01Client):
        def call(self, command_type, parameters=None):
            if command_type == "get_canvas_state":
                self.commands.append((command_type, parameters or {}))
                return client_canvas
            return super().call(command_type, parameters)

    with pytest.raises(BridgeError) as excinfo:
        macros.reset_aggregation(V01WithCanvas(), AGG_ID)
    assert "Unknown command type" in excinfo.value.message


# ── MCP tool layer (server.py) ─────────────────────────────────────────────


@pytest.fixture
def server_with_fake_client(monkeypatch):
    import server
    client = FakeV02Client(canvas_state=_canvas(with_toggle=True))
    monkeypatch.setattr(server, "_client", client)
    return server, client


def test_gh_set_plane_values_tool_normalizes(server_with_fake_client):
    server, client = server_with_fake_client
    out = server.gh_set_plane_values("comp-1", [PLANE_DICT, PLANE_FLAT])
    assert out["success"] is True
    sent = client.sent("set_plane_values")
    assert sent[0]["id"] == "comp-1"
    assert sent[0]["planes"][1] == {"origin": [5.0, 0.0, 0.0],
                                    "xAxis": [0.0, 1.0, 0.0],
                                    "yAxis": [0.0, 0.0, 1.0]}


def test_gh_set_plane_values_tool_rejects_bad_planes(server_with_fake_client):
    server, client = server_with_fake_client
    out = server.gh_set_plane_values("comp-1", [[1, 2, 3]])
    assert out["success"] is False
    assert out["error"] == "invalid_arguments"
    assert client.sent("set_plane_values") == []  # bridge never called


def test_gh_set_toggle_tool_wire_shape(server_with_fake_client):
    server, client = server_with_fake_client
    out = server.gh_set_toggle(TOGGLE_ID, True)
    assert out == {"success": True, "result": {"id": TOGGLE_ID, "value": True}}
    assert client.sent("set_toggle") == [{"id": TOGGLE_ID, "value": True}]


def test_gh_delete_tool_wire_shape(server_with_fake_client):
    server, client = server_with_fake_client
    out = server.gh_delete(["a", "b"])
    assert out["success"] is True
    assert out["result"]["deleted"] == 2
    assert client.sent("delete_components") == [{"ids": ["a", "b"]}]


def test_reset_aggregation_tool_success_and_error(server_with_fake_client):
    server, client = server_with_fake_client
    out = server.reset_aggregation(AGG_ID)
    assert out["success"] is True
    assert out["result"]["toggle_id"] == TOGGLE_ID

    bad = server.reset_aggregation("no-such-id")
    assert bad["success"] is False
    assert bad["error"] == "component_not_found"
