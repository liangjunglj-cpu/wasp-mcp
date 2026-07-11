"""wasp-mcp — FastMCP stdio server for driving Wasp in Grasshopper.

Talks to the GH_MCP_Wasp bridge component (TCP 127.0.0.1:8090, env override
WASP_MCP_PORT). Tool surface per PROTOCOL.md "Python MCP tool surface".

Run: ``uv run server.py`` (or the ``wasp-mcp`` console script).
"""

from __future__ import annotations

import base64
import json
import sys
from typing import Any, Dict, List, Optional, Union

from fastmcp import FastMCP
from fastmcp.utilities.types import Image

import expander
import macros
from gh_client import BridgeError, GHClient
from registry import RegistryLookupError, WaspRegistry

# v0.3 typed tool schemas: every list/dict param is annotated with its real
# JSON type AND additionally accepts a JSON-encoded string (some MCP clients
# serialize structured args to strings; see docs/v03-backlog.md #1).
StrList = Union[List[str], str]
OptionalStrList = Optional[Union[List[str], str]]
PlaneSpec = Union[Dict[str, Any], List[float]]
PlaneList = Union[List[PlaneSpec], str]
OptionalPlaneList = Optional[Union[List[PlaneSpec], str]]
ColorList = Union[List[Union[int, float]], str]
OptionalColorList = Optional[ColorList]

mcp = FastMCP("wasp-mcp")

_client = GHClient()
_registry = WaspRegistry()
_registry.scan()
print(
    f"wasp-mcp: {len(_registry.entries)} Wasp UserObjects indexed from "
    f"{_registry.directory}; bridge target {_client.host}:{_client.port}",
    file=sys.stderr,
)


def _ok(result: Any) -> Dict[str, Any]:
    return {"success": True, "result": result}


def _coerce_list(value: Any, name: str) -> Optional[List[Any]]:
    """Accept a real list, a JSON-encoded string, or None (-> None).

    Raises ValueError (surfaced as an "invalid_arguments" error dict) when
    the value is a string that is not valid JSON, or not list-shaped at all.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in ("null", "none"):
            return None
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{name} was sent as a string that is not valid JSON "
                f"({exc}); pass a JSON array, e.g. [\"item\"]"
            ) from None
        if value is None:
            return None
    if not isinstance(value, list):
        raise ValueError(
            f"{name} must be a list/array (got {type(value).__name__})")
    return value


def _require_list(value: Any, name: str) -> List[Any]:
    coerced = _coerce_list(value, name)
    if not coerced:
        raise ValueError(f"{name} is required and must be a non-empty list")
    return coerced


def _coerce_dict(value: Any, name: str) -> Optional[Dict[str, Any]]:
    """Accept a real dict, a JSON-encoded object string, or None (-> None)."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in ("null", "none"):
            return None
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{name} was sent as a string that is not valid JSON "
                f"({exc}); pass a JSON object, e.g. {{\"slot\": 1}}"
            ) from None
        if value is None:
            return None
    if not isinstance(value, dict):
        raise ValueError(
            f"{name} must be an object/dict (got {type(value).__name__})")
    return value


def _coerce_str(value: Optional[str]) -> Optional[str]:
    """Treat "", "null" and "none" as an omitted optional string."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("null", "none"):
        return None
    return value


def _invalid(exc: Exception) -> Dict[str, Any]:
    return {"success": False, "error": "invalid_arguments", "message": str(exc)}


def _with_solve(params: Dict[str, Any], solve: Optional[bool]) -> Dict[str, Any]:
    """Attach the v0.3 solve flag when explicitly requested (pre-v0.3 bridges
    ignore it)."""
    if solve is not None:
        params["solve"] = bool(solve)
    return params


def _call(command_type: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Send a bridge command; never raises — errors become informative dicts."""
    try:
        return _ok(_client.call(command_type, params))
    except BridgeError as exc:
        return exc.to_dict()


def _make_wait_client() -> GHClient:
    """Fresh client for long blocking waits (injectable for tests)."""
    return GHClient()


# ── Low-level passthroughs ─────────────────────────────────────────────────


@mcp.tool
def gh_add_component(component_type: str, x: float, y: float,
                     solve: Optional[bool] = None) -> dict:
    """Add a stock Grasshopper component to the canvas.

    Use for built-in components (e.g. "Number Slider", "Panel", "Mesh",
    "Geometry", "Construct Plane"). For Wasp components use
    gh_add_wasp_component instead.

    Args:
        component_type: Grasshopper component name (e.g. "Number Slider").
        x: Canvas x coordinate.
        y: Canvas y coordinate.
        solve: Pass false to suppress the automatic recompute (v0.3 bridge
            batching); finish the batch with gh_expire + gh_wait_idle.

    Returns:
        {"success": true, "result": {"id": ..., ...}} with the new
        component's instance guid, or an error dict.
    """
    return _call("add_component", _with_solve(
        {"type": component_type, "x": x, "y": y}, solve))


