"""Unit tests for ``source.services.suggestion_engine``.

Focuses on the post-ADR-010 score-based harmonic filter, the standard
self/exclude/crate/genre filters, the result cap and ordering, and the new
``ScoredTrack.harmonic_tier`` field.
"""

from __future__ import annotations

from source.config import MAX_SUGGESTIONS
from source.services.camelot import HarmonicTier
from source.services.suggestion_engine import ScoredTrack, get_suggestions


def _paths(results: list[ScoredTrack]) -> set[str]:
    return {s.track.full_file_path for s in results}


# ── Harmonic filter (the core feature) ─────────────────────────────────────


def test_get_suggestions_includes_semitone_match(make_track, make_library):
    """A SEMITONE match (key score 0.47) was dropped by the old hard filter.

    Under ADR-010 it must now appear — this is the core regression-prevention
    test for the feature.
    """
    current = make_track(camelot_key="1A")
    semitone = make_track(camelot_key="8A")  # wheel distance 5 -> SEMITONE
    library = make_library([current, semitone])

    results = get_suggestions(current, library)

    assert semitone.full_file_path in _paths(results)
    scored = next(s for s in results if s.track is semitone)
    assert scored.key_score == 0.47
    assert scored.harmonic_tier is HarmonicTier.SEMITONE


def test_get_suggestions_excludes_unrelated_key(make_track, make_library):
    """A track with no harmonic relationship (score 0.0) is filtered out."""
    current = make_track(camelot_key="8A")
    gap = make_track(camelot_key="11A")     # distance 3 — wheel gap, 0.0
    tritone = make_track(camelot_key="2A")  # distance 6 — tritone, 0.0
    library = make_library([current, gap, tritone])

    results = get_suggestions(current, library)

    assert _paths(results) == set()


def test_get_suggestions_excludes_self(make_track, make_library):
    current = make_track(camelot_key="8A")
    library = make_library([current])

    results = get_suggestions(current, library)

    assert current.full_file_path not in _paths(results)


def test_get_suggestions_excludes_exclude_paths(make_track, make_library):
    current = make_track(camelot_key="8A")
    other = make_track(camelot_key="9A")  # ADJACENT — would otherwise pass
    library = make_library([current, other])

    results = get_suggestions(current, library, exclude_paths={other.full_file_path})

    assert other.full_file_path not in _paths(results)


def test_get_suggestions_respects_allowed_crates(make_track, make_library):
    current = make_track(camelot_key="8A", crates=["House"])
    in_crate = make_track(camelot_key="9A", crates=["House"])
    out_crate = make_track(camelot_key="7A", crates=["Techno"])
    library = make_library([current, in_crate, out_crate])

    results = get_suggestions(current, library, allowed_crates={"House"})

    assert in_crate.full_file_path in _paths(results)
    assert out_crate.full_file_path not in _paths(results)


def test_get_suggestions_respects_allowed_genres(make_track, make_library):
    current = make_track(camelot_key="8A", genre="House")
    same_genre = make_track(camelot_key="9A", genre="House")
    other_genre = make_track(camelot_key="7A", genre="Techno")
    library = make_library([current, same_genre, other_genre])

    results = get_suggestions(current, library, allowed_genres={"House"})

    assert same_genre.full_file_path in _paths(results)
    assert other_genre.full_file_path not in _paths(results)


def test_get_suggestions_excludes_unparseable_camelot_key(make_track, make_library):
    current = make_track(camelot_key="8A")
    no_key = make_track(camelot_key="")
    bad_key = make_track(camelot_key="13A")  # parses the regex but fails 1-12 range
    library = make_library([current, no_key, bad_key])

    results = get_suggestions(current, library)

    assert no_key.full_file_path not in _paths(results)
    assert bad_key.full_file_path not in _paths(results)


def test_get_suggestions_excludes_when_current_has_no_key(make_track, make_library):
    current = make_track(camelot_key="")
    other = make_track(camelot_key="8A")
    library = make_library([current, other])

    results = get_suggestions(current, library)

    assert results == []


# ── Cap and ordering ───────────────────────────────────────────────────────


def test_get_suggestions_caps_at_max_suggestions(make_track, make_library):
    current = make_track(camelot_key="8A")
    # More candidates than the cap, all ADJACENT so all pass the filter.
    candidates = [make_track(camelot_key="9A") for _ in range(MAX_SUGGESTIONS + 15)]
    library = make_library([current, *candidates])

    results = get_suggestions(current, library)

    assert len(results) == MAX_SUGGESTIONS


