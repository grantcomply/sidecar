"""
JSON cache for parsed track metadata.

Reads/writes a single track_cache.json file in the user data directory,
replacing the old per-crate CSV export approach (see ADR-007).
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from source.config import PROJECT_ROOT, user_data_dir

logger = logging.getLogger(__name__)

CACHE_VERSION = 1

_CACHE_FILENAME = "track_cache.json"
_legacy_cache_migrated = False


def _migrate_legacy_cache(target: Path) -> None:
    """One-time migration of the old project-root track_cache.json.

    If a legacy cache exists at PROJECT_ROOT and the target in user data dir
    does not, move it. Runs at most once per process.
    """
    global _legacy_cache_migrated
    if _legacy_cache_migrated:
        return
    _legacy_cache_migrated = True

    legacy = Path(PROJECT_ROOT) / _CACHE_FILENAME
    if not legacy.is_file() or target.exists():
        return
    try:
        legacy.replace(target)
        logger.info("Migrated legacy cache from %s to %s", legacy, target)
    except OSError as e:
        logger.warning("Failed to migrate legacy cache: %s", e)


def get_cache_path() -> Path:
    """Return the path to the track cache file in the user data directory."""
    path = user_data_dir() / _CACHE_FILENAME
    _migrate_legacy_cache(path)
    return path


def load_cache(path: Path | None = None) -> dict | None:
    """Read the JSON cache file and return its contents.

    Returns None if the file doesn't exist, can't be parsed,
    or has a version mismatch.
    """
    if path is None:
        path = get_cache_path()

    if not path.is_file():
        logger.info("No cache file found at %s", path)
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read cache file: %s", e)
        return None

    if data.get("version") != CACHE_VERSION:
        logger.info(
            "Cache version mismatch (got %s, expected %d) — ignoring cache",
            data.get("version"), CACHE_VERSION,
        )
        return None

    return data


def save_cache(
    tracks: dict,
    crate_mtimes: dict,
    path: Path | None = None,
) -> None:
    """Write the track cache to a JSON file.

    Args:
        tracks: Dict keyed by file path, values are track metadata dicts.
        crate_mtimes: Dict mapping crate filenames to modification times.
        path: Override cache file path (defaults to project root).
    """
    if path is None:
        path = get_cache_path()

    data = {
        "version": CACHE_VERSION,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "crate_mtimes": crate_mtimes,
        "tracks": tracks,
    }

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("Cache saved: %d tracks to %s", len(tracks), path)
    except OSError as e:
        logger.error("Failed to write cache file: %s", e)
        raise
