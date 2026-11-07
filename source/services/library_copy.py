"""Every user-visible string for library sources, sync and settings (pure; no Tk).

Single home for the copy in ``ui-design-brief.md`` §7, so a wording change
touches one file. Lives in ``services`` (not ``ui``) because
``services/sync_outcome.py`` uses it and services must not import ui.

Conventions (brief §7): sentence case; counts with thousands separators;
provider names as the vendors write them (``rekordbox``, ``Serato DJ``);
toasts under about 75 characters and never containing a path.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Protocol

# ── Titles, headings and fixed strings ──

WINDOW_TITLE = "Sidecar — DJ Track Selector"
SECTION_HEADING = "Music sources"
SECTION_SUBTEXT = (
    "Turn on the DJ software you use. Sidecar reads its crates and playlists "
    "and never changes your libraries."
)
UNSAVED_CHANGES = "Unsaved changes"
SETTINGS_SAVED = "Settings saved"
NOT_SYNCED = "Not synced yet"
SYNCING = "Syncing…"
OFF_WITH_SNAPSHOT = "Off. Saved library kept."
OFF = "Off"
ZERO_SOURCES = "Turn on at least one source to load tracks."
BUTTON_CLOSE = "Close"
BUTTON_CANCEL = "Cancel"
BUTTON_SAVE = "Save"
BUTTON_BROWSE = "Browse"
BUTTON_SYNC = "Sync enabled sources"
BUTTON_SYNCING = "Syncing…"
ACTION_OPEN_SETTINGS = "Open settings"
DEFAULT_DASHBOARD_PROMPT = "Search for a track to begin"
PLACEHOLDER_NO_SOURCE = "Turn on a music source in Settings (⚙) to begin"
PLACEHOLDER_READING = "Reading your library…"
PLACEHOLDER_NOT_SYNCED = "Sync your library in Settings (⚙) to begin"
TOAST_NO_SOURCE = "No music source is turned on"
TOAST_NOT_SYNCED = "Your library isn't synced yet"

_DEFAULT_NOUN = "crate"
_PLAYLIST_NOUN = "playlist"
_RELATIVE_JUST_NOW_S = 45
_RELATIVE_MAX_DAYS = 29


def dialog_title(version: str) -> str:
    return f"Settings — Sidecar v{version}"


def precedence_note(first_name: str) -> str:
    """Shown while two or more sources are on (brief §5.9, after the merge exists)."""
    return f"When a track is in both, its details come from {first_name}."


def fallback_line(absolute: str) -> str:
    return f"Using your library from {absolute}."


# ── Numbers, nouns and names ──


def format_count(n: int) -> str:
    return f"{n:,}"


def pluralise(noun: str, n: int) -> str:
    """``"1 playlist"``, ``"75 playlists"`` (with thousands separators)."""
    return f"{format_count(n)} {noun if n == 1 else noun + 's'}"


def noun_title(noun: str, plural: bool = True) -> str:
    """``"Playlists"`` / ``"Playlist"``."""
    word = noun + "s" if plural else noun
    return word[:1].upper() + word[1:]


def crate_noun_for(nouns: Iterable[str]) -> str:
    """The word for crates/playlists given the enabled providers' nouns (brief O3).

    None, or only "crate" → "crate"; all the same other noun → that noun;
    any mix → "playlist".
    """
    distinct = set(nouns)
    if not distinct or distinct == {_DEFAULT_NOUN}:
        return _DEFAULT_NOUN
    if len(distinct) == 1:
        return next(iter(distinct))
    return _PLAYLIST_NOUN


def join_names(names: Sequence[str]) -> str:
    """``"a"``, ``"a and b"``, ``"a, b and c"``."""
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def overlay_empty_text(noun: str) -> str:
    return f"No {noun}s loaded. Sync a source in Settings."


BUTTON_SELECT_ALL = "Select all"
BUTTON_CLEAR = "Clear"
BUTTON_SELECT_SHOWN = "Select shown"
BUTTON_CLEAR_SHOWN = "Clear shown"


def find_placeholder(noun: str) -> str:
    """Search box placeholder in the playlist filter: ``Find a playlist``."""
    return f"Find a {noun}"


def no_match_text(noun: str, text: str) -> str:
    return f'No {noun}s match "{text}"'


def group_header(display_name: str) -> str:
    """Provider header in the playlist filter: ``REKORDBOX``, ``SERATO DJ``."""
    return display_name.upper()


def cleared_filter_message(noun: str) -> str:
    return f"No {noun}s selected — pick at least one {noun} to see suggestions."


def crates_heading(noun: str) -> str:
    """Tooltip heading and Now Playing info-line label: ``"Playlists"``."""
    return noun_title(noun)


def crate_tooltip_lines(
    groups: Sequence[tuple[str | None, Sequence[str]]], noun: str,
) -> list[str]:
    """Suggestion-tooltip crate lines (brief §5.10, T5.4).

    ``groups`` is ``(provider display name, labels)`` in registry order. A
    ``None`` name (one provider enabled, or a crate of unknown provider) uses
    the noun heading: ``Playlists: A, B``. Named groups give one line per
    provider: ``rekordbox: Club / Peak, Warm up``. Groups without labels are
    skipped. No provider colour, ever (colour is data).
    """
    return [
        f"{name if name else crates_heading(noun)}: {', '.join(labels)}"
        for name, labels in groups if labels
    ]


# ── Time ──


def _parse_utc(iso_utc: str) -> datetime | None:
    if not iso_utc:
        return None
    try:
        parsed = datetime.fromisoformat(iso_utc)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _plural_unit(n: int, unit: str) -> str:
    return f"{n} {unit}{'' if n == 1 else 's'} ago"


def relative_time(iso_utc: str, now: datetime) -> str:
    """``"just now"``, ``"12 minutes ago"``, ``"2 hours ago"``, ``"3 days ago"``, ``"on 3 Nov"``.

    ``now`` should be timezone-aware (UTC); a naive ``now`` is taken as UTC.
    Empty or unparsable input returns ``""``.
    """
    then = _parse_utc(iso_utc)
    if then is None:
        return ""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    seconds = (now - then).total_seconds()
    if seconds < _RELATIVE_JUST_NOW_S:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return _plural_unit(max(1, minutes), "minute")
    hours = minutes // 60
    if hours < 24:
        return _plural_unit(hours, "hour")
    days = hours // 24
    if days <= _RELATIVE_MAX_DAYS:
        return _plural_unit(days, "day")
    local_then, local_now = then.astimezone(), now.astimezone()
    day = f"{local_then.day} {local_then.strftime('%b')}"
    return f"on {day}" if local_then.year == local_now.year else f"on {day} {local_then.year}"


def absolute_time(iso_utc: str) -> str:
    """Local ``"3 Nov, 14:20"`` for the fallback line; ``""`` if unparsable."""
    then = _parse_utc(iso_utc)
    if then is None:
        return ""
    local = then.astimezone()
    return f"{local.day} {local.strftime('%b')}, {local.strftime('%H:%M')}"


# ── Settings dialog ──


def status_chip(
    *,
    enabled: bool,
    busy: bool,
    synced_at: str | None,
    track_count: int,
    crate_count: int,
    noun: str,
    auto_updates: bool,
    now: datetime,
) -> tuple[str, ...]:
    """One or two chip lines for a provider card (brief §5.1, §5.3, §5.4)."""
    if not enabled:
        return (OFF_WITH_SNAPSHOT if synced_at else OFF,)
    if busy:
        return (SYNCING,)
    if not synced_at:
        return (NOT_SYNCED,)
    counts = f"{pluralise('track', track_count)} · {pluralise(noun, crate_count)}"
    when = relative_time(synced_at, now)
    if auto_updates:
        return (f"Updates automatically · {counts}", f"Last updated {when}")
    return (f"Synced {when} · {counts}",)


class _IssueLike(Protocol):
    @property
    def severity(self) -> str: ...

    @property
    def setting_key(self) -> str | None: ...


Tone = Literal["error", "warning"]


def issue_tone(issue: _IssueLike, field_value: str) -> Tone:
    """Brief §5.2: warnings, and errors on an empty field (a prompt), are amber; others red."""
    if issue.severity == "warning":
        return "warning"
    if issue.setting_key is not None and not field_value:
        return "warning"
    return "error"


@dataclass(frozen=True)
class FooterState:
    sync_enabled: bool
    message: str
    tone: Tone | None
    close_label: str
    save_enabled: bool


def footer_state(
    enabled_ids: Sequence[str],
    errors: Mapping[str, str],
    names: Mapping[str, str],
    *,
    dirty: bool,
    busy: bool,
) -> FooterState:
    """Footer buttons and message (brief §4.1, §4.2).

    ``errors`` maps an enabled provider id to its first error message; such a
    provider is skipped by Sync, never a blocker for the others.
    """
    close_label = BUTTON_CANCEL if dirty else BUTTON_CLOSE
    save_enabled = dirty and not busy
    if not enabled_ids:
        return FooterState(False, ZERO_SOURCES, "warning", close_label, save_enabled)
    skipped = [pid for pid in enabled_ids if pid in errors]
    message, tone = "", None
    if skipped:
        first = skipped[0]
        # Nothing can sync: say so plainly (audit L3); otherwise the others still sync.
        verb = "Can't sync" if len(skipped) == len(enabled_ids) else "Skipped"
        message = f"{verb} {names.get(first, first)}: {errors[first]}"
        if len(skipped) > 1:
            message += f" (+{len(skipped) - 1} more)"
        tone = "warning"
    can_sync = len(skipped) < len(enabled_ids) and not busy
    return FooterState(can_sync, message, tone, close_label, save_enabled)


# ── Toasts ──


def format_load_toast(
    count: int, crate_count: int, noun: str, names: Sequence[str] = (),
) -> str:
    """One source: ``Loaded 1,248 tracks from 75 playlists``; several: name them (audit M2)."""
    if len(names) > 1:
        return f"Loaded {pluralise('track', count)} from {join_names(names)}"
    return f"Loaded {pluralise('track', count)} from {pluralise(noun, crate_count)}"


def format_sync_success(count: int, crate_count: int, noun: str, names: Sequence[str]) -> str:
    if len(names) > 1:
        return f"Synced {pluralise('track', count)} from {join_names(names)}"
    return f"Synced {pluralise('track', count)} from {pluralise(noun, crate_count)}"


def format_import_toast(count: int, names: Sequence[str]) -> str:
    return f"Imported {pluralise('track', count)} from {join_names(names)}"


def format_partial_failure(ok_names: Sequence[str], failed_name: str, error: str) -> str:
    return f"Synced {join_names(ok_names)}. {failed_name} sync failed: {error}"


def format_sync_failure(name: str, error: str) -> str:
    return f"{name} sync failed: {error}"


def format_all_failed(names: Sequence[str]) -> str:
    return f"Sync failed for {join_names(names)}"


def format_refresh_failure(name: str, error: str) -> str:
    return f"{name} auto-update failed: {error}"


# ── Copy search text (copy-track-search-text brief §8) ──
# Never say "Load" here: the DJ app's search finds the track, the DJ loads it.

# Icon-only button glyphs, one per state (state is never colour alone).
# All in the BMP with no emoji presentation; fallback ladder in brief §3.3.
BUTTON_COPY = "\u2750"  # ❐ ready
BUTTON_COPIED = "\u2713"  # ✓ copied
BUTTON_COPY_FAILED = "\u2715"  # ✕ failed
BUTTON_COPY_DISABLED = "\u2014"  # — nothing to copy
HEADER_COPY = "Copy"
COPY_NOTHING = "Nothing to copy: this track has no artist or title"
COPY_FAILED = "Couldn't copy to the clipboard. Try again."
COPY_FAILED_TOOLTIP = "Couldn't copy. Click to try again."
COPIED_TOAST_MAX = 75

_COPIED_TOAST_PREFIX = 'Copied "'
_COPIED_TOAST_SUFFIX = '"'
_ELLIPSIS = "\u2026"  # …


def format_copy_tooltip(query: str) -> str:
    """Ready tooltip; the middle line is the exact text that will be copied."""
    return "\n".join((
        "Copy to the clipboard:",
        query,
        "Then paste it into your DJ software's search box.",
    ))


def format_copied_tooltip(query: str) -> str:
    """Tooltip during the copied state (shown if the DJ re-hovers)."""
    return "\n".join((
        "Copied:",
        query,
        "Now paste it into your DJ software's search box.",
    ))


def format_copied_toast(text: str) -> str:
    """``Copied "<text>"``, with ``text`` cut with ``…`` so the toast fits ``COPIED_TOAST_MAX``.

    Truncates here rather than with ``ui/utils.truncate``: services must not
    import ui (blueprint D3; debt #4).
    """
    room = COPIED_TOAST_MAX - len(_COPIED_TOAST_PREFIX) - len(_COPIED_TOAST_SUFFIX)
    shown = text if len(text) <= room else text[: room - 1] + _ELLIPSIS
    return f"{_COPIED_TOAST_PREFIX}{shown}{_COPIED_TOAST_SUFFIX}"


# ── Empty library (brief §5.8) ──


@dataclass(frozen=True)
class EmptyLibraryState:
    placeholder: str
    toast_text: str | None


def empty_library_state(
    enabled_ids: Sequence[str],
    auto_import_pending_ids: Iterable[str],
    failed_ids: Iterable[str],
) -> EmptyLibraryState:
    """Dashboard placeholder (and startup toast) for an EMPTY library.

    ``auto_import_pending_ids``: enabled providers that update automatically
    and have no snapshot yet. Those not in ``failed_ids`` will import by themselves.
    """
    if not enabled_ids:
        return EmptyLibraryState(PLACEHOLDER_NO_SOURCE, TOAST_NO_SOURCE)
    failed = set(failed_ids)
    if any(pid not in failed for pid in auto_import_pending_ids):
        return EmptyLibraryState(PLACEHOLDER_READING, None)
    return EmptyLibraryState(PLACEHOLDER_NOT_SYNCED, TOAST_NOT_SYNCED)
