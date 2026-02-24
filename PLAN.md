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

### TODO — Core
- [ ] Integration tests against live REAPER
- [x] LuaSocket binary bundling (bundled Win/Mac/Linux in lua/deps/)
- [ ] Script timeout mechanism (`debug.sethook` with instruction count — needs investigation)
- [ ] `save` and `undo` convenience tools (wired up but not yet implemented)
- [ ] Reconnection backoff logic (currently connects once)
- [ ] API index bootstrap on first connect (auto-run `pairs(reaper)` to mark available functions)

### TODO — AI Composition Backends
These were implemented in the old `total-reaper-mcp` project (`server/ai/`) and need to be ported/integrated into the script-runner architecture. The idea: dedicated tools that leverage external AI models for music generation, feeding their output into REAPER via `run_lua`.

- [ ] **Composer's Assistant** integration
  - Multi-track MIDI infilling/generation with fine-grained user control
  - Paper: [Composer's Assistant 2 (arXiv:2407.14700)](https://arxiv.org/abs/2407.14700)
  - Repo: [m-malandro/composers-assistant](https://github.com/m-malandro/composers-assistant)
  - REAPER-specific version: [m-malandro/composers-assistant-REAPER](https://github.com/m-malandro/composers-assistant-REAPER)
  - T5-based transformer, supports rhythmic conditioning, note density, pitch, stylistic constraints
  - Expects a sibling directory clone: `../composers-assistant/`
  - Needs: model weights, tokenizer, torch + transformers deps
  - Old implementation: `server/ai/composers_assistant.py`
  - Best for: infilling (generate a part that fits with existing tracks), multi-track coherent generation

- [ ] **MIDI-GPT** integration
  - Controllable generative model for computer-assisted multitrack composition
  - Paper: [MIDI-GPT (arXiv:2501.17011)](https://arxiv.org/abs/2501.17011)
  - Repo: [Metacreation-Lab/MIDI-GPT](https://github.com/Metacreation-Lab/MIDI-GPT)
  - Transformer-based, supports track/bar-level infilling, conditioning on instrument type, style, note density, polyphony, duration
  - Expects a sibling directory clone: `../midi-gpt/`
  - Needs: model weights, torch + transformers deps
  - Old implementation: `server/ai/midi_gpt.py`
  - Best for: controllable generation with style/genre/density parameters

- [ ] **Claude-as-composer** (prompt-based generation)
  - Two-phase: gather project context → Claude generates MIDI note arrays → insert via `insert_midi` or `run_lua`
  - Already partially works via `run_lua` + Claude's own knowledge
  - Could add a dedicated `generate_music(what, style, bars, key)` tool that builds context prompts
  - Old implementation: `server/ai/claude_backend.py`, `server/dsl/generation_helpers.py`

- [ ] **Backend router**
  - Auto-select best backend based on task (infilling → Composer's Assistant, controllable gen → MIDI-GPT, creative/enhancement → Claude)
  - Old implementation: `server/ai/router.py`
  - Tool: `ai_generate(what, style?, bars?, key?, backend?)` — routes to the right backend

- [ ] **Rule-based pattern generator** (fallback)
  - No external deps, generates basic drum/bass/chord patterns
  - Useful when no AI models are available
  - Old implementation: `server/ai/pattern_generator.py`, `server/ai/music_theory.py`

### TODO — AI Composition Tools
| Tool | Status | Purpose |
|------|--------|---------|
| `generate_music(what, style?, bars?, key?, backend?)` | TODO | Generate MIDI via AI backend (Composer's Assistant, MIDI-GPT, Claude, or fallback) |
| `enhance_music(track, instruction?)` | TODO | Humanize, add variation, make more interesting — using AI |
| `continue_music(track, bars?)` | TODO | Extend existing music using AI |
| `ai_backends(action?)` | TODO | List/configure available AI backends |

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

## AI Composition Architecture

The script-runner approach changes how AI generation works compared to the old 756-tool project:

```
User: "generate a funky bassline"
  → generate_music(what="bass", style="funk", bars=4)
    → Router picks backend (e.g., MIDI-GPT for controllable generation)
    → Backend generates MIDI note data
    → run_lua() inserts the notes into REAPER
    → Returns: what was generated, which track, preview of notes
```

### Backends (from old project, to be ported)

| Backend | Best for | Requires | Links |
|---------|----------|----------|-------|
| Claude (prompt-based) | Enhancement, creative decisions, arrangement | Always available | — |
| [Composer's Assistant](https://github.com/m-malandro/composers-assistant) | Multi-track infilling, coherent parts | Sibling clone + model weights + torch | [Paper](https://arxiv.org/abs/2407.14700) |
| [MIDI-GPT](https://github.com/Metacreation-Lab/MIDI-GPT) | Controllable generation with style params | Sibling clone + model weights + torch | [Paper](https://arxiv.org/abs/2501.17011) |
| Pattern generator | Basic drums/bass/chords (no AI needed) | Nothing | — |

### Key difference from old project
Old: `dsl_generate` returns a prompt → Claude generates notes → Claude calls `dsl_midi_insert` (3 round trips, fragile)
New: `generate_music` does everything in one call — picks backend, generates, inserts, returns result. Claude can also just write a Lua script to do it manually if needed.

### Environment variables for backends
- `COMPOSERS_ASSISTANT_DIR` — Path to Composer's Assistant clone (default: `../Composers-Assistant-Official/`)
- `MIDI_GPT_DIR` — Path to MIDI-GPT clone (default: `../midi-gpt/`)

## Decisions

1. **Port:** Fixed 9500. Clear error if occupied, configurable via `REAPER_MCP_PORT`.
2. **Instances:** Single REAPER instance only.
3. **LuaSocket:** Bundle with project (ReaPack fallback for now).
4. **Script timeout:** Investigate after core is stable. Likely `debug.sethook` with instruction count.
5. **State diff:** Only on explicit `get_project_state()`, not automatic on every `run_lua`.
