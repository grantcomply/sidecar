"""Date-range helpers for the suggestion date-added filter.

Converts UI preset names and ISO date strings into the ``(date_from, date_to)``
Unix-epoch tuple that ``get_suggestions`` consumes. ``None`` in either slot means
"no bound" — an open-ended range (see the suggestion-filter brief §Open questions
Q2: a from-only or preset range has no upper "now" timestamp, so an impossible
future-dated track is never hidden).

``now`` is injectable on every entry point so the preset windows are deterministic
under test. Production callers omit it and get the wall clock.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Preset name -> number of trailing days, or a sentinel handled inline.
_PRESET_DAYS: dict[str, int] = {
    "last month": 30,
    "last 3 months": 90,
    "last 6 months": 180,
}

# Canonical preset identifiers, lower-cased. "any time" and "this year" are
# handled specially (no fixed day-window).
ANY_TIME = "any time"
THIS_YEAR = "this year"

DATE_FORMAT = "%Y-%m-%d"


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _parse_iso(value: str) -> float:
    """Parse a ``YYYY-MM-DD`` string to a UTC Unix epoch float.

    Raises ``ValueError`` on malformed input — the caller catches it and shows
    the inline "Enter a date as YYYY-MM-DD." error.
    """
    parsed = datetime.strptime(value.strip(), DATE_FORMAT)
    return parsed.replace(tzinfo=timezone.utc).timestamp()


def date_range_to_epoch(
    preset: str | None = None,
    from_str: str | None = None,
    to_str: str | None = None,
    now: datetime | None = None,
) -> tuple[float | None, float | None]:
    """Resolve a date filter to ``(date_from, date_to)`` epoch floats.

    A ``preset`` takes precedence over manual ``from_str`` / ``to_str``. Known
    presets (case-insensitive): "any time", "last month", "last 3 months",
    "last 6 months", "this year". "any time" — and any unrecognised preset —
    yields ``(None, None)``.

    Manual entry: ``from_str`` / ``to_str`` are ``YYYY-MM-DD``. An omitted /
    ``None`` ``to_str`` leaves the upper bound open (``None``), never "now".
    Malformed date strings raise ``ValueError``.

    ``now`` is injectable for deterministic preset tests; omit it in production.
    """
    if preset is not None:
        key = preset.strip().lower()
        if key == THIS_YEAR:
            current = _now(now)
            year_start = datetime(current.year, 1, 1, tzinfo=timezone.utc)
            return (year_start.timestamp(), None)
        days = _PRESET_DAYS.get(key)
        if days is not None:
            cutoff = _now(now).timestamp() - days * 86400
            return (cutoff, None)
        # "any time" or any unknown preset -> no filter.
        return (None, None)

    date_from = _parse_iso(from_str) if from_str else None
    date_to = _parse_iso(to_str) if to_str else None
    return (date_from, date_to)
