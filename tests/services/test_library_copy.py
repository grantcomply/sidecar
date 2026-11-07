"""Tests for the pure copy module (brief §7, plan T3c.1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from source.services import library_copy as c

NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)


def _ago(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        ({"seconds": 0}, "just now"),
        ({"seconds": 44}, "just now"),
        ({"seconds": 45}, "1 minute ago"),
        ({"minutes": 12}, "12 minutes ago"),
        ({"minutes": 59}, "59 minutes ago"),
        ({"minutes": 60}, "1 hour ago"),
        ({"hours": 2}, "2 hours ago"),
        ({"hours": 23, "minutes": 59}, "23 hours ago"),
        ({"hours": 24}, "1 day ago"),
        ({"days": 3}, "3 days ago"),
        ({"days": 29}, "29 days ago"),
        ({"seconds": -30}, "just now"),  # clock skew: never "in the future"
    ],
)
def test_relative_time_boundaries(delta, expected):
    assert c.relative_time(_ago(**delta), NOW) == expected


def test_relative_time_30_days_and_other_year():
    then = NOW - timedelta(days=30)
    local = then.astimezone()
    assert c.relative_time(then.isoformat(), NOW) == f"on {local.day} {local.strftime('%b')}"
    old = datetime(2025, 11, 3, 12, 0, tzinfo=timezone.utc)
    assert c.relative_time(old.isoformat(), NOW).endswith(" 2025")
    assert c.relative_time(old.isoformat(), NOW).startswith("on 3 Nov")


def test_relative_time_bad_input():
    assert c.relative_time("", NOW) == ""
    assert c.relative_time("not a date", NOW) == ""


def test_absolute_time_format():
    text = c.absolute_time("2026-11-03T14:20:00+00:00")
    local = datetime(2026, 11, 3, 14, 20, tzinfo=timezone.utc).astimezone()
    assert text == f"{local.day} {local.strftime('%b')}, {local.strftime('%H:%M')}"
    assert c.absolute_time("") == ""


@pytest.mark.parametrize(
    ("nouns", "expected"),
    [([], "crate"), (["crate"], "crate"), (["playlist"], "playlist"),
     (["playlist", "crate"], "playlist"), (["crate", "crate"], "crate")],
)
def test_crate_noun_for(nouns, expected):
    assert c.crate_noun_for(nouns) == expected


def test_counts_nouns_and_names():
    assert c.format_count(1248) == "1,248"
    assert c.pluralise("playlist", 1) == "1 playlist"
    assert c.pluralise("playlist", 75) == "75 playlists"
    assert c.pluralise("track", 1248) == "1,248 tracks"
    assert c.noun_title("playlist") == "Playlists"
    assert c.noun_title("crate", plural=False) == "Crate"
    assert c.join_names(["rekordbox"]) == "rekordbox"
    assert c.join_names(["rekordbox", "Serato DJ"]) == "rekordbox and Serato DJ"
    assert c.join_names(["a", "b", "c"]) == "a, b and c"


def _chip(**kw):
    base: dict[str, Any] = dict(enabled=True, busy=False, synced_at=_ago(minutes=2), track_count=1248,
                crate_count=75, noun="playlist", auto_updates=False, now=NOW)
    base.update(kw)
    return c.status_chip(**base)


def test_status_chip_five_cases():
    assert _chip(busy=True) == ("Syncing…",)
    assert _chip(synced_at=None) == ("Not synced yet",)
    assert _chip(synced_at=_ago(hours=2)) == ("Synced 2 hours ago · 1,248 tracks · 75 playlists",)
    assert _chip(auto_updates=True) == (
        "Updates automatically · 1,248 tracks · 75 playlists", "Last updated 2 minutes ago",
    )
    assert _chip(enabled=False) == ("Off. Saved library kept.",)
    assert _chip(enabled=False, synced_at=None) == ("Off",)


def test_status_chip_singular_counts():
    assert _chip(track_count=1, crate_count=1, noun="crate", synced_at=_ago(seconds=5)) == (
        "Synced just now · 1 track · 1 crate",
    )


@dataclass
class _Issue:
    severity: str
    setting_key: str | None = None


def test_issue_tone_rules():
    assert c.issue_tone(_Issue("warning", "db_path"), "x") == "warning"
    assert c.issue_tone(_Issue("error", "db_path"), "") == "warning"   # empty field: prompt
    assert c.issue_tone(_Issue("error", "db_path"), "C:/x/backup.db") == "error"
    assert c.issue_tone(_Issue("error", None), "") == "error"          # no field to fill


NAMES = {"rekordbox": "rekordbox", "serato": "Serato DJ"}


def test_footer_zero_enabled():
    f = c.footer_state([], {}, NAMES, dirty=False, busy=False)
    assert (f.sync_enabled, f.message, f.tone) == (False, "Turn on at least one source to load tracks.",
                                                   "warning")
    assert f.close_label == "Close" and not f.save_enabled


def test_footer_all_errored_disables_sync():
    f = c.footer_state(["rekordbox"], {"rekordbox": "Database not found"}, NAMES,
                       dirty=False, busy=False)
    assert not f.sync_enabled
    assert f.message == "Can't sync rekordbox: Database not found"


def test_footer_some_errored_skips_but_syncs():
    f = c.footer_state(["rekordbox", "serato"], {"serato": "Crates folder not found"}, NAMES,
                       dirty=False, busy=False)
    assert f.sync_enabled and f.message == "Skipped Serato DJ: Crates folder not found"
    many = c.footer_state(["rekordbox", "serato", "x"], {"serato": "a", "x": "b"}, NAMES,
                          dirty=False, busy=False)
    assert many.message.endswith("(+1 more)")


def test_footer_dirty_and_busy():
    dirty = c.footer_state(["rekordbox"], {}, NAMES, dirty=True, busy=False)
    assert dirty.close_label == "Cancel" and dirty.save_enabled and dirty.sync_enabled
    busy = c.footer_state(["rekordbox"], {}, NAMES, dirty=True, busy=True)
    assert not busy.save_enabled and not busy.sync_enabled


def test_empty_library_state_three_branches():
    none = c.empty_library_state([], [], [])
    assert none == c.EmptyLibraryState("Turn on a music source in Settings (⚙) to begin",
                                       "No music source is turned on")
    reading = c.empty_library_state(["rekordbox"], ["rekordbox"], [])
    assert reading == c.EmptyLibraryState("Reading your library…", None)
    failed = c.empty_library_state(["rekordbox"], ["rekordbox"], ["rekordbox"])
    serato = c.empty_library_state(["serato"], [], [])
    expected = c.EmptyLibraryState("Sync your library in Settings (⚙) to begin",
                                   "Your library isn't synced yet")
    assert failed == expected and serato == expected


TOASTS = [
    c.format_load_toast(1248, 75, "playlist"),
    c.format_sync_success(1248, 75, "playlist", ["rekordbox"]),
    c.format_sync_success(1300, 84, "playlist", ["rekordbox", "Serato DJ"]),
    c.format_import_toast(1248, ["rekordbox"]),
    c.format_partial_failure(["rekordbox"], "Serato DJ", "Crates folder not found"),
    c.format_sync_failure("rekordbox", "Database not found"),
    c.format_all_failed(["rekordbox", "Serato DJ"]),
    c.format_refresh_failure("rekordbox", "Database not found"),
    c.TOAST_NO_SOURCE,
    c.TOAST_NOT_SYNCED,
]


def test_toast_texts_exact():
    assert TOASTS[:8] == [
        "Loaded 1,248 tracks from 75 playlists",
        "Synced 1,248 tracks from 75 playlists",
        "Synced 1,300 tracks from rekordbox and Serato DJ",
        "Imported 1,248 tracks from rekordbox",
        "Synced rekordbox. Serato DJ sync failed: Crates folder not found",
        "rekordbox sync failed: Database not found",
        "Sync failed for rekordbox and Serato DJ",
        "rekordbox auto-update failed: Database not found",
    ]


@pytest.mark.parametrize("text", TOASTS)
def test_toasts_short_and_pathless(text):
    assert len(text) <= 75
    assert "\\" not in text and ":/" not in text


def test_all_failed_never_says_synced():
    assert "Synced" not in c.format_all_failed(["rekordbox", "Serato DJ"])


def test_panel_and_title_strings():
    assert c.WINDOW_TITLE == "Sidecar — DJ Track Selector"
    assert c.dialog_title("0.2.0") == "Settings — Sidecar v0.2.0"
    assert c.overlay_empty_text("playlist") == "No playlists loaded. Sync a source in Settings."
    assert c.cleared_filter_message("crate") == (
        "No crates selected — pick at least one crate to see suggestions."
    )
    assert c.precedence_note("rekordbox") == (
        "When a track is in both, its details come from rekordbox."
    )
    assert c.fallback_line("3 Nov, 14:20") == "Using your library from 3 Nov, 14:20."


def test_load_toast_names_sources_when_several():
    assert c.format_load_toast(740, 148, "playlist", ["rekordbox", "Serato DJ"]) == (
        "Loaded 740 tracks from rekordbox and Serato DJ"
    )
    assert c.format_load_toast(740, 75, "playlist", ["rekordbox"]) == (
        "Loaded 740 tracks from 75 playlists"
    )


KNOWN_PROVIDER_ERRORS = [
    # Serato
    "Crates folder not found", "No crates found in this folder",
    # rekordbox
    "Database not found", "Choose the file named master.db",
    "Not available in this build", "Couldn't read the database",
    "Database is busy, try again",
    # library_sync
    "Couldn't start the sync",
]


@pytest.mark.parametrize("error", KNOWN_PROVIDER_ERRORS)
@pytest.mark.parametrize(("ok", "failed"), [
    (["rekordbox"], "Serato DJ"), (["Serato DJ"], "rekordbox"),
])
def test_every_known_error_fits_the_partial_failure_toast(error, ok, failed):
    text = c.format_partial_failure(ok, failed, error)
    assert len(text) <= 75, (len(text), text)
    for fmt in (c.format_sync_failure, c.format_refresh_failure):
        assert len(fmt(failed, error)) <= 75


# ── Crate attribution in the suggestion tooltip (T5.4) ──


def test_crate_tooltip_lines_single_provider_uses_noun_heading():
    assert c.crate_tooltip_lines([(None, ["A", "B"])], "playlist") == ["Playlists: A, B"]
    assert c.crate_tooltip_lines([(None, ["House"])], "crate") == ["Crates: House"]


def test_crate_tooltip_lines_one_line_per_provider_in_given_order():
    groups = [("rekordbox", ["Club / Peak", "Warm up"]), ("Serato DJ", ["House - Bangers"])]
    assert c.crate_tooltip_lines(groups, "playlist") == [
        "rekordbox: Club / Peak, Warm up",
        "Serato DJ: House - Bangers",
    ]


def test_crate_tooltip_lines_skips_empty_groups_and_unknown_provider_uses_noun():
    groups = [("rekordbox", []), ("Serato DJ", ["X"]), (None, ["ghost"])]
    assert c.crate_tooltip_lines(groups, "playlist") == ["Serato DJ: X", "Playlists: ghost"]
    assert c.crate_tooltip_lines([], "crate") == []


# ── Copy search text (copy-track-search-text plan T1.4) ──

_COPY_GLYPHS = (c.BUTTON_COPY, c.BUTTON_COPIED, c.BUTTON_COPY_FAILED, c.BUTTON_COPY_DISABLED)
_AVOIDED_WORDS = ("load", "loaded", "sent", "send", "deck", "added", "selected")  # brief §8


def _copy_strings() -> list[str]:
    query = "Artist A Track One"
    return [
        *_COPY_GLYPHS,
        c.HEADER_COPY,
        c.COPY_NOTHING,
        c.COPY_FAILED,
        c.COPY_FAILED_TOOLTIP,
        c.format_copy_tooltip(query),
        c.format_copied_tooltip(query),
        c.format_copied_toast(query),
    ]


def test_copied_toast_short_text_shown_in_full_inside_quotes():
    assert c.format_copied_toast("Artist A Track One") == 'Copied "Artist A Track One"'


def test_copied_toast_long_text_truncated_to_max_with_ellipsis():
    toast = c.format_copied_toast("x" * 200)
    assert len(toast) == c.COPIED_TOAST_MAX == 75
    assert toast.startswith('Copied "')
    assert toast.endswith('…"')


def test_copied_toast_boundary_66_kept_67_truncated():
    at_limit = "y" * 66
    assert c.format_copied_toast(at_limit) == f'Copied "{at_limit}"'
    assert len(c.format_copied_toast(at_limit)) == 75
    over = c.format_copied_toast("y" * 67)
    assert len(over) == 75
    assert over.endswith('…"')


def test_copy_failed_fits_toast_limit():
    assert len(c.COPY_FAILED) <= c.COPIED_TOAST_MAX


def test_copy_strings_never_use_avoided_words():
    for text in _copy_strings():
        words = {w.strip(".,:;!?\"'").lower() for w in text.split()}
        assert not words & set(_AVOIDED_WORDS), text
        assert "load" not in text.lower(), text


def test_copy_tooltip_second_line_is_exact_query():
    query = "Artist A Track One"
    lines = c.format_copy_tooltip(query).split("\n")
    assert lines == [
        "Copy to the clipboard:",
        query,
        "Then paste it into your DJ software's search box.",
    ]


def test_copy_tooltip_long_query_not_altered_or_truncated():
    query = "Artist A " + "Long Title " * 20
    assert c.format_copy_tooltip(query).split("\n")[1] == query


def test_copied_tooltip_second_line_is_exact_query():
    query = "Artist A Track One"
    lines = c.format_copied_tooltip(query).split("\n")
    assert lines == ["Copied:", query, "Now paste it into your DJ software's search box."]


def test_copy_button_glyphs_single_distinct_bmp_characters():
    assert all(len(g) == 1 for g in _COPY_GLYPHS)
    assert len(set(_COPY_GLYPHS)) == len(_COPY_GLYPHS)
    assert all(ord(g) < 0x10000 for g in _COPY_GLYPHS)
    # Ready glyph is one of the brief §3.3 fallback ladder: ❐, ⧉, □.
    assert ord(c.BUTTON_COPY) in {0x2750, 0x29C9, 0x25A1}
    assert (c.BUTTON_COPIED, c.BUTTON_COPY_FAILED, c.BUTTON_COPY_DISABLED) == (
        "\u2713", "\u2715", "\u2014",  # ✓ ✕ —
    )
