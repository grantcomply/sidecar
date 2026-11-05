"""FilterDropdown with ``(key, label)`` items (ADR-015 D3, implementation plan T2.8).

Needs a live Tk root; skips cleanly where no display is available.
"""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")

_ITEMS = [("serato:A%%B", "A - B"), ("serato:House", "House")]


def _box_texts(dd) -> list[str]:
    import customtkinter as ctk

    return [w.cget("text") for w in dd.checklist.winfo_children()
            if isinstance(w, ctk.CTkCheckBox)]


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tk widget tests")
    root.withdraw()
    yield root
    root.destroy()


def _dropdown(tk_root):
    from source.ui.filter_bar import FilterDropdown

    dd = FilterDropdown(tk_root, host=tk_root, label="Crates")
    dd.set_items(_ITEMS)
    return dd


def test_pairs_selected_returns_keys(tk_root):
    dd = _dropdown(tk_root)
    assert dd.selected == {"serato:A%%B", "serato:House"}
    assert dd.all_selected is True


def test_pairs_checkbox_text_is_label(tk_root):
    dd = _dropdown(tk_root)
    texts = _box_texts(dd)
    assert texts == ["A - B", "House"]


def test_pairs_restore_by_key_and_single_pill_uses_label(tk_root):
    dd = _dropdown(tk_root)

    dd.restore(frozenset({"serato:A%%B"}))

    assert dd.selected == {"serato:A%%B"}
    assert dd.pill.cget("text") == "Crates: A - B"


def test_plain_strings_still_work_as_key_and_label(tk_root):
    from source.ui.filter_bar import FilterDropdown

    dd = FilterDropdown(tk_root, host=tk_root, label="Genres")
    dd.set_items(["House", "Techno"])

    assert dd.selected == {"House", "Techno"}
    assert _box_texts(dd) == ["House", "Techno"]


def test_set_items_again_drops_old_keys(tk_root):
    dd = _dropdown(tk_root)
    dd.set_items([("serato:New", "New")])
    assert dd.selected == {"serato:New"}


# ── preserve_selection (live refresh, T3b.5) ──


def test_preserve_selection_keeps_unchecked_adds_new_checked_drops_removed(tk_root):
    from source.ui.filter_bar import FilterDropdown

    fired: list[int] = []
    dd = FilterDropdown(tk_root, host=tk_root, label="Crates", on_change=lambda: fired.append(1))
    dd.set_items([("a", "A"), ("b", "B"), ("c", "C")])
    dd.restore(frozenset({"a", "c"}))  # b unchecked

    dd.set_items([("a", "A"), ("b", "B renamed"), ("d", "D")], preserve_selection=True)

    assert dd.selected == {"a", "d"}          # b stays unchecked, d new → checked, c gone
    assert not dd.all_selected
    texts = _box_texts(dd)
    assert texts == ["A", "B renamed", "D"]
    assert fired == []                        # on_change never fired
    assert dd.pill.cget("text") == "Crates: 2/3"


def test_without_preserve_selection_everything_rechecked(tk_root):
    from source.ui.filter_bar import FilterDropdown

    dd = FilterDropdown(tk_root, host=tk_root, label="Crates")
    dd.set_items([("a", "A"), ("b", "B")])
    dd.restore(frozenset({"a"}))
    dd.set_items([("a", "A"), ("b", "B")])
    assert dd.all_selected


def test_preserve_selection_with_unchanged_items_does_not_rebuild(tk_root):
    from source.ui.filter_bar import FilterDropdown

    dd = FilterDropdown(tk_root, host=tk_root, label="Crates")
    dd.set_items([("a", "A"), ("b", "B")])
    dd.restore(frozenset({"a"}))
    before = list(dd.checklist.winfo_children())

    dd.set_items([("a", "A"), ("b", "B")], preserve_selection=True)

    assert list(dd.checklist.winfo_children()) == before  # same widgets: no rebuild
    assert dd.selected == {"a"}


def test_set_label_changes_pill_and_empty_overlay_text(tk_root):
    from source.ui.filter_bar import FilterDropdown

    dd = FilterDropdown(tk_root, host=tk_root, label="Crates")
    dd.set_items([])
    dd.set_label("Playlists")
    assert dd.pill.cget("text") == "Playlists"
    assert dd._empty_label is not None
    assert dd._empty_label.cget("text") == "No playlists loaded. Sync a source in Settings."
    dd.set_items([("a", "A"), ("b", "B")])
    dd.restore(frozenset({"a"}))
    assert dd.pill.cget("text") == "Playlists: A"


# ── Playlist filter at scale (T3c.10) ──

GROUPED = [
    ("rekordbox:1", "Club / Peak", "rekordbox"), ("rekordbox:2", "Club / Warm up", "rekordbox"),
    ("serato:A", "House - Bangers", "Serato DJ"), ("serato:B", "Peak", "Serato DJ"),
]


def _searchable(tk_root, items=GROUPED):
    from source.ui.filter_bar import CRATE_OVERLAY_SIZE, FilterDropdown

    dd = FilterDropdown(tk_root, host=tk_root, label="Playlists",
                        searchable=True, overlay_size=CRATE_OVERLAY_SIZE)
    dd.set_items(items)
    return dd


