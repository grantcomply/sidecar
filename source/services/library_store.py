"""Per-provider library snapshots, schema v4 (ADR-015 D4).

One JSON file per provider at ``user_data_dir()/library/<provider_id>.json``,
plus a small metadata file ``<provider_id>.meta.json`` (synced_at,
change_token, content_hash, counts). Supersedes the single
``track_cache.json`` (ADR-007). Writes are atomic (temp file + replace).

When a sync's content is unchanged, only the metadata file is rewritten: the
change token and sync time still advance (live-refresh baseline), but the
multi-megabyte snapshot isn't rewritten every minute.

Also holds the one-time, read-only converter from the legacy v3
``track_cache.json`` to a Serato snapshot, so upgrading users need no
re-sync. The legacy file is never moved, renamed, rewritten or deleted
(downgrade safety).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from source import config
from source.providers.base import CrateInfo, ProviderSnapshot, TrackRecord
from source.services.crate_parser import crate_display_name, crate_stem

logger = logging.getLogger(__name__)

SNAPSHOT_SCHEMA = 4
LEGACY_CACHE_VERSION = 3
LEGACY_CACHE_FILENAME = "track_cache.json"
LEGACY_PROVIDER_ID = "serato"  # the v3 cache only ever held Serato data
_SERATO_LABEL_SEPARATOR = " - "
_SERATO_PATH_SEPARATOR = "%%"
_SNAPSHOT_DIRNAME = "library"
_META_SUFFIX = ".meta.json"
_ORPHAN_TMP_MIN_AGE_S = 60.0  # another app instance may be mid-write on a younger one


@dataclass(frozen=True)
class SnapshotSummary:
    synced_at: str
    track_count: int
    crate_count: int
    change_token: str | None


# ── Paths ──


def snapshot_dir() -> Path:
    """Directory holding provider snapshot files (not created; writes create it)."""
    return config.user_data_dir() / _SNAPSHOT_DIRNAME


def snapshot_path(provider_id: str) -> Path:
    return snapshot_dir() / f"{provider_id}.json"


def meta_path(provider_id: str) -> Path:
    return snapshot_dir() / f"{provider_id}{_META_SUFFIX}"


def cleanup_orphan_temp_files(*, min_age_s: float = _ORPHAN_TMP_MIN_AGE_S) -> int:
    """Delete leftover ``*.tmp`` files from interrupted snapshot writes. Returns the count."""
    folder = snapshot_dir()
    if not folder.is_dir():
        return 0
    cutoff = time.time() - min_age_s
    removed = 0
    for tmp in folder.glob("*.tmp"):
        try:
            if tmp.is_file() and tmp.stat().st_mtime < cutoff:
                tmp.unlink()
                removed += 1
        except OSError as e:
            logger.debug("Could not remove orphan %s (%s)", tmp.name, type(e).__name__)
    if removed:
        logger.info("Removed %d orphan snapshot temp file(s)", removed)
    return removed


def _legacy_cache_candidates() -> list[Path]:
    """Legacy v3 cache locations, in priority order (user data dir, then project root)."""
    return [
        config.user_data_dir() / LEGACY_CACHE_FILENAME,
        Path(config.PROJECT_ROOT) / LEGACY_CACHE_FILENAME,
    ]


# ── Serialisation ──


def _crates_to_json(crates: dict[str, CrateInfo]) -> dict[str, dict[str, Any]]:
    return {
        crate_id: {
            "provider_id": info.provider_id,
            "label": info.label,
            "path": list(info.path),
            "is_smart": info.is_smart,
        }
        for crate_id, info in crates.items()
    }


def _crates_from_json(data: dict[str, dict[str, Any]]) -> dict[str, CrateInfo]:
    return {
        crate_id: CrateInfo(
            id=crate_id,
            provider_id=str(info["provider_id"]),
            label=str(info["label"]),
            path=tuple(str(part) for part in info["path"]),
            is_smart=bool(info.get("is_smart", False)),
        )
        for crate_id, info in data.items()
    }


def content_hash(tracks: dict[str, Any], crates_json: dict[str, Any]) -> str:
    """SHA-256 of the library content (tracks + crates), independent of key order."""
    payload = json.dumps(
        {"tracks": tracks, "crates": crates_json}, sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        logger.warning("Failed to read %s: %s", path, e)
        return None
    if not isinstance(data, dict):
        logger.warning("Ignoring %s: not a JSON object", path)
        return None
    return data


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    """Write via a unique temp file in the same dir + ``os.replace``.

    A unique name means two concurrent writers can't clobber each other's temp
    file; the temp file is removed if anything fails.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        config.replace_with_retry(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError as cleanup_error:
            logger.debug("Could not remove %s: %s", tmp_name, cleanup_error)
        raise


# ── Public API ──


def _read_meta(provider_id: str) -> dict[str, Any] | None:
    data = _read_json(meta_path(provider_id))
    if data is None or data.get("schema") != SNAPSHOT_SCHEMA or data.get("provider") != provider_id:
        return None
    return data


def _write_meta(
    snapshot: ProviderSnapshot, new_hash: str, track_count: int, crate_count: int,
    synced_at: str,
) -> None:
    _write_json_atomic(meta_path(snapshot.provider_id), {
        "schema": SNAPSHOT_SCHEMA,
        "provider": snapshot.provider_id,
        "synced_at": synced_at,
        "change_token": snapshot.change_token,
        "content_hash": new_hash,
        "fingerprint": snapshot.fingerprint,
        "track_count": track_count,
        "crate_count": crate_count,
    })


def save_snapshot(snapshot: ProviderSnapshot, *, synced_at: str | None = None) -> bool:
    """Persist ``snapshot`` atomically. Returns True if its content changed.

    Unchanged content (same hash as the metadata file records, and the
    ``synced_at`` (UTC ISO) defaults to now; the legacy-cache conversion passes
    the old cache's sync time so the settings chip doesn't claim "just now".
    Unchanged content (same hash as the metadata file records, and the
    snapshot file present) rewrites only the small metadata file, so the
    change token and sync time still advance. Changed content rewrites the
    snapshot first, then the metadata. Raises ``OSError`` if a write fails;
    the previous files are left intact.
    """
    path = snapshot_path(snapshot.provider_id)
    tracks = cast(dict[str, Any], snapshot.tracks)
    crates_json = _crates_to_json(snapshot.crates)
    new_hash = content_hash(tracks, crates_json)
    stamp = synced_at or datetime.now(timezone.utc).isoformat()

    previous = _read_meta(snapshot.provider_id)
    changed = previous is None or previous.get("content_hash") != new_hash or not path.is_file()

    try:
        if changed:
            _write_json_atomic(path, {
                "schema": SNAPSHOT_SCHEMA,
                "provider": snapshot.provider_id,
                "synced_at": stamp,
                "fingerprint": snapshot.fingerprint,
                "change_token": snapshot.change_token,
                "content_hash": new_hash,
                "crates": crates_json,
                "tracks": tracks,
            })
        # Written after the snapshot: if we crash in between, the old hash in
        # the metadata just makes the next save rewrite the snapshot again.
        _write_meta(snapshot, new_hash, len(tracks), len(crates_json), stamp)
    except OSError as e:
        logger.error("Failed to write snapshot %s: %s", path, e)
        raise
    if changed:
        logger.info("Snapshot saved: %d tracks to %s", len(tracks), path)
    else:
        logger.info("Snapshot unchanged for %s; metadata updated only", snapshot.provider_id)
    return changed


def _load_valid(provider_id: str) -> dict[str, Any] | None:
    path = snapshot_path(provider_id)
    data = _read_json(path)
    if data is None:
        logger.info("No usable snapshot for %s at %s", provider_id, path)
        return None
    if data.get("schema") != SNAPSHOT_SCHEMA:
        logger.info(
            "Snapshot schema mismatch for %s (got %s, expected %d); ignoring",
            provider_id, data.get("schema"), SNAPSHOT_SCHEMA,
        )
        return None
    if data.get("provider") != provider_id:
        logger.warning(
            "Snapshot %s belongs to provider %r; ignoring", path, data.get("provider"),
        )
        return None
    return data


def load_snapshot(provider_id: str) -> ProviderSnapshot | None:
    """Load a provider's snapshot, or ``None`` if missing, unreadable or mismatched.

    The change token comes from the metadata file when it matches the
    snapshot's content (it advances on unchanged syncs).
    """
    data = _load_valid(provider_id)
    if data is None:
        return None
    meta = _read_meta(provider_id)
    token = data.get("change_token")
    if meta is not None and meta.get("content_hash") == data.get("content_hash"):
        token = meta.get("change_token")
    try:
        return ProviderSnapshot(
            provider_id=provider_id,
            tracks=cast(dict[str, TrackRecord], dict(data["tracks"])),
            crates=_crates_from_json(data.get("crates", {})),
            fingerprint={str(k): float(v) for k, v in data.get("fingerprint", {}).items()},
            change_token=token,
        )
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        logger.warning("Malformed snapshot for %s: %s", provider_id, e)
        return None


def snapshot_summary(provider_id: str) -> SnapshotSummary | None:
    """Cheap metadata about a provider's stored snapshot (watcher baseline, settings UI).

    Reads the small metadata file. Falls back to the full snapshot for files
    written before the metadata file existed.
    """
    meta = _read_meta(provider_id)
    if meta is not None and snapshot_path(provider_id).is_file():
        try:
            return SnapshotSummary(
                synced_at=str(meta.get("synced_at", "")),
                track_count=int(meta.get("track_count", 0)),
                crate_count=int(meta.get("crate_count", 0)),
                change_token=meta.get("change_token"),
            )
        except (TypeError, ValueError) as e:
            logger.warning("Malformed snapshot metadata for %s: %s", provider_id, e)
    data = _load_valid(provider_id)
    if data is None:
        return None
    try:
        return SnapshotSummary(
            synced_at=str(data.get("synced_at", "")),
            track_count=len(data.get("tracks", {})),
            crate_count=len(data.get("crates", {})),
            change_token=data.get("change_token"),
        )
    except TypeError as e:
        logger.warning("Malformed snapshot for %s: %s", provider_id, e)
        return None


# ── Legacy v3 cache conversion ──


def legacy_cache_exists() -> bool:
    """True if a legacy ``track_cache.json`` exists in any known location."""
    return any(path.is_file() for path in _legacy_cache_candidates())


def _fallback_stem(label: str) -> str:
    # Inverse of Serato's display formatting ('%%' -> ' - '). Only used for
    # labels with no matching crate file; wrong if the name itself contains
    # ' - ', which the next sync corrects.
    return label.replace(_SERATO_LABEL_SEPARATOR, _SERATO_PATH_SEPARATOR)


def _serato_crate(stem: str, label: str) -> CrateInfo:
    crate_id = f"{LEGACY_PROVIDER_ID}:{stem}"
    return CrateInfo(
        id=crate_id,
        provider_id=LEGACY_PROVIDER_ID,
        label=label,
        path=tuple(stem.split(_SERATO_PATH_SEPARATOR)),
    )


def legacy_v3_to_snapshot(data: dict[str, Any]) -> ProviderSnapshot:
    """Convert a parsed v3 cache dict to a Serato snapshot (pure).

    Crate ids come from the real ``.crate`` filenames in ``crate_mtimes``
    (exact, and empty crates included, as a fresh sync would produce). Labels
    with no matching filename fall back to reversing the display format.
    """
    crate_mtimes: dict[str, Any] = data.get("crate_mtimes", {})
    crates: dict[str, CrateInfo] = {}
    stem_for_label: dict[str, str] = {}
    for filename in sorted(crate_mtimes):  # the parser's order; first wins a label tie
        stem, label = crate_stem(filename), crate_display_name(filename)
        crates[f"{LEGACY_PROVIDER_ID}:{stem}"] = _serato_crate(stem, label)
        stem_for_label.setdefault(label, stem)

    tracks: dict[str, TrackRecord] = {}
    for path, record in data.get("tracks", {}).items():
        converted: dict[str, Any] = dict(record)
        ids: list[str] = []
        for label in record.get("crates", []):
            stem = stem_for_label.get(label) or _fallback_stem(label)
            crate_id = f"{LEGACY_PROVIDER_ID}:{stem}"
            crates.setdefault(crate_id, _serato_crate(stem, label))
            if crate_id not in ids:
                ids.append(crate_id)
        converted["crates"] = ids
        tracks[path] = cast(TrackRecord, converted)
    fingerprint = {str(k): float(v) for k, v in crate_mtimes.items()}
    return ProviderSnapshot(
        provider_id=LEGACY_PROVIDER_ID, tracks=tracks, crates=crates, fingerprint=fingerprint,
    )


def convert_legacy_cache_if_needed() -> bool:
    """Create ``library/serato.json`` from a v3 ``track_cache.json`` if needed.

    Runs only when no Serato snapshot exists. Reads the legacy file and leaves
    it untouched. A non-v3 or unreadable legacy file is skipped (the user
    re-syncs, as ADR-007 specifies). Returns True if a snapshot was written.
    """
    if snapshot_path(LEGACY_PROVIDER_ID).exists():
        return False
    for legacy in _legacy_cache_candidates():
        data = _read_json(legacy)
        if data is None:
            continue
        if data.get("version") != LEGACY_CACHE_VERSION:
            logger.info(
                "Legacy cache %s has version %s (need %d); not converting",
                legacy, data.get("version"), LEGACY_CACHE_VERSION,
            )
            return False
        try:
            snapshot = legacy_v3_to_snapshot(data)
        except (TypeError, ValueError, AttributeError) as e:
            logger.warning("Malformed legacy cache %s: %s", legacy, e)
            return False
        legacy_synced_at = data.get("synced_at")
        save_snapshot(
            snapshot, synced_at=legacy_synced_at if isinstance(legacy_synced_at, str) else None,
        )
        logger.info(
            "Converted legacy cache %s (%d tracks) to a Serato snapshot",
            legacy, len(snapshot.tracks),
        )
        return True
    return False
