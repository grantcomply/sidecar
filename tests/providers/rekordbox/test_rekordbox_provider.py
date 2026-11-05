"""Tests for ``RekordboxProvider`` with a fake database and synthetic files."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from source.providers.base import DeckLoadNotSupported, ProviderCapability, ProviderError
from source.providers.rekordbox.energy_cache import TagEnergyCache
from source.providers.rekordbox.paths import compute_change_token
from source.providers.rekordbox.provider import RekordboxProvider
from tests.providers.rekordbox.fakes import FakeMasterDb, content, fake_factory, playlist, song

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def env(tmp_path):
    rb_dir = tmp_path / "rekordbox"
    rb_dir.mkdir()
    (rb_dir / "master.db").write_bytes(b"synthetic")
    music = tmp_path / "music"
    music.mkdir()
    tmp_root = tmp_path / "temp"
    tmp_root.mkdir()
    return {"db": rb_dir / "master.db", "music": music, "tmp_root": tmp_root}


def _file(env, name: str) -> str:
    path = env["music"] / name
    path.write_bytes(b"synthetic audio")
    return str(path)


class _Reader:
    def __init__(self, value: int = 6) -> None:
        self.value = value
        self.calls: list[str] = []

    def __call__(self, path: str) -> int:
        self.calls.append(path)
        return self.value


def _provider(env, db_or_factory, reader=None, cache=None) -> RekordboxProvider:
    factory = db_or_factory if callable(db_or_factory) else fake_factory(db_or_factory)
    return RekordboxProvider(
        db_factory=factory,
        energy_cache=cache if cache is not None else TagEnergyCache(),
        energy_reader=reader if reader is not None else _Reader(),
        tmp_root=env["tmp_root"],
    )


def _settings(env, auto_refresh: str = "on") -> dict[str, str]:
    return {"db_path": str(env["db"]), "auto_refresh": auto_refresh}


def _library(env) -> FakeMasterDb:
    a = _file(env, "a.mp3")
    b = _file(env, "b.mp3")
    contents = [
        content("1", comment="8A - 7 - Groover", org=a),
        content("2", comment="Free text", org=b),
        content("3", org=str(env["music"] / "missing.mp3")),
        content("4", org="", folder="/contents_9/x.mp3"),
    ]
    playlists = [
        playlist("10", "Club", attribute=1),
        playlist("11", "Peak", parent="10"),
        playlist("12", "Warm up"),
        playlist("13", "Empty"),
    ]
    songs = [
        song("11", "1", 1), song("11", "2", 2), song("11", "999", 3),
        song("12", "1", 1), song("12", "3", 2), song("12", "4", 3),
    ]
    return FakeMasterDb(contents, playlists, songs)


def test_scan_crates_tracks_and_warnings(env):
    reader = _Reader(6)
    snapshot = _provider(env, _library(env), reader).scan(_settings(env))

    assert snapshot.provider_id == "rekordbox"
    assert {cid: (c.label, c.path) for cid, c in snapshot.crates.items()} == {
        "rekordbox:11": ("Club / Peak", ("Club", "Peak")),
        "rekordbox:12": ("Warm up", ("Warm up",)),
        "rekordbox:13": ("Empty", ("Empty",)),
    }
    a = os.path.normpath(str(env["music"] / "a.mp3"))
    missing = os.path.normpath(str(env["music"] / "missing.mp3"))
    assert snapshot.tracks[a].get("crates") == ["rekordbox:11", "rekordbox:12"]
    assert missing in snapshot.tracks  # kept, though the file is missing
    assert len(snapshot.tracks) == 3  # track 4 has no usable path
    assert snapshot.warnings == [
        "1 tracks have no file on this computer",
        "1 tracks have no usable file path",
        "1 playlist entries point to tracks that aren't in the collection",
    ]
    assert list(env["tmp_root"].iterdir()) == []  # private copy removed


def test_energy_comment_then_tag_then_none_and_cache(env):
    reader, cache = _Reader(5), TagEnergyCache()
    provider = _provider(env, _library(env), reader, cache)

    snapshot = provider.scan(_settings(env))
    energies = {Path(p).name: t.get("energy_level") for p, t in snapshot.tracks.items()}

    assert energies == {"a.mp3": 7, "b.mp3": 5, "missing.mp3": 0}
    assert [Path(p).name for p in reader.calls] == ["b.mp3"]  # comment energy & missing file skip it

    provider.scan(_settings(env))
    assert len(reader.calls) == 1  # second scan served from the cache


def test_org_path_preferred_over_local_folder_path(env):
    org = _file(env, "org.mp3")
    folder = _file(env, "folder.mp3")
    db = FakeMasterDb([content("1", org=org, folder=folder)], [playlist("1", "P")],
                      [song("1", "1", 1)])

    snapshot = _provider(env, db).scan(_settings(env))

    assert list(snapshot.tracks) == [os.path.normpath(org)]


def test_token_taken_before_reading(env):
    wal = env["db"].parent / "master.db-wal"
    before = compute_change_token(env["db"])
    db = _library(env)

    def factory(**_kw):
        wal.write_bytes(b"rekordbox wrote during the read")
        return db

    snapshot = _provider(env, factory).scan(_settings(env))

    assert snapshot.change_token == before
    assert compute_change_token(env["db"]) != before
    assert set(snapshot.fingerprint) == {"master.db"}


def test_integrity_failure_recopies_once_then_succeeds(env):
    good = _library(env)
    bad = FakeMasterDb([], [], [], quick_check="corrupt")
    dbs = iter([bad, good])
    calls: list[int] = []

    def factory(**_kw):
        calls.append(1)
        return next(dbs)

    snapshot = _provider(env, factory).scan(_settings(env))

    assert len(calls) == 2 and len(snapshot.tracks) == 3


def test_integrity_failure_twice_raises_busy(env):
    def factory(**_kw):
        return FakeMasterDb([], [], [], quick_check="corrupt")

    with pytest.raises(ProviderError, match="busy"):
        _provider(env, factory).scan(_settings(env))


def test_scan_missing_db_raises_not_found(env, tmp_path):
    provider = _provider(env, _library(env))
    with pytest.raises(ProviderError, match="^Database not found$"):
        provider.scan({"db_path": str(tmp_path / "nope" / "master.db"), "auto_refresh": "on"})


def test_validate_does_not_open_db(env, tmp_path, monkeypatch):
    calls: list[int] = []
    provider = _provider(env, lambda **_kw: calls.append(1))

    assert provider.validate(_settings(env)) == [] or importlib.util.find_spec("pyrekordbox") is None
    issues = provider.validate({"db_path": str(tmp_path / "nope" / "master.db")})
    assert [(i.severity, i.message, i.setting_key) for i in issues][0] == (
        "error", "Database not found", "db_path",
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    assert any("Not available" in i.message for i in provider.validate(_settings(env)))
    assert calls == []


def test_change_detection_only_when_auto_refresh_on(env):
    provider = _provider(env, _library(env))

    assert ProviderCapability.CHANGE_DETECTION in provider.capabilities(_settings(env, "on"))
    assert ProviderCapability.CHANGE_DETECTION not in provider.capabilities(_settings(env, "off"))
    assert provider.change_token(_settings(env, "off")) is None
    assert provider.change_token(_settings(env, "on")) == compute_change_token(env["db"])
    caps = provider.capabilities(_settings(env))
    assert ProviderCapability.DECK_LOAD not in caps
    assert ProviderCapability.SMART_PLAYLISTS not in caps


def test_change_token_none_when_db_missing(env, tmp_path):
    provider = _provider(env, _library(env))
    assert provider.change_token({"db_path": str(tmp_path / "nope" / "master.db"), "auto_refresh": "on"}) is None


def test_load_to_deck_not_supported(env):
    with pytest.raises(DeckLoadNotSupported):
        _provider(env, _library(env)).load_to_deck(_settings(env), "/x.mp3", 1)


def test_importing_provider_does_not_import_pyrekordbox():
    code = (
        "import sys; import source.providers.registry, source.providers.rekordbox.provider; "
        "print(sorted(m for m in ('pyrekordbox', 'sqlalchemy', 'sqlcipher3') if m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=_PROJECT_ROOT, capture_output=True, text=True,
        timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_default_settings_without_rekordbox_installed(env):
    # The session fixture points default_db_path at a missing temp file.
    provider = _provider(env, _library(env))

    assert provider.change_token(provider.default_settings()) is None
    assert provider.detect() is False
    assert provider.validate(provider.default_settings())[0].message == "Database not found"


@pytest.mark.parametrize("name", ["master.backup.db", "master.backup.20260101.db", "other.db"])
def test_wrong_database_file_name_rejected_everywhere(env, name):
    other = env["db"].parent / name
    other.write_bytes(b"synthetic backup")
    calls: list[int] = []
    provider = _provider(env, lambda **_kw: calls.append(1))
    settings = {"db_path": str(other), "auto_refresh": "on"}

    issues = provider.validate(settings)
    with pytest.raises(ProviderError, match="^Choose the file named master.db$"):
        provider.scan(settings)

    assert issues[0].message == "Choose the file named master.db"
    assert issues[0].setting_key == "db_path"
    assert provider.change_token(settings) is None
    assert calls == []  # never opened
    assert list(env["tmp_root"].iterdir()) == []  # never copied


@pytest.mark.skipif(sys.platform != "win32", reason="case-insensitive name rule is Windows-only")
def test_master_db_name_case_insensitive_on_windows(env):
    upper = env["db"].parent / "MASTER.DB"
    provider = _provider(env, _library(env))
    assert provider.validate({"db_path": str(upper), "auto_refresh": "on"}) == []


def test_energy_tag_failure_is_per_track_and_logged_once(env, caplog):
    def bad_reader(_path: str) -> int:
        raise RuntimeError("corrupt tag")

    provider = _provider(env, _library(env), reader=bad_reader)

    snapshot = provider.scan(_settings(env))

    energies = {Path(p).name: t.get("energy_level") for p, t in snapshot.tracks.items()}
    assert energies == {"a.mp3": 7, "b.mp3": 0, "missing.mp3": 0}
    failures = [r for r in caplog.records if "Energy tag read failed" in r.getMessage()]
    assert len(failures) == 1 and "RuntimeError" in failures[0].getMessage()
    assert "corrupt tag" not in caplog.text


def test_detected_values_with_and_without_database(env, monkeypatch):
    from source.providers.rekordbox import paths

    provider = _provider(env, _library(env))
    assert provider.detected_values({"db_path": "", "auto_refresh": "on"}) == {}  # none installed
    monkeypatch.setattr(paths, "default_db_path", lambda: env["db"])
    assert provider.detected_values({"db_path": "", "auto_refresh": "on"}) == {
        "db_path": str(env["db"]),
    }
    # A value the DJ chose is not "detected".
    assert provider.detected_values(_settings(env)) == {}


def test_new_copy_strings_on_specs():
    specs = {s.key: s for s in RekordboxProvider().setting_specs()}
    assert specs["db_path"].label == "Database"
    assert specs["db_path"].placeholder == "Choose the file named master.db"
    assert specs["db_path"].hint == (
        "Leave empty to use the database rekordbox created. Only choose a file if you moved it."
    )
    assert specs["auto_refresh"].label == "Update automatically"
    assert specs["auto_refresh"].hint == (
        "Checks about once a minute and updates quietly. Your setlist and filters stay as they are."
    )
