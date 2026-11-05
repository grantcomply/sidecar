"""Tests for the generic provider settings accessors in ``source.config`` (T2.3)."""

from __future__ import annotations

from dataclasses import dataclass

from source import config


@dataclass(frozen=True)
class _Spec:
    key: str
    env_key: str


_SPECS = (_Spec("subcrates_dir", "SERATO_SUBCRATES_DIR"),)


def test_parse_provider_list_strips_and_drops_empties():
    assert config.parse_provider_list(" rekordbox , ,serato,") == ["rekordbox", "serato"]
    assert config.parse_provider_list("") == []


def test_enabled_providers_round_trip_keeps_order(isolated_data_dir):
    assert config.get_enabled_providers() == []

    config.save_enabled_providers(["rekordbox", "serato"])

    assert config.get_enabled_providers() == ["rekordbox", "serato"]


def test_provider_settings_fall_back_to_defaults(isolated_data_dir):
    values = config.get_provider_settings(_SPECS, {"subcrates_dir": "C:/Default"})
    assert values == {"subcrates_dir": "C:/Default"}


def test_provider_settings_persist_under_legacy_env_key(isolated_data_dir):
    (isolated_data_dir / "settings.env").write_text("CHECK_FOR_UPDATES=false\n", encoding="utf-8")

    config.save_provider_settings(_SPECS, {"subcrates_dir": "D:/Crates", "unknown": "x"})

    assert config.get_provider_settings(_SPECS, {"subcrates_dir": "C:/Default"}) == {
        "subcrates_dir": "D:/Crates",
    }
    env = config._load_env()  # noqa: SLF001
    assert env == {"CHECK_FOR_UPDATES": "false", "SERATO_SUBCRATES_DIR": "D:/Crates"}


def test_save_env_failure_keeps_file_and_removes_tmp(isolated_data_dir, monkeypatch):
    env_file = isolated_data_dir / "settings.env"
    env_file.write_text("A=1\n", encoding="utf-8")

    def _fail(*_a, **_k):
        raise PermissionError("locked")

    monkeypatch.setattr(config.os, "replace", _fail)
    try:
        config._save_env({"A": "2"})  # noqa: SLF001
    except PermissionError:
        pass
    else:
        raise AssertionError("expected PermissionError")

    assert env_file.read_text(encoding="utf-8") == "A=1\n"
    assert sorted(p.name for p in isolated_data_dir.iterdir()) == ["settings.env"]


def test_save_env_writes_sorted_lines(isolated_data_dir):
    config._save_env({"B": "2", "A": "1"})  # noqa: SLF001
    assert (isolated_data_dir / "settings.env").read_text(encoding="utf-8") == "A=1\nB=2\n"


def test_save_enabled_providers_stamps_schema_so_choice_is_kept(isolated_data_dir, monkeypatch):
    from source.services import settings_migration

    # Pre-migration file (schema missing) for an existing Serato user...
    (isolated_data_dir / "settings.env").write_text("SERATO_SUBCRATES_DIR=X\n", encoding="utf-8")
    monkeypatch.setattr(settings_migration, "_detected_provider_ids", lambda: [])

    # ...who then saves an explicit (here: empty) provider list.
    config.save_enabled_providers([])

    assert config._load_env()["SETTINGS_SCHEMA"] == "2"  # noqa: SLF001
    assert settings_migration.effective_enabled_providers() == []


def test_save_library_settings_writes_once_and_strips_newlines(isolated_data_dir, monkeypatch):
    writes: list[dict] = []
    real = config._save_env

    def counting(env):
        writes.append(dict(env))
        real(env)

    monkeypatch.setattr(config, "_save_env", counting)
    specs_a = (_Spec("subcrates_dir", "SERATO_SUBCRATES_DIR"),)
    specs_b = (_Spec("db_path", "REKORDBOX_DB_PATH"),)

    config.save_library_settings(
        ["rekordbox", "serato"],
        [(specs_b, {"db_path": "C:/a\r\nINJECTED=1"}), (specs_a, {"subcrates_dir": "D:/c"})],
    )

    assert len(writes) == 1
    env = config._load_env()  # noqa: SLF001
    assert env["PROVIDERS_ENABLED"] == "rekordbox,serato"
    assert env["SETTINGS_SCHEMA"] == "2"
    assert env["REKORDBOX_DB_PATH"] == "C:/aINJECTED=1"
    assert "INJECTED" not in env
    assert env["SERATO_SUBCRATES_DIR"] == "D:/c"


def test_save_library_settings_failure_leaves_file_untouched(isolated_data_dir, monkeypatch):
    env_file = isolated_data_dir / "settings.env"
    env_file.write_text("PROVIDERS_ENABLED=serato\n", encoding="utf-8")

    def _fail(*_a, **_k):
        raise PermissionError("locked")

    monkeypatch.setattr(config.os, "replace", _fail)
    monkeypatch.setattr(config, "REPLACE_BACKOFF_SECONDS", 0)
    try:
        config.save_library_settings([], [])
    except PermissionError:
        pass
    assert env_file.read_text(encoding="utf-8") == "PROVIDERS_ENABLED=serato\n"