@mcp.tool
def gh_add_wasp_component(name: str, x: float, y: float,
                          solve: Optional[bool] = None) -> dict:
    """Add a Wasp component (from an installed .ghuser UserObject) to the canvas.

    The name is resolved against the local Wasp registry with fuzzy matching:
    "Basic Part", "basic_part" and "stochastic" all work. Use
    list_wasp_components to see what is available.

    Args:
        name: Wasp component name or registry key (fuzzy matched).
        x: Canvas x coordinate.
        y: Canvas y coordinate.
        solve: Pass false to suppress the automatic recompute (v0.3 bridge
            batching); finish the batch with gh_expire + gh_wait_idle.

    Returns:
        {"success": true, "result": {"id", "name", "nickname", "inputs",
        "outputs", "registryKey"}} — inputs/outputs list the real param
        names/nicknames/indices, which you should use for gh_connect.
    """
    try:
        comp = _registry.lookup(name)
    except RegistryLookupError as exc:
        return {
            "success": False,
            "error": "component_not_found",
            "message": str(exc),
            "suggestions": exc.suggestions,
        }
    response = _call("add_user_object", _with_solve(
        {"path": comp.path, "x": x, "y": y}, solve))
    if response.get("success"):
        response["result"]["registryKey"] = comp.key
        # Cache param docs for list_wasp_components.
        comp.inputs = response["result"].get("inputs")
        comp.outputs = response["result"].get("outputs")
    return response


@mcp.tool
def gh_connect(
    source_id: str,
    target_id: str,
    source_param: Optional[str] = None,
    target_param: Optional[str] = None,
    source_index: Optional[int] = None,
    target_index: Optional[int] = None,
    solve: Optional[bool] = None,
) -> dict:
    """Connect a source component output to a target component input.

    Params are resolved by name OR nickname, case-insensitively. For
    components with a single implicit output (Panel, Number Slider) simply
    omit source_param (optionally pass source_index=0).

    Args:
        source_id: Instance guid of the source component.
        target_id: Instance guid of the target component.
        source_param: Output param name/nickname (omit to use index or the
            component's single output).
        target_param: Input param name/nickname (omit to use index or the
            component's single input).
        source_index: Optional explicit output index (overrides name).
        target_index: Optional explicit input index (overrides name).
        solve: Pass false to suppress the automatic recompute (v0.3 bridge
            batching); finish the batch with gh_expire + gh_wait_idle.

    Returns:
        {"success": true, "result": {"connected": true}} or an error dict.
    """
    return _call("connect_by_name", _with_solve({
        "sourceId": source_id,
        "sourceParam": _coerce_str(source_param),
        "targetId": target_id,
        "targetParam": _coerce_str(target_param),
        "sourceIndex": source_index,
        "targetIndex": target_index,
    }, solve))


@mcp.tool
def gh_set_slider(
    component_id: str,
    value: float,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    solve: Optional[bool] = None,
) -> dict:
    """Set a Number Slider's value (and optionally its min/max range).

    Args:
        component_id: Instance guid of the Number Slider.
        value: New slider value.
        minimum: Optional new lower bound.
        maximum: Optional new upper bound.
        solve: Pass false to suppress the automatic recompute (v0.3 bridge
            batching); finish the batch with gh_expire + gh_wait_idle.
    """
    params: Dict[str, Any] = {"id": component_id, "value": value}
    if minimum is not None:
        params["min"] = minimum
    if maximum is not None:
        params["max"] = maximum
    return _call("set_slider", _with_solve(params, solve))


@mcp.tool
def gh_set_panel(component_id: str, text: str,
                 split_lines: Optional[bool] = None,
                 solve: Optional[bool] = None) -> dict:
    """Set the text of a Panel component.

    Multi-line content (e.g. Wasp rule grammars, one rule per line) is
    passed with "\\n" newlines. On a v0.3+ bridge each line becomes a
    SEPARATE data item by default (split_lines=true); pass
    split_lines=false to emit the whole text as one item (v0.1 behavior).
    Pre-v0.3 bridges ignore the flag and always emit one item.

    Args:
        component_id: Instance guid of the Panel.
        text: Panel text content.
        split_lines: One data item per line (default true on v0.3 bridges).
        solve: Pass false to suppress the automatic recompute (v0.3 bridge
            batching); finish the batch with gh_expire + gh_wait_idle.
    """
    params: Dict[str, Any] = {"id": component_id, "text": text}
    if split_lines is not None:
        params["split_lines"] = bool(split_lines)
    return _call("set_panel", _with_solve(params, solve))


@mcp.tool
def gh_set_geometry_ref(component_id: str, object_ids: StrList,
                        solve: Optional[bool] = None) -> dict:
    """Reference Rhino document geometry into a canvas param component.

    Points a Geometry/Mesh/Brep parameter component at existing Rhino
    objects by their document GUIDs.

    Args:
        component_id: Instance guid of the param component on the canvas.
        object_ids: Rhino object GUID strings to reference (JSON array; a
            JSON-encoded string is also accepted).
        solve: Pass false to suppress the automatic recompute (v0.3 bridge
            batching); finish the batch with gh_expire + gh_wait_idle.
    """
    try:
        ids = _require_list(object_ids, "object_ids")
    except ValueError as exc:
        return _invalid(exc)
    return _call("set_geometry_ref", _with_solve(
        {"id": component_id, "objectIds": ids}, solve))


