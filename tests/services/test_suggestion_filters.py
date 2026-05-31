"""Unit tests for ``source.services.suggestion_filters``.

Covers the ``SuggestionFilters`` value object (equality, defaults, dirty
detection via ``!=``, frozenset order-independence) and the ``build_filters``
normalisation helper (``None``-means-no-filter, cleared = empty frozenset).
"""

from __future__ import annotations

from source.services.suggestion_filters import SuggestionFilters, build_filters


# ── Defaults ────────────────────────────────────────────────────────────────


def test_default_filters_are_all_none_or_zero():
    f = SuggestionFilters()
    assert f.allowed_crates is None
    assert f.allowed_genres is None
    assert f.key_offset == 0
    assert f.date_from is None
    assert f.date_to is None


# ── Equality / dirty detection ──────────────────────────────────────────────


def test_two_defaults_compare_equal():
    assert SuggestionFilters() == SuggestionFilters()


def test_same_crates_different_order_compare_equal():
    """frozenset fields make equality order-independent (the dirty contract)."""
    a = SuggestionFilters(allowed_crates=frozenset({"House", "Techno", "Disco"}))
    b = SuggestionFilters(allowed_crates=frozenset({"Disco", "House", "Techno"}))
    assert a == b


def test_inequality_across_each_field():
    base = SuggestionFilters()
    assert base != SuggestionFilters(allowed_crates=frozenset({"X"}))
    assert base != SuggestionFilters(allowed_genres=frozenset({"X"}))
    assert base != SuggestionFilters(key_offset=1)
    assert base != SuggestionFilters(date_from=1.0)
    assert base != SuggestionFilters(date_to=1.0)


def test_empty_frozenset_differs_from_none():
    """A cleared filter (frozenset()) is NOT the same as no filter (None)."""
    assert SuggestionFilters(allowed_crates=frozenset()) != SuggestionFilters(
        allowed_crates=None
    )


def test_filters_are_hashable():
    """frozen + frozenset fields -> hashable (usable as dict keys / set members)."""
    s = {SuggestionFilters(allowed_crates=frozenset({"A"})), SuggestionFilters()}
    assert len(s) == 2


# ── build_filters normalisation ─────────────────────────────────────────────


def test_build_filters_all_selected_yields_none():
    f = build_filters(
        all_crates_selected=True,
        selected_crates={"House"},
        all_genres_selected=True,
        selected_genres={"House"},
        key_offset=0,
        date_range=(None, None),
    )
    assert f == SuggestionFilters()


def test_build_filters_subset_yields_frozenset():
    f = build_filters(
        all_crates_selected=False,
        selected_crates={"House", "Techno"},
        all_genres_selected=False,
        selected_genres={"Disco"},
        key_offset=2,
        date_range=(100.0, 200.0),
    )
    assert f.allowed_crates == frozenset({"House", "Techno"})
    assert f.allowed_genres == frozenset({"Disco"})
    assert f.key_offset == 2
    assert f.date_from == 100.0
    assert f.date_to == 200.0


def test_build_filters_cleared_yields_empty_frozenset():
    """None selected with all_selected False = intentional empty filter."""
    f = build_filters(
        all_crates_selected=False,
        selected_crates=set(),
        all_genres_selected=True,
        selected_genres={"House"},
        key_offset=0,
        date_range=(None, None),
    )
    assert f.allowed_crates == frozenset()
    assert f.allowed_genres is None


# ── Dirty detection / round-trip (the staged-vs-applied contract) ───────────


def test_dirty_when_staged_differs_from_applied():
    """Mirrors SuggestionPanel.is_dirty: staged != applied."""
    applied = SuggestionFilters()
    staged = build_filters(
        all_crates_selected=False,
        selected_crates={"House"},
        all_genres_selected=True,
        selected_genres=set(),
        key_offset=0,
        date_range=(None, None),
    )
    assert staged != applied  # dirty


def test_not_dirty_when_staged_equals_applied_via_build():
    """Toggle-off-then-on returns to equal — dirty clears for free."""
    applied = build_filters(
        all_crates_selected=False,
        selected_crates={"House", "Techno"},
        all_genres_selected=True,
        selected_genres=set(),
        key_offset=1,
        date_range=(100.0, None),
    )
    # Same logical state, crates given in a different order.
    staged = build_filters(
        all_crates_selected=False,
        selected_crates={"Techno", "House"},
        all_genres_selected=True,
        selected_genres=set(),
        key_offset=1,
        date_range=(100.0, None),
    )
    assert staged == applied  # not dirty


def test_apply_then_round_trip_is_clean():
    """Apply commits staged; a fresh build from the same state is clean."""
    staged = build_filters(
        all_crates_selected=False,
        selected_crates={"Disco"},
        all_genres_selected=False,
        selected_genres={"Deep"},
        key_offset=-2,
        date_range=(1.0, 2.0),
    )
    applied = staged  # Apply: applied <- staged (value copy; frozen dataclass)
    restaged = build_filters(
        all_crates_selected=False,
        selected_crates={"Disco"},
        all_genres_selected=False,
        selected_genres={"Deep"},
        key_offset=-2,
        date_range=(1.0, 2.0),
    )
    assert restaged == applied  # no spurious dirty after apply
