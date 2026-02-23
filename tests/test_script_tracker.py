"""Tests for server/script_tracker.py"""

import os
import tempfile
import pytest
from server.script_tracker import ScriptTracker


@pytest.fixture
def tracker(tmp_path):
    db_path = str(tmp_path / "test_scripts.db")
    return ScriptTracker(db_path=db_path)


class TestScriptTracker:
    def test_hash_deterministic(self):
        h1 = ScriptTracker.hash_code("print('hello')")
        h2 = ScriptTracker.hash_code("print('hello')")
        assert h1 == h2

    def test_hash_differs(self):
        h1 = ScriptTracker.hash_code("print('hello')")
        h2 = ScriptTracker.hash_code("print('world')")
        assert h1 != h2

    def test_record_and_retrieve(self, tracker):
        code = "print('test')"
        code_hash = tracker.record_execution(code, 10.5, True)

        script = tracker.get_script(code_hash)
        assert script is not None
        assert script.code == code
        assert script.run_count == 1
        assert script.error_count == 0
        assert script.total_elapsed_ms == pytest.approx(10.5)

    def test_duplicate_increments_count(self, tracker):
        code = "print('test')"
        h1 = tracker.record_execution(code, 10.0, True)
        h2 = tracker.record_execution(code, 15.0, True)
        assert h1 == h2

        script = tracker.get_script(h1)
        assert script.run_count == 2
        assert script.total_elapsed_ms == pytest.approx(25.0)

    def test_error_tracking(self, tracker):
        code = "bad code"
        tracker.record_execution(code, 1.0, False, error="syntax error")

        script = tracker.get_script(ScriptTracker.hash_code(code))
        assert script.error_count == 1
        assert script.last_error == "syntax error"

    def test_history(self, tracker):
        tracker.record_execution("print(1)", 5.0, True)
        tracker.record_execution("print(2)", 10.0, True)
        tracker.record_execution("print(3)", 15.0, False, "err")

        history = tracker.get_history(limit=10)
        assert len(history) == 3
        # Most recent first
        assert not history[0].success
        assert history[1].success

    def test_common_scripts(self, tracker):
        # Run same script 3 times
        for _ in range(3):
            tracker.record_execution("print('common')", 5.0, True)
        # Run another once
        tracker.record_execution("print('rare')", 5.0, True)

        common = tracker.get_common_scripts(min_runs=2)
        assert len(common) == 1
        assert common[0].run_count == 3

    def test_stats(self, tracker):
        tracker.record_execution("a()", 5.0, True)
        tracker.record_execution("a()", 5.0, True)
        tracker.record_execution("b()", 5.0, False, "err")

        stats = tracker.get_stats()
        assert stats["total_unique_scripts"] == 2
        assert stats["total_runs"] == 3
        assert stats["total_errors"] == 1
        assert stats["scripts_run_multiple_times"] == 1
