"""Tests for ``source.services.comment_format.parse_comment``."""

from __future__ import annotations

import pytest

from source.services.comment_format import CommentFields, parse_comment


@pytest.mark.parametrize(
    ("comment", "expected"),
    [
        ("4A - 7 - Banger - Fat Bass Vocal", CommentFields("4A", 7, "Banger", "Fat Bass Vocal")),
        ("8A - Energy 5 - Groover", CommentFields("8A", 5, "Groover", "")),
        ("12B - 3", CommentFields("12B", 3, "", "")),
        ("Commercial", CommentFields()),
        ("4A - high", CommentFields("4A", 0, "", "")),
        ("4A - 9 - Banger", CommentFields("4A", 0, "Banger", "")),
        ("4A - 0", CommentFields("4A", 0, "", "")),
        ("  4a  -  6  -  driver  -  Deep - Rolling ", CommentFields("4A", 6, "Driver", "Deep - Rolling")),
        ("4A - 7 - Unknowncat - x", CommentFields("4A", 7, "", "x")),
        ("13A - 7", CommentFields()),
        ("", CommentFields()),
    ],
    ids=[
        "full", "energy-word", "key-energy-only", "free-text", "non-numeric-energy",
        "energy-out-of-range", "energy-zero", "whitespace-and-case", "unknown-category",
        "invalid-key", "empty",
    ],
)
def test_parse_comment_cases(comment, expected):
    assert parse_comment(comment) == expected


def test_parse_comment_none_safe():
    assert parse_comment(None) == CommentFields()  # type: ignore[arg-type]
