"""DJ library provider contract (ADR-015, proposed).

Leaf module: stdlib imports only, so models, services and providers can all
depend on it without import cycles (same pattern as ``harmonic_tier.py``).

A provider is the only place DJ-software-specific knowledge lives (finding
the library, listing crates/playlists, reading track metadata, change
detection, and the reserved load-to-deck capability). Providers are
stateless: settings are passed into every call.

Message convention for ``ProviderIssue.message`` and ``ProviderError`` text:
a short complete phrase with an initial capital, no trailing period, no
provider name and no file path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Protocol, TypedDict, runtime_checkable


class ProviderError(Exception):
    """Configuration-level failure with a user-presentable message.

    Examples: folder missing, DB unreadable, DB key unavailable. Raised by
    ``LibraryProvider.scan()``.
    """


class DeckLoadNotSupported(ProviderError):
    """Raised by ``load_to_deck()`` when the provider lacks ``ProviderCapability.DECK_LOAD``."""


class SettingKind(str, Enum):
    DIRECTORY = "directory"
    FILE = "file"
    CHOICE = "choice"
    TEXT = "text"  # free text, e.g. the rekordbox DB key


@dataclass(frozen=True)
class SettingSpec:
    """Describes one provider setting so the settings UI can stay provider-agnostic."""

    key: str  # provider-local, e.g. "subcrates_dir"
    env_key: str  # persisted key, e.g. "SERATO_SUBCRATES_DIR" (explicit: legacy name kept)
    label: str  # functional label; microcopy owned by the UI designer
    kind: SettingKind
    choices: tuple[str, ...] = ()  # CHOICE only
    visible_when: tuple[str, str] | None = None  # (other_key, value)
    file_patterns: tuple[tuple[str, str], ...] = ()  # FILE only
    placeholder: str = ""  # empty-entry prompt
    hint: str = ""  # one grey help line under the field
    browse_title: str = ""  # title of the file/folder picker
    required: bool = True  # empty optional fields render no prompt
    secret: bool = False  # masked in the UI, never logged


class ProviderCapability(str, Enum):
    PLAYLIST_FOLDERS = "playlist_folders"  # crates have hierarchy worth grouping
    SMART_PLAYLISTS = "smart_playlists"
    NATIVE_PLAY_COUNT = "native_play_count"
    CHANGE_DETECTION = "change_detection"  # change_token() returns a real token (D11)
    DECK_LOAD = "deck_load"  # load_to_deck() works (D12); no provider declares it yet


@dataclass(frozen=True)
class CrateInfo:
    id: str  # f"{provider_id}:{native_id}" - globally unique, stable per provider
    provider_id: str
    label: str  # provider-formatted display text
    path: tuple[str, ...]  # folder hierarchy, leaf last
    is_smart: bool = False


class TrackRecord(TypedDict, total=False):
    """The track-dict contract.

    Identical to the existing cache track schema (``tag_reader.get_track_metadata``)
    plus crate ids.
    """

    file_name: str
    title: str
    artist: str
    album: str
    bpm: float
    key: str
    camelot_key: str
    genre: str
    date: str
    comments: str
    energy_level: int
    play_count: int
    date_added: float  # file creation time, ADR-013
    full_file_path: str
    crates: list[str]  # crate ids


@dataclass(frozen=True)
class ProviderIssue:
    severity: Literal["error", "warning"]
    message: str
    setting_key: str | None = None


@dataclass
class ProviderSnapshot:
    """Normalised, serialisable view of one provider's library."""

    provider_id: str
    tracks: dict[str, TrackRecord]  # keyed by provider-native absolute path
    crates: dict[str, CrateInfo]  # every crate seen, including empty ones
    fingerprint: dict[str, float] = field(default_factory=dict)
    change_token: str | None = None  # token observed at scan start (D11)
    warnings: list[str] = field(default_factory=list)


class ProgressCallback(Protocol):
    def __call__(self, message: str, current: int, total: int) -> None: ...


@runtime_checkable
class LibraryProvider(Protocol):
    """A source of DJ library data (Serato, rekordbox, ...)."""

    id: str  # persisted; NEVER rename ("serato", "rekordbox")
    display_name: str  # vendor styling: "Serato DJ", "rekordbox"
    crate_noun: str  # "crate" (Serato) | "playlist" (rekordbox); UI pluralises with "s"

    def setting_specs(self) -> tuple[SettingSpec, ...]: ...

    def default_settings(self) -> dict[str, str]:
        """Platform-aware auto-detected defaults (stat calls only)."""
        ...

    def detect(self) -> bool:
        """True if this DJ app's library appears to exist (first-run defaults only)."""
        ...

    def detected_values(self, settings: Mapping[str, str]) -> dict[str, str]:
        """Values in effect for settings left empty: for display only, never persisted.

        Stat calls only (UI-thread safe). Keys are setting keys from
        ``setting_specs()``. Lets the settings dialog show an auto-detected
        value (e.g. the rekordbox database path) without branching on provider ids.
        """
        ...

    def capabilities(self, settings: Mapping[str, str]) -> frozenset[ProviderCapability]: ...

    def validate(self, settings: Mapping[str, str]) -> list[ProviderIssue]:
        """Cheap and UI-thread safe; never imports optional dependencies."""
        ...

    def scan(
        self,
        settings: Mapping[str, str],
        progress: ProgressCallback | None = None,
    ) -> ProviderSnapshot:
        """Blocking; background thread only. Raises ``ProviderError``."""
        ...

    def change_token(self, settings: Mapping[str, str]) -> str | None:
        """Stat-only, any thread. ``None`` unless ``CHANGE_DETECTION`` is declared."""
        ...

    def load_to_deck(self, settings: Mapping[str, str], track_path: str, deck: int) -> None:
        """Load ``track_path`` onto 1-based ``deck``. May block: call off the Tk thread.

        Raises ``DeckLoadNotSupported`` unless ``DECK_LOAD`` is declared.
        """
        ...