@mcp.tool
def gh_set_plane_values(component_id: str, planes: PlaneList,
                        solve: Optional[bool] = None) -> dict:
    """Set persistent plane data directly on a floating Plane param (v0.2 bridge).

    Removes the need for the three-panels-into-Construct-Plane workaround:
    place a "Plane" param with gh_add_component, then set its planes here.
    On a v0.1 bridge this returns an unknown-command error — use the
    Construct Plane path instead (create_wasp_part does this automatically).

    Args:
        component_id: Instance guid of the Plane param component.
        planes: Planes (JSON array; a JSON-encoded string is also
            accepted), each either {"origin":[x,y,z], "xAxis":[x,y,z],
            "yAxis":[x,y,z]} or a flat 9-float list
            [ox,oy,oz, xx,xy,xz, yx,yy,yz]. xAxis/yAxis must be non-zero
            and non-parallel.
        solve: Pass false to suppress the automatic recompute (v0.3 bridge
            batching); finish the batch with gh_expire + gh_wait_idle.

    Returns:
        {"success": true, "result": {"count": n}} or an error dict.
    """
    try:
        plane_list = _require_list(planes, "planes")
        normalized = macros.normalize_planes(plane_list)
    except (TypeError, ValueError) as exc:
        return _invalid(exc)
    return _call("set_plane_values", _with_solve(
        {"id": component_id, "planes": normalized}, solve))


@mcp.tool
def gh_set_toggle(component_id: str, value: bool,
                  solve: Optional[bool] = None) -> dict:
    """Set a Boolean Toggle component's value (v0.2 bridge).

    Args:
        component_id: Instance guid of the Boolean Toggle.
        value: New toggle state (true/false).
        solve: Pass false to suppress the automatic recompute (v0.3 bridge
            batching); finish the batch with gh_expire + gh_wait_idle.

    Returns:
        {"success": true, "result": {"id": ..., "value": ...}} or an error
        dict (unknown-command error on a v0.1 bridge).
    """
    return _call("set_toggle", _with_solve(
        {"id": component_id, "value": value}, solve))


@mcp.tool
def gh_delete(component_ids: StrList) -> dict:
    """Delete components from the Grasshopper canvas (v0.2 bridge).

    The WaspMCP bridge component itself is never deleted; its entry comes
    back with {"deleted": false, "error": "cannot delete bridge"}.

    Args:
        component_ids: Instance guids of the components to remove (JSON
            array; a JSON-encoded string is also accepted).

    Returns:
        {"success": true, "result": {"deleted": n, "results": [{"id",
        "deleted", "error"?}, ...]}} or an error dict.
    """
    try:
        ids = _require_list(component_ids, "component_ids")
    except ValueError as exc:
        return _invalid(exc)
    return _call("delete_components", {"ids": ids})


@mcp.tool
def gh_group(ids: StrList, name: str, color: OptionalColorList = None) -> dict:
    """Group canvas components under a labeled GH_Group (v0.4 bridge).

    Purely visual — grouping never triggers a recompute. An id already in
    another group is fine (Grasshopper supports nested/overlapping groups).
    Ids that don't exist get per-id error entries in "results" while the
    rest are still grouped.

    Args:
        ids: Instance guids of the components to group (JSON array; a
            JSON-encoded string is also accepted).
        name: Group label shown on the canvas (e.g. "AGGREGATION").
        color: Optional group color as [r,g,b] or [r,g,b,a] with channels
            0-255, order RGBA (alpha LAST; defaults to 150, Grasshopper's
            own group transparency, when omitted). JSON-encoded string also
            accepted.

    Returns:
        {"success": true, "result": {"groupId", "name", "grouped",
        "colorOrder": "RGBA", "results": [{"id", "grouped", "error"?},
        ...]}} or an error dict (unknown-command error on pre-v0.4 bridges).
    """
    try:
        id_list = _require_list(ids, "ids")
        color_list = _coerce_list(color, "color")
        if color_list is not None:
            color_list = [int(round(float(c))) for c in color_list]
            if len(color_list) not in (3, 4) or \
                    any(c < 0 or c > 255 for c in color_list):
                raise ValueError(
                    "color must be [r,g,b] or [r,g,b,a] with each channel "
                    "in 0-255 (channel order RGBA, alpha last)")
    except (TypeError, ValueError) as exc:
        return _invalid(exc)
    params: Dict[str, Any] = {"ids": id_list, "name": name}
    if color_list is not None:
        params["color"] = color_list
    return _call("add_group", params)


