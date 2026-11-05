"""Parse the DJ comment convention ``"4A - 7 - Banger - Fat Bass Vocal"`` (pure).

``<Camelot key> - <energy 1-8> - <category> - <descriptors>``. Free-text
comments (e.g. ``"Commercial"``) parse to an empty ``CommentFields``.
Leaf module: depends only on ``camelot.parse_camelot`` and ``config``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from source.config import TRACK_CATEGORIES
from source.services.camelot import parse_camelot

_SEPARATOR = " - "
_MAX_PARTS = 4
_ENERGY_RE = re.compile(r"^(?:energy\s*)?(\d+)$", re.IGNORECASE)
_ENERGY_MIN, _ENERGY_MAX = 1, 8


@dataclass(frozen=True)
class CommentFields:
    camelot_key: str = ""
    energy: int = 0
    category: str = ""
    descriptors: str = ""


def _energy(part: str) -> int:
    match = _ENERGY_RE.match(part.strip())
    if not match:
        return 0
    value = int(match.group(1))
    return value if _ENERGY_MIN <= value <= _ENERGY_MAX else 0


def _category(part: str) -> str:
    wanted = part.strip().casefold()
    return next((c for c in TRACK_CATEGORIES if c.casefold() == wanted), "")


def parse_comment(comment: str) -> CommentFields:
    """Split on ``" - "`` (max 4 parts). Part 0 must be a valid Camelot key."""
    parts = [p.strip() for p in (comment or "").split(_SEPARATOR, _MAX_PARTS - 1)]
    key = parts[0].upper().replace(" ", "")
    if parse_camelot(key) is None:
        return CommentFields()
    energy = _energy(parts[1]) if len(parts) > 1 else 0
    category = _category(parts[2]) if len(parts) > 2 else ""
    descriptors = _SEPARATOR.join(parts[3:]) if len(parts) > 3 else ""
    return CommentFields(camelot_key=key, energy=energy, category=category, descriptors=descriptors)
