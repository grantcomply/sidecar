from __future__ import annotations

import re

from source.config import HARMONIC_TIER_SCORES
from source.services.harmonic_tier import HarmonicTier

# HarmonicTier is re-exported here so existing/expected callers can still do
# `from source.services.camelot import HarmonicTier`. It is defined in the
# dependency-free harmonic_tier.py leaf module to avoid a config<->camelot
# import cycle (ADR-010, blueprint §6 R3 option b).
__all__ = [
    "CAMELOT_RE",
    "HarmonicTier",
    "parse_camelot",
    "wheel_distance",
    "shift_key",
    "classify",
    "compatibility_score",
]

CAMELOT_RE = re.compile(r'^(\d{1,2})([AB])$')


def parse_camelot(key: str | None) -> tuple[int, str] | None:
    """Parse '4A' into (4, 'A'). Returns None if invalid."""
    if not key:
        return None
    m = CAMELOT_RE.match(key.strip())
    if not m:
        return None
    num = int(m.group(1))
    if num < 1 or num > 12:
        return None
    return (num, m.group(2))


def wheel_distance(n1: int, n2: int) -> int:
    """Return the unordered distance between two Camelot numbers on the wheel.

    The Camelot wheel has 12 numbered positions (1-12) that wrap (12 <-> 1).
    The distance is symmetric: ``wheel_distance(a, b) == wheel_distance(b, a)``.
    Range is 0-6.

    Note a semitone shift (+7 numbers one way) is the same as -5 the other way,
    so on this unordered scale a semitone maps to distance 5 (since +7 ≡ -5 mod
    12). See the canonical mapping table in architect-blueprint.md §1.
    """
    diff = abs(n1 - n2)
    return min(diff, 12 - diff)


def shift_key(key: str, steps: int) -> str | None:
    """Return the Camelot key ``steps`` positions around the wheel (same letter).

    +1 from ``8A`` -> ``9A``; -1 from ``1A`` -> ``12A`` (the number wraps mod 12).
    The letter is always preserved — a shift moves along the same A/B band. Returns
    ``None`` for an invalid or empty key.

    Direction lives HERE, in the engine layer, not in the harmonic score. This is
    the ADR-010 boundary: ``classify`` and ``compatibility_score`` stay symmetric;
    a directional offset is applied as a pre-shift to the target key string before
    the symmetric score is called. Do NOT push the ``steps`` sign into those
    functions (see ADR-010 Decision point 4 and blueprint R4 — the symmetry trap).
    """
    parsed = parse_camelot(key)
    if parsed is None:
        return None
    num, letter = parsed
    new_num = ((num - 1 + steps) % 12) + 1
    return f"{new_num}{letter}"


def classify(key1: str, key2: str) -> HarmonicTier:
    """Classify the harmonic relationship from ``key1`` to ``key2``.

    ``key1`` is the current track and ``key2`` is the candidate — "what can I
    play after key1". The classification is symmetric for every tier, including
    DIAGONAL: the valid ``{(B, +1), (A, -1)}`` letter-swap family is closed
    under reversal, so ``classify(k1, k2)`` and ``classify(k2, k1)`` always
    return the same tier. This is intended — see ADR-010 Decision point 4.

    Returns ``HarmonicTier.NONE`` for invalid keys or any relationship with no
    usable harmonic move.
    """
    p1 = parse_camelot(key1)
    p2 = parse_camelot(key2)
    if not p1 or not p2:
        return HarmonicTier.NONE

    n1, l1 = p1
    n2, l2 = p2

    # Same number.
    if n1 == n2:
        if l1 == l2:
            return HarmonicTier.PERFECT
        return HarmonicTier.RELATIVE

    # Different letter, wheel distance 1 -> diagonal move.
    if l1 != l2 and wheel_distance(n1, n2) == 1:
        # B->A is a +1 number step; A->B is a -1 number step. The mod-12
        # arithmetic expresses those steps with wrap-around (12<->1).
        b_to_a = l1 == "B" and n2 == (n1 % 12) + 1
        a_to_b = l1 == "A" and n2 == ((n1 - 2) % 12) + 1
        if b_to_a or a_to_b:
            return HarmonicTier.DIAGONAL
        # Dissonant reverse direction — explicitly no match, do not fall through.
        return HarmonicTier.NONE

    # Same-letter number-distance tiers.
    if l1 == l2:
        d = wheel_distance(n1, n2)
        if d == 1:
            return HarmonicTier.ADJACENT
        if d == 2:
            return HarmonicTier.ENERGY
        # Non-monotonic in distance: RELATED sits at d=4 but SEMITONE at d=5
        # scores higher — the score is a harmonic lookup, not a distance curve
        # (blueprint §6 R5).
        if d == 4:
            return HarmonicTier.RELATED
        if d == 5:
            return HarmonicTier.SEMITONE
        # d == 3 or d == 6: gaps in the wheel, no usable harmonic move.
        return HarmonicTier.NONE

    # Different letters with distance >= 2 — no usable relationship.
    return HarmonicTier.NONE


def compatibility_score(key1: str, key2: str) -> float:
    """Score the harmonic compatibility from ``key1`` to ``key2`` (0.0-1.0).

    ``key1`` is the current track, ``key2`` is the candidate. The relationship
    is classified into a ``HarmonicTier`` and looked up in
    ``HARMONIC_TIER_SCORES``. Default tier scores:

        Perfect match : 1.0
        Adjacent      : 0.8
        Relative      : 0.7
        Diagonal      : 0.62
        Energy ±2     : 0.57
        Semitone      : 0.47
        Related       : 0.37
        No match      : 0.0

    Of the four number-distance-1 letter-swap moves, only B->A with
    ``n2 = n1 + 1`` and A->B with ``n2 = n1 - 1`` count as a diagonal; the
    other two (e.g. ``compatibility_score("8B", "7A")``) score 0.0.

    The DIAGONAL tier is symmetric: the valid ``{(B, +1), (A, -1)}`` letter-swap
    family is closed under reversal, so
    ``compatibility_score(k1, k2) == compatibility_score(k2, k1)`` for every key
    pair. This is intended — see ADR-010 Decision point 4.
    """
    return HARMONIC_TIER_SCORES[classify(key1, key2)]
