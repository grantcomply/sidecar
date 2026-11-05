"""Fixtures for rekordbox provider tests: run without pyrekordbox installed."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from source.providers.rekordbox import db_reader


@pytest.fixture(autouse=True)
def _fake_pyrekordbox_loaded(monkeypatch):
    """Make db_reader behave as if pyrekordbox were imported (tests pass a fake factory).

    Real-import tests live in tests/services/test_log_safety.py and are skipped
    when pyrekordbox is missing.
    """
    monkeypatch.setattr(db_reader, "_pyrekordbox", SimpleNamespace(name="fake-pyrekordbox"))
    monkeypatch.setattr(db_reader, "_sql_text", lambda sql: sql)
