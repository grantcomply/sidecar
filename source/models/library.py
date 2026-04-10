import logging
import os
import csv
from pathlib import Path

from source.models.track import Track
from source.services.cache import load_cache

logger = logging.getLogger(__name__)


class TrackLibrary:
    def __init__(self):
        self._tracks: dict[str, Track] = {}  # keyed by full_file_path

    @property
    def tracks(self) -> list[Track]:
        return list(self._tracks.values())

    @property
    def count(self) -> int:
        return len(self._tracks)

    def load_from_csv_dir(self, csv_dir: str):
        """Load all CSV files from the given directory, deduplicating by file path."""
        self._tracks.clear()

        if not os.path.isdir(csv_dir):
            return

        csv_files = [f for f in os.listdir(csv_dir) if f.endswith('.csv')]

        for csv_file in sorted(csv_files):
            crate_name = csv_file.replace('.csv', '')
            csv_path = os.path.join(csv_dir, csv_file)

            try:
                with open(csv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        fp = row.get("FullFilePath", "") or ""
                        if not fp:
                            continue

                        if fp in self._tracks:
                            # Track already loaded — just add this crate
                            if crate_name not in self._tracks[fp].crates:
                                self._tracks[fp].crates.append(crate_name)
                        else:
                            self._tracks[fp] = Track.from_csv_row(row, crate_name)
            except Exception as e:
                logger.error("Error loading %s: %s", csv_file, e)

    def load_from_cache(self, cache_path: Path | None = None) -> bool:
        """Load all tracks from the JSON cache file.

        Returns True if the cache was loaded successfully, False otherwise.
        """
        self._tracks.clear()

        data = load_cache(cache_path)
        if data is None:
            return False

        tracks_data = data.get("tracks", {})
        for file_path, track_data in tracks_data.items():
            try:
                self._tracks[file_path] = Track.from_dict(track_data, file_path)
            except Exception as e:
                logger.error("Error loading track %s from cache: %s", file_path, e)

        logger.info("Loaded %d tracks from cache", len(self._tracks))
        return True

    @property
    def crate_names(self) -> list[str]:
        """Return sorted list of all unique crate names in the library."""
        names = set()
        for track in self._tracks.values():
            names.update(track.crates)
        return sorted(names)

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
