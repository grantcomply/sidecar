"""Tests for ``source.services.library_store`` (schema v4 snapshots + v3 converter).

All file I/O goes to ``tmp_path`` via the ``isolated_data_dir`` fixture.
"""

from __future__ import annotations

import json
import os

import pytest

from source.providers.base import CrateInfo, ProviderSnapshot, TrackRecord
from source.services import library_store


def _snapshot(title: str = "Song", token: str | None = "tok") -> ProviderSnapshot:
    tracks: dict[str, TrackRecord] = {
        "C:\\Music\\a.mp3": {
            "file_name": "a.mp3", "title": title, "bpm": 124.0, "energy_level": 5,
            "crates": ["serato:House%%Bangers"],
        },
    }
    crates = {
        "serato:House%%Bangers": CrateInfo(
            "serato:House%%Bangers", "serato", "House - Bangers", ("House", "Bangers"),
        ),
        "serato:Empty": CrateInfo("serato:Empty", "serato", "Empty", ("Empty",), is_smart=True),
    }
    return ProviderSnapshot(
        provider_id="serato", tracks=tracks, crates=crates,
        fingerprint={"House%%Bangers.crate": 1.5, "Empty.crate": 2.0}, change_token=token,
    )


def _write_legacy(path, payload) -> bytes:
    raw = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)
    return raw


def _legacy_payload(version: int = 3) -> dict:
    return {
        "version": version,
        "synced_at": "2026-01-01T00:00:00+00:00",
        "crate_mtimes": {"House%%Bangers.crate": 5.0, "A%%B.crate": 6.0, "Empty.crate": 7.0},
        "tracks": {
            "C:\\Music\\a.mp3": {"file_name": "a.mp3", "crates": ["House - Bangers", "A - B"]},
            "C:\\Music\\b.mp3": {"file_name": "b.mp3", "crates": ["A - B"]},
        },
    }


# ── Snapshots ──


def test_save_then_load_round_trips(isolated_data_dir):
    original = _snapshot()

    library_store.save_snapshot(original)
    loaded = library_store.load_snapshot("serato")

    assert loaded == original
    assert loaded is not None and loaded.change_token == "tok"
    assert (isolated_data_dir / "library" / "serato.json").is_file()


def test_save_leaves_no_tmp_file(isolated_data_dir):
    library_store.save_snapshot(_snapshot())
    assert not list((isolated_data_dir / "library").glob("*.tmp"))


def test_save_returns_changed_flag(isolated_data_dir):
    assert library_store.save_snapshot(_snapshot()) is True
    assert library_store.save_snapshot(_snapshot(token="other")) is False  # token isn't content
    assert library_store.save_snapshot(_snapshot(title="Edited")) is True


def test_save_failure_keeps_previous_file(isolated_data_dir, monkeypatch):
    library_store.save_snapshot(_snapshot())
    path = isolated_data_dir / "library" / "serato.json"
    before = path.read_bytes()

    def _fail(*_a, **_k):
        raise PermissionError("denied")

    monkeypatch.setattr(library_store.os, "replace", _fail)
    with pytest.raises(OSError):
        library_store.save_snapshot(_snapshot(title="Edited"))

    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.tmp"))


def test_file_fields_and_non_ascii_written_raw(isolated_data_dir):
    library_store.save_snapshot(_snapshot(title="Café"))
    text = (isolated_data_dir / "library" / "serato.json").read_text(encoding="utf-8")
    data = json.loads(text)

    assert "Café" in text
    assert data["schema"] == 4
    assert data["provider"] == "serato"
    assert data["synced_at"]
    assert set(data) == {
        "schema", "provider", "synced_at", "fingerprint", "change_token",
        "content_hash", "crates", "tracks",
    }


def _rewrite(isolated_data_dir, **changes) -> None:
    path = isolated_data_dir / "library" / "serato.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_load_schema_mismatch_returns_none(isolated_data_dir):
    library_store.save_snapshot(_snapshot())
    _rewrite(isolated_data_dir, schema=3)
    assert library_store.load_snapshot("serato") is None


