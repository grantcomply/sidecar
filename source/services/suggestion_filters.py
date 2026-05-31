"""The ``SuggestionFilters`` value object — the staged-vs-applied filter snapshot.

A frozen dataclass holding the four suggestion filters in their *engine-ready*
form (the ``None``-means-no-filter normalisation already applied). It is the unit
of staged-vs-applied state for the deferred-apply feature (ADR-012):

- **Staged** and **applied** are each a ``SuggestionFilters`` instance.
- **Dirty** detection is free via dataclass equality (``staged != applied``).
- **Cancel** restores the controls from the applied snapshot.
- It collapses the multi-keyword ``get_suggestions`` call into one typed argument.

``frozenset`` (not ``set``) is used for the crate/genre fields so the dataclass is
hashable and its equality is order-independent — two snapshots with the same
crates compare equal regardless of selection order.

Leaf module: no UI imports, importable by both the engine and the panel (mirrors
the ``harmonic_tier`` leaf-module precedent from ADR-010).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SuggestionFilters:
    allowed_crates: frozenset[str] | None = None   # None = no crate filter
    allowed_genres: frozenset[str] | None = None   # None = no genre filter
    key_offset: int = 0
    date_from: float | None = None
    date_to: float | None = None


def build_filters(
    *,
    all_crates_selected: bool,
    selected_crates: set[str] | frozenset[str],
    all_genres_selected: bool,
    selected_genres: set[str] | frozenset[str],
    key_offset: int,
    date_range: tuple[float | None, float | None],
) -> SuggestionFilters:
    """Assemble a ``SuggestionFilters`` from raw control state, engine-ready.

    Applies the ``None``-means-no-filter normalisation: when every crate (or
    genre) is selected the corresponding field is ``None`` (no filter); otherwise
    it is a ``frozenset`` of the selected names. A fully-cleared filter (none
    selected, ``all_*_selected`` False) yields an empty ``frozenset()`` — the
    engine then matches nothing, preserving today's intentional empty state.

    This is a pure helper so the panel's normalisation and dirty detection are
    unit-testable without a Tk display (implementation plan T4.3).
    """
    allowed_crates = None if all_crates_selected else frozenset(selected_crates)
    allowed_genres = None if all_genres_selected else frozenset(selected_genres)
    date_from, date_to = date_range
    return SuggestionFilters(
        allowed_crates=allowed_crates,
        allowed_genres=allowed_genres,
        key_offset=key_offset,
        date_from=date_from,
        date_to=date_to,
    )
