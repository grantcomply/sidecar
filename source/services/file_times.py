"""Cross-platform file creation-time reader.

Leaf module with no project dependencies (only ``os`` / ``sys`` / ``pathlib``),
so it cannot form an import cycle and can be imported freely by
``crate_parser.py`` — mirrors the ``harmonic_tier.py`` leaf-module pattern
(ADR-010). The platform-branching fallback chain lives here, isolated and
unit-testable via mocked ``os.stat`` / ``sys.platform``, so call sites stay
trivial. See ADR-013 and ``docs/cross-platform-guide.md`` ("File creation time").
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def file_creation_time(path: str | Path) -> float | None:
    """Return the file's creation time as a Unix timestamp, or None if unreadable.

    Fallback chain (first hit wins):
      1. ``os.stat(path)``; on ``OSError`` return ``None``.
      2. ``st_birthtime`` if present and ``> 0`` (macOS all versions; Windows on
         Python 3.12+).
      3. ``st_ctime`` if ``sys.platform == "win32"`` (Windows on Python 3.11:
         ``st_ctime`` *is* the creation time, not inode-change time).
      4. ``st_mtime`` (Linux/other dev machines — best available; not a shipping
         target).

    Returns ``None`` only when the file cannot be stat-ed. ``None`` is distinct
    from ``0.0``; the caller owns the policy of substituting ``0.0`` ("unknown")
    so this stays a pure stat-reader (preserves the engine's ``0.0``-excluded
    date-filter contract). See ADR-013 and ``docs/cross-platform-guide.md``.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None

    # st_birthtime is absent on Windows until Python 3.12, so guard with getattr.
    # Some filesystems report birthtime == 0 ("unknown birth"); treat that as a
    # miss and fall through to a usable value.
    birthtime = getattr(st, "st_birthtime", None)
    if birthtime is not None and birthtime > 0:
        return birthtime

    if sys.platform == "win32":
        return st.st_ctime

    return st.st_mtime
