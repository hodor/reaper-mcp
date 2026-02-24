"""FastMCP server entry point."""

import logging
from mcp.server.fastmcp import FastMCP

from server.tools import scripting, transport, tracks, midi, api_search, analytics, setup

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "reaper-mcp",
    instructions="""You are connected to REAPER DAW via MCP. You can:

1. **Run Lua scripts** in REAPER using `run_lua`. You have full access to the reaper.* API.
   Scripts are auto-wrapped in undo blocks. Errors come back with stack traces and line numbers.

2. **Use convenience tools** for common actions: play/stop, volume/pan/mute/solo, track management.

3. **Search the API** with `search_api` to find the right ReaScript functions before writing scripts.

4. **Inspect the project** with `get_project_state` to see all tracks, items, FX, markers, tempo.

When doing anything beyond basic track/transport operations, write a Lua script with `run_lua`.
Use `search_api` if you're unsure which REAPER API function to use.
Use `get_project_state` to understand the current project before making changes.

Script tips:
- Use `print()` to return information (output is captured and returned to you)
- Scripts run synchronously — keep them short and focused
- reaper.Undo_BeginBlock/EndBlock are added automatically
- All reaper.* functions are available plus any installed extensions (SWS, JS, etc.)
"""
)

# Register all tool modules
scripting.register(mcp)
transport.register(mcp)
tracks.register(mcp)
midi.register(mcp)
api_search.register(mcp)
analytics.register(mcp)
setup.register(mcp)

logger.info("reaper-mcp server initialized")
