"""In-process memo of energy read from file tags (ADR-015 D8, energy fallback).

Keyed by ``(path_key(path), st_mtime_ns, st_size)``, so an edited file is
re-read. Shared across scans for the life of the process; not persisted. It
is a pure memo, so the provider stays stateless as far as the contract goes.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable

from source.models.path_identity import path_key

logger = logging.getLogger(__name__)

_CacheKey = tuple[str, int, int]


class TagEnergyCache:
    """Thread-safe memo of ``reader(path)`` results."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[_CacheKey, int] = {}
        self.hits = 0
        self.reads = 0

    def get(self, path: str, reader: Callable[[str], int]) -> int:
        """Cached energy for ``path``; calls ``reader`` on a miss.

        A ``stat`` error returns 0 and isn't cached.
        """
        try:
            st = os.stat(path)
        except OSError as e:
            logger.debug("Energy cache stat failed (%s)", type(e).__name__)
            return 0
        key = (path_key(path), st.st_mtime_ns, st.st_size)
        with self._lock:
            if key in self._values:
                self.hits += 1
                return self._values[key]
        value = reader(path)  # outside the lock: tag reads are slow
        with self._lock:
            self._values[key] = value
            self.reads += 1
        return value

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
            self.hits = 0
            self.reads = 0


DEFAULT = TagEnergyCache()
