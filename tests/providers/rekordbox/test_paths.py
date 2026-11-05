"""Tests for ``source.providers.rekordbox.paths`` (synthetic data only)."""

from __future__ import annotations

import os

import pytest

from source.providers.rekordbox.paths import (
    compute_change_token,
    is_local_path,
    resolve_track_path,
)


def _db_dir(tmp_path):
    (tmp_path / "master.db").write_bytes(b"db")
    return tmp_path / "master.db"


def _bump(path, data: bytes, ns: int) -> None:
    path.write_bytes(data)
    os.utime(path, ns=(ns, ns))


def test_token_absent_wal_recorded(tmp_path):
    token = compute_change_token(_db_dir(tmp_path))
    assert token.startswith("master.db:")
    assert token.endswith("|master.db-wal:-")


def test_token_changes_with_wal_mtime_or_size(tmp_path):
    db = _db_dir(tmp_path)
    wal = tmp_path / "master.db-wal"
    _bump(wal, b"a", 1_000_000_000)
    first = compute_change_token(db)

    _bump(wal, b"a", 2_000_000_000)
    second = compute_change_token(db)
    _bump(wal, b"ab", 2_000_000_000)
    third = compute_change_token(db)

    assert len({first, second, third}) == 3


def test_token_ignores_shm(tmp_path):
    db = _db_dir(tmp_path)
    before = compute_change_token(db)
    _bump(tmp_path / "master.db-shm", b"shared memory", 3_000_000_000)

    assert compute_change_token(db) == before


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("C:/x", True), ("c:\\x", True), ("\\\\srv\\x", True), ("/Users/x", True),
        ("/contents_1/x", False), ("", False), ("relative/x", False),
    ],
)
def test_is_local_path(value, expected):
    assert is_local_path(value) is expected


ORG, FOLDER_LOCAL, LOCAL = "C:/org/a.mp3", "C:/folder/a.mp3", "C:/local/a.mp3"
CLOUD = "/contents_1/a.mp3"


@pytest.mark.parametrize(
    ("org", "folder", "local", "existing", "expected"),
    [
        (ORG, FOLDER_LOCAL, LOCAL, {ORG, FOLDER_LOCAL, LOCAL}, (ORG, True)),        # rule 1
        (ORG, FOLDER_LOCAL, LOCAL, {FOLDER_LOCAL, LOCAL}, (FOLDER_LOCAL, True)),    # rule 2
        (ORG, CLOUD, LOCAL, {CLOUD, LOCAL}, (LOCAL, True)),                          # rule 3
        (ORG, CLOUD, "", set(), (ORG, False)),                                       # rule 4
        ("", FOLDER_LOCAL, "", set(), (FOLDER_LOCAL, False)),                        # rule 5
        ("", CLOUD, "", {CLOUD}, (None, False)),                                     # rule 6
        ("", "", "", set(), (None, False)),                                          # rule 6
    ],
    ids=["1-org-exists", "2-folder-exists", "3-local-exists", "4-org-missing",
         "5-folder-missing", "6-cloud-only", "6-empty"],
)
def test_resolve_track_path_rules(org, folder, local, existing, expected):
    path, exists = resolve_track_path(org, folder, local, exists=lambda p: p in existing)
    expected_path, expected_exists = expected
    assert path == (os.path.normpath(expected_path) if expected_path else None)
    assert exists is expected_exists


def test_resolve_track_path_normalises_forward_slashes():
    path, _ = resolve_track_path("C:/Music/House/a.mp3", "", "", exists=lambda _p: True)
    assert path == os.path.normpath("C:/Music/House/a.mp3")
