"""Read a private copy of rekordbox's ``master.db`` (ADR-015 D8).

The ONLY module that imports pyrekordbox or SQLAlchemy, lazily (ADR-009
pattern), so the app starts and Serato works even if they fail to load.

Key and log safety: Sidecar never passes, stores or logs a database key
(pyrekordbox's built-in key is used). pyrekordbox logs the key at DEBUG, so its
loggers are pinned at ERROR right after import (``log_safety``; SQLAlchemy's at
WARNING). Every exception from
pyrekordbox/SQLAlchemy is turned into a fixed-text ``ProviderError ... from
None`` and only its type name is logged: their messages can embed the
connection URL, which contains the key.

No write API (commit/add/delete/flush) is ever called, even on the copy.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from source.providers.base import ProviderError
from source.services.log_safety import silence_secret_loggers

logger = logging.getLogger(__name__)

_UNAVAILABLE = "Not available in this build"
_READ_FAILED = "Couldn't read the database"
_BUSY = "Database is busy, try again"
_SMART_SKIPPED = "Smart playlists were skipped"
_ATTR_PLAYLIST, _ATTR_FOLDER, _ATTR_SMART = 0, 1, 4
_BPM_SCALE = 100.0

_pyrekordbox: Any = None
_sql_text: Any = None


@dataclass(frozen=True)
class RbTrack:
    content_id: str
    title: str
    artist: str
    album: str
    genre: str
    bpm: float
    scale_name: str
    comments: str
    play_count: int
    release_year: int
    org_path: str
    folder_path: str
    local_path: str


@dataclass(frozen=True)
class RbPlaylist:
    playlist_id: str
    path: tuple[str, ...]
    content_ids: tuple[str, ...]
    is_smart: bool


@dataclass(frozen=True)
class RbLibrary:
    tracks: dict[str, RbTrack]
    playlists: list[RbPlaylist]
    warnings: list[str]


class CopyIntegrityError(ProviderError):
    """``PRAGMA quick_check`` on the copy wasn't ``ok``; the caller re-copies once."""


def _ensure_pyrekordbox() -> None:
    """Import pyrekordbox + SQLAlchemy on first use, then pin their loggers."""
    global _pyrekordbox, _sql_text
    if _pyrekordbox is not None:
        silence_secret_loggers()
        return
    failed = False
    try:
        import pyrekordbox  # noqa: WPS433 - intentional lazy import
        from sqlalchemy import text

        _pyrekordbox, _sql_text = pyrekordbox, text
    except Exception as e:  # noqa: BLE001 - import boundary; type name only (key safety)
        logger.warning("rekordbox support unavailable (%s)", type(e).__name__)
        failed = True
    finally:
        # Even a partial import may have created pyrekordbox's loggers.
        silence_secret_loggers()
    if failed:
        # Raised outside the except block: neither __cause__ nor __context__
        # can carry the original exception (or its message) anywhere.
        raise ProviderError(_UNAVAILABLE)


def _default_factory() -> Callable[..., Any]:
    masterdb = getattr(_pyrekordbox, "masterdb", None)
    factory = getattr(masterdb, "MasterDatabase", None) if masterdb is not None else None
    return factory or _pyrekordbox.Rekordbox6Database


def _attr(obj: Any, name: str, default: Any) -> Any:
    """Attribute value, or ``default`` if missing or ``None`` (schema-drift tolerance, R14)."""
    try:
        value = getattr(obj, name)
    except Exception:  # noqa: BLE001 - lazy relationship loads can raise anything
        return default
    return default if value is None else value


def _deleted(row: Any) -> bool:
    """rekordbox soft-deletes rows by setting ``rb_local_deleted``; skip those."""
    return bool(_attr(row, "rb_local_deleted", 0))


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _track(content: Any) -> RbTrack:
    key = _attr(content, "Key", None)
    return RbTrack(
        content_id=str(_attr(content, "ID", "")),
        title=str(_attr(content, "Title", "")),
        artist=str(_attr(content, "ArtistName", "")),
        album=str(_attr(content, "AlbumName", "")),
        genre=str(_attr(content, "GenreName", "")),
        bpm=_as_float(_attr(content, "BPM", 0)) / _BPM_SCALE,
        scale_name=str(_attr(key, "ScaleName", "")) if key is not None else "",
        comments=str(_attr(content, "Commnt", "")),
        play_count=_as_int(_attr(content, "DJPlayCount", 0)),
        release_year=_as_int(_attr(content, "ReleaseYear", 0)),
        org_path=str(_attr(content, "OrgFolderPath", "")),
        folder_path=str(_attr(content, "FolderPath", "")),
        local_path=str(_attr(content, "rb_LocalFolderPath", "")),
    )


