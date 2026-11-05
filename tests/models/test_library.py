"""Tests for ``TrackLibrary`` with the crate index (ADR-015 D3/D6)."""

from __future__ import annotations

from source.models.library import TrackLibrary
from source.models.track import Track
from source.providers.base import CrateInfo
from source.services.library_merge import path_key


def _crate(stem: str, label: str) -> CrateInfo:
    return CrateInfo(f"serato:{stem}", "serato", label, tuple(stem.split("%%")))


def _library(make_track, tracks, crates) -> TrackLibrary:
    library = TrackLibrary()
    library.replace_all({path_key(t.full_file_path): t for t in tracks}, crates)
    return library


def test_replace_all_replaces_previous_contents(make_track):
    library = _library(make_track, [make_track(), make_track()], {})
    assert library.count == 2

    library.replace_all({}, {})

    assert library.count == 0
    assert library.crate_items == []


def test_crate_items_excludes_empty_crates_and_sorts_by_path_case_insensitively(make_track):
    crates = {
        c.id: c for c in [
            _crate("house", "house"), _crate("Zed", "Zed"), _crate("A%%B", "A - B"),
            _crate("Empty", "Empty"),
        ]
    }
    tracks = [
        make_track(crates=["serato:house", "serato:A%%B"]),
        make_track(crates=["serato:Zed"]),
    ]
    library = _library(make_track, tracks, crates)

    # casefold on the path tuple (T3c.10): A/B, house, Zed.
    assert library.crate_items == [
        ("serato:A%%B", "A - B"), ("serato:house", "house"), ("serato:Zed", "Zed"),
    ]
    assert library.crate_count == 3
    assert library.crate_provider("serato:Zed") == "serato"
    assert library.crate_provider("nope") is None


def test_crate_items_unknown_id_uses_id_as_label(make_track):
    library = _library(make_track, [make_track(crates=["serato:Ghost"])], {})
    assert library.crate_items == [("serato:Ghost", "serato:Ghost")]


def test_crate_label_falls_back_to_raw_id(make_track):
    library = _library(make_track, [], {"serato:A%%B": _crate("A%%B", "A - B")})

    assert library.crate_label("serato:A%%B") == "A - B"
    assert library.crate_label("serato:missing") == "serato:missing"


def test_track_by_path_normalises(make_track):
    track = make_track(full_file_path="/music/sub/../song.mp3")
    library = _library(make_track, [track], {})

    assert library.track_by_path("/music/song.mp3") is track
    assert library.track_by_path("/music/other.mp3") is None


def test_search_still_matches_title(make_track):
    # Built via from_dict (the real load path), which fills search_text.
    tracks = [
        Track.from_dict({"title": "Deep Groove"}, "/music/1.mp3"),
        Track.from_dict({"title": "Peak"}, "/music/2.mp3"),
    ]
    library = _library(make_track, tracks, {})

    assert [t.title for t in library.search("groove")] == ["Deep Groove"]
    assert library.search("  ") == []


# ── Attribution helpers (T5.3 leaf pill, T5.4 tooltip lines) ──


def _rb(native: str, path: tuple[str, ...]) -> CrateInfo:
    return CrateInfo(f"rekordbox:{native}", "rekordbox", " / ".join(path), path)


def test_crate_leaf_is_last_path_part_with_fallbacks(make_track):
    crates = {
        "rekordbox:1": _rb("1", ("Club", "Peak")),
        "serato:A%%B": _crate("A%%B", "A - B"),
        "serato:Odd": CrateInfo("serato:Odd", "serato", "Odd label", ()),
    }
    library = _library(make_track, [], crates)
    assert library.crate_leaf("rekordbox:1") == "Peak"
    assert library.crate_leaf("serato:A%%B") == "B"
    assert library.crate_leaf("serato:Odd") == "Odd label"  # no path: the label
    assert library.crate_leaf("serato:Ghost") == "serato:Ghost"  # unknown: the id


def test_crates_by_provider_groups_labels_in_provider_order(make_track):
    crates = {
        "rekordbox:1": _rb("1", ("Club", "Peak")),
        "rekordbox:2": _rb("2", ("Warm up",)),
        "serato:House": _crate("House", "House"),
        "other:x": CrateInfo("other:x", "other", "X", ("X",)),
    }
    library = _library(make_track, [], crates)
    ids = ["serato:House", "other:x", "rekordbox:2", "serato:Ghost", "rekordbox:1"]

    assert library.crates_by_provider(ids, ["rekordbox", "serato"]) == [
        ("rekordbox", ["Warm up", "Club / Peak"]),  # input order kept inside a group
        ("serato", ["House"]),
        ("other", ["X"]),  # not in the order: after the known ones
        (None, ["serato:Ghost"]),  # unknown crate: last, raw id
    ]
    assert library.crates_by_provider(["serato:House"], ["rekordbox", "serato"]) == [
        ("serato", ["House"]),  # a provider without the track gets no group
    ]
