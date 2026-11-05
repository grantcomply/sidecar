"""
Parse Serato .crate files and read ID3 metadata for all tracks.

Replaces the old export_crates.py — no CSV writing, just parsing. The ID3
reader lives in ``tag_reader.py``; its public names are re-exported here.
"""
import logging
import os
import struct
import sys
from collections.abc import Callable
from typing import Any

# Re-exported so existing callers and the test seam
# ``monkeypatch.setattr(crate_parser, "get_track_metadata", ...)`` keep working:
# parse_all_crates looks get_track_metadata up through this module's globals.
from source.services.tag_reader import KEY_TO_CAMELOT, get_track_metadata, to_camelot  # noqa: F401  re-export

logger = logging.getLogger(__name__)

DEFAULT_MUSIC_ROOT = "C:\\" if sys.platform == "win32" else "/"


def parse_crate_file(crate_path: str) -> list[str]:
    """Parse a Serato .crate binary file and return relative track paths."""
    ptrk = b'ptrk'
    try:
        with open(crate_path, 'rb') as f:
            buf = f.read()
        paths: list[str] = []
        while True:
            start = buf.find(ptrk)
            if start == -1:
                break
            buf = buf[start + len(ptrk):]
            length = struct.unpack('>I', buf[:4])[0]
            buf = buf[4:]
            song_bytes = buf[:length]
            song_bytes_swapped = bytearray(song_bytes)
            for i in range(0, len(song_bytes_swapped), 2):
                if i + 1 < len(song_bytes_swapped):
                    song_bytes_swapped[i], song_bytes_swapped[i + 1] = (
                        song_bytes_swapped[i + 1], song_bytes_swapped[i]
                    )
            song = song_bytes_swapped.decode('utf-16le')
            paths.append(song)
            buf = buf[length:]
        return paths
    except Exception as e:
        logger.error("Error parsing crate file: %s", e)
        return []


def crate_display_name(crate_filename: str) -> str:
    """Convert a .crate filename to a human-readable crate name.

    Example: 'House%%Bangers.crate' -> 'House - Bangers'
    """
    name = crate_filename.replace(".crate", "")
    name = name.replace("%%", " - ")
    return name


def crate_stem(crate_filename: str) -> str:
    """'House%%Bangers.crate' -> 'House%%Bangers' (stable Serato native id)."""
    return crate_filename.removesuffix(".crate")


# Legacy private names, kept as aliases for existing callers.
_crate_display_name = crate_display_name
_crate_stem = crate_stem


def parse_all_crates(
    subcrates_dir: str,
    music_root: str | None = None,
    progress_callback: Any = None,
    *,
    crate_key: Callable[[str], str] = crate_display_name,
) -> tuple[dict[str, dict], dict[str, float]]:
    """Parse all .crate files and read ID3 metadata for every track.

    Args:
        subcrates_dir: Path to Serato Subcrates folder.
        music_root: Root path for resolving track paths.
        progress_callback: Optional callable(message, current, total).
        crate_key: Maps a .crate filename to the value stored in each track's
            "crates" list. Defaults to the display name (the v3 cache shape);
            the Serato provider passes ``crate_stem`` to get stable ids.

    Returns:
        (tracks_dict, crate_mtimes_dict) where:
        - tracks_dict is keyed by full file path, value is a metadata dict
          with a "crates" list of crate keys (``crate_key``) the track belongs to.
        - crate_mtimes_dict maps crate filename to its modification time.
    """
    if music_root is None:
        music_root = DEFAULT_MUSIC_ROOT

    crate_files = [f for f in os.listdir(subcrates_dir) if f.endswith('.crate')]
    if not crate_files:
        logger.info("No .crate files found in %s", subcrates_dir)
        return ({}, {})

    logger.info("Found %d crate(s) in %s", len(crate_files), subcrates_dir)

    tracks: dict[str, dict] = {}
    crate_mtimes: dict[str, float] = {}

    for i, crate_file in enumerate(sorted(crate_files)):
        crate_path = os.path.join(subcrates_dir, crate_file)
        crate_name = crate_key(crate_file)
        # Progress/log text always uses the display name, whatever crate_key is.
        crate_label = crate_display_name(crate_file)

        # Record crate modification time
        try:
            crate_mtimes[crate_file] = os.path.getmtime(crate_path)
        except OSError:
            crate_mtimes[crate_file] = 0.0

        rel_paths = parse_crate_file(crate_path)
        for rel_path in rel_paths:
            absolute_path = os.path.normpath(os.path.join(music_root, rel_path))

            if absolute_path in tracks:
                # Track already seen — just add this crate
                if crate_name not in tracks[absolute_path]["crates"]:
                    tracks[absolute_path]["crates"].append(crate_name)
            else:
                meta = get_track_metadata(absolute_path)
                meta["crates"] = [crate_name]
                # date_added is the file's creation time, read fresh each sync by
                # get_track_metadata (no carry-forward — see ADR-013).
                tracks[absolute_path] = meta

        msg = f"  {crate_label} ({len(rel_paths)} tracks)"
        logger.info("%s", msg)
        if progress_callback:
            progress_callback(msg, i + 1, len(crate_files))

    logger.info(
        "Done. Parsed %d tracks from %d crates.",
        len(tracks), len(crate_files),
    )
    return (tracks, crate_mtimes)
