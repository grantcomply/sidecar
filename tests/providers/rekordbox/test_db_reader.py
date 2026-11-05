"""Tests for ``db_reader`` with a fake MasterDatabase (synthetic data only)."""

from __future__ import annotations

import builtins
import logging
import sys

import pytest

from source.providers.base import ProviderError
from source.providers.rekordbox import db_reader
from tests.providers.rekordbox.fakes import (
    SYNTHETIC_KEY,
    FakeMasterDb,
    content,
    fake_factory,
    playlist,
    song,
)



def _db(**kw) -> FakeMasterDb:
    contents = kw.pop("contents", [
        content("1", title="One", bpm=12450, scale="Am", comment="8A - 6", plays=3, year=2020,
                org="C:/m/1.mp3", folder="/contents_1/1.mp3"),
        content("2", scale=None, bpm=None),
    ])
    playlists = kw.pop("playlists", [
        playlist("f1", "Club", attribute=1),
        playlist("p1", "Peak", parent="f1"),
        playlist("p2", "Warm up"),
    ])
    songs = kw.pop("songs", [song("p1", "2", 2), song("p1", "1", 1), song("p2", "1", 1)])
    return FakeMasterDb(contents, playlists, songs, **kw)


def _read(db, tmp_path):
    return db_reader.read_library(tmp_path / "master.db", db_factory=fake_factory(db))


def test_field_mapping_and_defaults(tmp_path):
    lib = _read(_db(), tmp_path)

    one = lib.tracks["1"]
    assert (one.title, one.bpm, one.scale_name, one.comments) == ("One", 124.5, "Am", "8A - 6")
    assert (one.play_count, one.release_year) == (3, 2020)
    assert (one.org_path, one.folder_path, one.local_path) == ("C:/m/1.mp3", "/contents_1/1.mp3", "")
    two = lib.tracks["2"]
    assert two.scale_name == "" and two.bpm == 0.0


def test_missing_attribute_uses_default(tmp_path):
    row = content("9")
    del row.GenreName
    lib = _read(_db(contents=[row], songs=[]), tmp_path)
    assert lib.tracks["9"].genre == ""


def test_playlists_paths_order_and_folders(tmp_path):
    lib = _read(_db(), tmp_path)

    by_id = {p.playlist_id: p for p in lib.playlists}
    assert set(by_id) == {"p1", "p2"}  # folder f1 is not a playlist
    assert by_id["p1"].path == ("Club", "Peak")
    assert by_id["p1"].content_ids == ("1", "2")  # TrackNo order
    assert by_id["p2"].path == ("Warm up",)
    assert lib.warnings == []


def test_parent_cycle_does_not_hang(tmp_path):
    playlists = [playlist("a", "A", parent="b", attribute=1), playlist("b", "B", parent="a")]
    lib = _read(_db(playlists=playlists, songs=[]), tmp_path)
    assert lib.playlists[0].path == ("A", "B")


def test_smart_playlist_evaluated_or_skipped_with_one_warning(tmp_path):
    playlists = [
        playlist("s1", "Smart ok", attribute=4),
        playlist("s2", "Smart bad", attribute=4),
        playlist("s3", "Smart bad 2", attribute=4),
    ]
    db = _db(playlists=playlists, songs=[], smart_contents={"s1": [content("1")]})

    lib = _read(db, tmp_path)

    assert [(p.playlist_id, p.content_ids, p.is_smart) for p in lib.playlists] == [
        ("s1", ("1",), True),
    ]
    assert lib.warnings == ["Smart playlists were skipped"]


def test_quick_check_failure_raises_copy_integrity_error(tmp_path):
    db = _db(quick_check="*** in database main ***")
    with pytest.raises(db_reader.CopyIntegrityError, match="busy"):
        _read(db, tmp_path)
    assert db.closed and db.disposed


def test_factory_error_with_key_in_message_never_leaks(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)

    def factory(**_kw):
        raise RuntimeError(f"pysqlcipher://:{SYNTHETIC_KEY}@/x")

    with pytest.raises(ProviderError) as info:
        db_reader.read_library(tmp_path / "master.db", db_factory=factory)

    _assert_no_key(info.value, caplog, "Couldn't read the database")
    assert "RuntimeError" in caplog.text


def test_read_error_mid_way_closes_and_hides_message(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    db = _db(raise_on="get_playlist_songs",
             raise_with=ValueError(f"key={SYNTHETIC_KEY}"))

    with pytest.raises(ProviderError, match="^Couldn't read the database$"):
        _read(db, tmp_path)

    assert db.closed and db.disposed
    assert SYNTHETIC_KEY not in caplog.text


def test_success_closes_disposes_and_never_writes(tmp_path):
    db = _db()
    opened: list[dict] = []

    db_reader.read_library(tmp_path / "master.db", db_factory=fake_factory(db, opened))

    assert db.closed and db.disposed
    assert db.write_calls == []
    assert opened == [{"path": tmp_path / "master.db", "db_dir": tmp_path}]  # no key argument


def _assert_no_key(e: BaseException, caplog, message: str) -> None:
    assert str(e) == message
    assert e.__cause__ is None
    assert e.__context__ is None
    assert SYNTHETIC_KEY not in str(e)
    assert SYNTHETIC_KEY not in caplog.text
    assert all(SYNTHETIC_KEY not in r.getMessage() for r in caplog.records)


def test_default_factory_construction_error_never_leaks(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)

    def _broken_default():
        raise RuntimeError(SYNTHETIC_KEY)

    monkeypatch.setattr(db_reader, "_default_factory", _broken_default)

    with pytest.raises(ProviderError) as info:
        db_reader.read_library(tmp_path / "master.db")

    _assert_no_key(info.value, caplog, "Couldn't read the database")


def test_import_raising_non_importerror_with_key_never_leaks(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(db_reader, "_pyrekordbox", None)
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "pyrekordbox":
            raise RuntimeError(SYNTHETIC_KEY)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    with pytest.raises(ProviderError) as info:
        db_reader.read_library(tmp_path / "master.db")

    _assert_no_key(info.value, caplog, "Not available in this build")


def test_soft_deleted_rows_are_skipped(tmp_path):
    contents = [content("1", org="C:/m/1.mp3"), content("2", rb_local_deleted=1)]
    playlists = [playlist("p1", "Keep"), playlist("p2", "Gone", )]
    playlists[1].rb_local_deleted = 1
    songs = [song("p1", "1", 1), song("p1", "2", 2)]
    songs[1].rb_local_deleted = 1
    db = FakeMasterDb(contents, playlists, songs)

    lib = _read(db, tmp_path)

    assert set(lib.tracks) == {"1"}
    assert [(p.playlist_id, p.content_ids) for p in lib.playlists] == [("p1", ("1",))]


def test_pyrekordbox_import_failure_raises_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(db_reader, "_pyrekordbox", None)
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "pyrekordbox" or name.startswith("pyrekordbox."):
            raise ImportError("no pyrekordbox")
        return real_import(name, *args, **kwargs)

    monkeypatch.setitem(sys.modules, "pyrekordbox", None)
    monkeypatch.setattr(builtins, "__import__", _fake_import)

    with pytest.raises(ProviderError, match="Not available in this build") as info:
        db_reader.read_library(tmp_path / "master.db")
    assert info.value.__cause__ is None and info.value.__context__ is None
