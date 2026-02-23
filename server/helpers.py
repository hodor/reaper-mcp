"""Utility functions: dB conversion, track ref parsing."""

import math
from typing import Union


def db_to_linear(db: float) -> float:
    """Convert dB to linear volume (0dB = 1.0)."""
    return 10 ** (db / 20)


def linear_to_db(linear: float) -> float:
    """Convert linear volume to dB. Returns -inf for 0."""
    if linear <= 0:
        return float('-inf')
    return 20 * math.log10(linear)


def parse_volume(value: Union[str, int, float, dict], current_linear: float = 1.0) -> float:
    """Parse a volume value into linear.

    Accepts:
        - float/int: if > 1.0 or < -1.0, treated as dB; else linear
        - str: "-6dB", "+3dB", "-6", "0.5"
        - dict: {"db": -6}, {"linear": 0.5}, {"relative_db": -3}
    """
    if isinstance(value, dict):
        if "db" in value:
            return db_to_linear(float(value["db"]))
        elif "linear" in value:
            return float(value["linear"])
        elif "relative_db" in value:
            current_db = linear_to_db(current_linear)
            return db_to_linear(current_db + float(value["relative_db"]))
        raise ValueError(f"Unknown volume dict format: {value}")

    if isinstance(value, str):
        value = value.strip()
        # Relative: "+3dB", "-3dB", "+3", "-3"
        if value.startswith("+") or (value.startswith("-") and not value.replace("-", "").replace(".", "").isdigit()):
            num_str = value.lower().replace("db", "").strip()
            try:
                relative_db = float(num_str)
                current_db = linear_to_db(current_linear)
                return db_to_linear(current_db + relative_db)
            except ValueError:
                pass

        # Absolute dB: "-6dB", "0dB"
        if value.lower().endswith("db"):
            num_str = value[:-2].strip()
            return db_to_linear(float(num_str))

        # Numeric string
        num = float(value)
        if abs(num) > 1.0:
            return db_to_linear(num)  # Treat as dB
        return num  # Treat as linear

    # Numeric
    num = float(value)
    if abs(num) > 1.0:
        return db_to_linear(num)
    return num


def parse_pan(value: Union[str, int, float]) -> float:
    """Parse a pan value into -1.0 to 1.0.

    Accepts:
        - float: -1.0 to 1.0 directly
        - str: "L50" (50% left = -0.5), "R30" (30% right = 0.3), "C" (center = 0)
    """
    if isinstance(value, (int, float)):
        return max(-1.0, min(1.0, float(value)))

    if isinstance(value, str):
        value = value.strip().upper()
        if value == "C" or value == "CENTER":
            return 0.0
        if value.startswith("L"):
            num = float(value[1:]) / 100.0
            return -num
        if value.startswith("R"):
            num = float(value[1:]) / 100.0
            return num
        # Try as number
        return max(-1.0, min(1.0, float(value)))

    raise ValueError(f"Cannot parse pan value: {value}")


def resolve_track_ref(ref: Union[str, int], tracks: list) -> int:
    """Resolve a track reference to an index.

    Args:
        ref: track name (fuzzy) or 1-based index
        tracks: list of track dicts with 'name' and 'index' keys

    Returns: 0-based track index
    Raises: ValueError if not found or ambiguous
    """
    if isinstance(ref, int):
        # 1-based to 0-based
        idx = ref - 1 if ref > 0 else ref
        if 0 <= idx < len(tracks):
            return idx
        raise ValueError(f"Track index {ref} out of range (1-{len(tracks)})")

    if isinstance(ref, str):
        ref_lower = ref.strip().lower()

        # Exact match first
        for t in tracks:
            if t["name"].lower() == ref_lower:
                return t["index"]

        # Contains match
        matches = [t for t in tracks if ref_lower in t["name"].lower()]
        if len(matches) == 1:
            return matches[0]["index"]
        if len(matches) > 1:
            names = [m["name"] for m in matches]
            raise ValueError(
                f"Ambiguous track reference '{ref}'. Matches: {names}"
            )

        # Try as number
        try:
            return resolve_track_ref(int(ref), tracks)
        except (ValueError, IndexError):
            pass

        raise ValueError(
            f"No track found matching '{ref}'. "
            f"Available: {[t['name'] for t in tracks]}"
        )

    raise ValueError(f"Invalid track reference type: {type(ref)}")
