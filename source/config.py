import logging
import os
import shutil
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from platformdirs import user_data_dir as _platform_user_data_dir

from source.services.harmonic_tier import HarmonicTier

# source/ package directory and project root (one level up)
SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SOURCE_DIR)

_APP_NAME = "DJSidecar"
# Data-dir names of earlier releases, newest first (T5.6). Their contents are
# copied forward once; the old folders are never modified or deleted.
_LEGACY_APP_NAMES = ("SeratoSidecar",)
_SETTINGS_FILENAME = "settings.env"
_SETTINGS_BACKUP_FILENAME = "settings.env.pre-schema2.bak"  # settings_migration's backup
_LIBRARY_DIRNAME = "library"  # library_store's snapshot folder
_LEGACY_CACHE_FILENAME = "track_cache.json"  # library_store's v3 cache
_COPY_PENDING_MARKER = ".copy-forward-pending"  # present while a copy is unfinished
# Set (to anything non-empty) to skip the copy-forward. The test suite sets it
# before importing this module, so tests can never copy the real user's data.
SKIP_DATA_DIR_MIGRATION_ENV = "SIDECAR_SKIP_DATA_DIR_MIGRATION"

_logger = logging.getLogger(__name__)
_data_dir_migration_done = False  # once per process


REPLACE_ATTEMPTS = 5
REPLACE_BACKOFF_SECONDS = 0.05


