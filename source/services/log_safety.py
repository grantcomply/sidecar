"""Keep secret-bearing third-party loggers quiet (ADR-015 D8, key and log safety).

pyrekordbox 0.5.0 logs the rekordbox database key at DEBUG
(``logger.debug("Key: %s", key)``), and SQLAlchemy can log connection details,
which for SQLCipher include the key. Each logger tree is held at a minimum
level so nothing below it can reach any handler, whatever the root logger's
level is. pyrekordbox is held at ERROR, which also hides its per-open
"Rekordbox is running!" warning.

Leaf module: stdlib only. Lowering these levels, or logging exception text
from the rekordbox adapter, is a review blocker.
"""

from __future__ import annotations

import logging

# Minimum level per secret-bearing logger tree. Levels are only ever raised.
SECRET_LOGGER_MINIMUMS: dict[str, int] = {
    "pyrekordbox": logging.ERROR,
    "sqlalchemy": logging.WARNING,
}
SECRET_BEARING_LOGGERS = tuple(SECRET_LOGGER_MINIMUMS)


def _raise_to(logger: logging.Logger, minimum: int, *, set_if_notset: bool) -> None:
    if logger.level == logging.NOTSET:
        if set_if_notset:
            logger.setLevel(minimum)
    elif logger.level < minimum:
        logger.setLevel(minimum)


def silence_secret_loggers() -> None:
    """Hold pyrekordbox at ERROR and SQLAlchemy at WARNING, or stricter.

    The tree roots are set to their minimum if unset or lower. Any existing
    descendant (``pyrekordbox.*``, ``sqlalchemy.*``) with an explicit level
    below the minimum is raised too; unset descendants inherit from the root
    of their tree. A stricter preset level is never lowered.
    """
    manager = logging.Logger.manager
    for name, minimum in SECRET_LOGGER_MINIMUMS.items():
        _raise_to(logging.getLogger(name), minimum, set_if_notset=True)
        prefix = name + "."
        for child_name, child in list(manager.loggerDict.items()):
            if child_name.startswith(prefix) and isinstance(child, logging.Logger):
                _raise_to(child, minimum, set_if_notset=False)
