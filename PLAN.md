# reaper-mcp

The best AI interface for REAPER. Script-runner first, small tool surface, socket IPC.

## Philosophy

- Claude writes ReaScript. The MCP gives it a REPL with incredible error feedback and full context.
- 20 tools, not 756. Convenience tools for stuff you do every 30 seconds. Everything else: write a script.
- Socket connection to Lua bridge. No file polling.
- Every error comes back with a stack trace, line numbers, and source context.
- Track every script executed. Identify patterns. Graduate common scripts to dedicated tools over time.

## Architecture

```
Claude (MCP client, stdio)
  → Python server (FastMCP, 20 tools)
    → TCP socket (localhost:9500)
      → Lua bridge (REAPER defer loop, Mavriq LuaSocket, non-blocking)
        → reaper.* API
```

**Dependencies:**
- Python: FastMCP (via `uv`)
- REAPER: Mavriq LuaSocket (bundled / ReaPack install)
  - Cross-platform: Windows x64, macOS, Linux
  - Non-blocking via `settimeout(0)` in `reaper.defer()` loop

## Status

### Done
- [x] Lua bridge with TCP socket server, script execution, stdout capture, error tracing, undo blocks
- [x] Python async TCP client with reconnection, ping, timeouts
- [x] Script tracker (SQLite: hash dedup, run counts, timing, error rates)
- [x] API docs index (713 functions parsed from reascripthelp.html, FTS5 search)
- [x] 20 MCP tools across 6 modules (scripting, transport, tracks, midi, api_search, analytics)
- [x] Helpers: dB/linear conversion, pan parsing, track ref resolution
- [x] 47 unit tests, all passing
- [x] Project scaffolding (uv, pyproject.toml, .mcp.json)

### TODO
- [ ] Integration tests against live REAPER
- [ ] LuaSocket binary bundling (currently requires ReaPack install)
- [ ] Script timeout mechanism (`debug.sethook` with instruction count — needs investigation)
- [ ] `save` and `undo` convenience tools (wired up but not yet implemented)
- [ ] Reconnection backoff logic (currently connects once)
- [ ] API index bootstrap on first connect (auto-run `pairs(reaper)` to mark available functions)

## Tools (20)

### Script execution (the core)
| Tool | Status | Purpose |
|------|--------|---------|
| `run_lua(code, undo_label?, timeout_ms?)` | Done | Execute Lua in REAPER. Auto-wrapped in undo block. Returns result + stdout + errors with full stack trace + elapsed time |
| `get_project_state()` | Done | Full structured dump: tracks, items, FX, markers/regions, tempo, time sig, cursor, transport |

### API knowledge
| Tool | Status | Purpose |
|------|--------|---------|
| `search_api(query, limit?, available_only?)` | Done | FTS5 search over 713 ReaScript functions — signatures, descriptions, categories |
| `list_available_api(filter?)` | Done | Runtime discovery via `pairs(reaper)` — shows what's actually installed |

### Convenience
| Tool | Status | Purpose |
|------|--------|---------|
| `play` | Done | Start playback |
| `stop` | Done | Stop playback/recording |
| `record` | Done | Start recording |
| `set_tempo(bpm)` | Done | Set project tempo |
| `get_tempo()` | Done | Get tempo + time sig |
| `list_tracks()` | Done | Quick overview with volume/pan/mute/solo/FX |
| `create_track(name, index?)` | Done | Create track at position |
| `delete_track(ref)` | Done | Delete by name or index |
| `set_volume(track, value)` | Done | Accepts dB, linear, relative (+3dB) |
| `set_pan(track, value)` | Done | Accepts L50/R30/C or -1..1 |
| `mute(track)` / `unmute(track)` | Done | By name or index |
| `solo(track)` / `unsolo(track)` | Done | By name or index |
| `insert_midi(track, start_beat, length_beats, notes)` | Done | Quick note insertion |
| `read_midi(track)` | Done | Read MIDI notes as text |

### Analytics
| Tool | Status | Purpose |
|------|--------|---------|
| `get_script_history(limit?)` | Done | Recent scripts with timing, errors |
| `get_common_scripts(min_runs?)` | Done | Most-run scripts — candidates for new tools |

## IPC protocol

- **Transport:** TCP on `localhost:9500` (configurable via `REAPER_MCP_PORT`)
- **Framing:** Newline-delimited JSON (`\n` terminated)
- **Methods:** `exec`, `ping`, `state`, `list_api`
- **Request:** `{"method": "exec", "params": {"code": "..."}, "id": 1}\n`
- **Response:** `{"result": {...}, "error": null, "id": 1}\n`

## Script execution flow

1. Python hashes code (SHA256), logs to SQLite
2. Sends `{"method": "exec", "params": {"code": "..."}}` over socket
3. Lua bridge: overrides `print()`/`ShowConsoleMsg()`, wraps in undo block, runs via `xpcall` + `debug.traceback`
4. Returns: `{success, result, stdout, error: {message, line, traceback, source_context}, elapsed_ms}`
5. Python updates SQLite with timing/success/error, formats response for Claude

## Script deduplication

- SHA256 of exact code string
- `scripts` table: hash PK, code, run_count, error_count, total_elapsed_ms, first_seen, last_seen
- `script_runs` table: individual execution log
- `get_common_scripts(min_runs=2)` → candidates for dedicated MCP tools

## API documentation search

- 713 functions parsed from bundled `data/reascripthelp.html`
- SQLite FTS5 full-text search on name + signature + description
- Runtime discovery via `pairs(reaper)` marks what's actually available
- Categories inferred from naming patterns (MIDI, FX, Track, SWS, JS, etc.)

## Decisions

1. **Port:** Fixed 9500. Clear error if occupied, configurable via `REAPER_MCP_PORT`.
2. **Instances:** Single REAPER instance only.
3. **LuaSocket:** Bundle with project (ReaPack fallback for now).
4. **Script timeout:** Investigate after core is stable. Likely `debug.sethook` with instruction count.
5. **State diff:** Only on explicit `get_project_state()`, not automatic on every `run_lua`.
