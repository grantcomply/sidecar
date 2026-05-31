"""Unit tests for ``source.services.file_times.file_creation_time``.

The platform-branching fallback chain (ADR-013) is exercised by mocking
``os.stat`` (to return a stub stat object) and ``sys.platform``, so no real
files or platform are needed. Each branch of the chain is locked by an explicit
case — in particular the Windows-on-Python-3.11 ``st_ctime`` branch, so it can't
silently regress when the bundled interpreter later moves to 3.12 (where
``st_birthtime`` appears on Windows and takes precedence).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from source.services import file_times


def _stat_stub(*, birthtime=None, ctime=0.0, mtime=0.0):
    """Build a stub stat object.

    ``birthtime=None`` omits the ``st_birthtime`` attribute entirely (simulating
    Windows on Python 3.11, where CPython does not expose it). Any other value is
    set as ``st_birthtime``.
    """
    fields = {"st_ctime": ctime, "st_mtime": mtime}
    if birthtime is not None:
        fields["st_birthtime"] = birthtime
    return SimpleNamespace(**fields)


def test_birthtime_present_returns_birthtime_any_platform(monkeypatch):
    """macOS-style stat (st_birthtime > 0) wins regardless of platform string."""
    monkeypatch.setattr(file_times.sys, "platform", "darwin")
    monkeypatch.setattr(
        file_times.os, "stat",
        lambda _p: _stat_stub(birthtime=1_600_000_000.0, ctime=111.0, mtime=222.0),
    )
    assert file_times.file_creation_time("song.mp3") == 1_600_000_000.0


def test_birthtime_zero_falls_through(monkeypatch):
    """st_birthtime == 0 ("unknown birth") is a miss — does NOT return 0."""
    monkeypatch.setattr(file_times.sys, "platform", "linux")
    monkeypatch.setattr(
        file_times.os, "stat",
        lambda _p: _stat_stub(birthtime=0.0, ctime=111.0, mtime=222.0),
    )
    # Linux fall-through → st_mtime, not the zero birthtime.
    assert file_times.file_creation_time("song.mp3") == 222.0


def test_windows_python_311_returns_ctime(monkeypatch):
    """Windows with no st_birthtime (Python 3.11 sim) → st_ctime is creation time.

    Locks the load-bearing Windows-3.11 branch so a future interpreter bump can't
    silently regress it.
    """
    monkeypatch.setattr(file_times.sys, "platform", "win32")
    monkeypatch.setattr(
        file_times.os, "stat",
        lambda _p: _stat_stub(birthtime=None, ctime=1_650_000_000.0, mtime=222.0),
    )
    assert file_times.file_creation_time("song.mp3") == 1_650_000_000.0


def test_windows_python_312_prefers_birthtime(monkeypatch):
    """Windows on Python 3.12+ (st_birthtime > 0) prefers birthtime over ctime."""
    monkeypatch.setattr(file_times.sys, "platform", "win32")
    monkeypatch.setattr(
        file_times.os, "stat",
        lambda _p: _stat_stub(birthtime=1_600_000_000.0, ctime=1_650_000_000.0),
    )
    assert file_times.file_creation_time("song.mp3") == 1_600_000_000.0


def test_linux_falls_back_to_mtime(monkeypatch):
    """Linux with no usable st_birthtime → st_mtime (best available, dev-only)."""
    monkeypatch.setattr(file_times.sys, "platform", "linux")
    monkeypatch.setattr(
        file_times.os, "stat",
        lambda _p: _stat_stub(birthtime=None, ctime=111.0, mtime=1_700_000_000.0),
    )
    assert file_times.file_creation_time("song.mp3") == 1_700_000_000.0


def test_oserror_returns_none(monkeypatch):
    """A failed stat (OSError) returns None — distinct from 0.0 ("unknown")."""
    def _raise(_p):
        raise OSError("no such file")

    monkeypatch.setattr(file_times.os, "stat", _raise)
    assert file_times.file_creation_time("missing.mp3") is None
