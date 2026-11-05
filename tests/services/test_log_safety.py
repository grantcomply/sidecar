"""The rekordbox database key must never reach a log (ADR-015 D8, T3.5)."""

from __future__ import annotations

import importlib.util
import logging

import pytest

from source.services import log_safety
from tests.providers.rekordbox.fakes import SYNTHETIC_KEY

MINIMUMS = log_safety.SECRET_LOGGER_MINIMUMS
needs_pyrekordbox = pytest.mark.skipif(
    importlib.util.find_spec("pyrekordbox") is None, reason="pyrekordbox missing",
)


def _tree_loggers() -> list[tuple[logging.Logger, int]]:
    """Every existing pyrekordbox*/sqlalchemy* logger with its tree's minimum."""
    out = []
    for name, obj in list(logging.Logger.manager.loggerDict.items()):
        if not isinstance(obj, logging.Logger):
            continue
        for root, minimum in MINIMUMS.items():
            if name == root or name.startswith(root + "."):
                out.append((obj, minimum))
    return out


@pytest.fixture(autouse=True)
def _restore_levels():
    saved = {lg.name: lg.level for lg, _m in _tree_loggers()}
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)
    log_safety.silence_secret_loggers()


def test_minimums_are_error_for_pyrekordbox_and_warning_for_sqlalchemy():
    assert MINIMUMS == {"pyrekordbox": logging.ERROR, "sqlalchemy": logging.WARNING}


def test_silence_blocks_debug_on_child_loggers():
    logging.getLogger("pyrekordbox").setLevel(logging.NOTSET)
    logging.getLogger("sqlalchemy").setLevel(logging.DEBUG)

    log_safety.silence_secret_loggers()

    assert not logging.getLogger("pyrekordbox.db6.database").isEnabledFor(logging.WARNING)
    assert logging.getLogger("pyrekordbox.db6.database").isEnabledFor(logging.ERROR)
    assert not logging.getLogger("sqlalchemy.engine").isEnabledFor(logging.INFO)


def test_existing_descendant_with_low_explicit_level_is_raised():
    child = logging.getLogger("pyrekordbox.masterdb.database")
    child.setLevel(logging.DEBUG)
    engine = logging.getLogger("sqlalchemy.engine.Engine")
    engine.setLevel(logging.INFO)

    log_safety.silence_secret_loggers()

    assert child.level == logging.ERROR
    assert engine.level == logging.WARNING


def test_key_logged_at_debug_never_recorded_even_with_root_at_debug(caplog):
    logging.getLogger("pyrekordbox").setLevel(logging.NOTSET)
    logging.getLogger("pyrekordbox.x").setLevel(logging.DEBUG)
    log_safety.silence_secret_loggers()
    caplog.set_level(logging.DEBUG)  # root only

    logging.getLogger("pyrekordbox.x").debug("Key: %s", SYNTHETIC_KEY)
    logging.getLogger("pyrekordbox.x").warning("Rekordbox is running! %s", SYNTHETIC_KEY)
    logging.getLogger("sqlalchemy.engine").info("url pysqlcipher://:%s@/x", SYNTHETIC_KEY)

    assert SYNTHETIC_KEY not in caplog.text
    assert all(SYNTHETIC_KEY not in r.getMessage() for r in caplog.records)


def test_stricter_preset_level_is_not_lowered():
    logging.getLogger("pyrekordbox").setLevel(logging.CRITICAL)
    logging.getLogger("sqlalchemy").setLevel(logging.ERROR)
    logging.getLogger("pyrekordbox.strict").setLevel(logging.CRITICAL)

    log_safety.silence_secret_loggers()

    assert logging.getLogger("pyrekordbox").level == logging.CRITICAL
    assert logging.getLogger("sqlalchemy").level == logging.ERROR
    assert logging.getLogger("pyrekordbox.strict").level == logging.CRITICAL


@needs_pyrekordbox
def test_real_pyrekordbox_read_of_non_database_logs_nothing_below_minimums(
    tmp_path, caplog, monkeypatch,
):
    """Real pyrekordbox + SQLAlchemy, root at DEBUG: nothing below the minimums reaches a log."""
    from source.providers.base import ProviderError
    from source.providers.rekordbox import db_reader

    caplog.set_level(logging.DEBUG)  # root at DEBUG; restored afterwards by caplog
    fake_db = tmp_path / "master.db"
    fake_db.write_bytes(b"synthetic: not an SQLite database")
    monkeypatch.setattr(db_reader, "_pyrekordbox", None)  # force the real lazy import path

    with pytest.raises(ProviderError, match="^Couldn't read the database$"):
        db_reader.read_library(fake_db)

    for record in caplog.records:
        for root, minimum in MINIMUMS.items():
            if record.name == root or record.name.startswith(root + "."):
                assert record.levelno >= minimum, (record.name, record.levelname)
    for lg, minimum in _tree_loggers():
        assert lg.getEffectiveLevel() >= minimum, lg.name
    assert "Key:" not in caplog.text


@needs_pyrekordbox
def test_ensure_pyrekordbox_pins_loggers():
    from source.providers.rekordbox import db_reader

    logging.getLogger("pyrekordbox").setLevel(logging.DEBUG)
    db_reader._ensure_pyrekordbox()

    assert logging.getLogger("pyrekordbox").getEffectiveLevel() >= logging.ERROR
    assert logging.getLogger("sqlalchemy").getEffectiveLevel() >= logging.WARNING
