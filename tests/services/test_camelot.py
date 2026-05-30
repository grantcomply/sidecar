"""Unit tests for ``source.services.camelot``.

Covers ``parse_camelot``, ``wheel_distance``, ``classify`` (one case per
harmonic tier including mod-12 wrapping and the diagonal letter-swap), and
``compatibility_score`` (exact tier values, symmetry).

The DIAGONAL tier is symmetric: the valid ``{(B, +1), (A, -1)}`` letter-swap
family is closed under reversal, so the reverse of a valid diagonal is itself a
valid diagonal (``classify("9A","8B")`` returns ``DIAGONAL``) and the reverse
of a dissonant letter-swap is still dissonant. This is intended — see ADR-010
Decision point 4. The tests below assert that symmetric behaviour.
"""

from __future__ import annotations

import pytest

from source.services.camelot import (
    HarmonicTier,
    classify,
    compatibility_score,
    parse_camelot,
    shift_key,
    wheel_distance,
)
from source.config import HARMONIC_TIER_SCORES


# ── parse_camelot ──────────────────────────────────────────────────────────


def test_parse_camelot_valid_single_digit_returns_tuple():
    assert parse_camelot("8A") == (8, "A")


def test_parse_camelot_valid_double_digit_returns_tuple():
    assert parse_camelot("12B") == (12, "B")


def test_parse_camelot_whitespace_padded_returns_tuple():
    assert parse_camelot(" 8A ") == (8, "A")


def test_parse_camelot_empty_string_returns_none():
    assert parse_camelot("") is None


def test_parse_camelot_none_returns_none():
    assert parse_camelot(None) is None


def test_parse_camelot_number_above_range_returns_none():
    assert parse_camelot("13A") is None


def test_parse_camelot_number_zero_returns_none():
    assert parse_camelot("0A") is None


def test_parse_camelot_invalid_letter_returns_none():
    assert parse_camelot("8C") is None


def test_parse_camelot_missing_letter_returns_none():
    assert parse_camelot("8") is None


# ── wheel_distance ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "n1, n2, expected",
    [
        (8, 8, 0),
        (8, 9, 1),
        (12, 1, 1),   # wrap
        (8, 10, 2),
        (8, 12, 4),
        (1, 8, 5),    # semitone distance
        (8, 2, 6),    # tritone
    ],
)
def test_wheel_distance_returns_unordered_distance(n1, n2, expected):
    assert wheel_distance(n1, n2) == expected


@pytest.mark.parametrize("a, b", [(8, 9), (12, 1), (1, 8), (8, 2), (3, 11)])
def test_wheel_distance_is_symmetric(a, b):
    assert wheel_distance(a, b) == wheel_distance(b, a)


# ── classify ───────────────────────────────────────────────────────────────


def test_classify_identical_key_returns_perfect():
    assert classify("8A", "8A") is HarmonicTier.PERFECT


@pytest.mark.parametrize(
    "key1, key2",
    [("8A", "9A"), ("8A", "7A"), ("12A", "1A"), ("1A", "12A")],
)
def test_classify_adjacent_number_same_letter_returns_adjacent(key1, key2):
    assert classify(key1, key2) is HarmonicTier.ADJACENT


@pytest.mark.parametrize("key1, key2", [("8A", "8B"), ("8B", "8A")])
def test_classify_same_number_letter_swap_returns_relative(key1, key2):
    assert classify(key1, key2) is HarmonicTier.RELATIVE


@pytest.mark.parametrize(
    "key1, key2",
    [("8B", "9A"), ("8A", "7B"), ("12B", "1A"), ("1A", "12B")],
)
def test_classify_valid_diagonal_returns_diagonal(key1, key2):
    assert classify(key1, key2) is HarmonicTier.DIAGONAL


@pytest.mark.parametrize("key1, key2", [("8B", "7A"), ("8A", "9B")])
def test_classify_dissonant_reverse_diagonal_returns_none(key1, key2):
    """B->A with -1 and A->B with +1 are not diagonals — they score 0."""
    assert classify(key1, key2) is HarmonicTier.NONE


@pytest.mark.parametrize("key1, key2", [("9A", "8B"), ("7B", "8A")])
def test_classify_diagonal_is_symmetric(key1, key2):
    """The reverse of a valid diagonal is itself a valid diagonal.

    ``9A->8B`` is the reverse of the valid diagonal ``8B->9A``; ``7B->8A`` the
    reverse of ``8A->7B``. The ``{(B, +1), (A, -1)}`` letter-swap family is
    closed under reversal, so the DIAGONAL tier is symmetric. This is intended
    — see ADR-010 Decision point 4.
    """
    assert classify(key1, key2) is HarmonicTier.DIAGONAL


@pytest.mark.parametrize("key1, key2", [("8A", "10A"), ("8A", "6A")])
def test_classify_distance_two_same_letter_returns_energy(key1, key2):
    assert classify(key1, key2) is HarmonicTier.ENERGY


