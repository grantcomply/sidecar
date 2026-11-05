"""rekordbox library provider (ADR-015 D8).

Reads a private temp copy of rekordbox's ``master.db``; nothing in rekordbox's
folder is ever opened by SQLite or written. Importing this module does not
import pyrekordbox (that happens lazily in ``db_reader``).
"""

from __future__ import annotations

import importlib.util
import logging
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from source.providers.base import (
    CrateInfo,
    DeckLoadNotSupported,
    ProgressCallback,
    ProviderCapability,
    ProviderError,
    ProviderIssue,
    ProviderSnapshot,
    SettingKind,
    SettingSpec,
    TrackRecord,
)
from source.models.path_identity import path_key
from source.providers.rekordbox import db_copy, db_reader
from source.providers.rekordbox import paths as rb_paths
from source.providers.rekordbox import energy_cache as energy_cache_module
from source.providers.rekordbox.energy_cache import TagEnergyCache
from source.providers.rekordbox.mapping import to_track_record
from source.providers.rekordbox.paths import (
    TOKEN_FILES,
    WRONG_FILENAME_MESSAGE,
    compute_change_token,
    is_master_db,
    resolve_track_path,
)
from source.services import tag_reader
from source.services.comment_format import parse_comment
from source.services.file_times import file_creation_time

logger = logging.getLogger(__name__)

PROVIDER_ID = "rekordbox"
_LABEL_SEPARATOR = " / "
_NOT_FOUND = "Database not found"
_UNAVAILABLE = "Not available in this build"


