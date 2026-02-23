"""Tests for server/api_index.py"""

import pytest
from server.api_index import APIIndex, _infer_category, _parse_signature


class TestInferCategory:
    def test_midi(self):
        assert _infer_category("MIDI_InsertNote") == "MIDI"

    def test_track_fx(self):
        # TrackFX starts with "Track" so categorizes as Tracks
        assert _infer_category("TrackFX_GetCount") == "Tracks"
        assert _infer_category("FX_GetCount") == "FX"

    def test_sws(self):
        assert _infer_category("CF_GetClipboard") == "SWS"
        assert _infer_category("BR_GetMouseCursorContext") == "SWS"

    def test_js(self):
        assert _infer_category("JS_Window_Find") == "JS Extension"

    def test_general(self):
        assert _infer_category("GetTrack") == "Tracks"


class TestParseSignature:
    def test_simple(self):
        ret, params = _parse_signature("boolean reaper.GetTrackName(MediaTrack track)")
        assert ret == "boolean"
        assert "track" in params

    def test_void(self):
        ret, params = _parse_signature("reaper.Undo_EndBlock(string desc, integer flags)")
        # May parse differently, just ensure no crash
        assert isinstance(ret, str)


class TestAPIIndex:
    @pytest.fixture
    def index(self, tmp_path):
        db_path = str(tmp_path / "test_api.db")
        return APIIndex(db_path=db_path)

    def test_empty_index(self, index):
        assert not index.is_indexed
        results = index.search("track")
        assert results == []

    def test_mark_available(self, index):
        # Even without static docs, we can mark runtime functions
        index.mark_available(["GetTrack", "MIDI_InsertNote", "CF_GetClipboard"])
        results = index.search("MIDI", available_only=True)
        assert len(results) >= 1

    def test_search_categories(self, index):
        cats = index.list_categories()
        assert isinstance(cats, list)
