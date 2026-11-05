"""One-time settings and library migrations run at app startup (ADR-015 D7).

``migrate_settings`` is pure and idempotent. ``run_startup_migrations`` wires
it to the real settings file and converts a legacy v3 cache. Nothing is ever
deleted: existing keys are kept, the original settings file is backed up once
before its first migration write, and ``track_cache.json`` is only read.
A migration failure never stops startup, and never empties the library:
``effective_enabled_providers`` applies the migration in memory if the
settings file could not be updated.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from source import config
from source.providers.registry import all_providers
from source.services import library_store

logger = logging.getLogger(__name__)

SETTINGS_SCHEMA = config.CURRENT_SETTINGS_SCHEMA
_LEGACY_SERATO_KEY = "SERATO_SUBCRATES_DIR"
_BACKUP_SUFFIX = ".pre-schema2.bak"


def migrate_settings(
    env: Mapping[str, str],
    *,
    has_legacy_cache: bool,
    detected: Sequence[str],
) -> dict[str, str]:
    """Return a NEW settings dict at schema 2. Never mutates or drops keys. Idempotent.

    - Already at schema >= 2: unchanged copy.
    - Existing install (Serato folder set, or a legacy cache): enable Serato only.
    - Fresh install: enable whatever was detected, in the given (registry) order.
    """
    result = dict(env)
    if _schema_of(result) >= SETTINGS_SCHEMA:
        return result

    if result.get(_LEGACY_SERATO_KEY) or has_legacy_cache:
        result[config.PROVIDERS_ENABLED_KEY] = "serato"
    else:
        result[config.PROVIDERS_ENABLED_KEY] = ",".join(detected)
    result[config.SETTINGS_SCHEMA_KEY] = str(SETTINGS_SCHEMA)
    return result


def _schema_of(env: Mapping[str, str]) -> int:
    try:
        return int(env.get(config.SETTINGS_SCHEMA_KEY, "0") or "0")
    except ValueError:
        return 0


def _backup_once(env_file: Path) -> None:
    """Copy the settings file aside before its first migration write.

    Never overwrites an existing backup. Copies to a unique temp file first and
    moves it into place, so a half-written backup is never left behind.
    """
    backup = env_file.with_name(env_file.name + _BACKUP_SUFFIX)
    if not env_file.is_file() or backup.exists():
        return
    fd, tmp_name = tempfile.mkstemp(dir=env_file.parent, prefix=backup.name + ".", suffix=".tmp")
    os.close(fd)
    try:
        shutil.copy2(env_file, tmp_name)
        config.replace_with_retry(tmp_name, backup)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError as cleanup_error:
            logger.debug("Could not remove %s: %s", tmp_name, cleanup_error)
        raise
    logger.info("Backed up settings to %s", backup)


def _detected_provider_ids() -> list[str]:
    detected: list[str] = []
    for provider in all_providers():
        try:
            if provider.detect():
                detected.append(provider.id)
        except Exception:  # noqa: BLE001 - boundary: one provider's detect() must not stop startup
            logger.exception("Provider %s detection failed", provider.id)
    return detected


def _migrated(env: Mapping[str, str]) -> dict[str, str]:
    # An unfinished copy from the old data folder (T5.6) means an existing
    # install whose cache hasn't arrived yet: treat it like a legacy cache.
    return migrate_settings(
        env,
        has_legacy_cache=library_store.legacy_cache_exists() or config.copy_forward_pending(),
        detected=_detected_provider_ids(),
    )


def effective_enabled_providers() -> list[str]:
    """Enabled provider ids, applying the schema-2 migration in memory if needed.

    Normally the startup migration has persisted ``PROVIDERS_ENABLED``. If that
    write failed (e.g. a locked settings file), the stored file is still at
    schema < 2; computing the migration here keeps an existing user's library
    loading instead of silently showing nothing.
    """
    try:
        env = config._load_env()  # noqa: SLF001 - config's settings reader
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Could not read settings; using migration defaults: %s", e)
        env = {}
    if _schema_of(env) < SETTINGS_SCHEMA:
        env = _migrated(env)
    return config.parse_provider_list(env.get(config.PROVIDERS_ENABLED_KEY, ""))


def run_startup_migrations() -> None:
    """Migrate settings to schema 2 and convert a legacy v3 cache.

    Never raises ``OSError`` or ``UnicodeDecodeError``: startup must continue.
    """
    try:
        env = config._load_env()  # noqa: SLF001 - config's settings reader
        migrated = _migrated(env)
        if migrated != env:
            _backup_once(config.ENV_FILE)
            config._save_env(migrated)  # noqa: SLF001 - atomic settings writer
            logger.info(
                "Settings migrated to schema %d (providers: %r)",
                SETTINGS_SCHEMA, migrated.get(config.PROVIDERS_ENABLED_KEY),
            )
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Settings migration failed: %s", e)

    try:
        library_store.convert_legacy_cache_if_needed()
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Legacy cache conversion failed: %s", e)

    try:
        library_store.cleanup_orphan_temp_files()
    except OSError as e:
        logger.warning("Orphan temp cleanup failed: %s", e)