class RekordboxProvider:
    """rekordbox 6/7 library, read from a private copy of ``master.db``."""

    id = PROVIDER_ID
    display_name = "rekordbox"
    crate_noun = "playlist"

    def __init__(
        self,
        *,
        db_factory: Callable[..., Any] | None = None,
        energy_cache: TagEnergyCache | None = None,
        exists: Callable[[str], bool] = os.path.exists,
        energy_reader: Callable[[str], int] = tag_reader.read_energy_level,
        tmp_root: Path | None = None,
    ) -> None:
        # Test seams; the registry uses the defaults.
        self._db_factory = db_factory
        self._energy_cache = (
            energy_cache if energy_cache is not None else energy_cache_module.DEFAULT
        )
        self._exists = exists
        self._energy_reader = energy_reader
        self._tmp_root = tmp_root

    # ── Settings ──

    def setting_specs(self) -> tuple[SettingSpec, ...]:
        return (
            SettingSpec(
                key="db_path",
                env_key="REKORDBOX_DB_PATH",
                label="Database",
                kind=SettingKind.FILE,
                file_patterns=(("rekordbox database", "master.db"),),
                placeholder="Choose the file named master.db",
                hint=(
                    "Leave empty to use the database rekordbox created. "
                    "Only choose a file if you moved it."
                ),
                browse_title="Select your rekordbox database (master.db)",
                required=False,
            ),
            SettingSpec(
                key="auto_refresh",
                env_key="REKORDBOX_AUTO_REFRESH",
                label="Update automatically",
                kind=SettingKind.CHOICE,
                choices=("on", "off"),
                hint=(
                    "Checks about once a minute and updates quietly. "
                    "Your setlist and filters stay as they are."
                ),
            ),
        )

    def default_settings(self) -> dict[str, str]:
        return {"db_path": "", "auto_refresh": "on"}

    def _db_path(self, settings: Mapping[str, str]) -> Path | None:
        return rb_paths.resolve_db_path(settings)

    def detected_values(self, settings: Mapping[str, str]) -> dict[str, str]:
        """The database in effect when ``db_path`` is left empty (display only; stat calls)."""
        if settings.get("db_path"):
            return {}
        path = rb_paths.resolve_db_path(settings)
        if path is not None and is_master_db(path) and path.is_file():
            return {"db_path": str(path)}
        return {}

    def detect(self) -> bool:
        path = rb_paths.default_db_path()
        return path is not None and path.is_file()

    def capabilities(self, settings: Mapping[str, str]) -> frozenset[ProviderCapability]:
        caps = {ProviderCapability.PLAYLIST_FOLDERS, ProviderCapability.NATIVE_PLAY_COUNT}
        if settings.get("auto_refresh", "on") == "on":
            caps.add(ProviderCapability.CHANGE_DETECTION)
        # Not SMART_PLAYLISTS (unverified) and not DECK_LOAD (Phase 6).
        return frozenset(caps)

    def validate(self, settings: Mapping[str, str]) -> list[ProviderIssue]:
        """UI-thread safe: no DB open and no pyrekordbox import."""
        issues: list[ProviderIssue] = []
        path = self._db_path(settings)
        if path is not None and not is_master_db(path):
            issues.append(ProviderIssue("error", WRONG_FILENAME_MESSAGE, "db_path"))
        elif path is None or not path.is_file():
            issues.append(ProviderIssue("error", _NOT_FOUND, "db_path"))
        if importlib.util.find_spec("pyrekordbox") is None:
            issues.append(ProviderIssue("error", _UNAVAILABLE))
        return issues

    def change_token(self, settings: Mapping[str, str]) -> str | None:
        if ProviderCapability.CHANGE_DETECTION not in self.capabilities(settings):
            return None
        path = self._db_path(settings)
        if path is None or not is_master_db(path) or not path.is_file():
            return None
        return compute_change_token(path)

    def load_to_deck(self, settings: Mapping[str, str], track_path: str, deck: int) -> None:
        """Not available yet: rekordbox load-to-deck is the Phase 6 follow-up (ADR-014 bar)."""
        raise DeckLoadNotSupported("Loading to a deck isn't available for rekordbox yet")

    # ── Scan ──

    def _read(self, path: Path) -> db_reader.RbLibrary:
        """Copy, then read the copy. On a failed integrity check, re-copy once."""
        for attempt in (1, 2):
            with db_copy.private_copy(
                path, token_fn=compute_change_token, tmp_root=self._tmp_root,
            ) as copy:
                try:
                    return db_reader.read_library(copy, db_factory=self._db_factory)
                except db_reader.CopyIntegrityError:
                    if attempt == 2:
                        raise
                    logger.info("rekordbox copy failed its integrity check; copying again")
        raise AssertionError("unreachable")  # pragma: no cover

    def scan(
        self,
        settings: Mapping[str, str],
        progress: ProgressCallback | None = None,
    ) -> ProviderSnapshot:
        """Blocking; background thread only. Raises ``ProviderError``."""
        started = time.perf_counter()
        db_copy.cleanup_stale_copies(tmp_root=self._tmp_root)
        path = self._db_path(settings)
        if path is not None and not is_master_db(path):
            raise ProviderError(WRONG_FILENAME_MESSAGE)
        if path is None or not path.is_file():
            raise ProviderError(_NOT_FOUND)
        # Taken BEFORE copying, so a write during the scan triggers another refresh.
        # The fingerprint is taken at the same moment, so the two always agree.
        token = compute_change_token(path)
        fingerprint = _fingerprint(path)
        reads_before, hits_before = self._energy_cache.reads, self._energy_cache.hits
        lib = self._read(path)

        builder = _SnapshotBuilder(lib, exists=self._exists, energy=self._energy_for_scan())
        total = len(lib.playlists)
        for i, playlist in enumerate(lib.playlists, start=1):
            builder.add_playlist(playlist)
            if progress:
                progress("Reading playlists", i, total)

        logger.info(
            "rekordbox scan: %d tracks, %d playlists, %d tag reads, %d energy cache hits, %.2fs",
            len(builder.tracks), len(builder.crates),
            self._energy_cache.reads - reads_before, self._energy_cache.hits - hits_before,
            time.perf_counter() - started,
        )
        return ProviderSnapshot(
            provider_id=PROVIDER_ID,
            tracks=builder.tracks,
            crates=builder.crates,
            fingerprint=fingerprint,
            change_token=token,
            warnings=builder.warnings(lib.warnings),
        )

    def _energy_for_scan(self) -> Callable[[str, str, bool], int]:
        """Energy for one track: comment first (user option (a)), then the file tag, else 0.

        The tag fallback is best effort: a per-track boundary catches any
        failure, logs its type once per file per scan, and returns 0, so one bad
        audio file can't fail the whole rekordbox scan. (tag_reader keeps its own
        narrowed except, T3.9.)
        """
        warned: set[str] = set()

        def energy(comment: str, track_path: str, file_exists: bool) -> int:
            value = parse_comment(comment).energy
            if value or not file_exists:
                return value
            try:
                return self._energy_cache.get(track_path, self._energy_reader)
            except Exception as e:  # noqa: BLE001 - best-effort fallback, per-track boundary
                key = path_key(track_path)
                if key not in warned:
                    warned.add(key)
                    logger.warning("Energy tag read failed for one track (%s)", type(e).__name__)
                return 0

        return energy


