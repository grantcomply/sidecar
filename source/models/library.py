from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING

from source.models.track import Track
from source.models.path_identity import path_key

if TYPE_CHECKING:
    from source.providers.base import CrateInfo

logger = logging.getLogger(__name__)


class TrackLibrary:
    def __init__(self):
        self._tracks: dict[str, Track] = {}  # keyed by path_identity.path_key
        self._crates: dict[str, CrateInfo] = {}  # crate id -> info

    @property
    def tracks(self) -> list[Track]:
        return list(self._tracks.values())

    @property
    def count(self) -> int:
        return len(self._tracks)

    def replace_all(self, tracks: dict[str, Track], crates: Mapping[str, CrateInfo]) -> None:
        """Replace the library with already-merged tracks (keyed by path key) and crates."""
        self._tracks = dict(tracks)
        self._crates = dict(crates)

    def crate_label(self, crate_id: str) -> str:
        """Display label for a crate id, falling back to the raw id."""
        info = self._crates.get(crate_id)
        return info.label if info is not None else crate_id

    def track_by_path(self, path: str) -> Track | None:
        """Look a track up by file path, using the same normalisation as the merge."""
        return self._tracks.get(path_key(path))

    @property
    def crate_items(self) -> list[tuple[str, str]]:
        """``(id, label)`` for crates holding at least one track.

        Sorted case-insensitively by folder path (Phase 3c, T3c.10), so folder
        siblings stay together; the app groups the list by ``crate_provider``.
        """
        ids: set[str] = set()
        for track in self._tracks.values():
            ids.update(track.crates)
        return sorted(((cid, self.crate_label(cid)) for cid in ids), key=self._crate_sort_key)

    def _crate_sort_key(self, item: tuple[str, str]) -> tuple:
        cid, label = item
        info = self._crates.get(cid)
        path = info.path if info is not None else (label,)
        return (tuple(part.casefold() for part in path), label.casefold(), cid)

    def crate_provider(self, crate_id: str) -> str | None:
        """Provider id that owns a crate (``None`` for an unknown id)."""
        info = self._crates.get(crate_id)
        return info.provider_id if info is not None else None

    @property
    def crate_count(self) -> int:
        """Number of crates holding at least one track (as shown in the crate filter)."""
        return len(self.crate_items)

    @property
    def genre_names(self) -> list[str]:
        """Return sorted list of all unique genre names in the library."""
        names = set()
        for track in self._tracks.values():
            if track.genre:
                names.add(track.genre)
        return sorted(names)

    def search(self, query: str, limit: int = 20) -> list[Track]:
        """Search tracks by substring match on title, artist, filename."""
        if not query or not query.strip():
            return []

        q = query.strip().lower()
        results = []
        for track in self._tracks.values():
            if q in track.search_text:
                results.append(track)
                if len(results) >= limit:
                    break
        return results
