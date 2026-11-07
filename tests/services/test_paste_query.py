"""Tests for the paste query (blueprint D1, plan T1.2). Invented names only."""

from __future__ import annotations

import time

import pytest

from source.services.paste_query import _EDGE_SEPARATORS, paste_query


# ── Blueprint D1 worked examples (every row is a case) ──


@pytest.mark.parametrize(
    ("artist", "title", "file_name", "expected"),
    [
        ("Artist A", "Track One (Extended Mix)", "", "Artist A Track One"),
        ("Artist A feat. Singer B", "Track One", "", "Artist A Track One"),
        ("Artist A", "Track One feat. Singer B [Club Mix]", "", "Artist A Track One"),
        (
            "Artist A", "Track One (Original Mix) - Radio Edit", "",
            "Artist A Track One - Radio Edit",
        ),
        ("Artist A & Artist B", "Track One", "", "Artist A & Artist B Track One"),
        ("Artist A", "(Intro)", "", "Artist A (Intro)"),
        ("Artist A (UK)", "Track One", "", "Artist A Track One"),
        ("", "", "Artist A - Track One (Extended Mix).mp3", "Artist A - Track One"),
    ],
)
def test_paste_query_blueprint_worked_examples_match_table(artist, title, file_name, expected):
    assert paste_query(artist, title, file_name) == expected


# ── Basic shape ──


def test_paste_query_artist_and_title_joined_by_one_space():
    assert paste_query("Artist A", "Track One") == "Artist A Track One"


def test_paste_query_title_only_returns_title():
    assert paste_query("", "Track One") == "Track One"


def test_paste_query_artist_only_returns_artist():
    assert paste_query("Artist A", "", "") == "Artist A"


@pytest.mark.parametrize(
    ("artist", "title", "file_name"),
    [
        ("", "", ""),
        ("  ", "\t", ""),
        ("\n", "  ", " \t "),
        ("\x00", "\x7f", ""),
    ],
)
def test_paste_query_all_fields_empty_or_whitespace_returns_none(artist, title, file_name):
    assert paste_query(artist, title, file_name) is None


@pytest.mark.parametrize(
    ("artist", "title", "expected"),
    [
        ("Artist\tA", "Track\nOne", "Artist A Track One"),
        ("  Artist   A  ", "Track \r\n One", "Artist A Track One"),
        ("Artist\x00A", "Track\x1fOne\x7f", "Artist A Track One"),
    ],
)
def test_paste_query_whitespace_and_control_chars_collapse_to_one_space(artist, title, expected):
    assert paste_query(artist, title) == expected


def test_paste_query_adds_no_hyphen_between_fields():
    assert paste_query("A", "B") == "A B"


def test_paste_query_case_and_accents_kept():
    assert paste_query("ArTiSt Élan", "Über Track") == "ArTiSt Élan Über Track"


# ── Stripping, title ──


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Track One (Extended Mix)", "Track One"),
        ("Track One [Remix]", "Track One"),
        ("Track One {Free DL}", "Track One"),
        ("Track One (feat. Singer B)", "Track One"),
        ("Track One (Mix (Edit))", "Track One"),
        ("Track One (Original Mix) [Label]", "Track One"),
        ("Track One feat. Singer B", "Track One"),
        ("Track One ft Singer B", "Track One"),
        ("Track One Ft. Singer B", "Track One"),
        ("Track One featuring Singer B", "Track One"),
        ("Track One feat. Singer B [Club Mix]", "Track One"),
        ("Track One (Club Mix) feat. Singer B", "Track One"),
        ("Aftermath", "Aftermath"),
        ("Left Feather", "Left Feather"),
        ("Track One (Original Mix) - Radio Edit", "Track One - Radio Edit"),
        ("Track One - (Original Mix)", "Track One"),
        ("Track One / [Edit]", "Track One"),
        ("Track One (Extended", "Track One"),
        ("Track One)", "Track One"),
        ("Track)One", "Track One"),
        ("(Intro)", "(Intro)"),
        ("feat. Singer B", "feat. Singer B"),
        ("Don't Stop!", "Don't Stop!"),
    ],
)
def test_paste_query_title_decorations_stripped(title, expected):
    assert paste_query("", title) == expected


