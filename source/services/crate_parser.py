"""
Parse Serato .crate files and read ID3 metadata for all tracks.

Replaces the old export_crates.py — no CSV writing, just parsing.
"""
import logging
import os
import struct
import sys
from typing import Any

from mutagen.id3 import ID3
from source.services.camelot import parse_camelot

logger = logging.getLogger(__name__)

DEFAULT_MUSIC_ROOT = "C:\\" if sys.platform == "win32" else "/"

KEY_TO_CAMELOT = {
    "C": "8B", "C#": "3B", "Db": "3B", "D": "10B", "D#": "5B", "Eb": "5B",
    "E": "12B", "F": "7B", "F#": "2B", "Gb": "2B", "G": "9B", "G#": "4B", "Ab": "4B",
    "A": "11B", "A#": "6B", "Bb": "6B", "B": "1B",
    "Cm": "5A", "C#m": "12A", "Dbm": "12A", "Dm": "7A", "D#m": "2A", "Ebm": "2A",
    "Em": "9A", "Fm": "4A", "F#m": "11A", "Gbm": "11A", "Gm": "6A", "G#m": "1A", "Abm": "1A",
    "Am": "8A", "A#m": "3A", "Bbm": "3A", "Bm": "10A",
}


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


def to_camelot(key: str) -> str:
    """Convert a musical key string to its Camelot wheel notation."""
    clean_key = key.strip().replace("\u266d", "b").replace(" ", "")
    # Pass through if already in Camelot notation
    if parse_camelot(clean_key) is not None:
        return clean_key
    return KEY_TO_CAMELOT.get(clean_key, "")


def _tag_text(tags: Any, key: str) -> str:
    """Extract text from an ID3 tag frame, returning empty string if missing."""
    if key in tags:
        return str(tags[key].text[0]) if hasattr(tags[key], 'text') else str(tags[key])
    return ""


def get_track_metadata(path: str) -> dict[str, Any]:
    """Read ID3 tags from a track file and return a metadata dict.

    Returns a dict with keys: file_name, title, artist, album, bpm, key,
    camelot_key, genre, date, comments, energy_level, play_count, full_file_path.
    Numeric fields are returned as their native types (float/int).
    """
    file_name = os.path.basename(path)
    empty: dict[str, Any] = {
        "file_name": file_name,
        "title": "",
        "artist": "",
        "album": "",
        "bpm": 0.0,
        "key": "",
        "camelot_key": "",
        "genre": "",
        "date": "",
        "comments": "",
        "energy_level": 0,
        "play_count": 0,
        "full_file_path": path,
    }
    try:
        tags = ID3(path)
    except Exception:
        return empty

    key_raw = _tag_text(tags, 'TKEY')
    comments = str(tags['COMM::eng']) if 'COMM::eng' in tags else ""

    # Parse BPM as float
    bpm = 0.0
    bpm_str = _tag_text(tags, 'TBPM')
    if bpm_str:
        try:
            bpm = float(bpm_str)
        except ValueError:
            pass

    # Parse energy level as int
    energy_level = 0
    energy_str = _tag_text(tags, 'TXXX:EnergyLevel')
    if energy_str:
        try:
            energy_level = int(energy_str)
        except ValueError:
            pass

    # Parse play count as int
    play_count = 0
    play_str = _tag_text(tags, 'TXXX:SERATO_PLAYCOUNT')
    if play_str:
        try:
            play_count = int(play_str)
        except ValueError:
            pass

    return {
        "file_name": file_name,
        "title": _tag_text(tags, 'TIT2'),
        "artist": _tag_text(tags, 'TPE1'),
        "album": _tag_text(tags, 'TALB'),
        "bpm": bpm,
        "key": key_raw,
        "camelot_key": to_camelot(key_raw),
        "genre": _tag_text(tags, 'TCON'),
        "date": _tag_text(tags, 'TDRC'),
        "comments": comments,
        "energy_level": energy_level,
        "play_count": play_count,
        "full_file_path": path,
    }


def _crate_display_name(crate_filename: str) -> str:
    """Convert a .crate filename to a human-readable crate name.

    Example: 'House%%Bangers.crate' -> 'House - Bangers'
    """
    name = crate_filename.replace(".crate", "")
    name = name.replace("%%", " - ")
    return name


def parse_all_crates(
    subcrates_dir: str,
    music_root: str | None = None,
    progress_callback: Any = None,
) -> tuple[dict[str, dict], dict[str, float]]:
    """Parse all .crate files and read ID3 metadata for every track.

    Args:
        subcrates_dir: Path to Serato Subcrates folder.
        music_root: Root path for resolving track paths.
        progress_callback: Optional callable(message, current, total).

    Returns:
        (tracks_dict, crate_mtimes_dict) where:
        - tracks_dict is keyed by full file path, value is a metadata dict
          with a "crates" list of crate names the track belongs to.
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
        crate_name = _crate_display_name(crate_file)

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
                tracks[absolute_path] = meta

        msg = f"  {crate_name} ({len(rel_paths)} tracks)"
        logger.info("%s", msg)
        if progress_callback:
            progress_callback(msg, i + 1, len(crate_files))

    logger.info(
        "Done. Parsed %d tracks from %d crates.",
        len(tracks), len(crate_files),
    )
    return (tracks, crate_mtimes)
