"""Tests for the settings dialog view-model (T3c.5)."""

from __future__ import annotations

from source.providers.base import ProviderCapability
from source.providers.rekordbox.provider import RekordboxProvider
from source.providers.serato.provider import SeratoProvider
from source.services.library_store import SnapshotSummary
from source.services.settings_model import build_provider_views

SUMMARY = SnapshotSummary(synced_at="2026-11-05T10:00:00+00:00", track_count=740,
                          crate_count=75, change_token="t")


def _views(tmp_path, *, enabled, settings=None):
    rb_db = tmp_path / "rekordbox" / "master.db"
    rb_db.parent.mkdir(exist_ok=True)
    rb_db.write_bytes(b"x")
    providers = [RekordboxProvider(), SeratoProvider()]
    defaults = {p.id: p.default_settings() for p in providers}
    custom = settings or {}
    return build_provider_views(
        providers,
        enabled,
        lambda pid: {**defaults[pid], **custom.get(pid, {})},
        lambda pid: SUMMARY if pid == "rekordbox" else None,
        {"rekordbox": ("1 tracks have no file on this computer",)},
        {"serato": "Crates folder not found"},
    ), rb_db


def test_views_in_registry_order_with_enabled_flags(tmp_path):
    views, _db = _views(tmp_path, enabled=["serato"])
    assert [(v.provider_id, v.enabled) for v in views] == [("rekordbox", False), ("serato", True)]
    assert [v.display_name for v in views] == ["rekordbox", "Serato DJ"]
    assert [v.crate_noun for v in views] == ["playlist", "crate"]


def test_values_fall_back_to_defaults_and_include_specs(tmp_path):
    views, _db = _views(tmp_path, enabled=["rekordbox"])
    rb = views[0]
    assert rb.values == {"db_path": "", "auto_refresh": "on"}
    assert [s.key for s in rb.specs] == ["db_path", "auto_refresh"]


def test_detected_values_issues_summary_warnings_errors(tmp_path, monkeypatch):
    from source.providers.rekordbox import paths

    views, db = _views(tmp_path, enabled=["rekordbox"])
    assert views[0].detected == {}          # session fixture: no rekordbox installed
    assert views[0].issues[0].message == "Database not found"
    monkeypatch.setattr(paths, "default_db_path", lambda: db)
    views, _db = _views(tmp_path, enabled=["rekordbox"])
    rb, se = views
    assert rb.detected == {"db_path": str(db)}
    assert rb.issues == () or all(i.setting_key != "db_path" for i in rb.issues)
    assert rb.summary == SUMMARY and se.summary is None
    assert rb.warnings == ("1 tracks have no file on this computer",)
    assert se.last_error == "Crates folder not found" and rb.last_error is None
    assert rb.auto_updates and not se.auto_updates


def test_auto_updates_follows_setting(tmp_path):
    views, _db = _views(tmp_path, enabled=["rekordbox"],
                        settings={"rekordbox": {"auto_refresh": "off"}})
    assert ProviderCapability.CHANGE_DETECTION not in views[0].capabilities
    assert not views[0].auto_updates


def test_first_error_for_wrong_file(tmp_path):
    wrong = tmp_path / "backup.db"
    wrong.write_bytes(b"x")
    views, _db = _views(tmp_path, enabled=["rekordbox"],
                        settings={"rekordbox": {"db_path": str(wrong)}})
    assert views[0].first_error() == "Choose the file named master.db"
