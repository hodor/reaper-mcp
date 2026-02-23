"""MIDI tools: insert_midi, read_midi."""

from typing import Union, List
from mcp.server.fastmcp import FastMCP
from server.connection import get_connection, ConnectionError


def register(mcp: FastMCP):

    @mcp.tool()
    async def insert_midi(track: Union[str, int], start_beat: float,
                          length_beats: float, notes: list) -> str:
        """Insert MIDI notes into a track.

        Creates a new MIDI item and inserts notes. Beats are relative to project start.

        Args:
            track: Track name or 1-based index
            start_beat: Start position in beats (beat 1 = project start)
            length_beats: Length of the MIDI item in beats
            notes: List of note dicts, each with:
                - pitch: MIDI note number (0-127, 60=C4)
                - start: Start offset in beats from item start
                - length: Duration in beats
                - velocity: 1-127 (default 100)
                - channel: 0-15 (default 0)
        """
        conn = get_connection()

        # Build Lua code to create item and insert notes
        note_inserts = []
        for i, note in enumerate(notes):
            pitch = int(note.get("pitch", 60))
            start = float(note.get("start", 0))
            length = float(note.get("length", 0.5))
            vel = int(note.get("velocity", 100))
            ch = int(note.get("channel", 0))
            note_inserts.append(
                f"  reaper.MIDI_InsertNote(take, false, false, "
                f"ppq({start}), ppq({start + length}), {ch}, {pitch}, {vel}, true)"
            )

        notes_code = "\n".join(note_inserts)

        code = f"""
            -- Resolve track
            local track_ref = {repr(str(track)) if isinstance(track, str) else f'reaper.GetTrack(0, {int(track) - 1})'}
            local tr
            if type(track_ref) == "string" then
                local target = track_ref:lower()
                for i = 0, reaper.CountTracks(0) - 1 do
                    local t = reaper.GetTrack(0, i)
                    local _, name = reaper.GetTrackName(t)
                    if name:lower():find(target, 1, true) then
                        tr = t
                        break
                    end
                end
                if not tr then
                    print("ERROR: No track found matching '" .. track_ref .. "'")
                    return
                end
            else
                tr = track_ref
            end

            -- Convert beats to time
            local tempo = reaper.Master_GetTempo()
            local beat_dur = 60.0 / tempo
            local start_time = ({start_beat} - 1) * beat_dur
            local end_time = start_time + {length_beats} * beat_dur

            -- Create MIDI item
            local item = reaper.CreateNewMIDIItemInProj(tr, start_time, end_time)
            local take = reaper.GetActiveTake(item)

            -- Helper: beat offset to PPQ (960 PPQ per beat)
            local item_start_ppq = reaper.MIDI_GetPPQPosFromProjTime(take, start_time)
            local function ppq(beat_offset)
                return item_start_ppq + beat_offset * 960
            end

            -- Insert notes
{notes_code}

            reaper.MIDI_Sort(take)

            local _, track_name = reaper.GetTrackName(tr)
            print(string.format("Inserted %d notes into '%s' at beat %.1f (%.2fs)",
                {len(notes)}, track_name, {start_beat}, start_time))
        """

        try:
            result = await conn.execute(code, undo_label="Insert MIDI")
            if result.get("success"):
                return result.get("stdout", f"Inserted {len(notes)} notes")
            return f"Error: {result.get('error', {}).get('message', 'unknown')}"
        except ConnectionError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def read_midi(track: Union[str, int]) -> str:
        """Read MIDI notes from a track as human-readable text.

        Shows all notes with their pitch (note name), position, duration,
        velocity, and channel.

        Args:
            track: Track name or 1-based index
        """
        conn = get_connection()

        code = f"""
            local track_ref = {repr(str(track)) if isinstance(track, str) else f'reaper.GetTrack(0, {int(track) - 1})'}
            local tr
            if type(track_ref) == "string" then
                local target = track_ref:lower()
                for i = 0, reaper.CountTracks(0) - 1 do
                    local t = reaper.GetTrack(0, i)
                    local _, name = reaper.GetTrackName(t)
                    if name:lower():find(target, 1, true) then
                        tr = t
                        break
                    end
                end
                if not tr then
                    print("ERROR: No track found matching '" .. track_ref .. "'")
                    return
                end
            else
                tr = track_ref
                if not tr then
                    print("ERROR: Invalid track")
                    return
                end
            end

            local _, track_name = reaper.GetTrackName(tr)
            local note_names = {{"C","C#","D","D#","E","F","F#","G","G#","A","A#","B"}}

            local function pitch_name(p)
                return note_names[(p % 12) + 1] .. math.floor(p / 12 - 1)
            end

            local total_notes = 0
            local num_items = reaper.CountTrackMediaItems(tr)

            for item_idx = 0, num_items - 1 do
                local item = reaper.GetTrackMediaItem(tr, item_idx)
                local take = reaper.GetActiveTake(item)
                if take and reaper.TakeIsMIDI(take) then
                    local _, note_count = reaper.MIDI_CountEvts(take)
                    if note_count > 0 then
                        local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
                        print(string.format("Item at %.2fs (%d notes):", item_pos, note_count))

                        for n = 0, math.min(note_count, 200) - 1 do
                            local _, _, _, startppq, endppq, ch, pitch, vel = reaper.MIDI_GetNote(take, n)
                            local start_time = reaper.MIDI_GetProjTimeFromPPQPos(take, startppq)
                            local end_time = reaper.MIDI_GetProjTimeFromPPQPos(take, endppq)
                            local dur = end_time - start_time
                            local tempo = reaper.Master_GetTempo()
                            local start_beat = start_time * tempo / 60 + 1
                            local dur_beats = dur * tempo / 60

                            print(string.format("  %s (%-3d) | beat %6.2f | dur %.2f beats | vel %3d | ch %d",
                                pitch_name(pitch), pitch, start_beat, dur_beats, vel, ch))
                        end

                        if note_count > 200 then
                            print(string.format("  ... and %d more notes", note_count - 200))
                        end
                        total_notes = total_notes + note_count
                    end
                end
            end

            if total_notes == 0 then
                print("No MIDI notes found on track '" .. track_name .. "'")
            else
                print(string.format("\\nTotal: %d notes on '%s'", total_notes, track_name))
            end
        """

        try:
            result = await conn.execute(code)
            if result.get("success"):
                return result.get("stdout", "No output")
            return f"Error: {result.get('error', {}).get('message', 'unknown')}"
        except ConnectionError as e:
            return f"Error: {e}"