@pytest.mark.parametrize("key1, key2", [("1A", "8A"), ("8A", "3A")])
def test_classify_distance_five_same_letter_returns_semitone(key1, key2):
    assert classify(key1, key2) is HarmonicTier.SEMITONE


@pytest.mark.parametrize("key1, key2", [("10B", "2B"), ("8A", "12A")])
def test_classify_distance_four_same_letter_returns_related(key1, key2):
    assert classify(key1, key2) is HarmonicTier.RELATED


@pytest.mark.parametrize(
    "key1, key2",
    [
        ("8A", "11A"),  # distance 3 — wheel gap
        ("8A", "2A"),   # distance 6 — tritone
        ("8A", "10B"),  # different letter, distance >= 2
    ],
)
def test_classify_wheel_gap_returns_none(key1, key2):
    assert classify(key1, key2) is HarmonicTier.NONE


@pytest.mark.parametrize("key1, key2", [("", "8A"), ("8A", "13A")])
def test_classify_invalid_input_returns_none(key1, key2):
    assert classify(key1, key2) is HarmonicTier.NONE


# ── compatibility_score ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "key1, key2, expected",
    [
        ("8A", "8A", 1.0),    # PERFECT
        ("8A", "9A", 0.8),    # ADJACENT
        ("8A", "8B", 0.7),    # RELATIVE
        ("8B", "9A", 0.62),   # DIAGONAL
        ("8A", "10A", 0.57),  # ENERGY
        ("1A", "8A", 0.47),   # SEMITONE
        ("8A", "12A", 0.37),  # RELATED
        ("8A", "11A", 0.0),   # NONE
    ],
)
def test_compatibility_score_matches_tier_table(key1, key2, expected):
    assert compatibility_score(key1, key2) == expected


def test_compatibility_score_uses_config_tier_values():
    """Every tier score returned must come from HARMONIC_TIER_SCORES."""
    assert set(HARMONIC_TIER_SCORES.values()) == {1.0, 0.8, 0.7, 0.62, 0.57, 0.47, 0.37, 0.0}


def test_compatibility_score_diagonal_is_symmetric():
    """A valid diagonal pair scores > 0; a dissonant letter-swap pair scores 0.

    The DIAGONAL tier is symmetric: ``{8B, 9A}`` is a valid diagonal in both
    orderings, and ``{8B, 7A}`` is a dissonant letter-swap in both orderings.
    This is intended — see ADR-010 Decision point 4.
    """
    # Valid diagonal pair — symmetric, both directions score > 0.
    assert compatibility_score("8B", "9A") > 0
    assert compatibility_score("9A", "8B") > 0
    # Dissonant letter-swap pair — symmetric, both directions score 0.
    assert compatibility_score("8B", "7A") == 0.0
    assert compatibility_score("7A", "8B") == 0.0


@pytest.mark.parametrize(
    "key1, key2",
    [
        ("8A", "8A"),   # PERFECT
        ("8A", "9A"),   # ADJACENT
        ("8A", "8B"),   # RELATIVE
        ("8A", "10A"),  # ENERGY
        ("1A", "8A"),   # SEMITONE
        ("8A", "12A"),  # RELATED
    ],
)
def test_compatibility_score_non_diagonal_tiers_are_symmetric(key1, key2):
    assert compatibility_score(key1, key2) == compatibility_score(key2, key1)


# ── shift_key ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "key, steps, expected",
    [
        ("8A", 1, "9A"),     # +1 advances the number
        ("1A", -1, "12A"),   # -1 wraps backward 1 -> 12
        ("12B", 1, "1B"),    # +1 wraps forward 12 -> 1, letter preserved
        ("8A", 0, "8A"),     # no shift is an identity
        ("8B", -1, "7B"),    # letter preserved on a B key
        ("3A", 2, "5A"),     # +2 step
    ],
)
def test_shift_key_shifts_number_and_preserves_letter(key, steps, expected):
    assert shift_key(key, steps) == expected


@pytest.mark.parametrize("key", ["", "99X", "13A", "8C", "8"])
def test_shift_key_invalid_key_returns_none(key):
    assert shift_key(key, 1) is None


def test_shift_key_does_not_make_compatibility_score_asymmetric():
    """R4 guard: ``shift_key`` lives in the engine layer; it must NOT make the
    harmonic score directional.

    Direction is applied as a pre-shift to the target key string. The symmetric
    ``compatibility_score`` is unchanged: scoring a current key against a +1
    shifted target equals scoring the shifted target against the current key.
    Same key, both orderings -> same score. This guards against a future
    "simplification" that pushes the offset sign into ``classify`` /
    ``compatibility_score`` (ADR-010 Decision point 4; blueprint R4).
    """
    current = "8A"
    target = shift_key(current, 1)  # "9A"
    assert compatibility_score(current, target) == compatibility_score(target, current)
    # And the +1 shifted target is itself a PERFECT match for a candidate on that key.
    assert compatibility_score(target, "9A") == 1.0