def test_load_provider_mismatch_returns_none(isolated_data_dir):
    library_store.save_snapshot(_snapshot())
    _rewrite(isolated_data_dir, provider="rekordbox")
    assert library_store.load_snapshot("serato") is None


def test_load_corrupt_json_returns_none(isolated_data_dir):
    library_store.snapshot_dir().mkdir()
    (isolated_data_dir / "library" / "serato.json").write_text("{not json", encoding="utf-8")
    assert library_store.load_snapshot("serato") is None


def test_load_malformed_structure_returns_none(isolated_data_dir):
    library_store.save_snapshot(_snapshot())
    _rewrite(isolated_data_dir, crates={"x": {"label": "no provider or path"}})
    assert library_store.load_snapshot("serato") is None


def test_load_missing_returns_none_and_creates_nothing(isolated_data_dir):
    assert library_store.load_snapshot("serato") is None
    assert library_store.snapshot_summary("serato") is None
    assert not (isolated_data_dir / "library").exists()


def test_save_ignores_stale_tmp_from_another_writer(isolated_data_dir):
    lib_dir = isolated_data_dir / "library"
    lib_dir.mkdir()
    stale = lib_dir / "serato.json.tmp"
    stale.write_text("half-written by someone else", encoding="utf-8")

    library_store.save_snapshot(_snapshot())

    assert stale.read_text(encoding="utf-8") == "half-written by someone else"
    assert library_store.load_snapshot("serato") == _snapshot()
    assert sorted(p.name for p in lib_dir.iterdir()) == [
        "serato.json", "serato.json.tmp", "serato.meta.json",
    ]


def test_snapshot_summary_reports_counts_and_token(isolated_data_dir):
    library_store.save_snapshot(_snapshot())

    summary = library_store.snapshot_summary("serato")

    assert summary is not None
    assert (summary.track_count, summary.crate_count, summary.change_token) == (1, 2, "tok")
    assert summary.synced_at


# ── Legacy v3 conversion ──


def test_convert_legacy_maps_labels_to_ids_and_keeps_file(isolated_data_dir):
    legacy_path = isolated_data_dir / "track_cache.json"
    raw = _write_legacy(legacy_path, _legacy_payload())

    assert library_store.legacy_cache_exists()
    assert library_store.convert_legacy_cache_if_needed() is True

    assert legacy_path.read_bytes() == raw  # never moved, rewritten or deleted
    snapshot = library_store.load_snapshot("serato")
    assert snapshot is not None
    assert snapshot.tracks["C:\\Music\\a.mp3"].get("crates") == [
        "serato:House%%Bangers", "serato:A%%B",
    ]
    assert snapshot.crates["serato:A%%B"] == CrateInfo(
        "serato:A%%B", "serato", "A - B", ("A", "B"),
    )
    # Empty crates come from crate_mtimes, as a fresh sync would include them.
    assert set(snapshot.crates) == {"serato:House%%Bangers", "serato:A%%B", "serato:Empty"}
    summary = library_store.snapshot_summary("serato")
    assert summary is not None and summary.crate_count == 3
    assert snapshot.fingerprint == {
        "House%%Bangers.crate": 5.0, "A%%B.crate": 6.0, "Empty.crate": 7.0,
    }


def test_convert_legacy_second_run_is_noop(isolated_data_dir):
    _write_legacy(isolated_data_dir / "track_cache.json", _legacy_payload())
    library_store.convert_legacy_cache_if_needed()
    snapshot_file = isolated_data_dir / "library" / "serato.json"
    before = snapshot_file.read_bytes()

    assert library_store.convert_legacy_cache_if_needed() is False
    assert snapshot_file.read_bytes() == before


def test_convert_legacy_never_overwrites_existing_snapshot(isolated_data_dir):
    library_store.save_snapshot(_snapshot(title="Newer"))
    _write_legacy(isolated_data_dir / "track_cache.json", _legacy_payload())

    assert library_store.convert_legacy_cache_if_needed() is False
    loaded = library_store.load_snapshot("serato")
    assert loaded is not None
    assert loaded.tracks["C:\\Music\\a.mp3"].get("title") == "Newer"


