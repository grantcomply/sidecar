from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
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

    def crate_leaf(self, crate_id: str) -> str:
        """The crate's own name (``path[-1]``), without its folders (T5.3).

        Falls back to the label (then the raw id) when the path is unknown.
        """
        info = self._crates.get(crate_id)
        if info is None:
            return crate_id
        return info.path[-1] if info.path else info.label

    def crate_provider(self, crate_id: str) -> str | None:
        """Provider id that owns a crate (``None`` for an unknown id)."""
        info = self._crates.get(crate_id)
        return info.provider_id if info is not None else None

    def crates_by_provider(
        self, crate_ids: Iterable[str], provider_order: Sequence[str],
    ) -> list[tuple[str | None, list[str]]]:
        """Crate labels grouped by owning provider id (T5.4 tooltip lines).

        Groups follow ``provider_order``; providers not in it come next and
        crates of unknown provider (``None``) last. Labels keep input order.
        Providers holding none of the crates get no group.
        """
        groups: dict[str | None, list[str]] = {}
        for crate_id in crate_ids:
            groups.setdefault(self.crate_provider(crate_id), []).append(self.crate_label(crate_id))
        rank = {pid: i for i, pid in enumerate(provider_order)}

        def order(pid: str | None) -> tuple[int, int]:
            if pid is None:
                return (2, 0)
            return (0, rank[pid]) if pid in rank else (1, 0)

        return [(pid, groups[pid]) for pid in sorted(groups, key=order)]

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
