"""Core scripting tools: run_lua, get_project_state."""

from mcp.server.fastmcp import FastMCP
from server.connection import get_connection, ConnectionError
from server.script_tracker import get_tracker


def register(mcp: FastMCP):

    @mcp.tool()
    async def run_lua(code: str, undo_label: str = "AI Script",
                      timeout_ms: int = 10000) -> str:
        """Execute Lua code inside REAPER and return the result.

        The script runs in REAPER's Lua environment with full access to the
        reaper.* API. It is automatically wrapped in an undo block.

        All print() and reaper.ShowConsoleMsg() output is captured and returned.

        On error, returns the error message with a full stack trace, line number,
        and surrounding source context so you can fix and retry.

        Args:
            code: Lua source code to execute
            undo_label: Label for the undo history entry (default: "AI Script")
            timeout_ms: Maximum execution time in milliseconds (default: 10000)
        """
        tracker = get_tracker()
        conn = get_connection()

        try:
            result = await conn.execute(
                code,
                undo_label=undo_label,
                timeout=timeout_ms / 1000.0
            )
        except ConnectionError as e:
            return f"Connection error: {e}"

        # Track the execution
        error_msg = None
        if not result.get("success"):
            err = result.get("error", {})
            error_msg = err.get("message", "Unknown error") if isinstance(err, dict) else str(err)

        tracker.record_execution(
            code=code,
            elapsed_ms=result.get("elapsed_ms", 0),
            success=result.get("success", False),
            error=error_msg
        )

        # Format response
        parts = []

        if result.get("success"):
            if result.get("stdout"):
                parts.append(f"Output:\n{result['stdout']}")
            if result.get("result") is not None:
                parts.append(f"Return value: {result['result']}")
            if not parts:
                parts.append("Script executed successfully (no output)")
            parts.append(f"[{result.get('elapsed_ms', 0):.1f}ms]")
        else:
            parts.append("ERROR")
            err = result.get("error", {})
            if isinstance(err, dict):
                if err.get("message"):
                    parts.append(f"Message: {err['message']}")
                if err.get("line"):
                    parts.append(f"Line: {err['line']}")
                if err.get("source_context"):
                    context = err["source_context"]
                    if isinstance(context, list):
                        parts.append("Source:\n" + "\n".join(context))
                    else:
                        parts.append(f"Source:\n{context}")
                if err.get("traceback"):
                    parts.append(f"Traceback:\n{err['traceback']}")
            else:
                parts.append(str(err))

            if result.get("stdout"):
                parts.append(f"Output before error:\n{result['stdout']}")

        return "\n\n".join(parts)

    @mcp.tool()
    async def get_project_state() -> str:
        """Get the full state of the current REAPER project.

        Returns structured information about all tracks (name, volume, pan,
        mute, solo, armed, FX chain, items), markers, regions, tempo,
        time signature, cursor position, and transport state.

        Use this to understand what's in the project before writing scripts.
        """
        conn = get_connection()

        try:
            state = await conn.get_state()
        except ConnectionError as e:
            return f"Connection error: {e}"

        parts = []

        # Project info
        name = state.get("project_name", "Untitled")
        parts.append(f"Project: {name}")

        # Transport
        play_states = {0: "Stopped", 1: "Playing", 2: "Paused", 4: "Recording", 5: "Recording+Playing"}
        ps = state.get("play_state", 0)
        parts.append(f"Transport: {play_states.get(ps, f'Unknown ({ps})')}")

        # Tempo
        tempo = state.get("tempo", 120)
        ts = state.get("time_sig", {})
        parts.append(f"Tempo: {tempo:.1f} BPM, Time sig: {ts.get('numerator', 4)}/{ts.get('denominator', 4)}")
        parts.append(f"Cursor: {state.get('cursor', 0):.2f}s")

        # Tracks
        tracks = state.get("tracks", [])
        if tracks:
            parts.append(f"\nTracks ({len(tracks)}):")
            for t in tracks:
                flags = []
                if t.get("mute"): flags.append("MUTE")
                if t.get("solo"): flags.append("SOLO")
                if t.get("armed"): flags.append("REC")
                flag_str = f" [{', '.join(flags)}]" if flags else ""

                fx_str = ""
                if t.get("fx"):
                    fx_names = [fx["name"] for fx in t["fx"]]
                    fx_str = f" | FX: {', '.join(fx_names)}"

                items_str = ""
                if t.get("num_items", 0) > 0:
                    midi_items = sum(1 for item in t.get("items", []) if item.get("is_midi"))
                    audio_items = t["num_items"] - midi_items
                    item_parts = []
                    if midi_items: item_parts.append(f"{midi_items} MIDI")
                    if audio_items: item_parts.append(f"{audio_items} audio")
                    items_str = f" | Items: {', '.join(item_parts)}"

                vol_db = t.get("volume_db", 0)
                pan = t.get("pan", 0)
                pan_str = "C" if abs(pan) < 0.01 else f"L{int(abs(pan)*100)}" if pan < 0 else f"R{int(pan*100)}"

                parts.append(
                    f"  {t['index']+1}. {t['name']} | {vol_db:+.1f}dB {pan_str}{flag_str}{fx_str}{items_str}"
                )
        else:
            parts.append("\nNo tracks")

        # Markers
        markers = state.get("markers", [])
        if markers:
            parts.append(f"\nMarkers ({len(markers)}):")
            for m in markers:
                parts.append(f"  #{m['index']}: {m.get('name', '')} @ {m['position']:.2f}s")

        # Regions
        regions = state.get("regions", [])
        if regions:
            parts.append(f"\nRegions ({len(regions)}):")
            for r in regions:
                parts.append(f"  #{r['index']}: {r.get('name', '')} ({r['start']:.2f}s - {r['end']:.2f}s)")

        return "\n".join(parts)