@pytest.mark.parametrize("version", [2, 4])
def test_convert_non_v3_legacy_writes_no_snapshot(isolated_data_dir, version):
    raw = _write_legacy(isolated_data_dir / "track_cache.json", _legacy_payload(version))

    assert library_store.convert_legacy_cache_if_needed() is False
    assert library_store.load_snapshot("serato") is None
    assert (isolated_data_dir / "track_cache.json").read_bytes() == raw


def test_convert_corrupt_legacy_writes_no_snapshot(isolated_data_dir):
    (isolated_data_dir / "track_cache.json").write_text("{oops", encoding="utf-8")
    assert library_store.convert_legacy_cache_if_needed() is False
    assert library_store.load_snapshot("serato") is None


def test_convert_reads_project_root_legacy_in_place(isolated_data_dir, tmp_path):
    project_cache = tmp_path / "project" / "track_cache.json"
    raw = _write_legacy(project_cache, _legacy_payload())

    assert library_store.legacy_cache_exists()
    assert library_store.convert_legacy_cache_if_needed() is True
    assert project_cache.read_bytes() == raw
    assert not (isolated_data_dir / "track_cache.json").exists()


def test_no_legacy_cache(isolated_data_dir):
    assert library_store.legacy_cache_exists() is False
    assert library_store.convert_legacy_cache_if_needed() is False


def test_legacy_ids_exact_for_crate_name_containing_dash(isolated_data_dir):
    payload = {
        "version": 3,
        "crate_mtimes": {"Drum - Bass.crate": 1.0, "Old%%Drum - Bass.crate": 2.0},
        "tracks": {
            "/m/dash.mp3": {"crates": ["Drum - Bass", "Old - Drum - Bass"]},
        },
    }

    snapshot = library_store.legacy_v3_to_snapshot(payload)

    assert snapshot.tracks["/m/dash.mp3"].get("crates") == [
        "serato:Drum - Bass", "serato:Old%%Drum - Bass",
    ]
    assert snapshot.crates["serato:Old%%Drum - Bass"].path == ("Old", "Drum - Bass")


def test_legacy_label_without_crate_file_falls_back(isolated_data_dir):
    payload = {"version": 3, "crate_mtimes": {}, "tracks": {"/m/a.mp3": {"crates": ["A - B"]}}}

    snapshot = library_store.legacy_v3_to_snapshot(payload)

    assert snapshot.tracks["/m/a.mp3"].get("crates") == ["serato:A%%B"]
    assert snapshot.crates["serato:A%%B"].label == "A - B"


def test_legacy_label_tie_maps_to_first_filename(isolated_data_dir):
    # "A%%B.crate" and "A - B.crate" share a label; the parser processed sorted
    # filenames, so the first one ("A - B.crate") wins, and both crates exist.
    payload = {
        "version": 3,
        "crate_mtimes": {"A%%B.crate": 1.0, "A - B.crate": 2.0},
        "tracks": {"/m/a.mp3": {"crates": ["A - B"]}},
    }

    snapshot = library_store.legacy_v3_to_snapshot(payload)

    assert snapshot.tracks["/m/a.mp3"].get("crates") == ["serato:A - B"]
    assert set(snapshot.crates) == {"serato:A%%B", "serato:A - B"}


# ── Metadata file: unchanged syncs don't rewrite the snapshot (Phase 3b review) ──


def test_unchanged_save_rewrites_only_metadata(isolated_data_dir):
    library_store.save_snapshot(_snapshot(token="t1"))
    snap_file = isolated_data_dir / "library" / "serato.json"
    before_bytes = snap_file.read_bytes()
    before_mtime = snap_file.stat().st_mtime_ns

    changed = library_store.save_snapshot(_snapshot(token="t2"))

    assert changed is False
    assert snap_file.read_bytes() == before_bytes
    assert snap_file.stat().st_mtime_ns == before_mtime
    summary = library_store.snapshot_summary("serato")
    assert summary is not None and summary.change_token == "t2"  # baseline advanced
    loaded = library_store.load_snapshot("serato")
    assert loaded is not None and loaded.change_token == "t2"


