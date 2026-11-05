"""Build minimal Serato ``.crate`` file bytes for tests.

Real ``.crate`` files are a sequence of tagged chunks. ``parse_crate_file``
only scans for ``ptrk`` chunks (big-endian length + UTF-16-BE path), so a
``vrsn`` header plus one ``otrk``/``ptrk`` pair per track is enough.
"""

from __future__ import annotations

import struct
from pathlib import Path

_VERSION_TEXT = "1.0/Serato ScratchLive Crate"


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return tag + struct.pack(">I", len(payload)) + payload


def build_crate_bytes(paths: list[str]) -> bytes:
    """Return ``.crate`` bytes listing ``paths`` (relative, as Serato stores them)."""
    out = _chunk(b"vrsn", _VERSION_TEXT.encode("utf-16-be"))
    for path in paths:
        ptrk = _chunk(b"ptrk", path.encode("utf-16-be"))
        out += _chunk(b"otrk", ptrk)
    return out


def write_crate(subcrates_dir: Path, filename: str, paths: list[str]) -> Path:
    """Write a ``.crate`` file named ``filename`` into ``subcrates_dir``."""
    target = subcrates_dir / filename
    target.write_bytes(build_crate_bytes(paths))
    return target
