"""ReaScript API documentation parser and search index."""

import os
import re
import sqlite3
import logging
from dataclasses import dataclass
from typing import List, Optional
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

DB_DIR = os.path.join(os.path.expanduser("~"), ".reaper-mcp")
DB_PATH = os.path.join(DB_DIR, "api_index.db")

# Bundled docs location
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DOCS_PATH = os.path.join(DATA_DIR, "reascripthelp.html")


@dataclass
class APIFunction:
    name: str
    signature: str
    description: str
    return_type: str
    params: str
    category: str  # inferred from name prefix


class ReaScriptHTMLParser(HTMLParser):
    """Parse reascripthelp.html to extract Lua function signatures and descriptions."""

    def __init__(self):
        super().__init__()
        self.functions: List[dict] = []
        self._current_func_name: Optional[str] = None
        self._in_lua_div = False
        self._in_code = False
        self._capture_desc = False
        self._code_text = ""
        self._desc_parts: List[str] = []
        self._current_data: List[str] = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if tag == "a" and "name" in attr_dict:
            # New function anchor
            if self._current_func_name and self._code_text:
                self._save_current()
            self._current_func_name = attr_dict["name"]
            self._code_text = ""
            self._desc_parts = []
            self._in_lua_div = False
            self._capture_desc = False

        elif tag == "div":
            cls = attr_dict.get("class", "")
            if "l_func" in cls:
                self._in_lua_div = True
                self._capture_desc = False
            elif self._current_func_name and "func" not in cls:
                self._capture_desc = True

        elif tag == "code" and self._in_lua_div:
            self._in_code = True
            self._current_data = []

    def handle_endtag(self, tag):
        if tag == "code" and self._in_code:
            self._in_code = False
            self._code_text = "".join(self._current_data).strip()
            self._current_data = []
        elif tag == "div":
            if self._in_lua_div:
                self._in_lua_div = False
                self._capture_desc = True

    def handle_data(self, data):
        if self._in_code:
            self._current_data.append(data)
        elif self._capture_desc and self._current_func_name:
            text = data.strip()
            if text:
                self._desc_parts.append(text)

    def _save_current(self):
        if self._current_func_name and self._code_text:
            self.functions.append({
                "name": self._current_func_name,
                "signature": self._code_text,
                "description": " ".join(self._desc_parts).strip(),
            })

    def close(self):
        if self._current_func_name and self._code_text:
            self._save_current()
        super().close()


def _infer_category(name: str) -> str:
    """Infer a category from the function name."""
    prefixes = {
        "MIDI": "MIDI",
        "Track": "Tracks",
        "FX": "FX",
        "TrackFX": "FX",
        "TakeFX": "FX",
        "Item": "Items",
        "Take": "Takes",
        "Env": "Envelopes",
        "Marker": "Markers",
        "Project": "Project",
        "Master": "Master",
        "Audio": "Audio",
        "CF_": "SWS",
        "BR_": "SWS",
        "SNM_": "SWS",
        "NF_": "SWS",
        "JS_": "JS Extension",
        "ImGui_": "ImGui",
    }
    for prefix, category in prefixes.items():
        if name.startswith(prefix) or name.startswith("Get" + prefix) or name.startswith("Set" + prefix):
            return category
    if name.startswith("Get") or name.startswith("Set"):
        return "General"
    return "Other"


def _parse_signature(sig: str) -> tuple:
    """Parse 'rettype reaper.Name(type param, ...)' into parts."""
    # Remove 'reaper.' prefix variations
    sig = sig.replace("reaper.", "")

    # Try to extract return type, name, params
    match = re.match(r'^([\w\s,]*?)\s*(\w+)\s*\((.*)\)$', sig)
    if match:
        ret = match.group(1).strip()
        name = match.group(2).strip()
        params = match.group(3).strip()
        return ret or "void", params
    return "void", ""


