"""App-level sync wiring (Phase 3c review items 1, 9). Synthetic data; skips without a display.

The real app is constructed; the session fixtures already redirect its data
folder and rekordbox location to temp folders, and no provider is enabled.
"""

from __future__ import annotations

import pytest

from source.services.library_sync import ProviderSyncResult, SyncReport

tk = pytest.importorskip("tkinter")


@pytest.fixture
def app():
    try:
        probe = tk.Tk()
        probe.destroy()
    except tk.TclError:
        pytest.skip("no display available for Tk widget tests")
    from source.app import DJTrackSelectorApp

    a = DJTrackSelectorApp()
    a.withdraw()
    yield a
    if not a._closing:
        a._on_close()


class _QuietRunCoordinator:
    """Stands in for the real coordinator: a quiet refresh is running."""

    is_running = True
    manual_in_progress = False
    has_pending = False

    def wait_idle(self, _timeout):
        return True


def test_dialog_opened_during_quiet_run_is_not_busy_and_quiet_report_keeps_it_free(app):
    app._sync = _QuietRunCoordinator()
    app._open_settings()
    dlg = app._settings_dialog
    assert dlg is not None and not dlg.is_busy

    dlg.set_busy(True)  # e.g. left busy by an earlier state
    report = SyncReport((ProviderSyncResult(provider_id="rekordbox", changed=False),))
    app._sync_done_on_ui(report, silent=True)

    assert not dlg.is_busy


def test_single_provider_success_uses_its_own_count_and_noun(app):
    report = SyncReport((ProviderSyncResult(provider_id="rekordbox", track_count=740,
                                            crate_count=75),))
    assert app._sync_success_text(report, ["rekordbox"]) == "Synced 740 tracks from 75 playlists"
    serato = SyncReport((ProviderSyncResult(provider_id="serato", track_count=735,
                                            crate_count=82),))
    assert app._sync_success_text(serato, ["Serato DJ"]) == "Synced 735 tracks from 82 crates"