def replace_with_retry(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
    """``os.replace`` that retries Windows sharing violations (PermissionError).

    Antivirus scanners, backup tools or a reader holding the target open can
    briefly block a replace on Windows. Retries a few times with a short,
    growing backoff, then re-raises.
    """
    for attempt in range(1, REPLACE_ATTEMPTS + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS:
                raise
            time.sleep(REPLACE_BACKOFF_SECONDS * attempt)


def _platform_data_dir(app_name: str) -> Path:
    # appauthor=False suppresses the extra vendor-name folder level on Windows.
    # roaming=True selects %APPDATA% (Roaming) over %LOCALAPPDATA% on Windows;
    # no-op on macOS / Linux.
    return Path(_platform_user_data_dir(app_name, appauthor=False, roaming=True))


def user_data_dir() -> Path:
    """Return the platform-appropriate user data directory for this app.

    Creates the directory on first access and, once per process, copies an
    older release's data forward (see ``_migrate_legacy_data_dir``). Paths:
        Windows: %APPDATA%\\DJSidecar
        macOS:   ~/Library/Application Support/DJSidecar
        Linux:   ~/.local/share/DJSidecar  ($XDG_DATA_HOME)
    """
    return _resolve_user_data_dir()


def _resolve_user_data_dir() -> Path:
    """``user_data_dir``'s body (tests call this; the suite patches ``user_data_dir``)."""
    global _data_dir_migration_done
    path = _platform_data_dir(_APP_NAME)
    path.mkdir(parents=True, exist_ok=True)
    if not _data_dir_migration_done:
        _data_dir_migration_done = True
        if not os.environ.get(SKIP_DATA_DIR_MIGRATION_ENV):
            _migrate_legacy_data_dir(path)
    return path


def _migrate_legacy_data_dir(new: Path) -> None:
    """Copy settings and library data forward from an older data folder (T5.6).

    Runs when ``new`` has no ``settings.env`` yet, or when an earlier copy
    did not finish (the ``.copy-forward-pending`` marker is still there), and
    a legacy folder holds data: ``settings.env``, ``track_cache.json`` or
    ``library/`` (v0.1.6 only wrote ``settings.env`` once a setting was saved,
    so many installs have just the cache). Copies, never moves: an older
    install still finds its data. Never copies ``diagnostics/``.

    The marker is written before the first copy and removed only after the
    last step succeeds, so a failed copy is retried on the next start even if
    startup has since written a fresh ``settings.env`` (the retry replaces it
    with the legacy one). Errors are logged as a warning and never stop startup.
    """
    marker = new / _COPY_PENDING_MARKER
    if (new / _SETTINGS_FILENAME).exists() and not marker.exists():
        return
    legacy = next((d for d in map(_platform_data_dir, _LEGACY_APP_NAMES)
                   if d != new and _has_legacy_data(d)), None)
    if legacy is None:
        _remove_quietly(marker)  # nothing left to copy from: stop retrying
        return
    staged = new / (_SETTINGS_FILENAME + ".migrating")
    try:
        marker.touch()
        _copy_legacy_data(legacy, new, staged)
        marker.unlink()
    except OSError as e:
        _remove_quietly(staged)
        _logger.warning(
            "Could not copy data from the %s folder (%s); will retry on next start",
            legacy.name, type(e).__name__,
        )
    else:
        _logger.info("Copied settings and library data from the %s folder", legacy.name)


def copy_forward_pending() -> bool:
    """True while a copy from an older data folder has not finished (it retries next start).

    The older folder holds data, so this is an existing install: the settings
    migration treats it like one (Serato only, not fresh-install detection).
    """
    return (user_data_dir() / _COPY_PENDING_MARKER).exists()


def _has_legacy_data(folder: Path) -> bool:
    return (
        (folder / _SETTINGS_FILENAME).is_file()
        or (folder / _LEGACY_CACHE_FILENAME).is_file()
        or (folder / _LIBRARY_DIRNAME).is_dir()
    )


def _copy_legacy_data(legacy: Path, new: Path, staged: Path) -> None:
    """Copy library data, then the backup, then ``settings.env`` (via ``staged``)."""
    library = legacy / _LIBRARY_DIRNAME
    if library.is_dir():
        shutil.copytree(library, new / _LIBRARY_DIRNAME, dirs_exist_ok=True)
    elif (legacy / _LEGACY_CACHE_FILENAME).is_file():
        shutil.copy2(legacy / _LEGACY_CACHE_FILENAME, new / _LEGACY_CACHE_FILENAME)
    if (legacy / _SETTINGS_BACKUP_FILENAME).is_file():
        shutil.copy2(legacy / _SETTINGS_BACKUP_FILENAME, new / _SETTINGS_BACKUP_FILENAME)
    if (legacy / _SETTINGS_FILENAME).is_file():
        shutil.copy2(legacy / _SETTINGS_FILENAME, staged)
        replace_with_retry(staged, new / _SETTINGS_FILENAME)


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        _logger.debug("Could not remove %s (%s)", path.name, type(e).__name__)


# Computed after the copy-forward above, which runs inside user_data_dir().
ENV_FILE = user_data_dir() / "settings.env"


def _migrate_legacy_env() -> None:
    """One-time migration of the old project-root .env to user data dir.

    Silent no-op if there's nothing to migrate or the destination already exists.
    """
    legacy = Path(PROJECT_ROOT) / ".env"
    if not legacy.is_file() or ENV_FILE.exists():
        return
    try:
        legacy.replace(ENV_FILE)
    except OSError:
        # Non-fatal: a stale legacy file shouldn't prevent startup.
        pass


_migrate_legacy_env()


def _load_env() -> dict[str, str]:
    """Read settings env file into a dict. Returns empty dict if file doesn't exist."""
    env = {}
    if ENV_FILE.is_file():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def _write_env_atomic(env_file: Path, env: Mapping[str, str]) -> None:
    """Write ``env`` to ``env_file`` via a unique temp file + ``os.replace``.

    The previous file stays intact if anything fails, and the temp file is removed.
    """
    fd, tmp_name = tempfile.mkstemp(
        dir=env_file.parent, prefix=env_file.name + ".", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for key, value in sorted(env.items()):
                f.write(f"{key}={value}\n")
        replace_with_retry(tmp_name, env_file)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError as cleanup_error:
            _logger.debug("Could not remove %s: %s", tmp_name, cleanup_error)
        raise


def _save_env(env: Mapping[str, str]):
    """Write a dict back to the settings env file (atomically)."""
    _write_env_atomic(ENV_FILE, env)


def _save_user_env(env: Mapping[str, str]) -> None:
    """``_save_env`` for a user's own choices: they win over a pending copy-forward.

    Clears the ``.copy-forward-pending`` marker after the write, so a retry of
    an earlier failed copy never overwrites what the user saved since. The
    startup migration writes with ``_save_env`` and leaves the marker alone.
    """
    _save_env(env)
    marker = user_data_dir() / _COPY_PENDING_MARKER
    try:
        marker.unlink(missing_ok=True)
    except OSError as e:
        _logger.debug("Could not clear the copy-forward marker (%s)", type(e).__name__)


# ── Library provider settings (ADR-015 D7) ──
# Duck-typed so config never imports source.providers (no import cycle).

PROVIDERS_ENABLED_KEY = "PROVIDERS_ENABLED"
SETTINGS_SCHEMA_KEY = "SETTINGS_SCHEMA"
CURRENT_SETTINGS_SCHEMA = 2  # settings_migration.SETTINGS_SCHEMA mirrors this


class _SpecLike(Protocol):
    @property
    def key(self) -> str: ...

    @property
    def env_key(self) -> str: ...


def parse_provider_list(value: str) -> list[str]:
    """Split a comma-separated provider list: strip, drop empties, keep order."""
    return [part.strip() for part in value.split(",") if part.strip()]


def get_enabled_providers() -> list[str]:
    """Enabled provider ids in persisted (= merge precedence) order."""
    return parse_provider_list(_load_env().get(PROVIDERS_ENABLED_KEY, ""))


def save_enabled_providers(ids: Sequence[str]) -> None:
    """Persist enabled provider ids. Callers pass them in registry order.

    Also stamps the current settings schema, so a list the user saved is never
    recomputed by the in-memory migration fallback.
    """
    env = _load_env()
    env[PROVIDERS_ENABLED_KEY] = ",".join(ids)
    env[SETTINGS_SCHEMA_KEY] = str(CURRENT_SETTINGS_SCHEMA)
    _save_user_env(env)


def get_provider_settings(
    specs: Iterable[_SpecLike], defaults: Mapping[str, str],
) -> dict[str, str]:
    """Read each spec's ``env_key``, falling back to ``defaults[spec.key]``."""
    env = _load_env()
    return {
        spec.key: env.get(spec.env_key, defaults.get(spec.key, ""))
        for spec in specs
    }


def _clean_value(value: str) -> str:
    """One line only: a CR or LF would split ``settings.env`` into a forged key."""
    return value.replace("\r", "").replace("\n", "")


def save_library_settings(
    enabled_ids: Sequence[str],
    provider_values: Iterable[tuple[Iterable[_SpecLike], Mapping[str, str]]],
) -> None:
    """Persist the enabled list and every provider's values in ONE atomic write.

    The settings dialog's Save: either everything lands or nothing does.
    ``enabled_ids`` must already be in registry order. CR/LF are stripped.
    """
    env = _load_env()
    env[PROVIDERS_ENABLED_KEY] = ",".join(enabled_ids)
    env[SETTINGS_SCHEMA_KEY] = str(CURRENT_SETTINGS_SCHEMA)
    for specs, values in provider_values:
        for spec in specs:
            if spec.key in values:
                env[spec.env_key] = _clean_value(values[spec.key])
    _save_user_env(env)


def save_provider_settings(specs: Iterable[_SpecLike], values: Mapping[str, str]) -> None:
    """Persist the values whose keys appear in ``specs`` under their ``env_key``."""
    env = _load_env()
    for spec in specs:
        if spec.key in values:
            env[spec.env_key] = _clean_value(values[spec.key])
    _save_user_env(env)

SUGGESTION_WEIGHTS = {
    "key": 0.45,
    "energy": 0.35,
    "bpm": 0.20,
}

# Harmonic compatibility tier scores — see ADR-010.
# Non-monotonic by design: SEMITONE (wheel distance 5) outranks RELATED (distance 4).
HARMONIC_TIER_SCORES = {
    HarmonicTier.PERFECT:  1.0,
    HarmonicTier.ADJACENT: 0.8,
    HarmonicTier.RELATIVE: 0.7,
    HarmonicTier.DIAGONAL: 0.62,
    HarmonicTier.ENERGY:   0.57,
    HarmonicTier.SEMITONE: 0.47,
    HarmonicTier.RELATED:  0.37,
    HarmonicTier.NONE:     0.0,
}

BPM_MAX_DIFF = 20
ENERGY_SEVERE_PENALTY_THRESHOLD = 3
MAX_SUGGESTIONS = 60

KEY_OFFSET_RANGE = (-2, 2)  # inclusive min/max for the transition offset filter

# Live library refresh (ADR-015 D11). Defaults; tune against a real session.
REFRESH_POLL_SECONDS = 10          # how often the watcher stats each provider's change token
REFRESH_SETTLE_SECONDS = 5         # a new token must be stable this long (write burst over)
REFRESH_MIN_INTERVAL_SECONDS = 60  # at most one refresh per provider per this many seconds
REFRESH_MAX_INTERVAL_SECONDS = 300  # adaptive backoff ceiling after repeated no-change refreshes
# Refresh on window focus no sooner than this after the last request. 30 s, because an
# idle rekordbox changes its WAL about every 30 s: a shorter floor would let focus
# switching bypass the adaptive backoff.
REFRESH_FOCUS_FLOOR_SECONDS = 30

# Status colours (UI brief §5.7). Text always carries the meaning; colour supports it.
SUCCESS_COLOR = "#28a745"
WARNING_COLOR = "#ffc107"  # same hex as the score "usable" bucket; accepted overlap (brief §5.7)
ERROR_COLOR = "#dc3545"
INFO_COLOR = "#4AB8D4"
SECONDARY_TEXT_COLOR = "#999999"  # hints and secondary lines

# Track categories in the comment convention "4A - 7 - Banger - ..." (comment_format.py).
TRACK_CATEGORIES = ("Banger", "Driver", "Groover", "Filler", "Chiller", "Opener")

# Standard Camelot wheel colors — maps each key to a distinct hue
CAMELOT_COLORS = {
    "1A": "#E8637A", "1B": "#FF7A8F",
    "2A": "#E87C4A", "2B": "#FFB07A",
    "3A": "#E8A83A", "3B": "#FFD06B",
    "4A": "#D4C84A", "4B": "#E8DC5E",
    "5A": "#8FD45A", "5B": "#A3E86E",
    "6A": "#5AD47A", "6B": "#6EE88E",
    "7A": "#4AC8A8", "7B": "#5EDCBC",
    "8A": "#4AB8D4", "8B": "#5ECCE8",
    "9A": "#5A8FD4", "9B": "#6EA3E8",
    "10A": "#7A5AD4", "10B": "#8E6EE8",
    "11A": "#A84AD4", "11B": "#BC5EE8",
    "12A": "#D44A8F", "12B": "#E85EA3",
}


def energy_color(level: int) -> str:
    """Return a color for the energy level (1-8 scale). Cool→hot."""
    return {
        1: "#4AB8D4", 2: "#5ECCE8", 3: "#6BDB6B", 4: "#8FD45A",
        5: "#C8E650", 6: "#FFB732", 7: "#FF8C42", 8: "#FF5C5C",
    }.get(level, "#ffffff")
