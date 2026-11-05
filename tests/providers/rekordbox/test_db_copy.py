"""Tests for the private-copy routine (rekordbox's folder is only ever read)."""

from __future__ import annotations

import os
import time

import pytest

from source.providers.base import ProviderError
from source.providers.rekordbox import db_copy
from source.providers.rekordbox.paths import compute_change_token


@pytest.fixture
def rb_dir(tmp_path):
    folder = tmp_path / "rekordbox"
    folder.mkdir()
    for name, data in [
        ("master.db", b"db"), ("master.db-wal", b"wal"), ("master.db-journal", b"j"),
        ("master.db-shm", b"shm"), ("masterPlaylists6.xml", b"<xml/>"), ("other.db", b"x"),
    ]:
        (folder / name).write_bytes(data)
    return folder


@pytest.fixture
def tmp_root(tmp_path):
    root = tmp_path / "temp"
    root.mkdir()
    return root


def _stats(folder):
    return {p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in folder.iterdir()}


def test_copies_db_wal_journal_xml_but_never_shm(rb_dir, tmp_root):
    before = _stats(rb_dir)

    with db_copy.private_copy(
        rb_dir / "master.db", token_fn=compute_change_token, tmp_root=tmp_root,
    ) as copy:
        copied = sorted(p.name for p in copy.parent.iterdir())
        assert copy.name == "master.db" and copy.read_bytes() == b"db"
        assert copy.parent.parent == tmp_root

    assert copied == ["master.db", "master.db-journal", "master.db-wal", "masterPlaylists6.xml"]
    assert _stats(rb_dir) == before  # sources untouched
    assert list(tmp_root.iterdir()) == []  # copy removed


def test_token_change_on_first_attempt_retries(rb_dir, tmp_root):
    calls = {"n": 0}

    def token(_path):
        calls["n"] += 1
        return "moved" if calls["n"] == 2 else "stable"  # 2nd call = after 1st copy

    with db_copy.private_copy(rb_dir / "master.db", token_fn=token, delay_s=0, tmp_root=tmp_root):
        pass

    assert calls["n"] == 4
    assert list(tmp_root.iterdir()) == []


def test_always_changing_token_raises_busy_and_leaves_nothing(rb_dir, tmp_root):
    counter = iter(range(100))

    with pytest.raises(ProviderError, match="busy"):
        with db_copy.private_copy(
            rb_dir / "master.db", token_fn=lambda _p: str(next(counter)),
            delay_s=0, tmp_root=tmp_root,
        ):
            pass

    assert list(tmp_root.iterdir()) == []


def test_copy_oserror_retried_then_busy(rb_dir, tmp_root, monkeypatch):
    def _locked(*_a, **_k):
        raise PermissionError("sharing violation")

    monkeypatch.setattr(db_copy.shutil, "copyfile", _locked)

    with pytest.raises(ProviderError, match="busy"):
        with db_copy.private_copy(
            rb_dir / "master.db", token_fn=compute_change_token, delay_s=0, tmp_root=tmp_root,
        ):
            pass
    assert list(tmp_root.iterdir()) == []


def test_missing_db_raises_not_found(tmp_path, tmp_root):
    with pytest.raises(ProviderError, match="^Database not found$"):
        with db_copy.private_copy(
            tmp_path / "nope" / "master.db", token_fn=compute_change_token, tmp_root=tmp_root,
        ):
            pass


def test_copy_removed_even_when_block_raises(rb_dir, tmp_root):
    with pytest.raises(RuntimeError):
        with db_copy.private_copy(
            rb_dir / "master.db", token_fn=compute_change_token, tmp_root=tmp_root,
        ):
            raise RuntimeError("reader failed")
    assert list(tmp_root.iterdir()) == []


def test_cleanup_stale_copies_removes_only_old_prefixed_folders(tmp_root):
    old_copy = tmp_root / "sidecar-rb-old"
    new_copy = tmp_root / "sidecar-rb-new"
    other = tmp_root / "someone-else"
    for folder in (old_copy, new_copy, other):
        folder.mkdir()
        (folder / "f").write_bytes(b"x")
    old = time.time() - 7200
    os.utime(old_copy, (old, old))
    os.utime(other, (old, old))

    db_copy.cleanup_stale_copies(tmp_root=tmp_root, max_age_s=3600)

    assert sorted(p.name for p in tmp_root.iterdir()) == ["sidecar-rb-new", "someone-else"]


def test_other_database_name_is_never_copied(rb_dir, tmp_root):
    backup = rb_dir / "master.backup.db"
    backup.write_bytes(b"old")

    with pytest.raises(ProviderError, match="^Choose the file named master.db$"):
        with db_copy.private_copy(backup, token_fn=compute_change_token, tmp_root=tmp_root):
            pass
    assert list(tmp_root.iterdir()) == []


def test_after_token_raising_removes_candidate(rb_dir, tmp_root):
    calls = {"n": 0}

    def token(_path):
        calls["n"] += 1
        if calls["n"] == 2:
            raise PermissionError("stat failed")
        return "t"

    with pytest.raises(PermissionError):
        with db_copy.private_copy(rb_dir / "master.db", token_fn=token, tmp_root=tmp_root):
            pass
    assert list(tmp_root.iterdir()) == []


def test_interrupt_during_copy_removes_partial_copy(rb_dir, tmp_root, monkeypatch):
    real_copy = db_copy.shutil.copyfile
    calls = {"n": 0}

    def copy_then_interrupt(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt
        return real_copy(src, dst)

    monkeypatch.setattr(db_copy.shutil, "copyfile", copy_then_interrupt)

    with pytest.raises(KeyboardInterrupt):
        with db_copy.private_copy(
            rb_dir / "master.db", token_fn=compute_change_token, tmp_root=tmp_root,
        ):
            pass
    assert list(tmp_root.iterdir()) == []
