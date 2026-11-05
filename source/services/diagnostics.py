"""Built-in rekordbox diagnostics for CI and the rekordbox upgrade runbook (T3.12).

``--self-check-rekordbox``: the frozen build can import pyrekordbox and its
native SQLCipher module (no DB access; CI-safe).
``--check-rekordbox-library``: scans the user's library (private copy, nothing
saved) and writes a counts-only report. The report never contains track
titles, artists, track paths or the database key.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from source import config
from source.providers.base import ProviderError, ProviderSnapshot
from source.providers.registry import get_provider
# Accepted layering deviation (Phase 3a review): this tool is rekordbox-specific,
# so it uses the provider's own path rules to report the DB location.
from source.providers.rekordbox.paths import TOKEN_FILES, resolve_db_path
from source.services.comment_format import parse_comment
from source.services.log_safety import silence_secret_loggers

logger = logging.getLogger(__name__)

PROVIDER_ID = "rekordbox"
_PACKAGES = ("pyrekordbox", "sqlcipher3-wheels", "SQLAlchemy", "psutil")
_SELF_CHECK_MODULES = ("pyrekordbox", "sqlcipher3", "sqlalchemy.dialects.sqlite")


def _sqlcipher_works() -> bool:
    """The native SQLCipher library loads and answers in an in-memory database."""
    dbapi2 = importlib.import_module("sqlcipher3.dbapi2")
    conn = dbapi2.connect(":memory:")
    try:
        row = conn.execute("PRAGMA cipher_version").fetchone()
    finally:
        conn.close()
    return bool(row and row[0])


def self_check_rekordbox() -> int:
    """0 if pyrekordbox, sqlcipher3 and the SQLite dialect import and SQLCipher works.

    No access to any rekordbox file (CI-safe). Failures print a type name only.
    """
    silence_secret_loggers()
    step = "import"
    try:
        for name in _SELF_CHECK_MODULES:
            step = f"importing {name}"
            importlib.import_module(name)
        step = "SQLCipher cipher_version"
        if not _sqlcipher_works():
            print(f"rekordbox self-check FAILED: {step} returned nothing")
            return 1
    except Exception as e:  # noqa: BLE001 - CI boundary; type name only (key safety)
        print(f"rekordbox self-check FAILED: {type(e).__name__} ({step})")
        return 1
    finally:
        silence_secret_loggers()
    print("rekordbox self-check OK")
    return 0


def _package_versions() -> list[str]:
    lines = []
    for name in _PACKAGES:
        try:
            lines.append(f"  {name}: {importlib.metadata.version(name)}")
        except importlib.metadata.PackageNotFoundError:
            lines.append(f"  {name}: not installed")
    return lines


def display_path(path: Path | None) -> str:
    """Show the home folder as ``~`` so reports don't carry the user's name."""
    if path is None:
        return "not found"
    try:
        return str(Path("~") / path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def _db_lines(settings: dict[str, str]) -> list[str]:
    db_path = resolve_db_path(settings)
    source = "settings" if settings.get("db_path") else "auto-detected"
    lines = [f"Database ({source}): {display_path(db_path)}"]
    if db_path is not None:
        for name in TOKEN_FILES + ("master.db-shm",):
            p = db_path.parent / name
            try:
                st = p.stat()
                stamp = datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
                lines.append(f"  {name}: {st.st_size:,} bytes, modified {stamp}")
            except OSError:
                lines.append(f"  {name}: absent")
    return lines


def summarise_snapshot(snapshot: ProviderSnapshot) -> list[str]:
    """Counts only: never titles, artists, paths or keys."""
    tracks = list(snapshot.tracks.values())
    used_crates = {c for t in tracks for c in t.get("crates", [])}
    with_key = sum(1 for t in tracks if t.get("camelot_key"))
    comment_energy = sum(1 for t in tracks if parse_comment(t.get("comments", "")).energy)
    any_energy = sum(1 for t in tracks if t.get("energy_level", 0))
    exists = sum(1 for t in tracks if os.path.exists(t.get("full_file_path", "")))
    lines = [
        f"Tracks in scope (in at least one playlist): {len(tracks)}",
        f"Playlists: {len(snapshot.crates)} (with tracks: {len(used_crates)})",
        f"Tracks with a Camelot key: {with_key}; without: {len(tracks) - with_key}",
        f"Tracks with energy > 0: {any_energy} "
        f"(from comment: {comment_energy}, from file tag: {any_energy - comment_energy}); "
        f"no energy: {len(tracks) - any_energy}",
        f"Tracks whose file exists: {exists}/{len(tracks)}",
        "Warnings:" if snapshot.warnings else "Warnings: none",
    ]
    lines += [f"  - {w}" for w in snapshot.warnings]
    return lines


def _write_report(lines: list[str]) -> Path | None:
    folder = config.user_data_dir() / "diagnostics"
    target = folder / f"rekordbox-check-{datetime.now():%Y%m%d-%H%M%S}.txt"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as e:
        print(f"(could not write the report file: {type(e).__name__})")
        return None
    return target


def check_rekordbox_library() -> int:
    """Scan the rekordbox library without saving anything; report counts. 0 = OK, 1 = failed."""
    silence_secret_loggers()
    provider = get_provider(PROVIDER_ID)
    settings = config.get_provider_settings(provider.setting_specs(), provider.default_settings())
    lines = [
        f"Sidecar rekordbox library check, {datetime.now().isoformat(timespec='seconds')}",
        f"Python {sys.version.split()[0]} on {sys.platform}",
        "Packages:",
        *_package_versions(),
        *_db_lines(settings),
    ]
    status = 0
    errors = [i for i in provider.validate(settings) if i.severity == "error"]
    if errors:
        lines += [f"FAILED: {i.message}" for i in errors]
        status = 1
    else:
        started = time.perf_counter()
        try:
            snapshot = provider.scan(settings)
        except ProviderError as e:
            lines.append(f"FAILED: {e}")
            status = 1
        except Exception as e:  # noqa: BLE001 - tool boundary; type name only (key safety)
            logger.warning("rekordbox check failed unexpectedly (%s)", type(e).__name__)
            lines.append(f"FAILED: unexpected error ({type(e).__name__})")
            status = 1
        else:
            lines.append(f"Read time: {time.perf_counter() - started:.2f}s (snapshot not saved)")
            lines += summarise_snapshot(snapshot)
    lines.append("RESULT: OK" if status == 0 else "RESULT: FAILED")
    report = _write_report(lines)
    print("\n".join(lines))
    if report is not None:
        print(f"Report written to {display_path(report)}")
    return status