@mcp.tool
def gh_scribble(text: str, x: float, y: float, size: float = 14.0) -> dict:
    """Place a text scribble (canvas note) on the Grasshopper canvas (v0.4 bridge).

    Use for explainer notes above groups: what a stage does and why it
    exists. Purely visual — never triggers a recompute. Multi-line text
    uses "\\n".

    Args:
        text: Note text.
        x: Canvas x of the scribble pivot (top-left).
        y: Canvas y of the scribble pivot.
        size: Font size in points (default 14).

    Returns:
        {"success": true, "result": {"id", "text", "size"}} or an error
        dict (unknown-command error on pre-v0.4 bridges).
    """
    return _call("add_scribble", {"text": text, "x": x, "y": y, "size": size})


@mcp.tool
def gh_workflow_note(title: str, text: str, x: float, y: float,
                     width: int = 64) -> dict:
    """Place a workflow-level overview note: title + wrapped paragraphs (v0.4).

    The 'what is this whole graph doing' paragraph that individual stage
    explainers don't cover. Place it at the TOP-LEFT of the workflow's canvas
    zone, above everything. Text is wrapped to ~width chars per line with
    paragraph breaks preserved, so long descriptions stay in a tidy column
    instead of sprawling over components. Write it for someone opening the
    file cold: what the workflow produces, what drives it, where to look.

    Args:
        title: Short workflow title (rendered UPPERCASE with a separator).
        text: Overview body; may be long, use "\\n" for paragraph breaks.
        x: Canvas x of the note's top-left.
        y: Canvas y of the note's top-left.
        width: Wrap column in characters (default 64).

    Returns:
        {"success": true, "result": {"id", "lines"}} or an error dict.
    """
    try:
        result = macros.add_workflow_note(_client, title, text, x, y,
                                          width=width)
    except BridgeError as exc:
        return exc.to_dict()
    if result is None:
        return {"success": False, "error": "unsupported",
                "message": "workflow notes need a v0.4+ bridge"}
    return _ok(result)


@mcp.tool
def gh_set_nickname(component_id: str, nickname: str) -> dict:
    """Rename a component/param instance on the canvas (v0.4 bridge).

    Use to make generated workflows legible: name sliders after their role
    ("part count", "random seed") instead of leaving bare numbers. A pure
    rename never recomputes the solution; the bridge only refreshes the
    component's layout and repaints.

    Args:
        component_id: Instance guid of the component to rename.
        nickname: New display name.

    Returns:
        {"success": true, "result": {"id", "nickname"}} or an error dict
        (unknown-command error on pre-v0.4 bridges).
    """
    return _call("set_nickname", {"id": component_id, "nickname": nickname})


@mcp.tool
def gh_get_output(component_id: str, param: str, max_items: int = 1000) -> dict:
    """Read the output data of a component after the solution has computed.

    Meshes come back as {"vertices": [[x,y,z]...], "faces": [[a,b,c(,d)]...]},
    planes as {"origin","xAxis","yAxis"}, transforms as 16-float row-major
    arrays, primitives as-is. If the result has "truncated": true, raise
    max_items or bake instead. Returns error "solution_running" if the GH
    solution is still computing — retry after a moment.

    Args:
        component_id: Instance guid of the component.
        param: Output param name or nickname.
        max_items: Truncation limit for returned items.
    """
    return _call("get_component_output", {
        "id": component_id, "param": param, "maxItems": max_items,
    })


@mcp.tool
def gh_canvas_state() -> dict:
    """Snapshot the whole Grasshopper canvas.

    Returns all components (id, name, nickname, position, runtime
    error/warning messages), all connections, and the solution state
    ("idle" or "running"). Use to drift-check after a sequence of edits or
    to diagnose red/orange components.
    """
    return _call("get_canvas_state")


@mcp.tool
def gh_expire(component_ids: OptionalStrList = None) -> dict:
    """Expire components and schedule a recompute of the GH solution.

    Args:
        component_ids: Instance guids to expire (JSON array; a JSON-encoded
            string is also accepted); omit to recompute the entire document.

    Returns immediately with {"scheduled": true}; call gh_wait_idle (v0.3
    bridge) or poll gh_canvas_state for solutionState "idle" before reading
    outputs.
    """
    try:
        ids = _coerce_list(component_ids, "component_ids")
    except ValueError as exc:
        return _invalid(exc)
    params: Dict[str, Any] = {}
    if ids is not None:
        params["ids"] = ids
    return _call("expire_solution", params)


@mcp.tool
def gh_wait_idle(timeout_ms: int = 30000) -> dict:
    """Block until the Grasshopper solution is idle (v0.3 bridge).

    Replaces client-side sleep/retry loops after gh_expire or any batch of
    edits. The bridge polls the solution state every ~100 ms on its TCP
    thread (never occupying the UI thread) and answers once two consecutive
    reads are idle.

    Args:
        timeout_ms: Max wait in milliseconds (default 30000, bridge caps at
            120000).

    Returns:
        {"success": true, "result": {"idle": true, "waitedMs": n}}, an
        {"error": "wait_timeout"} dict on timeout, or an unknown-command
        error on pre-v0.3 bridges.
    """
    # The bridge blocks for up to timeout_ms before answering. Use a
    # DEDICATED client for the wait instead of mutating the shared client's
    # read_timeout: FastMCP may run tools on a threadpool, and a concurrent
    # tool call must not observe an inflated timeout (validator F6). Each
    # GHClient call opens its own TCP connection, so a second instance is
    # free of shared state.
    wait_client = _make_wait_client()
    base_timeout = getattr(wait_client, "read_timeout", 60.0) or 60.0
    wait_client.read_timeout = max(base_timeout, timeout_ms / 1000.0 + 10.0)
    try:
        return _ok(wait_client.call("wait_for_idle",
                                    {"timeoutMs": timeout_ms}))
    except BridgeError as exc:
        return exc.to_dict()


