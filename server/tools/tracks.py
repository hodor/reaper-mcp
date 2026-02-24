"""Track tools: list, create, delete, volume, pan, mute, solo."""

from typing import Union
from mcp.server.fastmcp import FastMCP
from server.connection import get_connection, ConnectionError
from server.helpers import parse_volume, parse_pan, linear_to_db


def register(mcp: FastMCP):

    @mcp.tool()
    async def list_tracks() -> str:
        """List all tracks in the project with their key properties."""
        conn = get_connection()
        try:
            state = await conn.get_state()
        except ConnectionError as e:
            return f"Error: {e}"

        tracks = state.get("tracks", [])
        if not tracks:
            return "No tracks in project"

        lines = [f"{len(tracks)} tracks:"]
        for t in tracks:
            flags = []
            if t.get("mute"): flags.append("M")
            if t.get("solo"): flags.append("S")
            if t.get("armed"): flags.append("R")
            flag_str = f" [{'/'.join(flags)}]" if flags else ""

            vol_db = t.get("volume_db", 0)
            pan = t.get("pan", 0)
            pan_str = "C" if abs(pan) < 0.01 else f"L{int(abs(pan)*100)}" if pan < 0 else f"R{int(pan*100)}"

            fx_count = len(t.get("fx", []))
            fx_str = f" | {fx_count} FX" if fx_count else ""

            lines.append(
                f"  {t['index']+1}. {t['name']} | {vol_db:+.1f}dB {pan_str}{flag_str}{fx_str}"
            )
        return "\n".join(lines)

    @mcp.tool()
    async def create_track(name: str, index: int = -1) -> str:
        """Create a new track.

        Args:
            name: Name for the new track
            index: Position to insert (1-based). -1 = end of track list
        """
        conn = get_connection()
        try:
            result = await conn.execute(f"""
                local count = reaper.CountTracks(0)
                local idx = {index}
                if idx < 0 then idx = count end
                if idx > 0 then idx = idx - 1 end
                reaper.InsertTrackAtIndex(idx, true)
                local track = reaper.GetTrack(0, idx)
                reaper.GetSetMediaTrackInfo_String(track, "P_NAME", {repr(name)}, true)
                print("Created track " .. (idx + 1) .. ": " .. {repr(name)})
            """, undo_label=f"Create track: {name}")
            if result.get("success"):
                return result.get("stdout", f"Created track: {name}")
            return f"Error: {result.get('error', {}).get('message', 'unknown')}"
        except ConnectionError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def delete_track(track: Union[str, int]) -> str:
        """Delete a track by name or index (1-based).

        Args:
            track: Track name or 1-based index number
        """
        conn = get_connection()
        try:
            if isinstance(track, int):
                idx = track - 1
                result = await conn.execute(f"""
                    local track = reaper.GetTrack(0, {idx})
                    if not track then
                        print("ERROR: No track at index {track}")
                        return
                    end
                    local _, name = reaper.GetTrackName(track)
                    reaper.DeleteTrack(track)
                    print("Deleted track {track}: " .. name)
                """, undo_label="Delete track")
            else:
                result = await conn.execute(f"""
                    local target = ({repr(track)}):lower()
                    for i = 0, reaper.CountTracks(0) - 1 do
                        local tr = reaper.GetTrack(0, i)
                        local _, name = reaper.GetTrackName(tr)
                        if name:lower():find(target, 1, true) then
                            reaper.DeleteTrack(tr)
                            print("Deleted track " .. (i+1) .. ": " .. name)
                            return
                        end
                    end
                    print("ERROR: No track found matching '" .. ({repr(track)}) .. "'")
                """, undo_label=f"Delete track: {track}")

            if result.get("success"):
                return result.get("stdout", "Done")
            return f"Error: {result.get('error', {}).get('message', 'unknown')}"
        except ConnectionError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def set_volume(track: Union[str, int], volume: Union[str, float]) -> str:
        """Set track volume.

        Args:
            track: Track name or 1-based index
            volume: Volume value. Accepts:
                - dB: -6, "-6dB"
                - Relative: "+3dB", "-3dB" (relative to current)
                - Linear: 0.5 (values between -1 and 1 treated as linear)
        """
        conn = get_connection()
        try:
            # Get current state to resolve track and current volume
            state = await conn.get_state()
            tracks = state.get("tracks", [])

            from server.helpers import resolve_track_ref
            try:
                idx = resolve_track_ref(track, tracks)
            except ValueError as e:
                return str(e)

            current_linear = tracks[idx]["volume_linear"]
            try:
                new_linear = parse_volume(volume, current_linear)
            except (ValueError, TypeError) as e:
                return f"Invalid volume: {e}"

            new_db = linear_to_db(new_linear)
            old_db = tracks[idx]["volume_db"]
            name = tracks[idx]["name"]

            result = await conn.execute(f"""
                local track = reaper.GetTrack(0, {idx})
                reaper.SetMediaTrackInfo_Value(track, "D_VOL", {new_linear})
            """, undo_label=f"Volume: {name}")

            if result.get("success"):
                return f"{name}: {old_db:+.1f}dB -> {new_db:+.1f}dB"
            return f"Error: {result.get('error', {}).get('message', 'unknown')}"
        except ConnectionError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def set_pan(track: Union[str, int], pan: Union[str, float]) -> str:
        """Set track pan position.

        Args:
            track: Track name or 1-based index
            pan: Pan value. Accepts:
                - Numeric: -1.0 (full left) to 1.0 (full right)
                - String: "L50" (50% left), "R30" (30% right), "C" (center)
        """
        conn = get_connection()
        try:
            state = await conn.get_state()
            tracks = state.get("tracks", [])

            from server.helpers import resolve_track_ref
            try:
                idx = resolve_track_ref(track, tracks)
            except ValueError as e:
                return str(e)

            try:
                pan_val = parse_pan(pan)
            except (ValueError, TypeError) as e:
                return f"Invalid pan: {e}"

            name = tracks[idx]["name"]
            result = await conn.execute(f"""
                local track = reaper.GetTrack(0, {idx})
                reaper.SetMediaTrackInfo_Value(track, "D_PAN", {pan_val})
            """, undo_label=f"Pan: {name}")

            pan_str = "C" if abs(pan_val) < 0.01 else f"L{int(abs(pan_val)*100)}" if pan_val < 0 else f"R{int(pan_val*100)}"
            if result.get("success"):
                return f"{name}: pan -> {pan_str}"
            return f"Error: {result.get('error', {}).get('message', 'unknown')}"
        except ConnectionError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def mute(track: Union[str, int]) -> str:
        """Mute a track.

        Args:
            track: Track name or 1-based index
        """
        return await _set_flag(track, "B_MUTE", 1, "Muted")

    @mcp.tool()
    async def unmute(track: Union[str, int]) -> str:
        """Unmute a track.

        Args:
            track: Track name or 1-based index
        """
        return await _set_flag(track, "B_MUTE", 0, "Unmuted")

    @mcp.tool()
    async def solo(track: Union[str, int]) -> str:
        """Solo a track.

        Args:
            track: Track name or 1-based index
        """
        return await _set_flag(track, "I_SOLO", 2, "Soloed")

    @mcp.tool()
    async def unsolo(track: Union[str, int]) -> str:
        """Unsolo a track.

        Args:
            track: Track name or 1-based index
        """
        return await _set_flag(track, "I_SOLO", 0, "Unsoloed")


    async def _set_flag(track_ref: Union[str, int], param: str, value: int, action: str) -> str:
        conn = get_connection()
        try:
            state = await conn.get_state()
            tracks = state.get("tracks", [])

            from server.helpers import resolve_track_ref
            try:
                idx = resolve_track_ref(track_ref, tracks)
            except ValueError as e:
                return str(e)

            name = tracks[idx]["name"]
            result = await conn.execute(f"""
                local track = reaper.GetTrack(0, {idx})
                reaper.SetMediaTrackInfo_Value(track, "{param}", {value})
            """, undo_label=f"{action}: {name}")

            if result.get("success"):
                return f"{action}: {name}"
            return f"Error: {result.get('error', {}).get('message', 'unknown')}"
        except ConnectionError as e:
            return f"Error: {e}"
