"""Pure label truncation helpers (no Tk)."""

from source.ui.utils import truncate, truncate_start


def test_truncate_start_keeps_the_leaf_and_cuts_at_a_separator():
    text = "Club Folder / My Sets / LiveSets / 02. CrumbsAndCream"
    out = truncate_start(text, 38)
    assert out == "\u2026 / LiveSets / 02. CrumbsAndCream"
    assert len(out) <= 38


def test_truncate_start_without_separator_and_short_text():
    assert truncate_start("abcdefghij", 5) == "\u2026ghij"
    assert truncate_start("short", 38) == "short"
    assert truncate("abcdefghij", 5) == "abcd\u2026"  # the end-cut helper is unchanged
