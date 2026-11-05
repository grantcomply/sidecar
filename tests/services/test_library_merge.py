"""Tests for ``source.services.library_merge`` (Phase 2: zero or one snapshot)."""

from __future__ import annotations

import logging
import os
import unicodedata

from source.providers.base import CrateInfo, ProviderSnapshot, TrackRecord
from source.services.library_merge import merge, path_key


def _snapshot(
    provider_id: str = "serato", tracks: dict[str, TrackRecord] | None = None,
) -> ProviderSnapshot:
    if tracks is None:
        tracks = {
            "/music/a.mp3": {"title": "A", "camelot_key": "8A", "crates": [f"{provider_id}:X"]},
        }
    crates = {f"{provider_id}:X": CrateInfo(f"{provider_id}:X", provider_id, "X", ("X",))}
    return ProviderSnapshot(provider_id=provider_id, tracks=tracks, crates=crates)


def test_merge_no_snapshots_returns_empty():
    assert merge([]) == ({}, {})


def test_merge_one_snapshot_builds_tracks_keyed_by_path_key():
    tracks, crates = merge([_snapshot()])

    key = path_key("/music/a.mp3")
    assert list(tracks) == [key]
    track = tracks[key]
    assert track.title == "A"
    assert track.camelot_number == 8 and track.camelot_letter == "A"
    assert track.full_file_path == "/music/a.mp3"
    assert track.crates == ["serato:X"]
    assert list(crates) == ["serato:X"]


def test_merge_bad_record_is_skipped_and_logged(caplog):
    records: dict[str, TrackRecord] = {
        "/music/ok.mp3": {"title": "ok"},
        "/music/bad.mp3": "not a dict",  # type: ignore[dict-item]
    }
    with caplog.at_level(logging.ERROR, logger="source.services.library_merge"):
        tracks, _ = merge([_snapshot(tracks=records)])

    assert [t.title for t in tracks.values()] == ["ok"]
    assert "bad.mp3" in caplog.text


def test_path_key_normalises_separators_and_dots():
    assert path_key("/music/./sub/../a.mp3") == path_key("/music/a.mp3")


def test_path_key_follows_os_case_rules():
    expected_equal = os.path.normcase("A") == os.path.normcase("a")
    assert (path_key("/Music/A.mp3") == path_key("/music/a.mp3")) is expected_equal


def test_path_key_unifies_nfd_and_nfc():
    nfc = unicodedata.normalize("NFC", "/music/Café.mp3")
    nfd = unicodedata.normalize("NFD", "/music/Café.mp3")
    assert nfc != nfd
    assert path_key(nfc) == path_key(nfd)


def test_merge_case_variant_paths_keep_first_and_union_crates(monkeypatch):
    # Simulate Windows case-insensitivity regardless of the test OS.
    monkeypatch.setattr(os.path, "normcase", str.lower)
    records: dict[str, TrackRecord] = {
        "/Music/A.mp3": {"title": "First", "crates": ["serato:X", "serato:Y"]},
        "/music/a.mp3": {"title": "Second", "crates": ["serato:Y", "serato:Z", "serato:Z"]},
    }

    tracks, _ = merge([_snapshot(tracks=records)])

    assert len(tracks) == 1
    track = next(iter(tracks.values()))
    assert track.title == "First"
    assert track.full_file_path == "/Music/A.mp3"
    assert track.crates == ["serato:X", "serato:Y", "serato:Z"]


def test_merge_reexports_path_key_from_models():
    from source.models import path_identity
    from source.services import library_merge

    assert library_merge.path_key is path_identity.path_key


# ── Multi-provider merge (T4.1, T4.2, T4.5) ──

from source.models.library import TrackLibrary  # noqa: E402
from source.services.suggestion_engine import get_suggestions  # noqa: E402
from source.services.suggestion_filters import SuggestionFilters  # noqa: E402


def _snap(pid: str, tracks: dict, crates: list[str]) -> ProviderSnapshot:
    return ProviderSnapshot(
        provider_id=pid,
        tracks=tracks,
        crates={c: CrateInfo(c, pid, c.split(":", 1)[1], (c.split(":", 1)[1],)) for c in crates},
    )


def _rb(tracks: dict) -> ProviderSnapshot:
    return _snap("rekordbox", tracks, ["rekordbox:41", "rekordbox:42"])


def _serato(tracks: dict) -> ProviderSnapshot:
    return _snap("serato", tracks, ["serato:House%%Bangers", "serato:Empty"])


SHARED = "/music/shared.mp3"


def _both():
    rb = _rb({SHARED: {
        "title": "RB Title", "camelot_key": "8A", "key": "Am", "bpm": 124.0,
        "comments": "8A - 7 - Banger", "energy_level": 7, "genre": "",
        "crates": ["rekordbox:41"],
    }})
    se = _serato({SHARED: {
        "title": "Serato Title", "camelot_key": "4A", "key": "Fm", "bpm": 0.0,
        "comments": "4A - 3", "energy_level": 3, "genre": "House",
        "crates": ["serato:House%%Bangers"],
    }})
    return rb, se


def test_same_path_in_two_snapshots_becomes_one_track_with_union_and_sources():
    tracks, crates = merge(list(_both()))

    assert len(tracks) == 1
    track = next(iter(tracks.values()))
    assert track.crates == ["rekordbox:41", "serato:House%%Bangers"]
    assert track.sources == ("rekordbox", "serato")
    assert set(crates) == {"rekordbox:41", "rekordbox:42", "serato:House%%Bangers", "serato:Empty"}


