"""Tests for the pure rekordbox → TrackRecord mapping (blueprint D8 table)."""

from __future__ import annotations

import dataclasses
import os
from typing import Any

import pytest

from source.providers.rekordbox.db_reader import RbTrack
from source.providers.rekordbox.mapping import to_track_record


_BASE = RbTrack(
    content_id="1", title="Synthetic Title", artist="Synthetic Artist",
    album="Synthetic Album", genre="House", bpm=124.5, scale_name="Am",
    comments="8A - 6 - Banger", play_count=4, release_year=2021,
    org_path="C:/m/a.mp3", folder_path="/contents_1/a.mp3", local_path="",
)


def _rb(**kw: Any) -> RbTrack:
    return dataclasses.replace(_BASE, **kw)


def test_every_field_mapped():
    path = os.path.normpath("C:/m/a.mp3")

    rec = to_track_record(_rb(), path=path, date_added=123.0, energy=6)

    assert rec == {
        "file_name": "a.mp3",
        "title": "Synthetic Title",
        "artist": "Synthetic Artist",
        "album": "Synthetic Album",
        "bpm": 124.5,
        "key": "Am",
        "camelot_key": "8A",
        "genre": "House",
        "date": "2021",
        "comments": "8A - 6 - Banger",
        "energy_level": 6,
        "play_count": 4,
        "date_added": 123.0,
        "full_file_path": path,
        "crates": [],
    }


@pytest.mark.parametrize(
    ("scale", "camelot"),
    [("Am", "8A"), ("8A", "8A"), ("B\u266d", "6B"), ("F#m", "11A"), ("", "")],
)
def test_camelot_from_scale_name(scale, camelot):
    rec = to_track_record(_rb(scale_name=scale), path="a.mp3", date_added=0.0, energy=0)
    assert rec.get("camelot_key") == camelot
    assert rec.get("key") == scale


def test_release_year_zero_is_empty_date():
    rec = to_track_record(_rb(release_year=0), path="a.mp3", date_added=0.0, energy=0)
    assert rec.get("date") == ""
