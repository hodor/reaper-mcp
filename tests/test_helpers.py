"""Tests for server/helpers.py"""

import math
import pytest
from server.helpers import (
    db_to_linear, linear_to_db, parse_volume, parse_pan, resolve_track_ref
)


class TestDbConversion:
    def test_zero_db_is_unity(self):
        assert db_to_linear(0) == pytest.approx(1.0)

    def test_minus_6db(self):
        assert db_to_linear(-6) == pytest.approx(0.5012, rel=0.01)

    def test_plus_6db(self):
        assert db_to_linear(6) == pytest.approx(1.9953, rel=0.01)

    def test_roundtrip(self):
        for db in [-12, -6, 0, 3, 6, 12]:
            assert linear_to_db(db_to_linear(db)) == pytest.approx(db, abs=0.01)

    def test_zero_linear_is_neg_inf(self):
        assert linear_to_db(0) == float('-inf')


class TestParseVolume:
    def test_db_string(self):
        assert parse_volume("-6dB") == pytest.approx(db_to_linear(-6), rel=0.01)

    def test_db_string_uppercase(self):
        assert parse_volume("-6DB") == pytest.approx(db_to_linear(-6), rel=0.01)

    def test_relative_plus(self):
        current = db_to_linear(0)
        result = parse_volume("+3dB", current)
        assert linear_to_db(result) == pytest.approx(3.0, abs=0.1)

    def test_relative_minus(self):
        current = db_to_linear(0)
        result = parse_volume("-3dB", current)
        assert linear_to_db(result) == pytest.approx(-3.0, abs=0.1)

    def test_linear_float(self):
        assert parse_volume(0.5) == pytest.approx(0.5)

    def test_large_number_treated_as_db(self):
        assert parse_volume(6) == pytest.approx(db_to_linear(6), rel=0.01)

    def test_dict_db(self):
        assert parse_volume({"db": -6}) == pytest.approx(db_to_linear(-6), rel=0.01)

    def test_dict_linear(self):
        assert parse_volume({"linear": 0.5}) == pytest.approx(0.5)

    def test_dict_relative(self):
        current = db_to_linear(0)
        result = parse_volume({"relative_db": 3}, current)
        assert linear_to_db(result) == pytest.approx(3.0, abs=0.1)


class TestParsePan:
    def test_center_string(self):
        assert parse_pan("C") == 0.0

    def test_left(self):
        assert parse_pan("L50") == pytest.approx(-0.5)

    def test_right(self):
        assert parse_pan("R30") == pytest.approx(0.3)

    def test_numeric(self):
        assert parse_pan(-0.7) == pytest.approx(-0.7)

    def test_clamps(self):
        assert parse_pan(5.0) == 1.0
        assert parse_pan(-5.0) == -1.0


class TestResolveTrackRef:
    TRACKS = [
        {"name": "Drums", "index": 0},
        {"name": "Electric Bass", "index": 1},
        {"name": "Lead Guitar", "index": 2},
        {"name": "Rhythm Guitar", "index": 3},
    ]

    def test_by_index(self):
        assert resolve_track_ref(1, self.TRACKS) == 0
        assert resolve_track_ref(2, self.TRACKS) == 1

    def test_by_exact_name(self):
        assert resolve_track_ref("Drums", self.TRACKS) == 0

    def test_by_partial_name(self):
        assert resolve_track_ref("Bass", self.TRACKS) == 1

    def test_case_insensitive(self):
        assert resolve_track_ref("drums", self.TRACKS) == 0

    def test_ambiguous(self):
        with pytest.raises(ValueError, match="Ambiguous"):
            resolve_track_ref("Guitar", self.TRACKS)

    def test_not_found(self):
        with pytest.raises(ValueError, match="No track found"):
            resolve_track_ref("Piano", self.TRACKS)

    def test_index_out_of_range(self):
        with pytest.raises(ValueError, match="out of range"):
            resolve_track_ref(10, self.TRACKS)
