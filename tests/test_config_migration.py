"""Data-dir rename ``SeratoSidecar`` -> ``DJSidecar`` with copy-forward (T5.6).

Every test points ``platformdirs`` at per-name folders under ``tmp_path``;
nothing here can reach the real user data folder.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from source import config
from source.providers.base import SettingKind, SettingSpec
from source.services import library_store, settings_migration

MARKER = ".copy-forward-pending"
_V3_CACHE = {
    "version": 3,
    "synced_at": "2026-09-19T10:00:00Z",
    "crate_mtimes": {"House.crate": 1.0},
    "tracks": {"/music/a.mp3": {"file_name": "a.mp3", "title": "A", "crates": ["House"]}},
}


@pytest.fixture
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """``(legacy, new)`` data folders; platformdirs resolves names under ``tmp_path``."""
    root = tmp_path / "appdata"

    def fake_platform_dir(name: str, appauthor=None, roaming=False) -> str:
        assert appauthor is False and roaming is True
        return str(root / name)

    monkeypatch.setattr(config, "_platform_user_data_dir", fake_platform_dir)
    monkeypatch.setattr(config, "_data_dir_migration_done", False)
    monkeypatch.delenv(config.SKIP_DATA_DIR_MIGRATION_ENV, raising=False)
    return root / "SeratoSidecar", root / "DJSidecar"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _legacy_install(legacy: Path, *, library: bool = True, cache: bool = False,
                    settings: bool = True) -> None:
    if settings:
        _write(legacy / "settings.env", "SERATO_SUBCRATES_DIR=/x\n")
        _write(legacy / "settings.env.pre-schema2.bak", "OLD=1\n")
    _write(legacy / "diagnostics" / "report.txt", "diag")
    if library:
        _write(legacy / "library" / "serato.json", '{"schema": 4}')
        _write(legacy / "library" / "nested" / "x.json", "{}")
    if cache:
        _write(legacy / "track_cache.json", json.dumps(_V3_CACHE))


def _snapshot(folder: Path) -> dict[str, str]:
    return {
        p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(folder.rglob("*")) if p.is_file()
    }


def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _new_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate the next app start (the copy-forward runs once per process)."""
    monkeypatch.setattr(config, "_data_dir_migration_done", False)


