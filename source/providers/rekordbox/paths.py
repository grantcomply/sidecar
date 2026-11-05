"""rekordbox database location, change token and track-path resolution (pure).

Only ``stat``/``exists`` calls; nothing here opens a rekordbox file.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

# -shm is deliberately excluded: it changes with rekordbox's own reads and
# checkpoints, which would trigger refreshes that change nothing (D11).
TOKEN_FILES = ("master.db", "master.db-wal")
DB_FILENAME = "master.db"
WRONG_FILENAME_MESSAGE = "Choose the file named master.db"

_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_CLOUD_PREFIX = "/contents_"  # rekordbox's non-local FolderPath form (Phase 0, T0.5)


def default_db_path() -> Path | None:
    """Where rekordbox 6/7 keeps ``master.db`` on this OS, or ``None`` if unknown."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "Pioneer" / "rekordbox" / "master.db" if appdata else None
    if sys.platform == "darwin":
        # Unverified on a real Mac (blueprint R13).
        return Path.home() / "Library" / "Pioneer" / "rekordbox" / "master.db"
    return None


def resolve_db_path(settings: Mapping[str, str]) -> Path | None:
    """The database path in effect: the ``db_path`` setting, else the OS default.

    Shared by the provider and the diagnostics so the two can't drift.
    """
    configured = settings.get("db_path", "")
    return Path(configured) if configured else default_db_path()


def is_master_db(path: Path) -> bool:
    """True if the file is named exactly ``master.db`` (case-insensitive on Windows).

    Only a file with this name may be read: its ``-wal``/``-journal`` companions
    are found by name, so another database (e.g. a rekordbox backup) would be
    paired with the live database's WAL.
    """
    if sys.platform == "win32":
        return path.name.casefold() == DB_FILENAME
    return path.name == DB_FILENAME


def compute_change_token(db_path: Path) -> str:
    """Stat-only token: ``"master.db:<mtime_ns>:<size>|master.db-wal:<mtime_ns>:<size>"``.

    An absent file is recorded as ``"<name>:-"``.
    """
    parts = []
    for name in TOKEN_FILES:
        try:
            st = (db_path.parent / name).stat()
        except OSError:
            parts.append(f"{name}:-")
        else:
            parts.append(f"{name}:{st.st_mtime_ns}:{st.st_size}")
    return "|".join(parts)


def is_local_path(p: str) -> bool:
    """True for a drive, UNC or absolute POSIX path that isn't rekordbox's ``/contents_`` form."""
    if not p:
        return False
    if _DRIVE_PATH_RE.match(p) or p.startswith("\\\\"):
        return True
    return p.startswith("/") and not p.startswith(_CLOUD_PREFIX)


def resolve_track_path(
    org: str,
    folder: str,
    local: str,
    *,
    exists: Callable[[str], bool] = os.path.exists,
) -> tuple[str | None, bool]:
    """Pick the track's file path from rekordbox's three path fields (blueprint D8).

    First hit wins:
      1. ``org`` (OrgFolderPath) if non-empty and the file exists;
      2. ``folder`` (FolderPath) if local and the file exists;
      3. ``local`` (rb_LocalFolderPath) if non-empty and the file exists;
      4. ``org`` if non-empty (file missing);
      5. ``folder`` if local (file missing);
      6. ``(None, False)``.

    Returns ``(os.path.normpath(path), file_exists)``.
    """
    folder_is_local = is_local_path(folder)
    candidates_existing = (
        org if org else None,
        folder if folder_is_local else None,
        local if local else None,
    )
    for candidate in candidates_existing:
        if candidate and exists(candidate):
            return os.path.normpath(candidate), True
    for candidate in (org if org else None, folder if folder_is_local else None):
        if candidate:
            return os.path.normpath(candidate), False
    return None, False