def _s(dd):
    assert dd._search is not None
    return dd._search


def _headers(dd) -> list[str]:
    return [r.widget.cget("text") for r in dd._rows if r.key is None and r.widget.grid_info()]


def _shown(dd) -> list[str]:
    return [r.key for r in dd._rows if r.key is not None and r.widget.grid_info()]


def test_headers_only_with_two_or_more_groups(tk_root):
    dd = _searchable(tk_root)
    assert _headers(dd) == ["REKORDBOX", "SERATO DJ"]
    single = _searchable(tk_root, [(k, l, "rekordbox") for k, l, _g in GROUPED[:2]])
    assert _headers(single) == []
    assert _shown(single) == ["rekordbox:1", "rekordbox:2"]


def test_search_hides_rows_and_empty_headers_but_keeps_ticks(tk_root):
    dd = _searchable(tk_root)
    dd.restore(frozenset({"rekordbox:1", "serato:A"}))
    _s(dd).insert(0, "house")
    dd._apply_search()
    assert _shown(dd) == ["serato:A"]
    assert _headers(dd) == ["SERATO DJ"]
    assert dd.selected == {"rekordbox:1", "serato:A"}  # hidden ticks survive
    _s(dd).delete(0, "end")
    dd._apply_search()
    assert len(_shown(dd)) == 4 and dd.selected == {"rekordbox:1", "serato:A"}


def test_select_and_clear_shown_act_on_visible_rows_only(tk_root):
    dd = _searchable(tk_root)
    dd.restore(frozenset())
    _s(dd).insert(0, "peak")
    dd._apply_search()
    assert dd._select_all_btn.cget("text") == "Select shown"
    assert dd._clear_btn.cget("text") == "Clear shown"
    dd._select_all()
    assert dd.selected == {"rekordbox:1", "serato:B"}   # "Peak" in both groups
    dd._deselect_all()
    assert dd.selected == set()
    _s(dd).delete(0, "end")
    dd._apply_search()
    assert dd._select_all_btn.cget("text") == "Select all"


def test_search_matches_full_label_so_folder_finds_children(tk_root):
    dd = _searchable(tk_root)
    _s(dd).insert(0, "CLUB")
    dd._apply_search()
    assert _shown(dd) == ["rekordbox:1", "rekordbox:2"]


def test_no_match_text(tk_root):
    dd = _searchable(tk_root)
    _s(dd).insert(0, "zzz")
    dd._apply_search()
    assert dd._no_match is not None and dd._no_match.grid_info()
    assert dd._no_match.cget("text") == 'No playlists match "zzz"'
    assert _headers(dd) == [] and _shown(dd) == []


def test_preserve_selection_keeps_state_across_groups(tk_root):
    dd = _searchable(tk_root)
    dd.restore(frozenset({"serato:A"}))
    dd.set_items(GROUPED + [("serato:C", "New", "Serato DJ")], preserve_selection=True)
    assert dd.selected == {"serato:A", "serato:C"}


def test_long_labels_truncated_with_full_text_kept(tk_root):
    long = "Folder / " * 6 + "Leaf"
    dd = _searchable(tk_root, [("rekordbox:9", long, "rekordbox")])
    box = next(r.widget for r in dd._rows if r.key == "rekordbox:9")
    assert len(box.cget("text")) <= 38 and box.cget("text") != long
    assert box.cget("text").endswith("Leaf")  # cut from the start
    _s(dd).insert(0, "leaf")   # search still matches the full label
    dd._apply_search()
    assert _shown(dd) == ["rekordbox:9"]


def test_search_placeholder_follows_noun(tk_root):
    dd = _searchable(tk_root)
    assert _s(dd).cget("placeholder_text") == "Find a playlist"
    dd.set_label("Crates")
    assert _s(dd).cget("placeholder_text") == "Find a crate"


def test_select_shown_flushes_a_pending_search_first(tk_root):
    dd = _searchable(tk_root)
    dd.restore(frozenset())
    _s(dd).insert(0, "peak")
    dd._schedule_search()          # debounce still pending: rows not yet filtered
    dd._select_all()               # "Select shown" must act on the rows that match
    assert dd.selected == {"rekordbox:1", "serato:B"}
    assert dd._search_after is None


def test_search_clears_when_overlay_closes(tk_root):
    dd = _searchable(tk_root)
    _s(dd).insert(0, "house")
    dd._apply_search()
    assert len(_shown(dd)) == 1
    dd._overlay.close()
    assert _s(dd).get() == "" and len(_shown(dd)) == 4
    assert dd._select_all_btn.cget("text") == "Select all"


def test_long_labels_cut_from_the_start_keeping_the_leaf(tk_root):
    label = "My Sets / LiveSets / 02. CrumbsAndCream"
    dd = _searchable(tk_root, [("rekordbox:9", "A" * 5 + " / " + label, "rekordbox")])
    box = next(r.widget for r in dd._rows if r.key == "rekordbox:9")
    assert box.cget("text").startswith("\u2026")
    assert box.cget("text").endswith("02. CrumbsAndCream")
