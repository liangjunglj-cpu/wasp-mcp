# wasp-mcp-server

MCP server that lets Claude (or any MCP client) drive [Wasp](https://github.com/ar0551/Wasp)
discrete aggregation — and general Grasshopper work — on a **live Grasshopper
canvas**: place and wire components, set sliders/panels/toggles, run
aggregations with seeds and fields, read outputs, capture the canvas and
viewport, and bake results into Rhino.

Generation is knowledge-guided: parameter aliases, wiring topology, and
staged templates distilled from the Wasp example corpus ship with the
package (`knowledge/`, see `LICENSE-KNOWLEDGE.md`), so the model composes
canonical Wasp workflows instead of guessing wire routes.

## Setup

You need Rhino 8 for Windows with Grasshopper, and
[Wasp](https://www.food4rhino.com/en/app/wasp) installed for the
aggregation workflows.

1. **Bridge** — in Rhino 8 run `_PackageManager`, search
   `wasp-mcp-bridge`, install. Open Grasshopper and drop the **WaspMCP**
   component on the canvas; it listens on `127.0.0.1:8090` (local only).
2. **Server** — with [uv](https://docs.astral.sh/uv/) installed
   (`winget install astral-sh.uv`), register with Claude:

   ```json
   {
     "mcpServers": {
       "WaspMCP": {
         "command": "uvx",
         "args": ["wasp-mcp-server"]
       }
     }
   }
   ```

   (Claude Desktop: `%APPDATA%\Claude\claude_desktop_config.json`;
   Claude Code: `claude mcp add WaspMCP -- uvx wasp-mcp-server`.)
3. **Restart Claude** with Grasshopper open and the WaspMCP component on
   the canvas. Optional shared-secret auth: set the component's `Token`
   input and the `WASP_MCP_TOKEN` environment variable to the same value.

Full protocol, cookbook, and tool reference:
https://github.com/liangjunglj-cpu/wasp-mcp

## What ships here

Only self-authored code and knowledge derived as factual observations from
openly licensed examples. Wasp itself (LGPL-3.0) is **not** bundled — the
bridge instantiates your locally installed Wasp UserObjects at runtime. See
`THIRD-PARTY-NOTICES.md`.
