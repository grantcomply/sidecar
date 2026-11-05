"""Tests for ``source.services.settings_migration`` (ADR-015 D7).

The pure ``migrate_settings`` is table-driven. ``run_startup_migrations`` runs
against copies in ``tmp_path`` only (``isolated_data_dir``), never real files.
"""

from __future__ import annotations

import json

import pytest

from source import config
from source.services import library_merge, library_store, settings_migration
from source.services.settings_migration import migrate_settings


@pytest.mark.parametrize(
    ("env", "has_legacy_cache", "detected", "expected_enabled"),
    [
        ({"SERATO_SUBCRATES_DIR": "C:/S"}, False, [], "serato"),
        ({"SERATO_SUBCRATES_DIR": "C:/S"}, False, ["rekordbox", "serato"], "serato"),
        ({}, True, ["rekordbox"], "serato"),
        ({}, False, ["rekordbox", "serato"], "rekordbox,serato"),
        ({}, False, ["serato"], "serato"),
        ({}, False, [], ""),
        ({"SERATO_SUBCRATES_DIR": ""}, False, [], ""),
    ],
    ids=[
        "existing-user-folder-set",
        "existing-user-ignores-detection",
        "legacy-cache-only",
        "fresh-both-detected",
        "fresh-serato-detected",
        "fresh-nothing-detected",
        "blank-folder-is-not-set",
    ],
)
def test_migrate_settings_rules(env, has_legacy_cache, detected, expected_enabled):
    result = migrate_settings(env, has_legacy_cache=has_legacy_cache, detected=detected)

    assert result["PROVIDERS_ENABLED"] == expected_enabled
    assert result["SETTINGS_SCHEMA"] == "2"


def test_migrate_settings_schema2_returns_unchanged_copy():
    env = {"SETTINGS_SCHEMA": "2", "PROVIDERS_ENABLED": "", "SERATO_SUBCRATES_DIR": "C:/S"}

    result = migrate_settings(env, has_legacy_cache=True, detected=["serato"])

    assert result == env
    assert result is not env


def test_migrate_settings_is_idempotent():
    once = migrate_settings({"SERATO_SUBCRATES_DIR": "C:/S"}, has_legacy_cache=False, detected=[])
    twice = migrate_settings(once, has_legacy_cache=False, detected=["rekordbox"])

    assert twice == once


def test_migrate_settings_keeps_unknown_keys_and_does_not_mutate_input():
    env = {"CHECK_FOR_UPDATES": "false", "SERATO_SUBCRATES_DIR": "C:/S"}
    original = dict(env)

    result = migrate_settings(env, has_legacy_cache=False, detected=[])

    assert env == original
    assert result["CHECK_FOR_UPDATES"] == "false"
    assert result["SERATO_SUBCRATES_DIR"] == "C:/S"


def test_migrate_settings_garbage_schema_treated_as_unmigrated():
    result = migrate_settings({"SETTINGS_SCHEMA": "abc"}, has_legacy_cache=True, detected=[])
    assert result["SETTINGS_SCHEMA"] == "2"
    assert result["PROVIDERS_ENABLED"] == "serato"


# ── run_startup_migrations (tmp_path copies only) ──


def _write_legacy_cache(data_dir, tracks=None) -> bytes:
    payload = {
        "version": 3,
        "synced_at": "2026-01-01T00:00:00+00:00",
        "crate_mtimes": {"House%%Bangers.crate": 5.0},
        "tracks": tracks if tracks is not None else {
            "C:\\Music\\a.mp3": {"file_name": "a.mp3", "crates": ["House - Bangers"]},
        },
    }
    raw = json.dumps(payload, indent=2).encode("utf-8")
    (data_dir / "track_cache.json").write_bytes(raw)
    return raw


@pytest.fixture
def no_detection(monkeypatch):
    monkeypatch.setattr(settings_migration, "_detected_provider_ids", lambda: [])


def test_run_startup_existing_user_migrates_and_backs_up(isolated_data_dir, no_detection):
    env_file = isolated_data_dir / "settings.env"
    original = "# my comment\nSERATO_SUBCRATES_DIR=D:\\Serato\\Subcrates\nCHECK_FOR_UPDATES=false\n"
    env_file.write_text(original, encoding="utf-8")
    legacy_raw = _write_legacy_cache(isolated_data_dir)

    settings_migration.run_startup_migrations()

    text = env_file.read_text(encoding="utf-8")
    assert "PROVIDERS_ENABLED=serato\n" in text
    assert "SETTINGS_SCHEMA=2\n" in text
    assert "SERATO_SUBCRATES_DIR=D:\\Serato\\Subcrates\n" in text
    assert "CHECK_FOR_UPDATES=false\n" in text
    backup = isolated_data_dir / "settings.env.pre-schema2.bak"
    assert backup.read_text(encoding="utf-8") == original
    # Legacy cache untouched; snapshot created from it.
    assert (isolated_data_dir / "track_cache.json").read_bytes() == legacy_raw
    snapshot = library_store.load_snapshot("serato")
    assert snapshot is not None
    assert snapshot.tracks["C:\\Music\\a.mp3"].get("crates") == ["serato:House%%Bangers"]
    assert not list(isolated_data_dir.glob("*.tmp"))