@mcp.tool
def gh_bake(component_id: str, param: str, layer: Optional[str] = None) -> dict:
    """Bake a component output's geometry into the Rhino document.

    Args:
        component_id: Instance guid of the component.
        param: Output param name or nickname to bake.
        layer: Target Rhino layer (e.g. "WASP::AGG"); bridge default if None.

    Returns:
        {"success": true, "result": {"bakedIds": [rhino guids]}}.
    """
    params: Dict[str, Any] = {"id": component_id, "param": param}
    if layer is not None:
        params["layer"] = layer
    return _call("bake_component_output", params)


@mcp.tool
def gh_clear() -> dict:
    """Clear the current Grasshopper document (removes all components)."""
    return _call("clear_document")


@mcp.tool
def gh_save(path: str) -> dict:
    """Save the current Grasshopper document to a .gh file.

    Args:
        path: Absolute destination path for the .gh file.
    """
    return _call("save_document", {"path": path})


# ── v0.5 vision passthroughs ───────────────────────────────────────────────


def _capture(command_type: str, params: Dict[str, Any]):
    """Send a capture command; decode the PNG into MCP image content.

    Pre-v0.5 bridges do not know the capture commands: their
    unknown-command answer is surfaced as a typed ``bridge_too_old`` error
    instead of a confusing bridge_command_failed.
    """
    try:
        result = _client.call(command_type, params)
    except BridgeError as exc:
        if exc.code == "bridge_command_failed" and \
                macros.is_unknown_command_error(exc.message):
            return {
                "success": False,
                "error": "bridge_too_old",
                "message": f"The connected GH_MCP_Wasp bridge does not "
                           f"implement {command_type!r}",
                "hint": "Capture commands need a v0.5+ bridge; rebuild/"
                        "reinstall GH_MCP_Wasp.gha and restart Grasshopper.",
            }
        return exc.to_dict()
    encoded = result.get("imageBase64")
    if not encoded:
        return {"success": False, "error": "bridge_protocol",
                "message": f"{command_type} returned no imageBase64 field"}
    try:
        data = base64.b64decode(encoded)
    except (ValueError, TypeError) as exc:
        return {"success": False, "error": "bridge_protocol",
                "message": f"{command_type} returned undecodable image "
                           f"data: {exc}"}
    return Image(data=data, format="png")


@mcp.tool
def gh_capture_viewport(viewport: Optional[str] = None,
                        width: Optional[int] = None,
                        height: Optional[int] = None,
                        zoom_extents: bool = False):
    """Capture a Rhino viewport to an image (v0.5 bridge).

    Returns the PNG as MCP image content (rendered inline by any MCP
    client), NOT base64 text. Use to see what an aggregation or generated
    geometry actually looks like.

    Args:
        viewport: Named viewport (e.g. "Perspective", "Top"); default the
            active viewport.
        width: Output width in px (bridge clamps to 1920).
        height: Output height in px (bridge clamps to 1080).
        zoom_extents: Zoom to the scene extents before capturing. The
            camera is NOT restored afterwards — manage it yourself if you
            need a fixed view.

    Returns:
        Image content on success; an error dict otherwise (typed
        "bridge_too_old" when the bridge predates v0.5).
    """
    params: Dict[str, Any] = {"zoomExtents": bool(zoom_extents)}
    if _coerce_str(viewport) is not None:
        params["viewport"] = viewport
    if width is not None:
        params["width"] = int(width)
    if height is not None:
        params["height"] = int(height)
    return _capture("capture_viewport", params)


@mcp.tool
def gh_capture_canvas(zoom: Optional[float] = None,
                      region: OptionalColorList = None):
    """Capture the Grasshopper canvas to an image (v0.5 bridge).

    Returns the PNG as MCP image content. Use to inspect canvas
    organization (groups, scribbles, layout) — e.g. after expand_template.

    Args:
        zoom: Output scale factor (bridge clamps total pixels to 4 MP).
        region: Optional canvas rectangle [x, y, w, h] in canvas
            coordinates (JSON array; a JSON-encoded string is also
            accepted) — pass a zone rect from a macro/expansion result to
            frame one workflow. Omit for the full document bounds.

    Returns:
        Image content on success; an error dict otherwise (typed
        "bridge_too_old" when the bridge predates v0.5).
    """
    params: Dict[str, Any] = {}
    if zoom is not None:
        params["zoom"] = float(zoom)
    try:
        region_list = _coerce_list(region, "region")
    except ValueError as exc:
        return _invalid(exc)
    if region_list is not None:
        if len(region_list) != 4:
            return _invalid(ValueError("region must be [x, y, w, h]"))
        params["region"] = [float(v) for v in region_list]
    return _capture("capture_canvas", params)


