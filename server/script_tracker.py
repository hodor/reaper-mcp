"""Script tracking and analytics with SQLite."""

import hashlib
import sqlite3
import time
import os
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class ScriptRecord:
    hash: str
    code: str
    run_count: int
    error_count: int
    total_elapsed_ms: float
    first_seen: float
    last_seen: float
    last_error: Optional[str]

    @property
    def avg_elapsed_ms(self) -> float:
        return self.total_elapsed_ms / self.run_count if self.run_count > 0 else 0

    @property
    def error_rate(self) -> float:
        return self.error_count / self.run_count if self.run_count > 0 else 0


@dataclass
class ScriptRun:
    id: int
    hash: str
    timestamp: float
    elapsed_ms: float
    success: bool
    error: Optional[str]


DB_DIR = os.path.join(os.path.expanduser("~"), ".reaper-mcp")
DB_PATH = os.path.join(DB_DIR, "scripts.db")


class ScriptTracker:
    """Track script executions in SQLite for analytics."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS scripts (
                    hash TEXT PRIMARY KEY,
                    code TEXT NOT NULL,
                    run_count INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    total_elapsed_ms REAL DEFAULT 0,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    last_error TEXT
                );

                CREATE TABLE IF NOT EXISTS script_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hash TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    elapsed_ms REAL DEFAULT 0,
                    success INTEGER NOT NULL,
                    error TEXT,
                    FOREIGN KEY (hash) REFERENCES scripts(hash)
                );

                CREATE INDEX IF NOT EXISTS idx_runs_hash ON script_runs(hash);
                CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON script_runs(timestamp);
                CREATE INDEX IF NOT EXISTS idx_scripts_run_count ON scripts(run_count DESC);
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @staticmethod
    def hash_code(code: str) -> str:
        """SHA256 hash of the exact code string."""
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    def record_execution(self, code: str, elapsed_ms: float, success: bool,
                         error: Optional[str] = None) -> str:
        """Record a script execution. Returns the code hash."""
        code_hash = self.hash_code(code)
        now = time.time()

        with self._connect() as conn:
            # Upsert into scripts
            existing = conn.execute(
                "SELECT hash FROM scripts WHERE hash = ?", (code_hash,)
            ).fetchone()

            if existing:
                conn.execute("""
                    UPDATE scripts SET
                        run_count = run_count + 1,
                        error_count = error_count + ?,
                        total_elapsed_ms = total_elapsed_ms + ?,
                        last_seen = ?,
                        last_error = CASE WHEN ? IS NOT NULL THEN ? ELSE last_error END
                    WHERE hash = ?
                """, (0 if success else 1, elapsed_ms, now,
                      error, error, code_hash))
            else:
                conn.execute("""
                    INSERT INTO scripts (hash, code, run_count, error_count,
                                        total_elapsed_ms, first_seen, last_seen, last_error)
                    VALUES (?, ?, 1, ?, ?, ?, ?, ?)
                """, (code_hash, code, 0 if success else 1,
                      elapsed_ms, now, now, error))

            # Log the individual run
            conn.execute("""
                INSERT INTO script_runs (hash, timestamp, elapsed_ms, success, error)
                VALUES (?, ?, ?, ?, ?)
            """, (code_hash, now, elapsed_ms, 1 if success else 0, error))

        return code_hash

    def get_history(self, limit: int = 20) -> List[ScriptRun]:
        """Get recent script runs."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT id, hash, timestamp, elapsed_ms, success, error
                FROM script_runs
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,)).fetchall()

        return [ScriptRun(
            id=r[0], hash=r[1], timestamp=r[2],
            elapsed_ms=r[3], success=bool(r[4]), error=r[5]
        ) for r in rows]

    def get_common_scripts(self, min_runs: int = 2, limit: int = 20) -> List[ScriptRecord]:
        """Get scripts that have been run multiple times."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT hash, code, run_count, error_count, total_elapsed_ms,
                       first_seen, last_seen, last_error
                FROM scripts
                WHERE run_count >= ?
                ORDER BY run_count DESC
                LIMIT ?
            """, (min_runs, limit)).fetchall()

        return [ScriptRecord(
            hash=r[0], code=r[1], run_count=r[2], error_count=r[3],
            total_elapsed_ms=r[4], first_seen=r[5], last_seen=r[6],
            last_error=r[7]
        ) for r in rows]

    def get_script(self, code_hash: str) -> Optional[ScriptRecord]:
        """Get a script by its hash."""
        with self._connect() as conn:
            row = conn.execute("""
                SELECT hash, code, run_count, error_count, total_elapsed_ms,
                       first_seen, last_seen, last_error
                FROM scripts
                WHERE hash = ?
            """, (code_hash,)).fetchone()

        if not row:
            return None

        return ScriptRecord(
            hash=row[0], code=row[1], run_count=row[2], error_count=row[3],
            total_elapsed_ms=row[4], first_seen=row[5], last_seen=row[6],
            last_error=row[7]
        )

    def get_stats(self) -> dict:
        """Get overall statistics."""
        with self._connect() as conn:
            total_scripts = conn.execute("SELECT COUNT(*) FROM scripts").fetchone()[0]
            total_runs = conn.execute("SELECT COUNT(*) FROM script_runs").fetchone()[0]
            total_errors = conn.execute(
                "SELECT COUNT(*) FROM script_runs WHERE success = 0"
            ).fetchone()[0]
            unique_repeated = conn.execute(
                "SELECT COUNT(*) FROM scripts WHERE run_count >= 2"
            ).fetchone()[0]

        return {
            "total_unique_scripts": total_scripts,
            "total_runs": total_runs,
            "total_errors": total_errors,
            "error_rate": total_errors / total_runs if total_runs > 0 else 0,
            "scripts_run_multiple_times": unique_repeated,
        }


# Singleton
_tracker: Optional[ScriptTracker] = None


def get_tracker() -> ScriptTracker:
    global _tracker
    if _tracker is None:
        _tracker = ScriptTracker()
    return _tracker
