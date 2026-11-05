"""Crate attribution in the suggestion tooltip (T5.4, brief §5.10).

One provider enabled: ``{Nouns}: A, B``. More: one line per provider that
holds the track, registry order, no provider colour. The app half runs on a
stub ``self`` (no window); the panel half needs a Tk root and skips without
a display. Synthetic data only.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from source.models.library import TrackLibrary
from source.providers.base import CrateInfo
from source.services.harmonic_tier import HarmonicTier
from source.services.suggestion_engine import ScoredTrack

tk = pytest.importorskip("tkinter")

_CRATES = {
    "rekordbox:1": CrateInfo("rekordbox:1", "rekordbox", "Club / Peak", ("Club", "Peak")),
    "rekordbox:2": CrateInfo("rekordbox:2", "rekordbox", "Warm up", ("Warm up",)),
    "serato:House%%Bangers": CrateInfo(
        "serato:House%%Bangers", "serato", "House - Bangers", ("House", "Bangers")),
}


def _app_lines(crate_ids: list[str], *, multi: bool, noun: str = "playlist") -> list[str]:
    from source.app import DJTrackSelectorApp

    library = TrackLibrary()
    library.replace_all({}, _CRATES)
    stub = SimpleNamespace(
        library=library, _multi_provider=multi, _noun=noun,
        _provider_name=DJTrackSelectorApp._provider_name,
    )
    return DJTrackSelectorApp._crate_tooltip_lines(stub, crate_ids)  # type: ignore[arg-type]


def test_one_provider_enabled_lists_labels_under_the_noun():
    assert _app_lines(["rekordbox:1", "rekordbox:2"], multi=False) == [
        "Playlists: Club / Peak, Warm up",
    ]
    assert _app_lines(["serato:House%%Bangers"], multi=False, noun="crate") == [
        "Crates: House - Bangers",
    ]


def test_two_providers_enabled_give_one_line_per_provider_in_registry_order():
    ids = ["serato:House%%Bangers", "rekordbox:1", "rekordbox:2"]
    assert _app_lines(ids, multi=True) == [
        "rekordbox: Club / Peak, Warm up",
        "Serato DJ: House - Bangers",
    ]


def test_two_providers_enabled_only_providers_holding_the_track_appear():
    assert _app_lines(["serato:House%%Bangers"], multi=True) == ["Serato DJ: House - Bangers"]


# ── Panel: the tooltip uses the app's lines ──


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tk widget tests")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def tooltips(monkeypatch) -> list[str]:
    from source.ui import suggestion_panel

    texts: list[str] = []
    monkeypatch.setattr(suggestion_panel, "Tooltip", lambda _widget, text: texts.append(text))
    return texts


def _scored(make_track, crates: list[str]) -> list[ScoredTrack]:
    return [ScoredTrack(
        track=make_track(crates=crates), total_score=0.9, key_score=1.0,
        energy_score=1.0, bpm_score=1.0, harmonic_tier=HarmonicTier.PERFECT,
    )]


def test_panel_tooltip_default_uses_noun_heading(tk_root, tooltips, make_track):
    from source.ui.suggestion_panel import SuggestionPanel

    panel = SuggestionPanel(tk_root)
    panel.set_crates([("serato:A", "A - B"), ("serato:C", "C")])
    panel.set_suggestions(_scored(make_track, ["serato:A", "serato:C"]))

    assert tooltips and tooltips[-1].endswith("\n\nCrates: A - B, C")


def test_panel_tooltip_uses_per_provider_lines(tk_root, tooltips, make_track):
    from source.ui.suggestion_panel import SuggestionPanel

    panel = SuggestionPanel(tk_root)
    seen: list[list[str]] = []

    def lines(ids):
        seen.append(list(ids))
        return ["rekordbox: Club / Peak", "Serato DJ: House - Bangers"]

    panel.set_crate_lines_fn(lines)
    panel.set_suggestions(_scored(make_track, ["rekordbox:1", "serato:House%%Bangers"]))

    assert seen == [["rekordbox:1", "serato:House%%Bangers"]]
    assert tooltips[-1].endswith("\n\nrekordbox: Club / Peak\nSerato DJ: House - Bangers")


def test_panel_tooltip_has_no_crate_lines_for_a_track_without_crates(
    tk_root, tooltips, make_track,
):
    from source.ui.suggestion_panel import SuggestionPanel

    panel = SuggestionPanel(tk_root)
    panel.set_suggestions(_scored(make_track, []))

    assert tooltips and "Crates" not in tooltips[-1] and not tooltips[-1].endswith("\n")


# ── Now Playing info line: labels only, first 3 plus "(+N)" ──


def test_now_playing_info_line_labels_only_first_three_plus_count(tk_root, make_track):
    from source.ui.track_detail import NowPlayingDashboard

    library = TrackLibrary()
    library.replace_all({}, _CRATES)
    dash = NowPlayingDashboard(tk_root)
    dash.set_crate_label_fn(library.crate_label)
    dash.set_crate_noun("playlist")
    crates = ["rekordbox:1", "serato:House%%Bangers", "rekordbox:2", "serato:Extra"]
    dash.set_track(make_track(crates=crates))

    info = dash.info_label.cget("text")
    assert "Playlists: Club / Peak, House - Bangers, Warm up (+1)" in info
    assert "rekordbox" not in info and "Serato" not in info  # no provider tag