class _SnapshotBuilder:
    """Accumulates tracks, crates and warning counts for one scan."""

    def __init__(
        self,
        lib: db_reader.RbLibrary,
        *,
        exists: Callable[[str], bool],
        energy: Callable[[str, str, bool], int],
    ) -> None:
        self._lib = lib
        self._exists = exists
        self._energy = energy
        self.tracks: dict[str, TrackRecord] = {}
        self.crates: dict[str, CrateInfo] = {}
        self._path_for: dict[str, str | None] = {}  # content id -> resolved path (None = unusable)
        self.missing_files = 0
        self.no_path = 0
        self.unknown_entries = 0

    def add_playlist(self, playlist: db_reader.RbPlaylist) -> None:
        crate_id = f"{PROVIDER_ID}:{playlist.playlist_id}"
        self.crates[crate_id] = CrateInfo(
            id=crate_id,
            provider_id=PROVIDER_ID,
            label=_LABEL_SEPARATOR.join(playlist.path),
            path=playlist.path,
            is_smart=playlist.is_smart,
        )
        for content_id in playlist.content_ids:
            track_path = self._track_path(content_id)
            if track_path is None:
                continue
            crates = self.tracks[track_path].setdefault("crates", [])
            if crate_id not in crates:
                crates.append(crate_id)

    def _track_path(self, content_id: str) -> str | None:
        if content_id in self._path_for:
            return self._path_for[content_id]
        rb = self._lib.tracks.get(content_id)
        if rb is None:
            self.unknown_entries += 1  # counted per entry, not cached
            return None
        track_path, file_exists = resolve_track_path(
            rb.org_path, rb.folder_path, rb.local_path, exists=self._exists,
        )
        self._path_for[content_id] = track_path
        if track_path is None:
            self.no_path += 1
            return None
        if not file_exists:
            self.missing_files += 1
        if track_path not in self.tracks:
            created = file_creation_time(track_path) if file_exists else None
            self.tracks[track_path] = to_track_record(
                rb,
                path=track_path,
                date_added=created if created is not None else 0.0,
                energy=self._energy(rb.comments, track_path, file_exists),
            )
        return track_path

    def warnings(self, library_warnings: list[str]) -> list[str]:
        out: list[str] = []
        if self.missing_files:
            out.append(f"{self.missing_files} tracks have no file on this computer")
        if self.no_path:
            out.append(f"{self.no_path} tracks have no usable file path")
        if self.unknown_entries:
            out.append(
                f"{self.unknown_entries} playlist entries point to tracks that aren't in the "
                "collection"
            )
        return out + list(library_warnings)


def _fingerprint(db_path: Path) -> dict[str, float]:
    result: dict[str, float] = {}
    for name in TOKEN_FILES:
        try:
            result[name] = (db_path.parent / name).stat().st_mtime
        except OSError:
            continue
    return result
