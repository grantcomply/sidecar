"""Unit tests for ``source.services.tag_reader`` (extracted from crate_parser)."""

from __future__ import annotations

import pytest

from source.services import crate_parser, tag_reader


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Am", "8A"),
        ("F#m", "11A"),
        ("8A", "8A"),
        ("B♭", "6B"),
        (" A m ", "8A"),
        ("H#", ""),
        ("", ""),
    ],
)
def test_to_camelot_known_inputs_return_expected(raw, expected):
    assert tag_reader.to_camelot(raw) == expected


def test_get_track_metadata_missing_file_returns_empty_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(tag_reader, "file_creation_time", lambda _p: None)
    path = str(tmp_path / "missing.mp3")

    meta = tag_reader.get_track_metadata(path)

    assert meta == {
        "file_name": "missing.mp3",
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
        "date_added": 0.0,
        "full_file_path": path,
    }


def test_crate_parser_reexports_tag_reader_names():
    assert crate_parser.get_track_metadata is tag_reader.get_track_metadata
    assert crate_parser.to_camelot is tag_reader.to_camelot
    assert crate_parser.KEY_TO_CAMELOT is tag_reader.KEY_TO_CAMELOT


# ── read_energy_level (T3.11) and the narrowed except (T3.9) ──


def _write_id3(path, frames) -> None:
    from mutagen.id3 import ID3

    tags = ID3()
    for frame in frames:
        tags.add(frame)
    tags.save(str(path))


def test_read_energy_level_reads_txxx_tag(tmp_path):
    from mutagen.id3 import TXXX  # pyright: ignore[reportPrivateImportUsage]

    f = tmp_path / "synthetic.mp3"
    _write_id3(f, [TXXX(encoding=3, desc="EnergyLevel", text="6")])

    assert tag_reader.read_energy_level(str(f)) == 6


def test_read_energy_level_non_integer_tag_returns_zero(tmp_path):
    from mutagen.id3 import TXXX  # pyright: ignore[reportPrivateImportUsage]

    f = tmp_path / "synthetic.mp3"
    _write_id3(f, [TXXX(encoding=3, desc="EnergyLevel", text="high")])

    assert tag_reader.read_energy_level(str(f)) == 0


def test_read_energy_level_without_tag_returns_zero(tmp_path):
    from mutagen.id3 import TIT2  # pyright: ignore[reportPrivateImportUsage]

    f = tmp_path / "synthetic.mp3"
    _write_id3(f, [TIT2(encoding=3, text="Synthetic")])

    assert tag_reader.read_energy_level(str(f)) == 0


def test_read_energy_level_non_id3_and_missing_return_zero(tmp_path):
    wav = tmp_path / "synthetic.wav"
    wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")

    assert tag_reader.read_energy_level(str(wav)) == 0
    assert tag_reader.read_energy_level(str(tmp_path / "missing.mp3")) == 0


def test_get_track_metadata_energy_and_playcount_parity(tmp_path, monkeypatch):
    from mutagen.id3 import TXXX  # pyright: ignore[reportPrivateImportUsage]

    monkeypatch.setattr(tag_reader, "file_creation_time", lambda _p: 1.0)
    f = tmp_path / "synthetic.mp3"
    _write_id3(f, [
        TXXX(encoding=3, desc="EnergyLevel", text="6"),
        TXXX(encoding=3, desc="SERATO_PLAYCOUNT", text="x"),
    ])

    meta = tag_reader.get_track_metadata(str(f))

    assert meta["energy_level"] == 6
    assert meta["play_count"] == 0  # non-integer → 0, as before


def test_get_track_metadata_non_id3_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(tag_reader, "file_creation_time", lambda _p: None)
    wav = tmp_path / "synthetic.wav"
    wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")

    meta = tag_reader.get_track_metadata(str(wav))

    assert meta["title"] == "" and meta["energy_level"] == 0 and meta["date_added"] == 0.0


def test_get_track_metadata_does_not_swallow_unexpected_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(tag_reader, "file_creation_time", lambda _p: None)

    def _boom(_path):
        raise KeyError("unexpected")

    monkeypatch.setattr(tag_reader, "ID3", _boom)

    with pytest.raises(KeyError):
        tag_reader.get_track_metadata(str(tmp_path / "x.mp3"))


@pytest.mark.parametrize(("raw", "expected"), [("8a", "8A"), (" 12b ", "12B"), ("F\u266fm", "11A")])
def test_to_camelot_normalises_case_and_sharp_sign(raw, expected):
    assert tag_reader.to_camelot(raw) == expected
