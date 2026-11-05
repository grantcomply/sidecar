"""Pure ``RbTrack`` → ``TrackRecord`` mapping (blueprint D8 field table).

rekordbox is the source of truth: no tag reads here. Energy and the resolved
path are computed by the provider and passed in.
"""

from __future__ import annotations

import os

from source.providers.base import TrackRecord
from source.providers.rekordbox.db_reader import RbTrack
from source.services.tag_reader import to_camelot


def to_track_record(rb: RbTrack, *, path: str, date_added: float, energy: int) -> TrackRecord:
    """Map one rekordbox track to the snapshot track-dict. ``crates`` is filled by the caller."""
    return {
        "file_name": os.path.basename(path),
        "title": rb.title,
        "artist": rb.artist,
        "album": rb.album,
        "bpm": rb.bpm,
        "key": rb.scale_name,
        "camelot_key": to_camelot(rb.scale_name) if rb.scale_name else "",
        "genre": rb.genre,
        "date": str(rb.release_year) if rb.release_year else "",
        "comments": rb.comments,
        "energy_level": energy,
        "play_count": rb.play_count,
        "date_added": date_added,
        "full_file_path": path,
        "crates": [],
    }