class APIIndex:
    """SQLite FTS5-based API documentation search."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS api_functions (
                    name TEXT PRIMARY KEY,
                    signature TEXT NOT NULL,
                    description TEXT,
                    return_type TEXT,
                    params TEXT,
                    category TEXT,
                    available INTEGER DEFAULT 0
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS api_fts USING fts5(
                    name, signature, description, category,
                    content='api_functions',
                    content_rowid='rowid'
                );

                CREATE TRIGGER IF NOT EXISTS api_ai AFTER INSERT ON api_functions BEGIN
                    INSERT INTO api_fts(rowid, name, signature, description, category)
                    VALUES (new.rowid, new.name, new.signature, new.description, new.category);
                END;

                CREATE TRIGGER IF NOT EXISTS api_ad AFTER DELETE ON api_functions BEGIN
                    INSERT INTO api_fts(api_fts, rowid, name, signature, description, category)
                    VALUES('delete', old.rowid, old.name, old.signature, old.description, old.category);
                END;

                CREATE TRIGGER IF NOT EXISTS api_au AFTER UPDATE ON api_functions BEGIN
                    INSERT INTO api_fts(api_fts, rowid, name, signature, description, category)
                    VALUES('delete', old.rowid, old.name, old.signature, old.description, old.category);
                    INSERT INTO api_fts(rowid, name, signature, description, category)
                    VALUES (new.rowid, new.name, new.signature, new.description, new.category);
                END;
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @property
    def is_indexed(self) -> bool:
        """Check if the index has been populated."""
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM api_functions").fetchone()[0]
        return count > 0

    def build_index(self, html_path: Optional[str] = None) -> int:
        """Parse reascripthelp.html and build the search index. Returns count of functions indexed."""
        html_path = html_path or DOCS_PATH
        if not os.path.exists(html_path):
            logger.warning(f"API docs not found at {html_path}")
            return 0

        with open(html_path, "r", encoding="utf-8", errors="replace") as f:
            html = f.read()

        parser = ReaScriptHTMLParser()
        parser.feed(html)
        parser.close()

        with self._connect() as conn:
            # Clear existing
            conn.execute("DELETE FROM api_functions")
            conn.execute("DELETE FROM api_fts")

            for func in parser.functions:
                ret_type, params = _parse_signature(func["signature"])
                category = _infer_category(func["name"])
                conn.execute("""
                    INSERT OR REPLACE INTO api_functions
                    (name, signature, description, return_type, params, category)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (func["name"], func["signature"], func["description"],
                      ret_type, params, category))

        logger.info(f"Indexed {len(parser.functions)} API functions")
        return len(parser.functions)

    def mark_available(self, function_names: List[str]) -> None:
        """Mark functions as available on the user's REAPER install."""
        with self._connect() as conn:
            conn.execute("UPDATE api_functions SET available = 0")
            for name in function_names:
                conn.execute(
                    "UPDATE api_functions SET available = 1 WHERE name = ?",
                    (name,)
                )
            # Add runtime-only functions not in static docs
            for name in function_names:
                existing = conn.execute(
                    "SELECT name FROM api_functions WHERE name = ?", (name,)
                ).fetchone()
                if not existing:
                    category = _infer_category(name)
                    conn.execute("""
                        INSERT INTO api_functions
                        (name, signature, description, return_type, params, category, available)
                        VALUES (?, ?, ?, ?, ?, ?, 1)
                    """, (name, f"reaper.{name}(...)", "Undocumented (extension function)",
                          "unknown", "unknown", category))

    def search(self, query: str, limit: int = 20, available_only: bool = False) -> List[APIFunction]:
        """Full-text search across function names, signatures, and descriptions."""
        with self._connect() as conn:
            # FTS5 query — escape special chars
            fts_query = re.sub(r'[^\w\s]', ' ', query).strip()
            if not fts_query:
                return []

            # Search with FTS5, adding wildcards for partial matches
            terms = fts_query.split()
            fts_expr = " OR ".join(f'"{t}"*' for t in terms)

            sql = """
                SELECT f.name, f.signature, f.description,
                       f.return_type, f.params, f.category
                FROM api_functions f
                JOIN api_fts ON f.rowid = api_fts.rowid
                WHERE api_fts MATCH ?
            """
            if available_only:
                sql += " AND f.available = 1"
            sql += f" ORDER BY rank LIMIT {limit}"

            rows = conn.execute(sql, (fts_expr,)).fetchall()

        return [APIFunction(
            name=r[0], signature=r[1], description=r[2],
            return_type=r[3], params=r[4], category=r[5]
        ) for r in rows]

    def get_function(self, name: str) -> Optional[APIFunction]:
        """Get a specific function by exact name."""
        with self._connect() as conn:
            row = conn.execute("""
                SELECT name, signature, description, return_type, params, category
                FROM api_functions WHERE name = ?
            """, (name,)).fetchone()

        if not row:
            return None
        return APIFunction(
            name=row[0], signature=row[1], description=row[2],
            return_type=row[3], params=row[4], category=row[5]
        )

    def list_categories(self) -> List[dict]:
        """List all categories with function counts."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT category, COUNT(*) as count,
                       SUM(available) as available_count
                FROM api_functions
                GROUP BY category
                ORDER BY count DESC
            """).fetchall()

        return [{"category": r[0], "total": r[1], "available": r[2]} for r in rows]


# Singleton
_index: Optional[APIIndex] = None


def get_api_index() -> APIIndex:
    global _index
    if _index is None:
        _index = APIIndex()
    return _index
