"""
Text parsing: extract footage readings, dates, and pipe/job IDs from OCR output.
"""

import re
from collections import Counter

# -------------------------------------------------------------------
# Footage
# -------------------------------------------------------------------

# Matches: -2.0ft  352.2ft  12ft  5.5m  100.00 ft  3.2 m  etc.
# Requires the unit to follow immediately or with one space.
_FOOTAGE_RE = re.compile(
    r"(-?\d{1,5}(?:\.\d{1,3})?)\s*(?P<unit>ft|feet|m(?:eters?)?)\b",
    re.IGNORECASE,
)


def parse_footage(texts: list[str]) -> list[tuple[float, str]]:
    """
    Parse all footage/distance readings from a list of OCR text strings.
    Returns a list of (value, unit) tuples where unit is 'ft' or 'm'.

    Also handles cases where the number and unit are on separate lines
    (e.g. OCR returns ['3.84', 'ft'] as two separate strings).
    """
    readings = []

    # Pass 1: parse each line individually
    for text in texts:
        for match in _FOOTAGE_RE.finditer(text):
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            raw_unit = match.group("unit").lower()
            unit = "m" if raw_unit.startswith("m") else "ft"
            readings.append((value, unit))

    # Pass 2: join adjacent pairs and re-parse (catches split "3.84" / "ft")
    for i in range(len(texts) - 1):
        joined = texts[i].strip() + " " + texts[i + 1].strip()
        for match in _FOOTAGE_RE.finditer(joined):
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            raw_unit = match.group("unit").lower()
            unit = "m" if raw_unit.startswith("m") else "ft"
            pair = (value, unit)
            if pair not in readings:
                readings.append(pair)

    return readings


def sanitize_footage(readings: list[tuple[float, str]], max_plausible: float = 5000) -> list[tuple[float, str]]:
    """
    Remove obviously wrong readings (e.g. OCR misread 352 as 3520).
    Discards values whose absolute value exceeds max_plausible.
    """
    return [(v, u) for v, u in readings if abs(v) <= max_plausible]


def compute_total(readings: list[tuple[float, str]]) -> tuple[float, str] | tuple[None, None]:
    """
    Given a list of (value, unit) readings from across a video,
    return (total_footage, unit) as max - min.
    Prefers ft over m if both units appear (keeps them separate).
    Returns (None, None) if no readings.
    """
    if not readings:
        return None, None

    for unit in ("ft", "m"):
        unit_vals = [v for v, u in readings if u == unit]
        if unit_vals:
            return round(max(unit_vals) - min(unit_vals), 2), unit

    return None, None


# -------------------------------------------------------------------
# Date
# -------------------------------------------------------------------

# Common date formats seen in inspection video overlays
_DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\b"),   # MM/DD/YYYY or DD-MM-YYYY
    re.compile(r"\b(\d{4}[/\-]\d{1,2}[/\-]\d{1,2})\b"),       # YYYY-MM-DD
    re.compile(r"\b(\d{1,2}\s+\w{3}\w*\s+\d{2,4})\b"),         # 12 Jan 2024
]


def parse_date(texts: list[str]) -> str | None:
    """
    Return the first date-like string found in the OCR texts, or None.
    """
    for text in texts:
        for pattern in _DATE_PATTERNS:
            m = pattern.search(text)
            if m:
                return m.group(1)
    return None


def most_common_date(dates: list[str | None]) -> str | None:
    """Return the most frequently seen date from a list (ignoring None)."""
    valid = [d for d in dates if d]
    if not valid:
        return None
    return Counter(valid).most_common(1)[0][0]


# -------------------------------------------------------------------
# Pipe / Job ID
# -------------------------------------------------------------------

# Look for label prefixes commonly seen in inspection overlays
_PIPE_ID_RE = re.compile(
    r"(?:pipe|job|id|survey|section|seg(?:ment)?|line|main|lateral|asset)"
    r"\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\-_./]{1,30})",
    re.IGNORECASE,
)


def parse_pipe_id(texts: list[str]) -> str | None:
    """
    Return the first pipe/job ID found in OCR texts, or None.
    """
    for text in texts:
        m = _PIPE_ID_RE.search(text)
        if m:
            return m.group(1).strip()
    return None


def most_common_pipe_id(ids: list[str | None]) -> str | None:
    """Return the most frequently seen pipe ID from a list (ignoring None)."""
    valid = [i for i in ids if i]
    if not valid:
        return None
    return Counter(valid).most_common(1)[0][0]
