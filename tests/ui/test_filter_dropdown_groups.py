"""Crate filter grouped by provider: the T5.3 remainder (implementation plan T5.9).

Already covered in ``test_filter_dropdown_pairs.py`` (T3c.10) and not repeated
here: headers only with two or more groups, search hiding rows and headers,
``Select shown`` / ``Clear shown``, no-match text, label truncation. This file
adds the single-selection leaf-name pill, the app's item builder (registry
order, case-insensitive sort, no header for a provider without crates), the
empty overlay with disabled buttons and ``preserve_selection`` with groups.

Needs a live Tk root; skips cleanly where no display is available.
Synthetic data only.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from source.models.library import TrackLibrary
from source.models.path_identity import path_key
from source.providers.base import CrateInfo

tk = pytest.importorskip("tkinter")

# (crate id, label, group, leaf) as the app passes them.
GROUPED = [
    ("rekordbox:1", "Club / Peak", "rekordbox", "Peak"),
    ("rekordbox:2", "Club / Warm up", "rekordbox", "Warm up"),
    ("serato:House%%Bangers", "House - Bangers", "Serato DJ", "Bangers"),
    ("serato:Peak", "Peak", "Serato DJ", "Peak"),
]


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tk widget tests")
    root.withdraw()
    yield root
    root.destroy()


def _dropdown(tk_root, items=GROUPED, label="Playlists"):
    from source.ui.filter_bar import CRATE_OVERLAY_SIZE, FilterDropdown

    dd = FilterDropdown(tk_root, host=tk_root, label=label,
                        searchable=True, overlay_size=CRATE_OVERLAY_SIZE)
    dd.set_items(items)
    return dd


def _headers(dd) -> list[str]:
    return [r.widget.cget("text") for r in dd._rows if r.key is None and r.widget.grid_info()]


def _keys(dd) -> list[str]:
    return [r.key for r in dd._rows if r.key is not None]


# ── Single-selection pill: the leaf name ──


def test_single_selection_pill_shows_leaf_not_full_path(tk_root):
    dd = _dropdown(tk_root)
    dd.restore(frozenset({"rekordbox:2"}))
    assert dd.pill.cget("text") == "Playlists: Warm up"
    dd.restore(frozenset({"serato:House%%Bangers"}))
    assert dd.pill.cget("text") == "Playlists: Bangers"


def test_single_selection_leaf_truncated_at_ten_characters(tk_root):
    items = [("rekordbox:9", "Sets / Extremely Long Name", "rekordbox", "Extremely Long Name"),
             ("rekordbox:8", "Other", "rekordbox", "Other")]
    dd = _dropdown(tk_root, items)
    dd.restore(frozenset({"rekordbox:9"}))
    assert dd.pill.cget("text") == "Playlists: Extremely…"


def test_leaf_missing_or_empty_falls_back_to_label(tk_root):
    dd = _dropdown(tk_root, [("a", "Alpha", "rekordbox", ""), ("b", "Beta", "rekordbox"),
                             ("c", "Gamma")])
    dd.restore(frozenset({"a"}))
    assert dd.pill.cget("text") == "Playlists: Alpha"
    dd.restore(frozenset({"b"}))
    assert dd.pill.cget("text") == "Playlists: Beta"


def test_selected_returns_crate_ids_only(tk_root):
    dd = _dropdown(tk_root)
    assert dd.selected == {key for key, *_rest in GROUPED}
    dd.restore(frozenset({"serato:Peak"}))
    assert dd.selected == {"serato:Peak"}


# ── The app's item builder (registry order, sort, empty providers) ──


def _library(tracks_crates: list[list[str]], crates: list[CrateInfo]) -> TrackLibrary:
    from source.models.track import Track

    tracks = {}
    for i, crate_ids in enumerate(tracks_crates):
        path = f"/music/t{i}.mp3"
        tracks[path_key(path)] = Track(file_name=f"t{i}.mp3", full_file_path=path,
                                       crates=list(crate_ids))
    library = TrackLibrary()
    library.replace_all(tracks, {c.id: c for c in crates})
    return library


def _rb(native: str, *path: str) -> CrateInfo:
    return CrateInfo(f"rekordbox:{native}", "rekordbox", " / ".join(path), tuple(path))


def _se(*path: str) -> CrateInfo:
    return CrateInfo("serato:" + "%%".join(path), "serato", " - ".join(path), tuple(path))


def _filter_items(library: TrackLibrary):
    from source.app import DJTrackSelectorApp

    stub = SimpleNamespace(library=library, _provider_name=DJTrackSelectorApp._provider_name)
    return DJTrackSelectorApp._crate_filter_items(stub)  # type: ignore[arg-type]


def test_app_items_registry_order_case_insensitive_sort_and_leaf():
    crates = [_se("Afro"), _rb("2", "club", "Warm up"), _rb("1", "Club", "peak"),
              _rb("3", "Ambient")]
    library = _library([["serato:Afro", "rekordbox:1", "rekordbox:2", "rekordbox:3"]], crates)

    assert _filter_items(library) == [
        ("rekordbox:3", "Ambient", "rekordbox", "Ambient"),
        ("rekordbox:1", "Club / peak", "rekordbox", "peak"),  # casefolded path: club/peak
        ("rekordbox:2", "club / Warm up", "rekordbox", "Warm up"),
        ("serato:Afro", "Afro", "Serato DJ", "Afro"),  # after rekordbox despite "A"
    ]


def test_provider_without_crates_gets_no_header(tk_root):
    # Serato crates exist in the index but hold no tracks: one group, flat list.
    crates = [_rb("1", "Club", "Peak"), _rb("2", "Warm up"), _se("Unused")]
    library = _library([["rekordbox:1"], ["rekordbox:2"]], crates)
    items = _filter_items(library)
    assert {group for _k, _l, group, _leaf in items} == {"rekordbox"}

    dd = _dropdown(tk_root, items)

    assert _headers(dd) == []
    assert _keys(dd) == ["rekordbox:1", "rekordbox:2"]


# ── Empty overlay ──


def test_empty_overlay_copy_and_disabled_buttons(tk_root):
    dd = _dropdown(tk_root, [])
    assert dd._empty_label is not None
    assert dd._empty_label.cget("text") == "No playlists loaded. Sync a source in Settings."
    assert dd._select_all_btn.cget("state") == "disabled"
    assert dd._clear_btn.cget("state") == "disabled"
    assert dd.pill.cget("text") == "Playlists"

    dd.set_items(GROUPED, preserve_selection=True)  # first sync lands
    assert dd._empty_label is None
    assert dd._select_all_btn.cget("state") == "normal"
    assert dd._clear_btn.cget("state") == "normal"
    assert dd.all_selected


# ── preserve_selection with groups ──


def test_preserve_selection_when_a_group_disappears_and_list_goes_flat(tk_root):
    dd = _dropdown(tk_root)
    dd.restore(frozenset({"rekordbox:1", "serato:Peak"}))

    dd.set_items(GROUPED[:2], preserve_selection=True)  # Serato turned off

    assert _headers(dd) == []
    assert dd.selected == {"rekordbox:1"}
    assert dd.pill.cget("text") == "Playlists: Peak"  # leaf, now from rekordbox


def test_preserve_selection_when_a_second_group_appears(tk_root):
    dd = _dropdown(tk_root, GROUPED[:2])
    dd.restore(frozenset({"rekordbox:2"}))

    dd.set_items(GROUPED, preserve_selection=True)  # Serato turned on: new ids start checked

    assert _headers(dd) == ["REKORDBOX", "SERATO DJ"]
    assert dd.selected == {"rekordbox:2", "serato:House%%Bangers", "serato:Peak"}


def test_preserve_selection_follows_a_renamed_playlist_by_id(tk_root):
    dd = _dropdown(tk_root)
    dd.restore(frozenset({"rekordbox:1"}))
    renamed = [("rekordbox:1", "Club / Peak Time", "rekordbox", "Peak Time"), *GROUPED[1:]]

    dd.set_items(renamed, preserve_selection=True)

    assert dd.selected == {"rekordbox:1"}
    assert dd.pill.cget("text") == "Playlists: Peak Time"
    box = next(r.widget for r in dd._rows if r.key == "rekordbox:1")
    assert box.cget("text") == "Club / Peak Time"


def test_preserve_selection_survives_an_active_search(tk_root):
    dd = _dropdown(tk_root)
    dd.restore(frozenset({"serato:Peak"}))
    assert dd._search is not None
    dd._search.insert(0, "peak")
    dd._apply_search()

    dd.set_items(GROUPED + [("serato:New", "New", "Serato DJ", "New")], preserve_selection=True)

    shown = [r.key for r in dd._rows if r.key is not None and r.widget.grid_info()]
    assert shown == ["rekordbox:1", "serato:Peak"]  # search re-applied to the new rows
    assert dd.selected == {"serato:Peak", "serato:New"}


def test_unknown_provider_crate_gets_group_none_and_no_blank_header(tk_root):
    # A crate id with no index entry (unknown provider): group None, sorted last.
    crates = [_rb("1", "Club", "Peak"), _se("House")]
    library = _library([["rekordbox:1", "serato:House", "ghost:1"]], crates)
    items = _filter_items(library)
    assert items[-1] == ("ghost:1", "ghost:1", None, "ghost:1")

    dd = _dropdown(tk_root, items)

    assert _headers(dd) == ["REKORDBOX", "SERATO DJ"]  # no "" header for the unknown crate
    # Rendered above the first header, not under the last provider's.
    assert _keys(dd) == ["ghost:1", "rekordbox:1", "serato:House"]
    assert [r.key for r in dd._rows][:2] == ["ghost:1", None]


def test_unknown_provider_crate_stays_in_place_in_a_flat_list(tk_root):
    items = [("rekordbox:1", "Peak", "rekordbox", "Peak"), ("ghost:1", "ghost:1", None, "ghost:1")]
    dd = _dropdown(tk_root, items)
    assert _headers(dd) == []
    assert _keys(dd) == ["rekordbox:1", "ghost:1"]