def test_changed_save_rewrites_snapshot_and_metadata(isolated_data_dir):
    library_store.save_snapshot(_snapshot(title="A", token="t1"))
    assert library_store.save_snapshot(_snapshot(title="B", token="t2")) is True
    loaded = library_store.load_snapshot("serato")
    assert loaded is not None
    assert next(iter(loaded.tracks.values())).get("title") == "B"
    assert loaded.change_token == "t2"


def test_previous_hash_comes_from_metadata_not_the_snapshot(isolated_data_dir, monkeypatch):
    library_store.save_snapshot(_snapshot())
    reads: list[str] = []
    real_read = library_store._read_json

    def spy(path):
        reads.append(path.name)
        return real_read(path)

    monkeypatch.setattr(library_store, "_read_json", spy)
    library_store.save_snapshot(_snapshot(token="t9"))

    assert "serato.json" not in reads  # the big file isn't parsed to compare
    assert "serato.meta.json" in reads


def test_missing_metadata_forces_full_write(isolated_data_dir):
    library_store.save_snapshot(_snapshot())
    (isolated_data_dir / "library" / "serato.meta.json").unlink()
    assert library_store.save_snapshot(_snapshot()) is True
    assert (isolated_data_dir / "library" / "serato.meta.json").is_file()


def test_summary_falls_back_to_snapshot_without_metadata(isolated_data_dir):
    library_store.save_snapshot(_snapshot(token="tok"))
    (isolated_data_dir / "library" / "serato.meta.json").unlink()
    summary = library_store.snapshot_summary("serato")
    assert summary is not None and summary.change_token == "tok" and summary.track_count == 1


def test_stale_metadata_token_not_applied_to_different_content(isolated_data_dir):
    library_store.save_snapshot(_snapshot(title="A", token="t1"))
    meta = isolated_data_dir / "library" / "serato.meta.json"
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["content_hash"] = "other"
    data["change_token"] = "stale"
    meta.write_text(json.dumps(data), encoding="utf-8")

    loaded = library_store.load_snapshot("serato")
    assert loaded is not None and loaded.change_token == "t1"


def test_cleanup_orphan_temp_files_removes_only_old_tmp(isolated_data_dir):
    import os
    import time

    lib = isolated_data_dir / "library"
    lib.mkdir()
    old_tmp, new_tmp, keep = lib / "serato.json.a.tmp", lib / "serato.json.b.tmp", lib / "serato.json"
    for f in (old_tmp, new_tmp, keep):
        f.write_text("x", encoding="utf-8")
    past = time.time() - 600
    os.utime(old_tmp, (past, past))

    assert library_store.cleanup_orphan_temp_files() == 1
    assert sorted(p.name for p in lib.iterdir()) == ["serato.json", "serato.json.b.tmp"]


def test_replace_retries_sharing_violation(isolated_data_dir, monkeypatch):
    from source import config

    real_replace = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("sharing violation")
        return real_replace(src, dst)

    monkeypatch.setattr(config.os, "replace", flaky)
    monkeypatch.setattr(config, "REPLACE_BACKOFF_SECONDS", 0)

    library_store.save_snapshot(_snapshot())
    assert library_store.load_snapshot("serato") == _snapshot()


def test_legacy_conversion_keeps_the_old_sync_time(isolated_data_dir):
    payload = _legacy_payload()
    payload["synced_at"] = "2026-01-01T00:00:00+00:00"
    _write_legacy(isolated_data_dir / "track_cache.json", payload)

    library_store.convert_legacy_cache_if_needed()

    summary = library_store.snapshot_summary("serato")
    assert summary is not None and summary.synced_at == "2026-01-01T00:00:00+00:00"
