"""Unit tests for ``source.services.suggestion_engine``.

Focuses on the post-ADR-010 score-based harmonic filter, the standard
self/exclude/crate/genre filters, the result cap and ordering, and the new
``ScoredTrack.harmonic_tier`` field.
"""

from __future__ import annotations

from source.config import MAX_SUGGESTIONS
from source.services.camelot import HarmonicTier
from source.services.suggestion_engine import ScoredTrack, get_suggestions
from source.services.suggestion_filters import SuggestionFilters


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


# ── Key transition offset (re-anchor + same-key suppression) ────────────────


def test_get_suggestions_offset_excludes_same_key(make_track, make_library):
    """With key_offset=1, no PERFECT same-key (current) track is offered."""
    current = make_track(camelot_key="8A")
    same_key = make_track(camelot_key="8A")  # PERFECT vs current -> suppressed
    one_up = make_track(camelot_key="9A")    # one step up
    library = make_library([current, same_key, one_up])

    results = get_suggestions(current, library, key_offset=1)

    assert same_key.full_file_path not in _paths(results)
    assert one_up.full_file_path in _paths(results)


def test_get_suggestions_offset_scores_shifted_target_as_perfect(make_track, make_library):
    """A track exactly at current+1 scores PERFECT against the shifted target."""
    current = make_track(camelot_key="8A")
    one_up = make_track(camelot_key="9A")  # == shift_key("8A", 1)
    library = make_library([current, one_up])

    results = get_suggestions(current, library, key_offset=1)

    scored = next(s for s in results if s.track is one_up)
    assert scored.key_score == 1.0
    assert scored.harmonic_tier is HarmonicTier.PERFECT


def test_get_suggestions_offset_zero_matches_baseline(make_track, make_library):
    """key_offset=0 is byte-for-byte identical to the no-offset baseline.

    Mirrors test_get_suggestions_populates_harmonic_tier — same library, same
    expected scores and tiers, just with the default argument made explicit.
    """
    current = make_track(camelot_key="8A")
    candidates = [
        make_track(camelot_key="8A"),   # PERFECT — NOT suppressed at offset 0
        make_track(camelot_key="9A"),   # ADJACENT
        make_track(camelot_key="8B"),   # RELATIVE
        make_track(camelot_key="10A"),  # ENERGY
        make_track(camelot_key="3A"),   # SEMITONE
        make_track(camelot_key="12A"),  # RELATED
    ]
    library = make_library([current, *candidates])

    baseline = get_suggestions(current, library)
    explicit = get_suggestions(current, library, key_offset=0)

    assert _paths(explicit) == _paths(baseline)
    baseline_by_path = {s.track.full_file_path: s for s in baseline}
    for scored in explicit:
        twin = baseline_by_path[scored.track.full_file_path]
        assert scored.key_score == twin.key_score
        assert scored.total_score == twin.total_score
        assert scored.harmonic_tier is twin.harmonic_tier
    # Same-key (PERFECT) candidate is present at offset 0 — not suppressed.
    assert any(s.key_score == 1.0 for s in explicit)


def test_get_suggestions_offset_with_current_no_key_falls_back(make_track, make_library):
    """Current track with empty key + offset falls back gracefully (offset 0).

    ``shift_key`` returns None for an empty key, so the offset path is skipped.
    With no current key the harmonic gate excludes every candidate (same as the
    no-offset behaviour) — the call must not crash and returns an empty list.
    """
    current = make_track(camelot_key="")
    other = make_track(camelot_key="8A")
    library = make_library([current, other])

    results = get_suggestions(current, library, key_offset=1)

    assert results == []


def test_get_suggestions_offset_with_invalid_current_key_falls_back(make_track, make_library):
    """A non-empty but INVALID current key + offset falls back to offset 0.

    Unlike the empty-key case, ``camelot_key="13A"`` is truthy so it passes the
    ``if key_offset and current.camelot_key`` guard and reaches ``shift_key``,
    which returns ``None`` for the out-of-range number. This exercises the
    ``if shifted:`` fallback the empty-key test short-circuits past: the target
    stays the (invalid) current key, no same-key suppression occurs, and the call
    must not crash. The harmonic gate then excludes the candidate (invalid current
    key scores 0.0 against anything), reproducing offset-0 behaviour exactly.
    """
    current = make_track(camelot_key="13A")  # parses the regex, fails 1-12 range
    same_key = make_track(camelot_key="13A")
    other = make_track(camelot_key="8A")
    library = make_library([current, same_key, other])

    offset_results = get_suggestions(current, library, key_offset=1)
    baseline_results = get_suggestions(current, library, key_offset=0)

    # No crash, and behaves exactly as offset 0 (no same-key suppression kicked in).
    assert _paths(offset_results) == _paths(baseline_results)
    assert offset_results == []


# ── Date-added range filter ─────────────────────────────────────────────────

# Three fixed epoch timestamps (seconds). OLD < MID < NEW.
_OLD = 1_600_000_000.0   # 2020-09-13
_MID = 1_700_000_000.0   # 2023-11-14
_NEW = 1_740_000_000.0   # 2025-02-19