# ── Discovery ──────────────────────────────────────────────────────────────


@mcp.tool
def gh_list_component_types(filter: Optional[str] = None,
                            category: Optional[str] = None,
                            limit: int = 100) -> dict:
    """List installed Grasshopper component types (v0.3 bridge).

    Enumerates Grasshopper's ComponentServer proxies — every component from
    every installed plugin, not just Wasp. Use gh_component_schema for the
    full input/output signature of one type.

    Args:
        filter: Case-insensitive substring matched against name, nickname
            and description (e.g. "mesh").
        category: Case-insensitive substring matched against the component
            category (e.g. "Wasp", "Mesh").
        limit: Max entries returned (default 100; "total" reports the full
            match count).

    Returns:
        {"success": true, "result": {"components": [{"name", "nickname",
        "category", "subCategory", "guid", "description"}], "total": n}}.
    """
    params: Dict[str, Any] = {"limit": limit}
    if _coerce_str(filter) is not None:
        params["filter"] = filter
    if _coerce_str(category) is not None:
        params["category"] = category
    return _call("list_component_types", params)


@mcp.tool
def gh_component_schema(name: str) -> dict:
    """Describe a Grasshopper component type's full signature (v0.3 bridge).

    The bridge instantiates the component IN MEMORY (never on the canvas),
    reads its params, and discards it. Accepts a component name (exact then
    substring match) or a component GUID from gh_list_component_types.

    Args:
        name: Component type name (e.g. "Mesh Box") or GUID.

    Returns:
        {"success": true, "result": {"name", "nickname", "guid", "category",
        "subCategory", "description", "inputs": [{"name", "nickname",
        "index", "typeName", "description", "optional", "defaultValue"?}],
        "outputs": [...]}}.
    """
    return _call("get_component_schema", {"name": name})


@mcp.tool
def list_wasp_components(category: Optional[str] = None) -> dict:
    """List all Wasp components installed on this machine.

    Each entry has: key (use with gh_add_wasp_component and macros),
    filename, path, category (part/connection/rule/aggregation/field/
    disco/util, guessed from the name), and cached inputs/outputs docs when
    the component has been placed at least once this session.

    Args:
        category: Optional filter (e.g. "aggregation").
    """
    entries = _registry.list_entries()
    if category:
        entries = [e for e in entries if e["category"] == category.lower()]
    return {
        "success": True,
        "directory": str(_registry.directory),
        "count": len(entries),
        "components": entries,
    }


@mcp.tool
def refresh_registry() -> dict:
    """Rescan %APPDATA%/Grasshopper/UserObjects for Wasp_*.ghuser files.

    Use after installing or updating Wasp UserObjects while the server is
    running.
    """
    entries = _registry.scan()
    return {
        "success": True,
        "directory": str(_registry.directory),
        "count": len(entries),
        "keys": sorted(entries),
    }


# ── Templates (v0.5 expansion engine) ──────────────────────────────────────


@mcp.tool
def list_templates() -> dict:
    """Enumerate the stage templates the expander can build (v0.5).

    Templates are mined-and-abstracted corpus subgraphs with typed SLOTS
    (see docs/generation-principles.md): the same paneling stage accepts a
    box, a loft, or a referenced surface. Sources: server/knowledge
    arch_patterns.json (architectural corpus) and wasp_patterns.json (Wasp
    corpus). No bridge round-trip.

    Returns:
        {"success": true, "count": n, "templates": [{"id", "stage_name",
        "knowledge_file", "slots": {name: {kind, default?, optional?,
        range_evidence?, arity?, ref_param?}}, "outputs", "source_files",
        "evidence_strength", "expandable", "expansion_blocked"?,
        "issues"?}]} — expandable=false entries are data-only until their
        bodies are upgraded (issues) or the bridge grows a capability
        (expansion_blocked).
    """
    entries = expander.list_templates()
    return {"success": True, "count": len(entries), "templates": entries}


