"""
Read ID3 metadata from a track file and convert musical keys to Camelot.

Extracted unchanged from ``crate_parser.py`` (ADR-015, implementation plan
T1.2). Used by the Serato provider; ``crate_parser`` re-exports the public
names so existing callers and test seams keep working. The rekordbox
provider uses only ``to_camelot`` and ``read_energy_level`` (energy fallback).
"""
import logging
import os
from typing import Any

from mutagen import MutagenError  # pyright: ignore[reportPrivateImportUsage] - public API
from mutagen.id3 import ID3
from source.services.camelot import parse_camelot
from source.services.file_times import file_creation_time

logger = logging.getLogger(__name__)

_ENERGY_TAG = "TXXX:EnergyLevel"

KEY_TO_CAMELOT = {
    "C": "8B", "C#": "3B", "Db": "3B", "D": "10B", "D#": "5B", "Eb": "5B",
    "E": "12B", "F": "7B", "F#": "2B", "Gb": "2B", "G": "9B", "G#": "4B", "Ab": "4B",
    "A": "11B", "A#": "6B", "Bb": "6B", "B": "1B",
    "Cm": "5A", "C#m": "12A", "Dbm": "12A", "Dm": "7A", "D#m": "2A", "Ebm": "2A",
    "Em": "9A", "Fm": "4A", "F#m": "11A", "Gbm": "11A", "Gm": "6A", "G#m": "1A", "Abm": "1A",
    "Am": "8A", "A#m": "3A", "Bbm": "3A", "Bm": "10A",
}


def to_camelot(key: str) -> str:
    """Convert a musical key string to its Camelot wheel notation."""
    clean_key = key.strip().replace("\u266d", "b").replace("\u266f", "#").replace(" ", "")
    # Pass through if already in Camelot notation (normalised to upper case, "8a" -> "8A")
    if parse_camelot(clean_key.upper()) is not None:
        return clean_key.upper()
    return KEY_TO_CAMELOT.get(clean_key, "")


def _tag_text(tags: Any, key: str) -> str:
    """Extract text from an ID3 tag frame, returning empty string if missing."""
    if key in tags:
        return str(tags[key].text[0]) if hasattr(tags[key], 'text') else str(tags[key])
    return ""


def _tag_int(tags: Any, key: str) -> int:
    """Integer value of a tag frame; 0 if missing or not an integer."""
    text = _tag_text(tags, key)
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        return 0


def read_energy_level(path: str) -> int:
    """Read only ``TXXX:EnergyLevel`` from a file's ID3 tags.

    Returns 0 for a missing file, a non-ID3 file, a missing tag or a
    non-integer value. ID3-only, like ``get_track_metadata``.
    """
    try:
        tags = ID3(path)
    except (MutagenError, OSError) as e:
        logger.debug("No readable ID3 tags (%s)", type(e).__name__)
        return 0
    return _tag_int(tags, _ENERGY_TAG)


def get_track_metadata(path: str) -> dict[str, Any]:
    """Read ID3 tags from a track file and return a metadata dict.

    Returns a dict with keys: file_name, title, artist, album, bpm, key,
    camelot_key, genre, date, comments, energy_level, play_count, full_file_path.
    Numeric fields are returned as their native types (float/int).
    """
    file_name = os.path.basename(path)

    # "date added" is the file's CREATION time, read cross-platform via
    # file_times.file_creation_time (st_birthtime / Windows st_ctime / mtime
    # fallback — see cross-platform-guide.md "File creation time" and ADR-013).
    # Read fresh on every sync (no carry-forward). file_creation_time swallows
    # OSError and returns None, which we map to 0.0 = "unknown" — the contract
    # suggestion_engine.py:88-93's date filter relies on.
    ct = file_creation_time(path)
    date_added = ct if ct is not None else 0.0

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
        "date_added": date_added,
        "full_file_path": path,
    }
    try:
        tags = ID3(path)
    except (MutagenError, OSError) as e:  # ID3NoHeaderError subclasses MutagenError
        logger.debug("No readable ID3 tags (%s)", type(e).__name__)
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

    energy_level = _tag_int(tags, _ENERGY_TAG)
    play_count = _tag_int(tags, 'TXXX:SERATO_PLAYCOUNT')

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
        "date_added": date_added,
        "full_file_path": path,
    }
