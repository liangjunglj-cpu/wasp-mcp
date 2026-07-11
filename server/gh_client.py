"""TCP transport to the GH_MCP_Wasp Grasshopper bridge.

Protocol (PROTOCOL.md, "Transport"):
  - TCP, localhost only, default port 8090 (env override: WASP_MCP_PORT).
  - Request: one UTF-8 JSON object ``{"type": "<command>", "parameters": {...}}``,
    newline-terminated; client closes the connection after reading the response.
  - Response: one JSON object ``{"success": true, "result": {...}}`` or
    ``{"success": false, "error": "<message>"}``.

Typed errors are raised as :class:`BridgeError` with a machine-readable
``code`` (``bridge_unreachable``, ``bridge_timeout``, ``bridge_protocol``,
``bridge_command_failed``) plus a human hint where applicable.
"""

from __future__ import annotations

import json
import os
import socket
from typing import Any, Dict, Optional

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8090
CONNECT_TIMEOUT = 5.0   # seconds
READ_TIMEOUT = 60.0     # seconds (aggregations can take a while)

UNREACHABLE_HINT = (
    "Grasshopper does not appear to be running the WaspMCP bridge. "
    "Open Rhino + Grasshopper and place the WaspMCP component "
    "(GH_MCP_Wasp.gha) on the canvas; it listens on 127.0.0.1:{port}. "
    "Override the port with the WASP_MCP_PORT environment variable."
)


def bridge_token() -> str:
    """Resolve the optional shared-secret token (env WASP_MCP_TOKEN).

    PROTOCOL v0.5 "Optional shared-secret auth": when the WaspMCP component
    has a Token configured, every request must carry a top-level "token"
    field. An empty/absent env var means open access (no field sent). The
    value is read per request so a token set after server start still takes
    effect, and it MUST never be logged or embedded in error messages.
    """
    return os.environ.get("WASP_MCP_TOKEN", "").strip()


def bridge_port() -> int:
    """Resolve the bridge port (env override WASP_MCP_PORT, default 8090)."""
    raw = os.environ.get("WASP_MCP_PORT", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            raise BridgeError(
                "bridge_protocol",
                f"WASP_MCP_PORT is not a valid integer: {raw!r}",
            ) from None
    return DEFAULT_PORT


class BridgeError(Exception):
    """Typed transport/command error from the Grasshopper bridge."""

    def __init__(self, code: str, message: str, hint: Optional[str] = None):
        self.code = code
        self.message = message
        self.hint = hint
        super().__init__(f"{code}: {message}")

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"success": False, "error": self.code, "message": self.message}
        if self.hint:
            out["hint"] = self.hint
        return out


class GHClient:
    """One-shot-connection JSON client for the WaspMCP TCP bridge."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: Optional[int] = None,
        connect_timeout: float = CONNECT_TIMEOUT,
        read_timeout: float = READ_TIMEOUT,
    ):
        self.host = host
        self.port = port if port is not None else bridge_port()
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout

    # -- low level ---------------------------------------------------------

    def send_raw(self, command_type: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send one command, return the full parsed response envelope.

        Raises BridgeError only for transport-level failures; a
        ``{"success": false}`` envelope is returned as-is.
        """
        command: Dict[str, Any] = {"type": command_type,
                                   "parameters": parameters or {}}
        token = bridge_token()
        if token:
            # v0.5 shared-secret auth: top-level field on EVERY request.
            # Never logged, never echoed into BridgeError messages.
            command["token"] = token
        payload = (json.dumps(command) + "\n").encode("utf-8")

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.connect_timeout)
            try:
                sock.connect((self.host, self.port))
            except (ConnectionRefusedError, socket.timeout, TimeoutError, OSError) as exc:
                raise BridgeError(
                    "bridge_unreachable",
                    f"Could not connect to Grasshopper bridge at "
                    f"{self.host}:{self.port} ({exc.__class__.__name__}: {exc})",
                    hint=UNREACHABLE_HINT.format(port=self.port),
                ) from exc

            try:
                sock.sendall(payload)
            except OSError as exc:
                raise BridgeError(
                    "bridge_unreachable",
                    f"Connection to bridge lost while sending: {exc}",
                    hint=UNREACHABLE_HINT.format(port=self.port),
                ) from exc

            sock.settimeout(self.read_timeout)
            buffer = b""
            while True:
                try:
                    chunk = sock.recv(65536)
                except (socket.timeout, TimeoutError) as exc:
                    raise BridgeError(
                        "bridge_timeout",
                        f"No complete response from bridge within "
                        f"{self.read_timeout:.0f}s for command {command_type!r}",
                        hint="The Grasshopper solution may be busy; try gh_canvas_state "
                             "to check solutionState, or increase the timeout.",
                    ) from exc
                except OSError as exc:
                    raise BridgeError(
                        "bridge_protocol",
                        f"Socket error while reading response: {exc}",
                    ) from exc

                if not chunk:
                    break  # connection closed by bridge
                buffer += chunk

                # Bridge replies end with a newline; also accept a complete
                # JSON object without waiting for connection close.
                parsed = self._try_parse(buffer)
                if parsed is not None:
                    return parsed

            if not buffer:
                raise BridgeError(
                    "bridge_protocol",
                    f"Bridge closed the connection without a response for {command_type!r}",
                )
            parsed = self._try_parse(buffer)
            if parsed is None:
                raise BridgeError(
                    "bridge_protocol",
                    f"Bridge returned unparseable data for {command_type!r}: "
                    f"{buffer[:200]!r}",
                )
            return parsed
        finally:
            try:
                sock.close()
            except OSError:
                pass

    @staticmethod
    def _try_parse(buffer: bytes) -> Optional[Dict[str, Any]]:
        """Attempt to parse the accumulated buffer as one JSON object."""
        try:
            text = buffer.decode("utf-8-sig").strip()
        except UnicodeDecodeError:
            return None  # partial multibyte sequence; keep reading
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    # -- high level --------------------------------------------------------

    def call(self, command_type: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a command and return ``result``; raise BridgeError on failure."""
        response = self.send_raw(command_type, parameters)
        if response.get("success"):
            result = response.get("result", {})
            return result if isinstance(result, dict) else {"value": result}
        raise BridgeError(
            "bridge_command_failed",
            str(response.get("error", "unknown bridge error")),
        )
