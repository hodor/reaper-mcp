"""Transport tools: play, stop, record, tempo."""

from mcp.server.fastmcp import FastMCP
from server.connection import get_connection, ConnectionError


def register(mcp: FastMCP):

    @mcp.tool()
    async def play() -> str:
        """Start playback in REAPER."""
        conn = get_connection()
        try:
            await conn.execute("reaper.Main_OnCommand(1007, 0)")  # Transport: Play
            return "Playing"
        except ConnectionError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def stop() -> str:
        """Stop playback/recording in REAPER."""
        conn = get_connection()
        try:
            await conn.execute("reaper.Main_OnCommand(1016, 0)")  # Transport: Stop
            return "Stopped"
        except ConnectionError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def record() -> str:
        """Start recording in REAPER. Make sure a track is armed first."""
        conn = get_connection()
        try:
            await conn.execute("reaper.Main_OnCommand(1013, 0)")  # Transport: Record
            return "Recording"
        except ConnectionError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def set_tempo(bpm: float) -> str:
        """Set the project tempo.

        Args:
            bpm: Tempo in beats per minute (20-960)
        """
        if bpm < 20 or bpm > 960:
            return f"BPM must be between 20 and 960, got {bpm}"
        conn = get_connection()
        try:
            result = await conn.execute(f"""
                local old = reaper.Master_GetTempo()
                reaper.SetCurrentBPM(0, {bpm}, true)
                return string.format("%.1f -> %.1f BPM", old, {bpm})
            """)
            if result.get("success"):
                return result.get("stdout", "") or result.get("result", f"Tempo set to {bpm} BPM")
            return f"Error: {result.get('error', {}).get('message', 'unknown')}"
        except ConnectionError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def get_tempo() -> str:
        """Get the current tempo and time signature."""
        conn = get_connection()
        try:
            result = await conn.execute("""
                local tempo = reaper.Master_GetTempo()
                local ts_num, ts_den = reaper.TimeMap_GetTimeSigAtTime(0, 0)
                print(string.format("%.1f BPM, %d/%d time signature", tempo, ts_num, ts_den))
            """)
            if result.get("success"):
                return result.get("stdout", "")
            return f"Error: {result.get('error', {}).get('message', 'unknown')}"
        except ConnectionError as e:
            return f"Error: {e}"
