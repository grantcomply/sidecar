"""Unit tests for ``source.services.crate_parser.parse_all_crates``.

Focus: ``date_added`` is the file's **creation time**, read **fresh on every
sync** (ADR-013). There is no longer any carry-forward — ``parse_all_crates``
uses whatever ``get_track_metadata`` seeds (creation time) as-is, and a path
appearing in two crates is seeded once with both crate names appended.

Real ID3 / binary-crate I/O is avoided by monkeypatching the two module seams
``parse_crate_file`` (crate -> relative paths) and ``get_track_metadata``
(path -> metadata dict), and using ``tmp_path`` only to hold empty ``.crate``
files so ``os.listdir`` finds them.
"""

from __future__ import annotations

from pathlib import Path

from source.services import crate_parser

# Fixed epoch timestamp (seconds) the stubbed metadata seeds as the creation time.
_CREATION_TIME = 1_600_000_000.0   # 2020-09-13


def _make_crate_files(subcrates_dir: Path, names: list[str]) -> None:
    """Create empty ``.crate`` files so ``os.listdir`` discovers them.

    Contents are irrelevant — ``parse_crate_file`` is monkeypatched to return
    controlled relative paths per crate.
    """
    for name in names:
        (subcrates_dir / name).write_bytes(b"")


def _metadata_stub(date_added: float):
    """Return a ``get_track_metadata`` replacement seeding a fixed ``date_added``.

    Mirrors the real function's contract: every parsed path carries the seeded
    creation-time ``date_added`` (used as-is — no carry-forward).
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


def test_date_added_uses_fresh_creation_time(tmp_path, monkeypatch):
    """``date_added`` is the freshly-seeded creation time from ``get_track_metadata``."""
    subcrates = tmp_path / "Subcrates"
    subcrates.mkdir()
    _make_crate_files(subcrates, ["House.crate"])

    track_path = str((tmp_path / "music" / "song.mp3"))

    monkeypatch.setattr(crate_parser, "get_track_metadata", _metadata_stub(_CREATION_TIME))
    monkeypatch.setattr(
        crate_parser, "parse_crate_file", lambda _crate: ["music/song.mp3"]
    )

    tracks, _mtimes = crate_parser.parse_all_crates(
        str(subcrates), music_root=str(tmp_path)
    )

    assert track_path in tracks
    assert tracks[track_path]["date_added"] == _CREATION_TIME


def test_path_in_two_crates_seeds_once_and_appends_crate(tmp_path, monkeypatch):
    """A path in two crates is seeded once; the 2nd crate only appends its name."""
    subcrates = tmp_path / "Subcrates"
    subcrates.mkdir()
    # Two crates; sorted() processes "A_Bangers" before "B_Groovers".
    _make_crate_files(subcrates, ["A_Bangers.crate", "B_Groovers.crate"])

    track_path = str((tmp_path / "music" / "shared.mp3"))

    monkeypatch.setattr(crate_parser, "get_track_metadata", _metadata_stub(_CREATION_TIME))
    # Both crates contain the same relative path.
    monkeypatch.setattr(
        crate_parser, "parse_crate_file", lambda _crate: ["music/shared.mp3"]
    )

    tracks, _mtimes = crate_parser.parse_all_crates(
        str(subcrates), music_root=str(tmp_path)
    )

    assert track_path in tracks
    entry = tracks[track_path]
    assert entry["date_added"] == _CREATION_TIME
    # Both crate names appended, each exactly once.
    assert entry["crates"] == ["A_Bangers", "B_Groovers"]