def _playlist_path(playlist: Any, by_id: dict[str, Any]) -> tuple[str, ...]:
    """Folder hierarchy, leaf last. Stops on a repeated id (cycle-safe)."""
    names: list[str] = []
    seen: set[str] = set()
    node = playlist
    while node is not None:
        node_id = str(_attr(node, "ID", ""))
        if node_id in seen:
            break
        seen.add(node_id)
        names.append(str(_attr(node, "Name", "")))
        node = by_id.get(str(_attr(node, "ParentID", "")))
    return tuple(reversed(names))


def _playlists(db: Any, warnings: list[str]) -> list[RbPlaylist]:
    rows = [p for p in db.get_playlist() if not _deleted(p)]
    by_id = {str(_attr(p, "ID", "")): p for p in rows}
    entries: dict[str, list[tuple[int, str]]] = {}
    for song in db.get_playlist_songs():
        if _deleted(song):
            continue
        entries.setdefault(str(_attr(song, "PlaylistID", "")), []).append(
            (_as_int(_attr(song, "TrackNo", 0)), str(_attr(song, "ContentID", ""))),
        )
    result: list[RbPlaylist] = []
    smart_warned = False
    for row in rows:
        attribute = _as_int(_attr(row, "Attribute", -1))
        pid = str(_attr(row, "ID", ""))
        if attribute == _ATTR_PLAYLIST:
            ids = tuple(cid for _no, cid in sorted(entries.get(pid, []), key=lambda e: e[0]))
            result.append(RbPlaylist(pid, _playlist_path(row, by_id), ids, is_smart=False))
        elif attribute == _ATTR_SMART:
            try:
                ids = tuple(str(_attr(c, "ID", "")) for c in db.get_playlist_contents(row))
            except Exception as e:  # noqa: BLE001 - smart evaluation is best effort
                logger.info("Smart playlist skipped (%s)", type(e).__name__)
                if not smart_warned:
                    warnings.append(_SMART_SKIPPED)
                    smart_warned = True
                continue
            result.append(RbPlaylist(pid, _playlist_path(row, by_id), ids, is_smart=True))
        # _ATTR_FOLDER and anything else only contribute to paths.
    return result


def read_library(copy_path: Path, *, db_factory: Callable[..., Any] | None = None) -> RbLibrary:
    """Open the private copy at ``copy_path``, read tracks and playlists, close it.

    Raises ``ProviderError`` (fixed text) for every failure, ``CopyIntegrityError``
    when ``PRAGMA quick_check`` isn't ``ok``.
    """
    _ensure_pyrekordbox()
    db: Any = None
    try:
        factory = db_factory or _default_factory()
        # No key argument: pyrekordbox's built-in key is used. Never pass one.
        db = factory(path=copy_path, db_dir=copy_path.parent)
        # Again now that the engine exists: SQLAlchemy may have created loggers.
        silence_secret_loggers()
        check = db.session.execute(_sql_text("PRAGMA quick_check")).scalar()
        if check != "ok":
            raise CopyIntegrityError(_BUSY)
        warnings: list[str] = []
        tracks = {
            t.content_id: t for t in (_track(c) for c in db.get_content() if not _deleted(c))
        }
        return RbLibrary(tracks=tracks, playlists=_playlists(db, warnings), warnings=warnings)
    except ProviderError:
        raise
    except Exception as e:  # noqa: BLE001 - adapter boundary; see module docstring (key safety)
        logger.warning("rekordbox read failed (%s)", type(e).__name__)
    finally:
        if db is not None:
            # Documented cleanup boundary: Windows must release the file
            # handles before private_copy deletes the folder.
            with contextlib.suppress(Exception):
                db.close()
            with contextlib.suppress(Exception):
                db.engine.dispose()
    # Only reached on failure. Raised outside the except block so neither
    # __cause__ nor __context__ refers to the original (possibly key-bearing) error.
    raise ProviderError(_READ_FAILED)
