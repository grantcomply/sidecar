"""Private temp copy of the rekordbox database (ADR-015 D8, read-only rule).

SQLite never opens anything in rekordbox's folder: the database files are
copied (read-only) into a fresh private temp folder and the copy is opened.
Stdlib only.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from source.providers.base import ProviderError
from source.providers.rekordbox.paths import WRONG_FILENAME_MESSAGE, is_master_db

logger = logging.getLogger(__name__)

# master.db-shm is deliberately NOT copied: it is SQLite's shared-memory index,
# which SQLite rebuilds from -wal when it opens the copy. A copied -shm can be
# inconsistent with the copied -wal, and the no-shm copy is the configuration
# the Phase 0 spike verified while rekordbox was running.
COPY_FILES = ("master.db", "master.db-wal", "master.db-journal", "masterPlaylists6.xml")
TEMP_PREFIX = "sidecar-rb-"

_NOT_FOUND = "Database not found"
_BUSY = "Database is busy, try again"


def _copy_once(db_path: Path, tmp_root: Path | None) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir=tmp_root))
    try:
        for name in COPY_FILES:
            src = db_path if name == "master.db" else db_path.parent / name
            if src.is_file():
                shutil.copyfile(src, tmp / name)  # opens the source read-only
    except BaseException:
        # Any failure (including KeyboardInterrupt) must not leave a copy behind.
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return tmp


@contextmanager
def private_copy(
    db_path: Path,
    *,
    token_fn: Callable[[Path], str],
    attempts: int = 3,
    delay_s: float = 0.2,
    tmp_root: Path | None = None,
) -> Iterator[Path]:
    """Yield the path of a private copy of ``master.db``; delete the copy afterwards.

    Torn-copy guard: the change token is taken before and after copying; if it
    moved (or the copy failed, e.g. a sharing violation), retry. Raises
    ``ProviderError`` if the database is missing or stays busy.
    """
    if not is_master_db(db_path):
        # The companions below are found by name; never pair them with another DB.
        raise ProviderError(WRONG_FILENAME_MESSAGE)
    if not db_path.is_file():
        raise ProviderError(_NOT_FOUND)
    tmp: Path | None = None
    for attempt in range(1, attempts + 1):
        before = token_fn(db_path)
        try:
            candidate = _copy_once(db_path, tmp_root)
        except OSError as e:
            logger.info("rekordbox copy attempt %d failed (%s)", attempt, type(e).__name__)
        else:
            try:
                unchanged = token_fn(db_path) == before
            except BaseException:
                shutil.rmtree(candidate, ignore_errors=True)
                raise
            if unchanged:
                tmp = candidate
                break
            logger.info("rekordbox database changed during copy (attempt %d)", attempt)
            shutil.rmtree(candidate, ignore_errors=True)
        if attempt < attempts:
            time.sleep(delay_s)
    if tmp is None:
        raise ProviderError(_BUSY)
    try:
        yield tmp / "master.db"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if tmp.exists():
            logger.debug("Temporary rekordbox copy not fully removed yet; next scan cleans it")


def cleanup_stale_copies(*, tmp_root: Path | None = None, max_age_s: float = 3600) -> None:
    """Delete ``sidecar-rb-*`` temp folders older than ``max_age_s``. Touches nothing else."""
    root = tmp_root if tmp_root is not None else Path(tempfile.gettempdir())
    cutoff = time.time() - max_age_s
    try:
        candidates = list(root.glob(f"{TEMP_PREFIX}*"))
    except OSError as e:
        logger.debug("Could not list temp folder (%s)", type(e).__name__)
        return
    for folder in candidates:
        try:
            if folder.is_dir() and folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError as e:
            logger.debug("Could not check stale copy (%s)", type(e).__name__)
