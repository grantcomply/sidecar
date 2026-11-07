"""The paste query: the text the DJ pastes into rekordbox's or Serato's search box (pure).

The copy button on a suggestion row puts this text on the clipboard. The DJ
pastes it into the DJ app's own search, which highlights the track, and loads
it with that app's own controls (blueprint D1, ADR-016).

Principle: **less is more.** Both DJ apps find a track from any words or
substrings it contains, so the query keeps the core artist and title words and
drops decorations: bracketed segments (``(Extended Mix)``, ``[Label]``) and
``feat.`` credits. Every word left comes from the track's own fields, so it
still matches.

This is **not** ``Track.search_text`` (``source/models/track.py``), which is
Sidecar's own lowercase search haystack for ``TrackLibrary.search``.

Leaf module: standard library only. ``PurePath`` is used, never ``Path``: no
file-system access.
"""

from __future__ import annotations

import re
from pathlib import PurePath

# Rule 1: runs of whitespace and control characters become one space.
_WHITESPACE_RE = re.compile(r"[\s\x00-\x1f\x7f]+")

# Rule 2.1: one innermost balanced (…), […] or {…} segment.
_BALANCED_BRACKETS_RE = re.compile(r"\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}")

# Rule 2.2: an unmatched opening bracket cuts to the end; stray closers become a space.
_UNMATCHED_OPEN_RE = re.compile(r"[(\[{].*$")
_STRAY_CLOSE_RE = re.compile(r"[)\]}]")

# Rule 2.3: a standalone feat / feat. / ft / ft. / featuring token and everything after it.
# Standalone means preceded by a space (or the start) and followed by a space
# (or the end), so "Aftermath", "Left" and "Feather" never match.
_FEAT_TAIL_RE = re.compile(
    r"(?:^|\s)(?:feat\.?|ft\.?|featuring)(?=\s|$).*$",
    re.IGNORECASE,
)

# Rule 2.4: separators (and spaces) stripped from the ends; kept between words.
_EDGE_SEPARATORS = " -\u2013\u2014/,;:&+|~"  # space - – — / , ; : & + | ~


def _clean(s: str) -> str:
    """Rule 1: collapse whitespace and control characters to one space; strip the ends."""
    return _WHITESPACE_RE.sub(" ", s).strip()


def _remove_balanced_brackets(s: str) -> str:
    """Remove balanced bracket segments, innermost first, until none is left."""
    while True:
        stripped = _BALANCED_BRACKETS_RE.sub(" ", s)
        if stripped == s:
            return s
        s = stripped


def _strip_decorations(s: str) -> str:
    """Rule 2: drop bracketed segments and a feat. tail; fall back to ``s`` if nothing is left.

    ``s`` is expected to be already ``_clean``ed.
    """
    stripped = _remove_balanced_brackets(s)
    stripped = _UNMATCHED_OPEN_RE.sub("", stripped)
    stripped = _STRAY_CLOSE_RE.sub(" ", stripped)  # a space: "Track)One" -> "Track One"
    stripped = _FEAT_TAIL_RE.sub("", stripped)
    stripped = _clean(stripped).strip(_EDGE_SEPARATORS)
    return stripped or s


def _normalised(s: str) -> str:
    """Rules 1 and 2 for one field; ``""`` when the field is missing."""
    cleaned = _clean(s)
    return _strip_decorations(cleaned) if cleaned else ""


def paste_query(artist: str, title: str, file_name: str = "") -> str | None:
    """The text to paste into a DJ app's search box, or None when there is nothing to copy.

    - Title present: ``"{artist} {title}"`` (one space), or the title alone.
    - No title: the file name without its extension; the artist is not added.
    - No title and no file name: the artist alone.
    - Nothing at all: ``None``.

    Every field is normalised and stripped of bracketed segments and feat.
    credits (blueprint D1). Case and accents are kept.
    """
    clean_artist = _normalised(artist)
    clean_title = _normalised(title)
    if clean_title:
        return f"{clean_artist} {clean_title}" if clean_artist else clean_title

    cleaned_file = _clean(file_name)
    # PurePath flavour doesn't matter: file_name is always a same-OS basename.
    stem = _normalised(PurePath(cleaned_file).stem) if cleaned_file else ""
    if stem:
        return stem
    return clean_artist or None