def test_get_suggestions_date_from_excludes_older(make_track, make_library):
    """date_from drops candidates added before the threshold."""
    current = make_track(camelot_key="8A")
    old = make_track(camelot_key="9A", date_added=_OLD)
    new = make_track(camelot_key="9A", date_added=_NEW)
    library = make_library([current, old, new])

    results = get_suggestions(current, library, date_from=_MID)

    assert old.full_file_path not in _paths(results)
    assert new.full_file_path in _paths(results)


def test_get_suggestions_date_to_excludes_newer(make_track, make_library):
    """date_to drops candidates added after the threshold."""
    current = make_track(camelot_key="8A")
    old = make_track(camelot_key="9A", date_added=_OLD)
    new = make_track(camelot_key="9A", date_added=_NEW)
    library = make_library([current, old, new])

    results = get_suggestions(current, library, date_to=_MID)

    assert old.full_file_path in _paths(results)
    assert new.full_file_path not in _paths(results)


def test_get_suggestions_date_window_bounds_both_ends(make_track, make_library):
    """date_from + date_to keep only candidates inside the window (inclusive)."""
    current = make_track(camelot_key="8A")
    old = make_track(camelot_key="9A", date_added=_OLD)
    mid = make_track(camelot_key="9A", date_added=_MID)
    new = make_track(camelot_key="9A", date_added=_NEW)
    library = make_library([current, old, mid, new])

    results = get_suggestions(current, library, date_from=_OLD, date_to=_MID)

    assert _paths(results) == {old.full_file_path, mid.full_file_path}


def test_get_suggestions_date_from_excludes_unknown_date(make_track, make_library):
    """A track with date_added == 0.0 is excluded when date_from is set.

    The intended "can't prove it's in range" behaviour (blueprint §4): an unknown
    add-date (legacy / failed stat) drops out of any from-bounded window.
    """
    current = make_track(camelot_key="8A")
    unknown = make_track(camelot_key="9A", date_added=0.0)
    known = make_track(camelot_key="9A", date_added=_NEW)
    library = make_library([current, unknown, known])

    results = get_suggestions(current, library, date_from=_MID)

    assert unknown.full_file_path not in _paths(results)
    assert known.full_file_path in _paths(results)


def test_get_suggestions_date_none_reproduces_baseline(make_track, make_library):
    """date_from=None and date_to=None (the default) apply no date filter.

    Even a 0.0-dated track survives when no date bound is set — baseline behaviour.
    """
    current = make_track(camelot_key="8A")
    old = make_track(camelot_key="9A", date_added=_OLD)
    unknown = make_track(camelot_key="9A", date_added=0.0)
    library = make_library([current, old, unknown])

    baseline = get_suggestions(current, library)
    explicit_none = get_suggestions(current, library, date_from=None, date_to=None)

    assert _paths(baseline) == {old.full_file_path, unknown.full_file_path}
    assert _paths(explicit_none) == _paths(baseline)


# ── SuggestionFilters snapshot path (ADR-012) ───────────────────────────────


def test_get_suggestions_filters_object_matches_crate_kwarg(make_track, make_library):
    """Passing a filters= snapshot is identical to the equivalent kwargs path."""
    current = make_track(camelot_key="8A", crates=["House"])
    in_crate = make_track(camelot_key="9A", crates=["House"])
    out_crate = make_track(camelot_key="7A", crates=["Techno"])
    library = make_library([current, in_crate, out_crate])

    via_kwarg = get_suggestions(current, library, allowed_crates={"House"})
    via_filters = get_suggestions(
        current, library,
        filters=SuggestionFilters(allowed_crates=frozenset({"House"})),
    )

    assert _paths(via_filters) == _paths(via_kwarg)
    assert in_crate.full_file_path in _paths(via_filters)
    assert out_crate.full_file_path not in _paths(via_filters)


def test_get_suggestions_filters_object_supersedes_kwargs(make_track, make_library):
    """When filters= is given it supersedes the individual kwargs."""
    current = make_track(camelot_key="8A", crates=["House"])
    in_crate = make_track(camelot_key="9A", crates=["House"])
    out_crate = make_track(camelot_key="7A", crates=["Techno"])
    library = make_library([current, in_crate, out_crate])

    # The kwarg says Techno, but the filters object (which wins) says House.
    results = get_suggestions(
        current, library,
        allowed_crates={"Techno"},
        filters=SuggestionFilters(allowed_crates=frozenset({"House"})),
    )

    assert in_crate.full_file_path in _paths(results)
    assert out_crate.full_file_path not in _paths(results)


def test_get_suggestions_default_filters_object_is_no_filter(make_track, make_library):
    """A default SuggestionFilters() applies no filtering (reproduces baseline)."""
    current = make_track(camelot_key="8A")
    other = make_track(camelot_key="9A")
    library = make_library([current, other])

    baseline = get_suggestions(current, library)
    with_filters = get_suggestions(current, library, filters=SuggestionFilters())

    assert _paths(with_filters) == _paths(baseline)