def test_run_startup_second_run_changes_nothing(isolated_data_dir, no_detection):
    env_file = isolated_data_dir / "settings.env"
    env_file.write_text("SERATO_SUBCRATES_DIR=X\n", encoding="utf-8")
    settings_migration.run_startup_migrations()
    after_first = env_file.read_text(encoding="utf-8")
    backup = isolated_data_dir / "settings.env.pre-schema2.bak"
    backup_first = backup.read_text(encoding="utf-8")

    settings_migration.run_startup_migrations()

    assert env_file.read_text(encoding="utf-8") == after_first
    assert backup.read_text(encoding="utf-8") == backup_first == "SERATO_SUBCRATES_DIR=X\n"


def test_run_startup_fresh_install_without_settings_file(isolated_data_dir, monkeypatch):
    monkeypatch.setattr(settings_migration, "_detected_provider_ids", lambda: ["serato"])

    settings_migration.run_startup_migrations()

    text = (isolated_data_dir / "settings.env").read_text(encoding="utf-8")
    assert text == "PROVIDERS_ENABLED=serato\nSETTINGS_SCHEMA=2\n"
    assert not (isolated_data_dir / "settings.env.pre-schema2.bak").exists()
    assert library_store.load_snapshot("serato") is None


def _fail(*_a, **_k):
    raise PermissionError("denied")


def test_run_startup_write_failure_does_not_raise(isolated_data_dir, no_detection, monkeypatch):
    (isolated_data_dir / "settings.env").write_text("SERATO_SUBCRATES_DIR=X\n", encoding="utf-8")
    monkeypatch.setattr(config.os, "replace", _fail)
    monkeypatch.setattr(library_store, "convert_legacy_cache_if_needed", _fail)

    settings_migration.run_startup_migrations()  # must not raise

    assert (isolated_data_dir / "settings.env").read_text(encoding="utf-8") == (
        "SERATO_SUBCRATES_DIR=X\n"
    )
    leftovers = [p.name for p in isolated_data_dir.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_locked_settings_still_loads_existing_library(isolated_data_dir, no_detection, monkeypatch):
    # settings.env can't be written (e.g. locked), so PROVIDERS_ENABLED is never
    # persisted. The library must still load from the converted legacy cache.
    env_file = isolated_data_dir / "settings.env"
    env_file.write_text("SERATO_SUBCRATES_DIR=X\n", encoding="utf-8")
    _write_legacy_cache(isolated_data_dir)
    monkeypatch.setattr(config, "_write_env_atomic", _fail)

    settings_migration.run_startup_migrations()

    assert "PROVIDERS_ENABLED" not in env_file.read_text(encoding="utf-8")
    enabled = settings_migration.effective_enabled_providers()
    assert enabled == ["serato"]
    snapshots = [s for pid in enabled if (s := library_store.load_snapshot(pid))]
    tracks, _crates = library_merge.merge(snapshots)
    assert len(tracks) == 1


def test_effective_enabled_providers_uses_persisted_value_at_schema2(isolated_data_dir):
    (isolated_data_dir / "settings.env").write_text(
        "PROVIDERS_ENABLED=\nSETTINGS_SCHEMA=2\nSERATO_SUBCRATES_DIR=X\n", encoding="utf-8",
    )
    assert settings_migration.effective_enabled_providers() == []


def test_effective_enabled_providers_unreadable_settings_falls_back(
    isolated_data_dir, no_detection, monkeypatch,
):
    _write_legacy_cache(isolated_data_dir)
    monkeypatch.setattr(config, "_load_env", _fail)

    assert settings_migration.effective_enabled_providers() == ["serato"]


def test_detect_raising_any_exception_is_logged_and_skipped(monkeypatch, caplog):
    from source.providers.rekordbox.provider import RekordboxProvider
    from source.providers.serato.provider import SeratoProvider

    def _boom(self):
        raise RuntimeError("driver exploded")

    monkeypatch.setattr(SeratoProvider, "detect", _boom)
    monkeypatch.setattr(RekordboxProvider, "detect", lambda self: True)

    # Serato's failure doesn't stop rekordbox from being detected.
    assert settings_migration._detected_provider_ids() == ["rekordbox"]
    assert "serato" in caplog.text and "driver exploded" in caplog.text


def test_backup_failure_leaves_no_tmp_and_no_backup(isolated_data_dir, no_detection, monkeypatch):
    (isolated_data_dir / "settings.env").write_text("SERATO_SUBCRATES_DIR=X\n", encoding="utf-8")
    monkeypatch.setattr(settings_migration.shutil, "copy2", _fail)

    settings_migration.run_startup_migrations()

    names = sorted(p.name for p in isolated_data_dir.iterdir())
    assert names == ["settings.env"]
    assert (isolated_data_dir / "settings.env").read_text(encoding="utf-8") == (
        "SERATO_SUBCRATES_DIR=X\n"
    )


def test_detected_provider_ids_uses_registry_detect_in_registry_order(monkeypatch):
    from source.providers.rekordbox.provider import RekordboxProvider
    from source.providers.serato.provider import SeratoProvider

    monkeypatch.setattr(RekordboxProvider, "detect", lambda self: False)
    monkeypatch.setattr(SeratoProvider, "detect", lambda self: True)
    assert settings_migration._detected_provider_ids() == ["serato"]
    monkeypatch.setattr(RekordboxProvider, "detect", lambda self: True)
    assert settings_migration._detected_provider_ids() == ["rekordbox", "serato"]
    monkeypatch.setattr(SeratoProvider, "detect", lambda self: False)
    monkeypatch.setattr(RekordboxProvider, "detect", lambda self: False)
    assert settings_migration._detected_provider_ids() == []
