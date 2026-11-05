"""NowPlayingDashboard.set_empty_message (Phase 3c, T3c.7). Skips without a display."""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tk widget tests")
    root.withdraw()
    yield root
    root.destroy()


def test_placeholder_set_restored_and_never_over_a_track(tk_root, make_track):
    from source.ui.track_detail import NowPlayingDashboard

    dash = NowPlayingDashboard(tk_root)
    dash.set_empty_message("Reading your library…")
    assert dash.title_label.cget("text") == "Reading your library…"
    dash.set_empty_message(None)
    assert dash.title_label.cget("text") == "Search for a track to begin"

    dash.set_crate_noun("playlist")
    track = make_track(title="Synthetic", crates=["rekordbox:1"])
    dash.set_track(track)
    dash.set_empty_message("Sync your library in Settings (⚙) to begin")
    assert dash.title_label.cget("text") == "Synthetic"
    assert "Playlists: rekordbox:1" in dash.info_label.cget("text")