@mcp.tool
def expand_template(
    template_id: str,
    bindings: Optional[Union[Dict[str, Any], str]] = None,
    x: float = 0.0,
    y: float = 0.0,
) -> dict:
    """Expand a stage template into a live canvas subgraph (v0.5).

    Binds the template's slots, places the body (stock components BY GUID
    from corpus dump evidence, Wasp components via the registry), wires the
    exact recorded param names, batches everything with solve:false + one
    final recompute, and applies the v0.4 organization conventions (INPUTS
    group with role-nicknamed sliders, stage group, explainer scribble).
    ALL binding problems (unknown slots, unbound required slots, kind
    mismatches) are reported as one typed error BEFORE anything is placed.

    Args:
        template_id: Template id from list_templates
            (e.g. "arch.attractor_scale_grid").
        bindings: Slot bindings (JSON object; a JSON-encoded string is also
            accepted). Driver slots take numbers ("count": 120) or "a To b"
            domain text; geometry/wasp slots take a component id string,
            {"component_id": "...", "param": "..."} for a named upstream
            output, or {"rhino_ids": ["..."]} to reference Rhino geometry
            (geometry slots only; lists allowed for arity 1..n slots).
            Driver slots with defaults may be omitted — they still get a
            slider at the template's evidence-based default/range.
        x: Canvas x of the expansion zone's origin (drivers column).
        y: Canvas y of the expansion zone's origin.

    Returns:
        {"success": true, "result": <zone manifest>} — the manifest carries
        "zone" {x,y,width,height}, "all_ids", "components" (body ref → id),
        "drivers"/"referenced_params" (slot → id), "outputs" (name →
        {component_id, param} for gh_get_output), a per-stage "stages"
        breakdown and the "organization" report. Typed errors:
        template_not_found, template_blocked, template_not_expandable,
        invalid_bindings (with a per-problem "details" list), bridge_too_old.
    """
    try:
        binding_dict = _coerce_dict(bindings, "bindings")
    except ValueError as exc:
        return _invalid(exc)
    try:
        return _ok(expander.expand_template(
            _client, _registry, template_id, binding_dict, x=x, y=y))
    except (BridgeError, RegistryLookupError, ValueError) as exc:
        return _macro_error(exc)


# ── Macros ─────────────────────────────────────────────────────────────────


@mcp.tool
def create_wasp_part(
    name: str,
    geometry_object_ids: StrList,
    connection_planes: OptionalPlaneList = None,
    connection_object_ids: OptionalStrList = None,
    x: float = 0.0,
    y: float = 0.0,
) -> dict:
    """Create a Wasp Basic Part wired to referenced Rhino geometry.

    Places Basic Part + a Mesh param referencing the given Rhino objects +
    a name panel, and (optionally) Connection From Plane fed either by
    explicit planes or by referenced planar geometry.

    NOTE: connection-plane Z axes (xAxis × yAxis) must point OUTWARD from
    the part volume, or every placement collides with the host part.

    Args:
        name: Part name (fed into the part's NAME input).
        geometry_object_ids: Rhino GUIDs of the part's mesh geometry (JSON
            array; a JSON-encoded string is also accepted).
        connection_planes: Optional connection planes (JSON array; a
            JSON-encoded string is also accepted), each either
            {"origin":[x,y,z], "xAxis":[x,y,z], "yAxis":[x,y,z]} or a flat
            9-float list [ox,oy,oz, xx,xy,xz, yx,yy,yz].
        connection_object_ids: Alternative to planes — Rhino GUIDs of planar
            geometry to derive connections from.
        x: Canvas x for the part component.
        y: Canvas y for the part component.

    Returns:
        Ids of every placed component, incl. part_id and the part's output
        param name (feed part_id into define_rules / run_aggregation).
    """
    try:
        geometry_ids = _require_list(geometry_object_ids, "geometry_object_ids")
        planes = _coerce_list(connection_planes, "connection_planes")
        conn_ids = _coerce_list(connection_object_ids, "connection_object_ids")
    except ValueError as exc:
        return _invalid(exc)
    try:
        return _ok(macros.create_wasp_part(
            _client, _registry, name, geometry_ids,
            connection_planes=planes,
            connection_object_ids=conn_ids, x=x, y=y,
        ))
    except (BridgeError, RegistryLookupError, ValueError) as exc:
        return _macro_error(exc)


@mcp.tool
def define_rules(
    grammar_text: str,
    parts_component_ids: StrList,
    x: float = 0.0,
    y: float = 200.0,
) -> dict:
    """Create Wasp aggregation rules from a text grammar.

    Places Rule From Text fed by the grammar (one rule per line) and wires
    the given part components into it. Wasp rule syntax here is
    "PART|conn_PART|conn", e.g. "P|1_P|0": connection 1 of an existing part
    named P hosts connection 0 of a new part P (pipe between part name and
    connection index, underscore between the existing-part half and the
    new-part half). Rules are directional — write both directions if you
    want both.

    Wasp has two OTHER rule languages this macro rejects: "TYPE>TYPE"
    connection-type grammars (e.g. "END>END") belong in Rules Generator's
    GR input, and "P|c_P|c>node_node" graph rules go in a panel wired
    directly into Graph-Grammar Aggregation (run_aggregation mode="graph").

    Args:
        grammar_text: Rule grammar, one rule per line ("\\n" separated),
            e.g. "P|1_P|0\\nP|2_P|0".
        parts_component_ids: part_id values from create_wasp_part (JSON
            array; a JSON-encoded string is also accepted).
        x: Canvas x for the rules component.
        y: Canvas y for the rules component.

    Returns:
        Ids of placed components incl. rules_component_id (pass as rule_id
        to run_aggregation).
    """
    try:
        part_ids = _require_list(parts_component_ids, "parts_component_ids")
    except ValueError as exc:
        return _invalid(exc)
    try:
        return _ok(macros.define_rules(
            _client, _registry, grammar_text, part_ids, x=x, y=y,
        ))
    except (BridgeError, RegistryLookupError, ValueError) as exc:
        return _macro_error(exc)