def test_get_suggestions_sorted_by_total_score_descending(make_track, make_library):
    current = make_track(camelot_key="8A", bpm=124.0, energy=5)
    perfect = make_track(camelot_key="8A", bpm=124.0, energy=5)   # strongest
    related = make_track(camelot_key="12A", bpm=124.0, energy=5)  # weakest key
    adjacent = make_track(camelot_key="9A", bpm=124.0, energy=5)
    library = make_library([current, related, adjacent, perfect])

    results = get_suggestions(current, library)

    scores = [s.total_score for s in results]
    assert scores == sorted(scores, reverse=True)
    assert results[0].track is perfect


# ── harmonic_tier plumbing ─────────────────────────────────────────────────


def test_get_suggestions_populates_harmonic_tier(make_track, make_library):
    """Every ScoredTrack carries a HarmonicTier consistent with its key_score."""
    current = make_track(camelot_key="8A")
    candidates = [
        make_track(camelot_key="8A"),   # PERFECT
        make_track(camelot_key="9A"),   # ADJACENT
        make_track(camelot_key="8B"),   # RELATIVE
        make_track(camelot_key="10A"),  # ENERGY
        make_track(camelot_key="3A"),   # SEMITONE
        make_track(camelot_key="12A"),  # RELATED
    ]
    library = make_library([current, *candidates])

    results = get_suggestions(current, library)

    expected_score_to_tier = {
        1.0: HarmonicTier.PERFECT,
        0.8: HarmonicTier.ADJACENT,
        0.7: HarmonicTier.RELATIVE,
        0.57: HarmonicTier.ENERGY,
        0.47: HarmonicTier.SEMITONE,
        0.37: HarmonicTier.RELATED,
    }
    for scored in results:
        assert isinstance(scored.harmonic_tier, HarmonicTier)
        assert scored.harmonic_tier is not HarmonicTier.NONE
        assert scored.harmonic_tier is expected_score_to_tier[scored.key_score]


def test_get_suggestions_populates_diagonal_tier(make_track, make_library):
    """A DIAGONAL candidate (8B -> 9A) carries the DIAGONAL tier and 0.62 score."""
    current = make_track(camelot_key="8B")
    diagonal = make_track(camelot_key="9A")  # B->A, n2 = n1 + 1 -> DIAGONAL
    library = make_library([current, diagonal])

    results = get_suggestions(current, library)

    scored = next(s for s in results if s.track is diagonal)
    assert scored.harmonic_tier is HarmonicTier.DIAGONAL
    assert scored.key_score == 0.62


# ── Axis scoring fallbacks ─────────────────────────────────────────────────


def test_get_suggestions_unknown_energy_uses_neutral_score(make_track, make_library):
    """Missing energy on either track yields the neutral 0.5 energy score."""
    current = make_track(camelot_key="8A", energy=0)
    candidate = make_track(camelot_key="9A", energy=0)
    library = make_library([current, candidate])

    results = get_suggestions(current, library)

    assert len(results) == 1
    assert results[0].energy_score == 0.5


def test_get_suggestions_unknown_bpm_uses_neutral_score(make_track, make_library):
    """Missing BPM on either track yields the neutral 0.5 BPM score."""
    current = make_track(camelot_key="8A", bpm=0.0)
    candidate = make_track(camelot_key="9A", bpm=0.0)
    library = make_library([current, candidate])

    results = get_suggestions(current, library)

    assert len(results) == 1
    assert results[0].bpm_score == 0.5


def test_get_suggestions_large_energy_gap_applies_severe_penalty(make_track, make_library):
    """An energy gap above the severe threshold scales the energy score down."""
    current = make_track(camelot_key="8A", energy=1)
    candidate = make_track(camelot_key="9A", energy=8)  # gap of 7 > threshold
    library = make_library([current, candidate])

    results = get_suggestions(current, library)

    assert len(results) == 1
    # 1.0 - 7/8 = 0.125, then * 0.3 severe penalty.
    assert results[0].energy_score == (1.0 - 7 / 8.0) * 0.3


# ── Edge cases ─────────────────────────────────────────────────────────────


def test_get_suggestions_empty_library_returns_empty_list(make_track, empty_library):
    current = make_track(camelot_key="8A")

    assert get_suggestions(current, empty_library) == []
