"""Unit tests for the suggestion-panel empty-state copy decision.

``empty_state_message`` is the pure helper extracted from
``SuggestionPanel.set_suggestions`` so the precedence between the
all-cleared-crate, all-cleared-genre, date-range, and generic empty states is
verified without a Tk display.
"""

from __future__ import annotations

from source.ui.suggestion_panel import empty_state_message

_CRATES = "No crates selected — pick at least one crate to see suggestions."
_GENRES = "No genres selected — pick at least one genre to see suggestions."
_DATE = (
    "No tracks found in this date range. "
    "Try a wider window or reset the date filter."
)
_GENERIC = "No compatible tracks found"


def test_active_empty_crates_yields_crates_message():
    assert empty_state_message(
        crates_active_empty=True,
        genres_active_empty=False,
        date_filter_active=False,
    ) == _CRATES


def test_active_empty_genres_yields_genres_message():
    assert empty_state_message(
        crates_active_empty=False,
        genres_active_empty=True,
        date_filter_active=False,
    ) == _GENRES


def test_crates_take_precedence_over_genres_and_date():
    # When more than one applies, crates win.
    assert empty_state_message(
        crates_active_empty=True,
        genres_active_empty=True,
        date_filter_active=True,
    ) == _CRATES


def test_genres_take_precedence_over_date():
    assert empty_state_message(
        crates_active_empty=False,
        genres_active_empty=True,
        date_filter_active=True,
    ) == _GENRES


def test_date_filter_message_when_no_filter_cleared():
    assert empty_state_message(
        crates_active_empty=False,
        genres_active_empty=False,
        date_filter_active=True,
    ) == _DATE


def test_generic_fallback_when_nothing_active():
    assert empty_state_message(
        crates_active_empty=False,
        genres_active_empty=False,
        date_filter_active=False,
    ) == _GENERIC
