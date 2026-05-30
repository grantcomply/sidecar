"""Unit tests for ``source.services.crate_parser.parse_all_crates``.

Focus: the ``date_added`` carry-forward logic (Phase 2 of
suggestion-filter-enhancements) — the highest-risk part of the feature. A
first-seen track is mtime-seeded, but on later syncs the prior non-zero
``date_added`` must be carried forward UNCHANGED so the value never drifts to a
fresh mtime.

Real ID3 / binary-crate I/O is avoided by monkeypatching the two module seams
``parse_crate_file`` (crate -> relative paths) and ``get_track_metadata``
(path -> metadata dict), and using ``tmp_path`` only to hold empty ``.crate``
files so ``os.listdir`` finds them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from source.services import crate_parser

# Fixed epoch timestamps (seconds). The "seed" is what a fresh stat() would
# return now; the "prior" is the frozen first-seen value carried forward.
_SEED_MTIME = 1_740_000_000.0   # 2025-02-19 — fresh mtime on re-sync
_PRIOR_DATE = 1_600_000_000.0   # 2020-09-13 — frozen first-seen value


def _make_crate_files(subcrates_dir: Path, names: list[str]) -> None:
    """Create empty ``.crate`` files so ``os.listdir`` discovers them.

    Contents are irrelevant — ``parse_crate_file`` is monkeypatched to return
    controlled relative paths per crate.
    """
    for name in names:
        (subcrates_dir / name).write_bytes(b"")


def _metadata_stub(date_added: float):
    """Return a ``get_track_metadata`` replacement that mtime-seeds every track.

    Mirrors the real function's contract: a freshly-seen path always carries the
    seeded ``date_added`` (the value carry-forward must later override).
    """

    def _get(path: str) -> dict:
        return {
            "file_name": Path(path).name,
            "title": "",
            "artist": "",
            "bpm": 0.0,
            "camelot_key": "",
            "genre": "",
            "energy_level": 0,
            "date_added": date_added,
            "full_file_path": path,
        }

    return _get


def test_carry_forward_overrides_fresh_mtime_no_drift(tmp_path, monkeypatch):
    """A prior non-zero ``date_added`` wins over the freshly-seeded mtime.

    This is the no-drift guarantee: re-tagging / re-syncing a track refreshes its
    file mtime, but the first-seen add-date must stay put.
    """
    subcrates = tmp_path / "Subcrates"
    subcrates.mkdir()
    _make_crate_files(subcrates, ["House.crate"])

    track_path = str((tmp_path / "music" / "song.mp3"))

    # Every freshly-parsed track is seeded with the NEW mtime...
    monkeypatch.setattr(crate_parser, "get_track_metadata", _metadata_stub(_SEED_MTIME))
    # ...and the crate resolves to one relative path under music_root=tmp_path.
    monkeypatch.setattr(
        crate_parser, "parse_crate_file", lambda _crate: ["music/song.mp3"]
    )

    # Prior cache holds a DIFFERENT, older first-seen date for the same path.
    previous = {track_path: {"date_added": _PRIOR_DATE}}

    tracks, _mtimes = crate_parser.parse_all_crates(
        str(subcrates), music_root=str(tmp_path), previous_tracks=previous
    )

    assert track_path in tracks
    # The carried-forward prior wins — the date did NOT drift to the new mtime.
    assert tracks[track_path]["date_added"] == _PRIOR_DATE
    assert tracks[track_path]["date_added"] != _SEED_MTIME


def test_carry_forward_across_two_crates_seeds_once_and_appends_crate(
    tmp_path, monkeypatch
):
    """A path in two crates carries the date forward once; the 2nd crate only
    appends its name (no re-seed, no overwrite of the frozen date)."""
    subcrates = tmp_path / "Subcrates"
    subcrates.mkdir()
    # Two crates; sorted() processes "A_Bangers" before "B_Groovers".
    _make_crate_files(subcrates, ["A_Bangers.crate", "B_Groovers.crate"])

    track_path = str((tmp_path / "music" / "shared.mp3"))

    monkeypatch.setattr(crate_parser, "get_track_metadata", _metadata_stub(_SEED_MTIME))
    # Both crates contain the same relative path.
    monkeypatch.setattr(
        crate_parser, "parse_crate_file", lambda _crate: ["music/shared.mp3"]
    )

    previous = {track_path: {"date_added": _PRIOR_DATE}}

    tracks, _mtimes = crate_parser.parse_all_crates(
        str(subcrates), music_root=str(tmp_path), previous_tracks=previous
    )

    assert track_path in tracks
    entry = tracks[track_path]
    # Frozen date carried forward exactly once — second sighting did not touch it.
    assert entry["date_added"] == _PRIOR_DATE
    # Both crate names appended, each exactly once.
    assert entry["crates"] == ["A_Bangers", "B_Groovers"]


def test_no_previous_uses_seeded_mtime(tmp_path, monkeypatch):
    """With no prior cache, the freshly-seeded mtime is kept (baseline)."""
    subcrates = tmp_path / "Subcrates"
    subcrates.mkdir()
    _make_crate_files(subcrates, ["House.crate"])

    track_path = str((tmp_path / "music" / "song.mp3"))

    monkeypatch.setattr(crate_parser, "get_track_metadata", _metadata_stub(_SEED_MTIME))
    monkeypatch.setattr(
        crate_parser, "parse_crate_file", lambda _crate: ["music/song.mp3"]
    )

    tracks, _mtimes = crate_parser.parse_all_crates(
        str(subcrates), music_root=str(tmp_path), previous_tracks=None
    )

    assert tracks[track_path]["date_added"] == _SEED_MTIME


def test_carry_forward_skips_zero_prior_date(tmp_path, monkeypatch):
    """A prior ``date_added`` of 0.0 (unknown) does NOT win — the seed is kept.

    Only a non-zero first-seen value is frozen; an unknown prior re-seeds.
    """
    subcrates = tmp_path / "Subcrates"
    subcrates.mkdir()
    _make_crate_files(subcrates, ["House.crate"])

    track_path = str((tmp_path / "music" / "song.mp3"))

    monkeypatch.setattr(crate_parser, "get_track_metadata", _metadata_stub(_SEED_MTIME))
    monkeypatch.setattr(
        crate_parser, "parse_crate_file", lambda _crate: ["music/song.mp3"]
    )

    previous = {track_path: {"date_added": 0.0}}

    tracks, _mtimes = crate_parser.parse_all_crates(
        str(subcrates), music_root=str(tmp_path), previous_tracks=previous
    )

    assert tracks[track_path]["date_added"] == _SEED_MTIME
