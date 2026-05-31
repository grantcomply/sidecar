"""Unit tests for the load-bearing filter-bar microcopy helpers (T3 review).

These cover the pure label functions extracted from ``KeyOffsetControl`` and
``DateRangeControl`` so the brief's microcopy is verified without a Tk display.
"""

from __future__ import annotations

from source.ui.filter_bar import (
    date_pill_label,
    filter_pill_label,
    key_offset_label,
)


# ── key_offset_label ──


def test_key_offset_label_zero_is_same_key():
    assert key_offset_label(0) == "Transition: same key"


def test_key_offset_label_positive_has_plus_sign():
    assert key_offset_label(1) == "Transition: +1"
    assert key_offset_label(2) == "Transition: +2"


def test_key_offset_label_negative_uses_unicode_minus():
    # U+2212 MINUS SIGN, not an ASCII hyphen.
    assert key_offset_label(-1) == "Transition: −1"
    assert key_offset_label(-2) == "Transition: −2"
    assert "−" in key_offset_label(-1)
    assert "-" not in key_offset_label(-1)


# ── date_pill_label ──


def test_date_pill_label_default_is_any_time():
    assert date_pill_label(is_default=True) == "Added: any time"


def test_date_pill_label_default_ignores_other_args():
    # Default state always wins regardless of stale preset/from args.
    label = date_pill_label(
        is_default=True, preset="Last month", from_str="2026-01-01")
    assert label == "Added: any time"


def test_date_pill_label_preset_lowercased():
    assert date_pill_label(
        is_default=False, preset="Last 3 months") == "Added: last 3 months"
    assert date_pill_label(
        is_default=False, preset="This year") == "Added: this year"


def test_date_pill_label_from_only():
    assert date_pill_label(
        is_default=False, from_str="2026-03-01") == "Added: from 2026-03-01"


def test_date_pill_label_from_and_to_uses_en_dash():
    label = date_pill_label(
        is_default=False, from_str="2026-01-01", to_str="2026-03-01")
    # U+2013 EN DASH between the two dates, per the brief microcopy table.
    assert label == "Added: 2026-01-01 – 2026-03-01"
    assert "–" in label


# ── filter_pill_label ──


def test_filter_pill_label_all_selected_is_plain_label():
    # All selected = no filter active = plain label, no count suffix.
    assert filter_pill_label("Crates", selected=9, total=9) == "Crates"


def test_filter_pill_label_empty_list_is_plain_label():
    # No items loaded behaves like the no-filter default.
    assert filter_pill_label("Crates", selected=0, total=0) == "Crates"


def test_filter_pill_label_zero_selected_reads_none():
    # The intentional all-cleared state — clearer than "0/N" that it's deliberate.
    assert filter_pill_label("Crates", selected=0, total=9) == "Crates: none"
    assert filter_pill_label("Genres", selected=0, total=4) == "Genres: none"


def test_filter_pill_label_single_uses_name():
    assert filter_pill_label(
        "Crates", selected=1, total=9, only="House") == "Crates: House"


def test_filter_pill_label_partial_uses_count():
    assert filter_pill_label("Crates", selected=3, total=9) == "Crates: 3/9"
