"""Tests for the built-in rekordbox diagnostics (T3.12). Synthetic data only."""

from __future__ import annotations

import importlib.util

import pytest

from source.providers.base import CrateInfo, ProviderError, ProviderIssue, ProviderSnapshot
from source.providers.registry import PROVIDERS
from source.services import diagnostics

TITLE, ARTIST = "Synthetic Secret Title", "Synthetic Secret Artist"


class _FakeRekordbox:
    id = "rekordbox"
    display_name = "rekordbox"
    crate_noun = "playlist"

    def __init__(self, track_path: str, *, error: Exception | None = None,
                 issues: list[ProviderIssue] | None = None) -> None:
        self._path = track_path
        self._error = error
        self._issues = issues or []
        self.scans = 0

    def setting_specs(self):
        return ()

    def default_settings(self):
        return {}

    def validate(self, _settings):
        return self._issues

    def scan(self, _settings, progress=None):
        self.scans += 1
        if self._error is not None:
            raise self._error
        return ProviderSnapshot(
            provider_id="rekordbox",
            tracks={self._path: {
                "title": TITLE, "artist": ARTIST, "camelot_key": "8A",
                "comments": "8A - 6", "energy_level": 6, "full_file_path": self._path,
                "crates": ["rekordbox:1"],
            }},
            crates={
                "rekordbox:1": CrateInfo("rekordbox:1", "rekordbox", "A / B", ("A", "B")),
                "rekordbox:2": CrateInfo("rekordbox:2", "rekordbox", "Empty", ("Empty",)),
            },
            warnings=["1 tracks have no file on this computer"],
        )


@pytest.fixture
def fake(isolated_data_dir, tmp_path, monkeypatch):
    track = tmp_path / "Synthetic Secret Folder" / "synthetic-secret-file.mp3"
    track.parent.mkdir()
    track.write_bytes(b"x")
    provider = _FakeRekordbox(str(track))
    monkeypatch.setitem(PROVIDERS, "rekordbox", provider)
    return provider, str(track), isolated_data_dir


def _report_text(data_dir) -> str:
    reports = list((data_dir / "diagnostics").glob("rekordbox-check-*.txt"))
    assert len(reports) == 1
    return reports[0].read_text(encoding="utf-8")


def test_check_reports_counts_and_exit_zero(fake, capsys):
    provider, _track, data_dir = fake

    assert diagnostics.check_rekordbox_library() == 0

    text = _report_text(data_dir)
    assert "Tracks in scope (in at least one playlist): 1" in text
    assert "Playlists: 2 (with tracks: 1)" in text
    assert "from comment: 1, from file tag: 0" in text
    assert "Tracks whose file exists: 1/1" in text
    assert "1 tracks have no file on this computer" in text
    assert "RESULT: OK" in text
    assert "RESULT: OK" in capsys.readouterr().out
    assert provider.scans == 1


def test_check_report_contains_no_titles_artists_or_track_paths(fake, capsys):
    _provider, track, data_dir = fake

    diagnostics.check_rekordbox_library()

    for text in (_report_text(data_dir), capsys.readouterr().out):
        for secret in (TITLE, ARTIST, track, "Synthetic Secret Folder", "synthetic-secret-file"):
            assert secret not in text


def test_check_provider_error_exits_one_with_fixed_message(fake, monkeypatch):
    provider, _track, data_dir = fake
    provider._error = ProviderError("Database is busy, try again")

    assert diagnostics.check_rekordbox_library() == 1

    text = _report_text(data_dir)
    assert "FAILED: Database is busy, try again" in text
    assert "RESULT: FAILED" in text


def test_check_unexpected_error_reports_type_only(fake):
    provider, _track, data_dir = fake
    provider._error = RuntimeError("pysqlcipher://:SYNTHETIC-KEY-123@/x")

    assert diagnostics.check_rekordbox_library() == 1

    text = _report_text(data_dir)
    assert "unexpected error (RuntimeError)" in text
    assert "SYNTHETIC-KEY-123" not in text


def test_check_validation_error_skips_scan(fake):
    provider, _track, data_dir = fake
    provider._issues = [ProviderIssue("error", "Database not found", "db_path")]

    assert diagnostics.check_rekordbox_library() == 1
    assert provider.scans == 0
    assert "FAILED: Database not found" in _report_text(data_dir)


@pytest.mark.skipif(importlib.util.find_spec("pyrekordbox") is None, reason="pyrekordbox missing")
def test_self_check_ok_when_packages_import(capsys):
    assert diagnostics.self_check_rekordbox() == 0
    assert "OK" in capsys.readouterr().out


def test_self_check_fails_cleanly_on_import_error(monkeypatch, capsys):
    def _fail(name):
        raise ImportError(name)

    monkeypatch.setattr(diagnostics.importlib, "import_module", _fail)

    assert diagnostics.self_check_rekordbox() == 1
    assert "FAILED" in capsys.readouterr().out


def test_self_check_any_exception_reports_type_only(monkeypatch, capsys):
    def _fail(name):
        raise RuntimeError("pysqlcipher://:SYNTHETIC-KEY-123@/x")

    monkeypatch.setattr(diagnostics.importlib, "import_module", _fail)

    assert diagnostics.self_check_rekordbox() == 1
    out = capsys.readouterr().out
    assert "RuntimeError" in out and "SYNTHETIC-KEY-123" not in out


def test_self_check_fails_when_sqlcipher_returns_no_version(monkeypatch, capsys):
    monkeypatch.setattr(diagnostics.importlib, "import_module", lambda _name: None)
    monkeypatch.setattr(diagnostics, "_sqlcipher_works", lambda: False)

    assert diagnostics.self_check_rekordbox() == 1
    assert "cipher_version" in capsys.readouterr().out


def test_display_path_hides_home_folder():
    from pathlib import Path

    inside = Path.home() / "AppData" / "x" / "master.db"
    assert diagnostics.display_path(inside) == str(Path("~") / "AppData" / "x" / "master.db")
    assert diagnostics.display_path(None) == "not found"


def test_check_report_hides_home_folder(fake):
    from pathlib import Path

    _provider, _track, data_dir = fake
    diagnostics.check_rekordbox_library()

    text = _report_text(data_dir)
    assert str(Path.home()) not in text