@mcp.tool
def run_aggregation(
    part_ids: StrList,
    rule_id: str,
    count: int,
    seed: Optional[int] = None,
    mode: str = "stochastic",
    x: float = 400.0,
    y: float = 100.0,
    field_component_id: Optional[str] = None,
) -> dict:
    """Place and run a Wasp aggregation.

    Places the aggregation component (stochastic / field / graph), wires the
    parts and rules into it (batched, no intermediate solves on a v0.3
    bridge), pulses RESET automatically so the aggregation initializes from
    complete inputs (corpus files use a Button; the auto-wired Boolean
    Toggle produces the same False→True→False edge), then recomputes and
    waits for the solution to settle.

    Mode differences (real Wasp component signatures):
      - "stochastic": N count slider + optional seed slider.
      - "field": N slider, NO seed; REQUIRES field_component_id wired into
        the FIELD input.
      - "graph": NO N and NO seed (count/seed ignored); rule_id should be a
        PANEL carrying "P|c_P|c>node_node" graph rules (wired directly into
        RULES — Rule From Text is not part of that language).

    Args:
        part_ids: part_id values from create_wasp_part (JSON array; a
            JSON-encoded string is also accepted).
        rule_id: rules_component_id from define_rules (stochastic/field) or
            a panel id with graph rules (graph).
        count: Number of parts to aggregate (N slider; ignored for graph).
        seed: Optional random seed (stochastic mode only).
        mode: "stochastic" (default), "field", or "graph".
        x: Canvas x for the aggregation component.
        y: Canvas y for the aggregation component.
        field_component_id: Component whose FIELD output drives a
            field-mode aggregation (required when mode="field").

    Returns:
        Ids of placed components incl. aggregation_id and the aggregation's
        parts output param (PART_OUT — the output extractors read; AGGR is
        the aggregation object). Pass aggregation_id to get_aggregation.
    """
    try:
        ids = _require_list(part_ids, "part_ids")
    except ValueError as exc:
        return _invalid(exc)
    try:
        return _ok(macros.run_aggregation(
            _client, _registry, ids, rule_id, count,
            seed=seed, mode=mode, x=x, y=y,
            field_component_id=field_component_id,
        ))
    except (BridgeError, RegistryLookupError, ValueError) as exc:
        return _macro_error(exc)


@mcp.tool
def get_aggregation(
    aggregation_id: str,
    out: str = "meshes",
    layer: Optional[str] = None,
    max_items: int = 1000,
) -> dict:
    """Extract results from a computed Wasp aggregation.

    out="meshes": Get Part Geometry downstream, returns serialized meshes.
    out="transforms": Deconstruct Part downstream, returns part transforms.
    out="bake": bakes the aggregated geometry into the Rhino document.

    Idempotent: an extractor of the right type already wired to this
    aggregation is reused instead of placing a duplicate ("reused_extractor"
    in the result says which happened).

    Args:
        aggregation_id: aggregation_id from run_aggregation.
        out: "meshes" (default), "transforms", or "bake".
        layer: Rhino layer for out="bake" (default "WASP::AGG").
        max_items: Truncation limit when returning data.

    Returns:
        Placed extractor ids plus "data" (meshes/transforms) or "bakedIds".
    """
    try:
        return _ok(macros.get_aggregation(
            _client, _registry, aggregation_id, out=out, layer=layer,
            max_items=max_items,
        ))
    except (BridgeError, RegistryLookupError, ValueError) as exc:
        return _macro_error(exc)


@mcp.tool
def reset_aggregation(aggregation_id: str) -> dict:
    """Reset a Wasp aggregation via its RESET input (v0.2 bridge required).

    Wires a Boolean Toggle onto the aggregation's RESET input if none is
    connected yet, then pulses it false -> true -> false with a solution
    expiry after each step (Wasp's own examples use a Button on RESET; the
    toggle pulse produces the same edge). Use after changing rules/parts/
    seed to force the aggregation to recompute from scratch.

    Args:
        aggregation_id: aggregation_id from run_aggregation (or the instance
            guid of any Wasp aggregation component on the canvas).

    Returns:
        {"success": true, "result": {"aggregation_id", "toggle_id",
        "created_toggle", "pulse", "all_ids"}} or an error dict.
    """
    try:
        return _ok(macros.reset_aggregation(_client, aggregation_id))
    except (BridgeError, RegistryLookupError, ValueError) as exc:
        return _macro_error(exc)


def _macro_error(exc: Exception) -> Dict[str, Any]:
    if isinstance(exc, BridgeError):
        return exc.to_dict()
    if isinstance(exc, RegistryLookupError):
        return {
            "success": False,
            "error": "component_not_found",
            "message": str(exc),
            "suggestions": exc.suggestions,
        }
    return {"success": False, "error": "invalid_arguments", "message": str(exc)}


def main() -> None:
    """Entry point: run the FastMCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
