"""Tests for the pure sync-outcome rules (Phase 3b review)."""

from __future__ import annotations

from source.services.library_sync import ProviderSyncResult, SyncReport
from source.services.sync_outcome import sync_outcome

NAMES = {"rekordbox": "rekordbox", "serato": "Serato DJ"}


def _report(*results: ProviderSyncResult, follow_up: bool = False) -> SyncReport:
    return SyncReport(results=results, follow_up_pending=follow_up)


def _ok(pid: str, changed: bool = True) -> ProviderSyncResult:
    return ProviderSyncResult(provider_id=pid, track_count=10, changed=changed)


def _fail(pid: str, error: str = "Crates folder not found") -> ProviderSyncResult:
    return ProviderSyncResult(provider_id=pid, error=error)


def _outcome(report, silent, prev=None):
    return sync_outcome(prev or {}, report, silent=silent, provider_name=NAMES.__getitem__)


def test_manual_partial_failure_still_reloads_and_shows_failure():
    # Merged manual run: Serato fails, rekordbox succeeds with a change.
    out = _outcome(_report(_ok("rekordbox", changed=True), _fail("serato")), silent=False)

    assert out.reload and out.stop_audio and not out.preserve_state
    assert [t.text for t in out.toasts] == [
        "Synced rekordbox. Serato DJ sync failed: Crates folder not found",
    ]
    assert out.success_toast is False
    assert out.errors == {"serato": "Crates folder not found"}


def test_manual_success_reloads_with_success_toast():
    out = _outcome(_report(_ok("rekordbox", changed=False)), silent=False)
    assert out.reload and out.success_toast and out.toasts == ()
    assert out.clear_dialog_syncing


def test_manual_all_failed_no_reload():
    out = _outcome(_report(_fail("rekordbox", "rekordbox database is busy")), silent=False)
    assert not out.reload and not out.stop_audio and not out.success_toast
    assert len(out.toasts) == 1


def test_manual_with_follow_up_keeps_dialog_syncing():
    out = _outcome(_report(_ok("rekordbox"), follow_up=True), silent=False)
    assert out.clear_dialog_syncing is False


def test_silent_change_reloads_quietly():
    out = _outcome(_report(_ok("rekordbox", changed=True)), silent=True)
    assert out.reload and out.preserve_state and not out.stop_audio
    assert out.toasts == () and not out.success_toast and not out.clear_dialog_syncing


def test_silent_no_change_does_nothing():
    out = _outcome(_report(_ok("rekordbox", changed=False)), silent=True)
    assert not out.reload and out.toasts == ()


def test_silent_partial_failure_still_reloads_the_change():
    out = _outcome(_report(_ok("rekordbox", changed=True), _fail("serato")), silent=True)
    assert out.reload and out.preserve_state
    assert [t.text for t in out.toasts] == ["Serato DJ auto-update failed: Crates folder not found"]


def test_silent_error_toast_deduplicated_until_cleared():
    first = _outcome(_report(_fail("rekordbox", "busy")), silent=True)
    again = _outcome(_report(_fail("rekordbox", "busy")), silent=True, prev=first.errors)
    different = _outcome(_report(_fail("rekordbox", "gone")), silent=True, prev=again.errors)
    recovered = _outcome(_report(_ok("rekordbox", changed=False)), silent=True, prev=different.errors)
    after = _outcome(_report(_fail("rekordbox", "busy")), silent=True, prev=recovered.errors)

    assert len(first.toasts) == 1
    assert again.toasts == ()
    assert len(different.toasts) == 1
    assert recovered.errors == {}
    assert len(after.toasts) == 1


def test_manual_failure_suppresses_same_error_on_next_refresh():
    manual = _outcome(_report(_fail("rekordbox", "busy")), silent=False)
    refresh = _outcome(_report(_fail("rekordbox", "busy")), silent=True, prev=manual.errors)
    assert len(manual.toasts) == 1 and refresh.toasts == ()


def test_prev_errors_not_mutated():
    prev = {"rekordbox": "busy"}
    _outcome(_report(_ok("rekordbox")), silent=True, prev=prev)
    assert prev == {"rekordbox": "busy"}


# ── Phase 3c table (T3c.2) ──

from source.config import ERROR_COLOR, WARNING_COLOR  # noqa: E402


def test_table_silent_new_error_is_amber_8s():
    (toast,) = _outcome(_report(_fail("rekordbox", "Database not found")), silent=True).toasts
    assert (toast.text, toast.color, toast.duration_ms) == (
        "rekordbox auto-update failed: Database not found", WARNING_COLOR, 8000,
    )


def test_table_manual_partial_failure_is_amber_8s():
    (toast,) = _outcome(_report(_ok("rekordbox"), _fail("serato")), silent=False).toasts
    assert (toast.color, toast.duration_ms, toast.action_label) == (WARNING_COLOR, 8000, None)


def test_table_manual_single_failure_is_red_4s():
    (toast,) = _outcome(_report(_fail("rekordbox", "Database not found")), silent=False).toasts
    assert (toast.text, toast.color, toast.duration_ms) == (
        "rekordbox sync failed: Database not found", ERROR_COLOR, 4000,
    )


def test_table_manual_all_failed_is_red_8s_with_open_settings():
    out = _outcome(_report(_fail("rekordbox", "a"), _fail("serato", "b")), silent=False)
    (toast,) = out.toasts
    assert (toast.text, toast.color, toast.duration_ms, toast.action_label) == (
        "Sync failed for rekordbox and Serato DJ", ERROR_COLOR, 8000, "Open settings",
    )
    assert "Synced" not in toast.text and not out.success_toast


def test_import_candidate_only_for_quiet_change_into_empty_library():
    changed = _report(_ok("rekordbox", changed=True))
    assert sync_outcome({}, changed, silent=True, provider_name=NAMES.__getitem__,
                        library_was_empty=True).import_candidate
    assert not sync_outcome({}, changed, silent=True, provider_name=NAMES.__getitem__,
                            library_was_empty=False).import_candidate
    assert not sync_outcome({}, _report(_ok("rekordbox", changed=False)), silent=True,
                            provider_name=NAMES.__getitem__, library_was_empty=True).import_candidate
    assert not sync_outcome({}, changed, silent=False, provider_name=NAMES.__getitem__,
                            library_was_empty=True).import_candidate


def test_ok_provider_ids_listed_in_report_order():
    out = sync_outcome({}, _report(_ok("rekordbox"), _fail("serato"), _ok("x")), silent=False,
                       provider_name=lambda pid: pid)
    assert out.ok_provider_ids == ("rekordbox", "x")