def _point_config_at(new: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the settings/library code use ``new``, as ``ENV_FILE`` would in the app."""
    monkeypatch.setattr(config, "user_data_dir", lambda: new)
    monkeypatch.setattr(config, "ENV_FILE", new / "settings.env")
    monkeypatch.setattr(config, "PROJECT_ROOT", str(_mkdir(tmp_path / "project")))
    # A fresh install would auto-enable whatever is detected: make both "detected".
    monkeypatch.setattr(settings_migration, "_detected_provider_ids",
                        lambda: ["rekordbox", "serato"])


def test_app_name_and_legacy_names():
    assert config._APP_NAME == "DJSidecar"
    assert config._LEGACY_APP_NAMES == ("SeratoSidecar",)


def test_copy_happens_on_first_resolve(dirs):
    legacy, new = dirs
    _legacy_install(legacy)

    assert config._resolve_user_data_dir() == new

    assert (new / "settings.env").read_text(encoding="utf-8") == "SERATO_SUBCRATES_DIR=/x\n"
    assert (new / "settings.env.pre-schema2.bak").read_text(encoding="utf-8") == "OLD=1\n"
    assert (new / "library" / "serato.json").read_text(encoding="utf-8") == '{"schema": 4}'
    assert (new / "library" / "nested" / "x.json").is_file()
    assert not (new / "diagnostics").exists()
    assert not (new / "settings.env.migrating").exists()
    assert not (new / MARKER).exists()  # finished copy: no retry next start


def test_legacy_folder_is_left_intact(dirs):
    legacy, new = dirs
    _legacy_install(legacy, cache=True)
    before = _snapshot(legacy)

    config._migrate_legacy_data_dir(_mkdir(new))

    assert _snapshot(legacy) == before


def test_legacy_cache_copied_only_without_library_folder(dirs):
    legacy, new = dirs
    _legacy_install(legacy, library=False, cache=True)

    config._migrate_legacy_data_dir(_mkdir(new))

    assert json.loads((new / "track_cache.json").read_text(encoding="utf-8")) == _V3_CACHE
    assert not (new / "library").exists()


def test_legacy_cache_not_copied_when_library_exists(dirs):
    legacy, new = dirs
    _legacy_install(legacy, library=True, cache=True)

    config._migrate_legacy_data_dir(_mkdir(new))

    assert (new / "library" / "serato.json").is_file()
    assert not (new / "track_cache.json").exists()


@pytest.mark.parametrize("what", ["cache", "library"])
def test_legacy_folder_without_settings_is_still_copied(dirs, what):
    # v0.1.6 wrote settings.env only once a setting was saved.
    legacy, new = dirs
    _legacy_install(legacy, settings=False, library=what == "library", cache=what == "cache")

    config._migrate_legacy_data_dir(_mkdir(new))

    assert not (new / "settings.env").exists()
    assert (new / "track_cache.json").is_file() or (new / "library" / "serato.json").is_file()
    assert not (new / MARKER).exists()


def test_legacy_folder_with_only_diagnostics_is_ignored(dirs):
    legacy, new = dirs
    _write(legacy / "diagnostics" / "report.txt", "diag")

    config._migrate_legacy_data_dir(_mkdir(new))

    assert _snapshot(new) == {}


def test_no_copy_when_new_folder_already_has_settings(dirs):
    legacy, new = dirs
    _legacy_install(legacy)
    _write(new / "settings.env", "PROVIDERS_ENABLED=rekordbox\n")

    config._migrate_legacy_data_dir(new)

    assert _snapshot(new) == {"settings.env": "PROVIDERS_ENABLED=rekordbox\n"}


def test_idempotent(dirs):
    legacy, new = dirs
    _legacy_install(legacy)
    config._migrate_legacy_data_dir(_mkdir(new))
    _write(new / "settings.env", "PROVIDERS_ENABLED=rekordbox\n")  # user changed it since
    (new / "library" / "serato.json").unlink()
    after_first = _snapshot(new)

    config._migrate_legacy_data_dir(new)

    assert _snapshot(new) == after_first


def test_no_legacy_folder_is_a_no_op(dirs):
    _legacy, new = dirs

    config._migrate_legacy_data_dir(_mkdir(new))

    assert _snapshot(new) == {}
    assert not (new / MARKER).exists()


def test_runs_once_per_process(dirs, monkeypatch):
    calls: list[Path] = []
    monkeypatch.setattr(config, "_migrate_legacy_data_dir", calls.append)

    config._resolve_user_data_dir()
    config._resolve_user_data_dir()

    assert calls == [dirs[1]]


def test_skip_env_var_disables_the_copy(dirs, monkeypatch):
    legacy, new = dirs
    _legacy_install(legacy)
    monkeypatch.setenv(config.SKIP_DATA_DIR_MIGRATION_ENV, "1")

    assert config._resolve_user_data_dir() == new
    assert not (new / "settings.env").exists()


def test_os_error_logs_a_warning_keeps_the_marker_and_does_not_raise(dirs, monkeypatch, caplog):
    legacy, new = dirs
    _legacy_install(legacy, library=False)

    def denied(*_args, **_kwargs):
        raise PermissionError(13, "denied", str(legacy / "settings.env"))

    monkeypatch.setattr(config.shutil, "copy2", denied)
    with caplog.at_level(logging.WARNING, logger=config.__name__):
        assert config._resolve_user_data_dir() == new

    assert not (new / "settings.env").exists()
    assert (new / MARKER).exists()  # retried on the next start
    assert any(r.levelno == logging.WARNING and "PermissionError" in r.getMessage()
               for r in caplog.records)
    assert not any(str(legacy) in r.getMessage() for r in caplog.records)


def test_failed_final_replace_removes_the_staged_temp(dirs, monkeypatch):
    legacy, new = dirs
    _legacy_install(legacy, library=False)

    def busy(_src, _dst):
        raise PermissionError(13, "busy")

    monkeypatch.setattr(config, "replace_with_retry", busy)
    config._migrate_legacy_data_dir(_mkdir(new))

    assert not (new / "settings.env.migrating").exists()
    assert not (new / "settings.env").exists()
    assert (new / MARKER).exists()


def test_failed_copy_is_retried_after_startup_wrote_fresh_settings(
    dirs, tmp_path, monkeypatch,
):
    legacy, new = dirs
    _legacy_install(legacy, library=False)
    real_copy2 = config.shutil.copy2

    def denied(*_args, **_kwargs):
        raise PermissionError(13, "denied")

    # Start 1: the copy fails, then startup migrations write settings.env anyway.
    monkeypatch.setattr(config.shutil, "copy2", denied)
    config._resolve_user_data_dir()
    _point_config_at(new, tmp_path, monkeypatch)
    settings_migration.run_startup_migrations()
    assert (new / "settings.env").is_file() and (new / MARKER).exists()

    # Start 2: the marker forces a retry; the legacy settings replace the auto-written ones.
    monkeypatch.setattr(config.shutil, "copy2", real_copy2)
    _new_process(monkeypatch)
    config._resolve_user_data_dir()

    assert (new / "settings.env").read_text(encoding="utf-8") == "SERATO_SUBCRATES_DIR=/x\n"
    assert (new / "settings.env.pre-schema2.bak").read_text(encoding="utf-8") == "OLD=1\n"
    assert not (new / MARKER).exists()


def test_cache_only_install_becomes_serato_only_without_resync(dirs, tmp_path, monkeypatch):
    """v0.1.6 user who never saved a setting: existing install, not a fresh one."""
    legacy, new = dirs
    _legacy_install(legacy, settings=False, library=False, cache=True)

    config._resolve_user_data_dir()
    _point_config_at(new, tmp_path, monkeypatch)

    env = config._load_env()
    assert env == {}
    migrated = settings_migration.migrate_settings(
        env, has_legacy_cache=library_store.legacy_cache_exists(),
        detected=["rekordbox", "serato"],
    )
    assert migrated[config.PROVIDERS_ENABLED_KEY] == "serato"

    settings_migration.run_startup_migrations()  # the real startup path, end to end

    assert config._load_env()[config.PROVIDERS_ENABLED_KEY] == "serato"
    assert library_store.load_snapshot("serato") is not None  # converted: no re-sync
    assert settings_migration.effective_enabled_providers() == ["serato"]


def test_unfinished_copy_counts_as_an_existing_install(dirs, tmp_path, monkeypatch):
    """Cache-only copy failed: startup must not auto-enable rekordbox meanwhile."""
    legacy, new = dirs
    _legacy_install(legacy, settings=False, library=False, cache=True)
    real_copy2 = config.shutil.copy2

    def denied(*_args, **_kwargs):
        raise PermissionError(13, "denied")

    monkeypatch.setattr(config.shutil, "copy2", denied)
    config._resolve_user_data_dir()
    _point_config_at(new, tmp_path, monkeypatch)
    assert config.copy_forward_pending()

    settings_migration.run_startup_migrations()
    assert config._load_env()[config.PROVIDERS_ENABLED_KEY] == "serato"

    # Next start: the retry brings the cache over and it converts.
    monkeypatch.setattr(config.shutil, "copy2", real_copy2)
    _new_process(monkeypatch)
    config._resolve_user_data_dir()
    settings_migration.run_startup_migrations()
    assert not config.copy_forward_pending()
    assert library_store.load_snapshot("serato") is not None


def test_test_suite_never_migrates_real_user_data():
    """conftest sets the skip variable before ``source.config`` is imported."""
    assert os.environ.get(config.SKIP_DATA_DIR_MIGRATION_ENV)
    real = config._platform_data_dir(config._APP_NAME)
    assert config.user_data_dir() != real  # session-wide redirect still in place
    assert config.ENV_FILE.parent != real


@pytest.mark.parametrize("save", ["library", "provider", "enabled"])
def test_user_save_after_a_failed_copy_wins_over_the_retry(dirs, tmp_path, monkeypatch, save):
    legacy, new = dirs
    _legacy_install(legacy, library=False)
    real_copy2 = config.shutil.copy2

    def denied(*_args, **_kwargs):
        raise PermissionError(13, "denied")

    # Start 1: copy fails; startup's own migration write keeps the marker.
    monkeypatch.setattr(config.shutil, "copy2", denied)
    config._resolve_user_data_dir()
    _point_config_at(new, tmp_path, monkeypatch)
    settings_migration.run_startup_migrations()
    assert (new / MARKER).exists()

    # The user saves in Settings: their choice wins, the marker goes.
    spec = SettingSpec("db_path", "REKORDBOX_DB_PATH", "Database", SettingKind.FILE)
    if save == "library":
        config.save_library_settings(["rekordbox"], [([spec], {"db_path": "D:/x/master.db"})])
    elif save == "provider":
        config.save_enabled_providers(["rekordbox"])
        config.save_provider_settings([spec], {"db_path": "D:/x/master.db"})
    else:
        config.save_enabled_providers(["rekordbox"])
    assert not (new / MARKER).exists()
    saved = (new / "settings.env").read_text(encoding="utf-8")

    # Start 2: no retry, nothing overwritten.
    monkeypatch.setattr(config.shutil, "copy2", real_copy2)
    _new_process(monkeypatch)
    config._resolve_user_data_dir()

    assert (new / "settings.env").read_text(encoding="utf-8") == saved
    assert "PROVIDERS_ENABLED=rekordbox" in saved
    assert "SERATO_SUBCRATES_DIR" not in saved


def test_user_save_ignores_a_marker_it_cannot_remove(dirs, tmp_path, monkeypatch, caplog):
    _legacy, new = dirs
    _mkdir(new)
    _point_config_at(new, tmp_path, monkeypatch)
    (new / MARKER).touch()
    real_unlink = Path.unlink

    def stuck(self, *args, **kwargs):
        if self.name == MARKER:
            raise PermissionError(13, "busy")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", stuck)
    with caplog.at_level(logging.DEBUG, logger=config.__name__):
        config.save_enabled_providers(["serato"])  # must not raise

    assert "PROVIDERS_ENABLED=serato" in (new / "settings.env").read_text(encoding="utf-8")
    assert any("copy-forward marker" in r.getMessage() for r in caplog.records)
