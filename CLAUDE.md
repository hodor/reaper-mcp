# CLAUDE.md

## Project Overview

MCP server for REAPER DAW. Script-runner first: Claude writes Lua scripts, the MCP executes them in REAPER via TCP socket, and returns results with full error context (stack traces, line numbers, source context). 20 tools total — convenience tools for high-frequency actions, `run_lua` for everything else.

## Architecture

```
Claude (MCP client, stdio)
  → Python server (FastMCP, 20 tools)
    → TCP socket (localhost:9500, newline-delimited JSON)
      → Lua bridge (REAPER defer loop, Mavriq LuaSocket, non-blocking)
        → reaper.* API
```

### Key files
- **server/app.py** — FastMCP entry point, registers all tool modules, contains system instructions
- **server/__main__.py** — `python -m server` entry point
- **server/connection.py** — `ReaperConnection` async TCP client. Singleton via `get_connection()`. Handles connect, reconnect, request/response, ping.
- **server/tools/** — 6 tool modules, each exports `register(mcp)`:
  - `scripting.py` — `run_lua`, `get_project_state` (the core)
  - `transport.py` — play, stop, record, set_tempo, get_tempo
  - `tracks.py` — list_tracks, create_track, delete_track, set_volume, set_pan, mute/unmute, solo/unsolo
  - `midi.py` — insert_midi, read_midi
  - `api_search.py` — search_api, list_available_api
  - `analytics.py` — get_script_history, get_common_scripts
- **server/script_tracker.py** — `ScriptTracker` SQLite logger. Hash-based dedup, run counts, timing, error rates. Singleton via `get_tracker()`. DB at `~/.reaper-mcp/scripts.db`.
- **server/api_index.py** — `APIIndex` parses `reascripthelp.html` into SQLite FTS5 index. 713 functions. Singleton via `get_api_index()`. DB at `~/.reaper-mcp/api_index.db`.
- **server/helpers.py** — `db_to_linear`, `linear_to_db`, `parse_volume`, `parse_pan`, `resolve_track_ref`
- **lua/bridge.lua** — REAPER-side TCP server. Non-blocking socket in `reaper.defer()` loop. Commands: `exec` (run Lua with full error capture), `ping`, `state` (project dump), `list_api` (runtime function discovery).
- **lua/install.lua** — Run in REAPER to check if LuaSocket is installed
- **data/reascripthelp.html** — Bundled ReaScript API docs (713 functions)

## Commands

```bash
# Run the server
uv run python -m server

# Run tests
uv run pytest tests/ -v

# Install / reinstall
uv pip install -e "."
```

## Environment variables

- `REAPER_MCP_PORT` — TCP port (default: 9500)

## Key patterns

### Tool registration
Each module in `server/tools/` exports `register(mcp: FastMCP)`. Tools are defined as `@mcp.tool()` decorated async functions inside `register()`. All registered in `server/app.py`.

### Connection
All tools use `get_connection()` singleton. The connection is lazy — connects on first use. All communication is async via `asyncio.StreamReader`/`StreamWriter`.

```python
conn = get_connection()
result = await conn.execute("reaper.Main_OnCommand(1007, 0)")
state = await conn.get_state()
```

### Script tracking
Every `run_lua` call automatically tracks the script in SQLite:
- SHA256 hash as primary key — identical scripts increment `run_count`
- Individual runs logged in `script_runs` table
- `get_common_scripts()` finds patterns worth graduating to dedicated tools

### Convenience tools generate Lua
Convenience tools (volume, pan, etc.) don't use a separate protocol — they generate Lua code strings and call `conn.execute()`. The Lua bridge only speaks one language: Lua scripts.

### Track resolution
`resolve_track_ref(ref, tracks)` in helpers.py: accepts 1-based index or name string. Name matching is case-insensitive, supports partial matches (e.g., "bass" finds "Electric Bass"), raises `ValueError` on ambiguity or not-found.

### Volume/Pan parsing
- Volume: `-6`, `"-6dB"`, `"+3dB"` (relative), `0.5` (linear), `{"db": -6}`, `{"relative_db": 3}`
- Pan: `"L50"`, `"R30"`, `"C"`, `-1.0` to `1.0`

## Testing

```bash
uv run pytest tests/ -v                        # All tests (47)
uv run pytest tests/test_helpers.py -v         # Just helpers
uv run pytest tests/test_script_tracker.py -v  # Just tracker
```

- Unit tests don't require REAPER running
- `test_connection.py` tests that connection fails gracefully without a server
- `test_script_tracker.py` uses `tmp_path` fixture for isolated SQLite
- `test_api_index.py` tests parsing and search with temp DB

## REAPER setup

1. Install Mavriq LuaSocket: run `lua/install.lua` in REAPER for instructions
2. Load `lua/bridge.lua` as a REAPER script (Actions > Load script)
3. The bridge prints startup banner to REAPER console and listens on port 9500

## Protocol

Newline-delimited JSON over TCP:
- `{"method": "exec", "params": {"code": "...", "undo_label": "..."}, "id": 1}\n`
- `{"method": "ping", "id": 0}\n`
- `{"method": "state", "id": 2}\n`
- `{"method": "list_api", "params": {"filter": "MIDI"}, "id": 3}\n`

Responses: `{"result": ..., "error": null, "id": 1}\n`

Script execution response:
```json
{
  "success": true/false,
  "result": "return value",
  "stdout": "captured print() output",
  "error": {"message": "...", "line": 12, "traceback": "...", "source_context": ["..."]},
  "elapsed_ms": 45
}
```
