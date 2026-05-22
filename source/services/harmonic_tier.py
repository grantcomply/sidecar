"""Harmonic compatibility tier vocabulary.

Leaf module with no project dependencies. It exists so that both
``camelot.py`` (domain logic) and ``config.py`` (tuning data) can share the
``HarmonicTier`` enum without forming an import cycle — see ADR-010 and
architect-blueprint.md §6 R3 (option b).
"""

from __future__ import annotations

from enum import Enum


class HarmonicTier(Enum):
    """Named harmonic-mixing relationship between two Camelot keys.

    Each member's value is its human-readable display string, so the UI can
    render ``tier.value`` directly. See ADR-010 for the tier model and
    ``HARMONIC_TIER_SCORES`` in ``config.py`` for the score assigned to each.
    """

    PERFECT = "Perfect match"
    ADJACENT = "Adjacent"
    RELATIVE = "Relative"
    DIAGONAL = "Diagonal"
    ENERGY = "Energy ±2"
    SEMITONE = "Semitone"
    RELATED = "Related"
    NONE = "No match"