# ── Stripping, artist ──


@pytest.mark.parametrize(
    ("artist", "expected"),
    [
        ("Artist A feat. Singer B", "Artist A"),
        ("Artist A ft. Singer B", "Artist A"),
        ("Artist A (UK)", "Artist A"),
        ("Artist A & Artist B", "Artist A & Artist B"),
        ("Artist A, Artist B", "Artist A, Artist B"),
        ("Artist A x Artist B", "Artist A x Artist B"),
        ("Artist A vs. Artist B", "Artist A vs. Artist B"),
    ],
)
def test_paste_query_artist_decorations_stripped_collaborations_kept(artist, expected):
    assert paste_query(artist, "") == expected


def test_paste_query_artist_and_title_both_stripped_combined():
    query = paste_query("Artist A feat. Singer B", "Track One (Extended Mix)")
    assert query == "Artist A Track One"


# ── File-name fallback ──


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("Artist A - Track One.mp3", "Artist A - Track One"),
        ("Artist A - Track One (Extended Mix).mp3", "Artist A - Track One"),
        ("a.b.c.flac", "a.b.c"),
    ],
)
def test_paste_query_no_title_uses_stripped_file_stem(file_name, expected):
    assert paste_query("", "", file_name) == expected


def test_paste_query_no_title_file_stem_without_artist_prefix():
    assert paste_query("Artist A", "", "Artist A - Track One.mp3") == "Artist A - Track One"


def test_paste_query_whitespace_title_falls_back_to_file_stem():
    assert paste_query("Artist A", "   ", "Track One.mp3") == "Track One"


# ── Edge cases (code review) ──

_SEPARATORS = [s for s in _EDGE_SEPARATORS if s != " "]
_DEEP_NESTING_BUDGET_S = 1.0


def test_edge_separators_cover_review_list():
    assert set("–—&|~:") <= set(_SEPARATORS)


@pytest.mark.parametrize("sep", _SEPARATORS)
def test_paste_query_dangling_separator_either_end_removed(sep):
    assert paste_query("", f"Track One {sep}") == "Track One"
    assert paste_query("", f"{sep} Track One") == "Track One"
    assert paste_query("", f"Track One {sep} (Extended Mix)") == "Track One"
    assert paste_query("", f"[Label] {sep} Track One") == "Track One"


@pytest.mark.parametrize("sep", _SEPARATORS)
def test_paste_query_separator_between_words_kept(sep):
    assert paste_query("", f"Track {sep} One") == f"Track {sep} One"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("[Label] - Track One", "Track One"),
        ("Track One feat.", "Track One"),
        ("Track One ft", "Track One"),
        ("Track One FEATURING Singer B", "Track One"),
        ("Track One feat.Singer B", "Track One feat.Singer B"),
        ("Craft", "Craft"),
        ("Soft Focus", "Soft Focus"),
        ("Featherweight", "Featherweight"),
        ("Track One (Mix]", "Track One"),
        ("Track One [A (B] C)", "Track One C"),
        ("(Track One", "(Track One"),
    ],
)
def test_paste_query_title_edge_cases_follow_d1(title, expected):
    assert paste_query("", title) == expected


def test_paste_query_bracket_only_file_stem_falls_back_to_unstripped():
    assert paste_query("", "", "(Intro).mp3") == "(Intro)"


def test_paste_query_whitespace_file_name_uses_artist():
    assert paste_query("Artist A", "", "  ") == "Artist A"


def test_paste_query_deep_nesting_returns_quickly():
    title = "(" * 2000 + "x" + ")" * 2000
    start = time.perf_counter()
    result = paste_query("", title)
    assert time.perf_counter() - start < _DEEP_NESTING_BUDGET_S
    assert result == title  # everything is bracketed, so rule 2.5 keeps the field