def test_rekordbox_scalars_win_and_empty_values_fall_back():
    track = next(iter(merge(list(_both()))[0].values()))

    assert (track.title, track.camelot_key, track.key) == ("RB Title", "8A", "Am")
    assert (track.comments, track.energy) == ("8A - 7 - Banger", 7)
    assert track.bpm == 124.0
    assert track.genre == "House"  # rekordbox left it empty: Serato fills it


def test_bpm_zero_from_rekordbox_falls_back_to_serato():
    rb = _rb({SHARED: {"bpm": 0.0, "crates": []}})
    se = _serato({SHARED: {"bpm": 126.0, "crates": []}})
    assert next(iter(merge([rb, se])[0].values())).bpm == 126.0


def test_sources_follow_precedence_order():
    rb, se = _both()
    track = next(iter(merge([se, rb])[0].values()))  # serato given first
    assert track.sources == ("serato", "rekordbox")
    assert track.title == "Serato Title"


def test_full_file_path_from_highest_precedence_record(monkeypatch):
    monkeypatch.setattr(os.path, "normcase", str.lower)
    rb = _rb({"C:/Music/A.mp3": {"title": "x", "crates": []}})
    se = _serato({r"c:\music\a.mp3": {"title": "y", "crates": []}})
    tracks, _ = merge([rb, se])
    assert [t.full_file_path for t in tracks.values()] == ["C:/Music/A.mp3"]


def test_windows_case_and_separators_merge(monkeypatch):
    monkeypatch.setattr(os.path, "normcase", lambda p: p.lower().replace("/", "\\"))
    rb = _rb({os.path.normpath("C:/Music/A.mp3"): {"crates": ["rekordbox:41"]}})
    se = _serato({r"C:\Music\A.mp3": {"crates": ["serato:House%%Bangers"]}})
    assert len(merge([rb, se])[0]) == 1


def test_nfd_and_nfc_names_merge():
    nfc = unicodedata.normalize("NFC", "/music/Café.mp3")
    nfd = unicodedata.normalize("NFD", "/music/Café.mp3")
    tracks, _ = merge([_rb({nfc: {"crates": []}}), _serato({nfd: {"crates": []}})])
    assert len(tracks) == 1
    assert next(iter(tracks.values())).sources == ("rekordbox", "serato")


def test_disjoint_tracks_both_present_with_own_sources():
    rb = _rb({"/m/rb.mp3": {"title": "R", "crates": []}})
    se = _serato({"/m/se.mp3": {"title": "S", "crates": []}})
    tracks, _ = merge([rb, se])
    assert sorted((t.title, t.sources) for t in tracks.values()) == [
        ("R", ("rekordbox",)), ("S", ("serato",)),
    ]


def test_crate_id_collision_logged_and_first_kept(caplog):
    a = _snap("rekordbox", {}, ["shared:1"])
    b = _snap("serato", {}, ["shared:1"])
    b.crates["shared:1"] = CrateInfo("shared:1", "serato", "other", ("other",))
    with caplog.at_level(logging.ERROR, logger="source.services.library_merge"):
        _, crates = merge([a, b])
    assert crates["shared:1"].provider_id == "rekordbox"
    assert "more than one snapshot" in caplog.text


def test_crate_filter_admits_merged_track_via_either_crate(make_track):
    rb, se = _both()
    other = _rb({"/m/now.mp3": {"title": "Now", "camelot_key": "8A", "bpm": 124.0,
                                "energy_level": 6, "crates": ["rekordbox:42"]}})
    rb.tracks.update(other.tracks)
    tracks, crates = merge([rb, se])
    library = TrackLibrary()
    library.replace_all(tracks, crates)
    current = library.track_by_path("/m/now.mp3")
    assert current is not None

    scored = get_suggestions(current, library, filters=SuggestionFilters(
        allowed_crates=frozenset({"serato:House%%Bangers"}),  # rekordbox:41 not selected
    ))

    assert [s.track.full_file_path for s in scored] == [SHARED]


def test_sources_round_trip_through_track_from_dict():
    from source.models.track import Track

    assert Track.from_dict({"sources": ["rekordbox", "serato"]}, "/x").sources == (
        "rekordbox", "serato",
    )
    assert Track.from_dict({}, "/x").sources == ()


# ── Phase 3c review merge rules ──


def test_energy_zero_from_rekordbox_falls_back_to_serato():
    rb = _rb({SHARED: {"energy_level": 0, "crates": []}})
    se = _serato({SHARED: {"energy_level": 5, "crates": []}})
    assert next(iter(merge([rb, se])[0].values())).energy == 5


def test_key_and_camelot_taken_as_a_pair():
    # rekordbox has a musical key but no Camelot value; Serato has both.
    rb = _rb({SHARED: {"key": "Am", "camelot_key": "", "crates": []}})
    se = _serato({SHARED: {"key": "Fm", "camelot_key": "4A", "crates": []}})
    track = next(iter(merge([rb, se])[0].values()))
    assert (track.key, track.camelot_key) == ("Fm", "4A")  # never "Am" beside "4A"


def test_key_pair_from_rekordbox_when_it_has_camelot():
    rb = _rb({SHARED: {"key": "", "camelot_key": "8A", "crates": []}})
    se = _serato({SHARED: {"key": "Fm", "camelot_key": "4A", "crates": []}})
    track = next(iter(merge([rb, se])[0].values()))
    assert (track.key, track.camelot_key) == ("", "8A")


def test_native_play_count_of_first_provider_wins_even_when_zero():
    rb = _rb({SHARED: {"play_count": 0, "crates": []}})
    se = _serato({SHARED: {"play_count": 12, "crates": []}})
    native = merge([rb, se], native_play_count={"rekordbox", "serato"})[0]
    assert next(iter(native.values())).play_count == 0
    # Without the capability the generic first-non-empty rule applies.
    generic = merge([rb, se])[0]
    assert next(iter(generic.values())).play_count == 12
