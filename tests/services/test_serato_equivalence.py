"""Golden-equivalence test for the Serato provider refactor (blueprint R1).

1. ``SeratoProvider.scan`` flattened back to the v3 shape (``_to_v3``, kept
   here as a local helper since Phase 2 stopped writing v3) must equal what
   the pre-provider code produced (``parse_all_crates`` with its default
   display-name crate key).
2. Upgrade path: a legacy v3 cache converted by ``library_store`` must load
   the same library (tracks, crate ids and labels) as a fresh provider sync.

Uses real ``.crate`` bytes and a deterministic metadata stub.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from source.models.library import TrackLibrary
from source.providers.base import ProviderSnapshot
from source.providers.serato.provider import SeratoProvider
from source.services import crate_parser, library_merge, library_store
from tests.fixtures.crate_bytes import write_crate


def _to_v3(snapshot: ProviderSnapshot) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    """Flatten a snapshot to the legacy v3 cache shape ``(tracks, crate_mtimes)``.

    Crate ids map back to labels, preserving order and dropping repeats (the
    pre-provider parser de-duplicated by label).
    """
    tracks: dict[str, dict[str, Any]] = {}
    for path, record in snapshot.tracks.items():
        flat: dict[str, Any] = dict(record)
        labels: list[str] = []
        for crate_id in record.get("crates", []):
            label = snapshot.crates[crate_id].label
            if label not in labels:
                labels.append(label)
        flat["crates"] = labels
        tracks[path] = flat
    return tracks, dict(snapshot.fingerprint)


def _stub_metadata(path: str) -> dict:
    """Deterministic, fresh dict per call (the scan mutates ``crates``)."""
    name = Path(path).name
    return {
        "file_name": name,
        "title": f"Title {name}",
        "artist": "Artist",
        "album": "",
        "bpm": 120.0 + len(name),
        "key": "Am",
        "camelot_key": "8A",
        "genre": "House",
        "date": "2020",
        "comments": "8A - 5 - Groover",
        "energy_level": 5,
        "play_count": 3,
        "date_added": 1_600_000_000.0,
        "full_file_path": path,
    }


def _build_tree(subcrates: Path) -> None:
    # One empty crate, one nested (A%%B), overlapping membership, and a crate
    # whose own name contains " - ".
    write_crate(subcrates, "Empty.crate", [])
    write_crate(subcrates, "Drum - Bass.crate", ["Music/four.mp3"])
    write_crate(subcrates, "A%%B.crate", ["Music/one.mp3", "Music/two.mp3"])
    write_crate(subcrates, "Overlap.crate", ["Music/two.mp3", "Music/three.mp3"])
    write_crate(subcrates, "Zed%%Deep%%Leaf.crate", ["Music/one.mp3", "Music/one.mp3"])


@pytest.fixture
def subcrates(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(crate_parser, "get_track_metadata", _stub_metadata)
    folder = tmp_path / "Subcrates"
    folder.mkdir()
    return folder


def _old_and_new(folder: Path):
    old = crate_parser.parse_all_crates(str(folder))
    new = _to_v3(SeratoProvider().scan({"subcrates_dir": str(folder)}))
    return old, new


def test_provider_v3_output_equals_legacy_parse(subcrates):
    _build_tree(subcrates)

    (old_tracks, old_mtimes), (new_tracks, new_mtimes) = _old_and_new(subcrates)

    assert new_tracks == old_tracks
    assert new_mtimes == old_mtimes
    # Dict order matters for the JSON file: compare key sequences too.
    assert list(new_tracks) == list(old_tracks)
    for path in old_tracks:
        assert list(new_tracks[path]) == list(old_tracks[path])
    # Sanity: the tree exercised what we meant it to.
    assert "Empty.crate" in new_mtimes
    assert any(t["crates"] == ["A - B", "Overlap"] for t in new_tracks.values())


def test_provider_v3_output_equals_legacy_when_labels_collide(subcrates):
    # "A%%B.crate" and "A - B.crate" share the label "A - B". The legacy parser
    # de-duplicated by label; the provider must flatten to the same list.
    write_crate(subcrates, "A%%B.crate", ["Music/one.mp3"])
    write_crate(subcrates, "A - B.crate", ["Music/one.mp3"])

    (old_tracks, old_mtimes), (new_tracks, new_mtimes) = _old_and_new(subcrates)

    assert new_tracks == old_tracks
    assert new_mtimes == old_mtimes


def test_provider_v3_output_equals_legacy_for_no_crates(subcrates):
    assert _old_and_new(subcrates) == (({}, {}), ({}, {}))


def _library(snapshot: ProviderSnapshot) -> TrackLibrary:
    library = TrackLibrary()
    library.replace_all(*library_merge.merge([snapshot]))
    return library


def test_converted_legacy_cache_loads_same_library_as_fresh_sync(subcrates):
    _build_tree(subcrates)
    # What the pre-provider app wrote to track_cache.json (v3).
    tracks, crate_mtimes = crate_parser.parse_all_crates(str(subcrates))
    legacy = {"version": 3, "synced_at": "x", "crate_mtimes": crate_mtimes, "tracks": tracks}

    upgraded_snapshot = library_store.legacy_v3_to_snapshot(legacy)
    fresh_snapshot = SeratoProvider().scan({"subcrates_dir": str(subcrates)})
    # Exact crate ids and empty crates, straight from crate_mtimes filenames.
    assert upgraded_snapshot.crates == fresh_snapshot.crates
    assert upgraded_snapshot.fingerprint == fresh_snapshot.fingerprint
    upgraded = _library(upgraded_snapshot)
    fresh = _library(fresh_snapshot)

    assert upgraded.count == fresh.count == len(tracks)
    assert {t.full_file_path: t for t in upgraded.tracks} == {
        t.full_file_path: t for t in fresh.tracks
    }
    assert upgraded.crate_items == fresh.crate_items
    # Same visible crate list as the old TrackLibrary.crate_names.
    old_crate_names = sorted({name for t in tracks.values() for name in t["crates"]})
    assert [label for _id, label in upgraded.crate_items] == old_crate_names
    assert upgraded.genre_names == fresh.genre_names


def test_converted_snapshot_summary_matches_fresh_sync(subcrates, isolated_data_dir):
    _build_tree(subcrates)
    tracks, crate_mtimes = crate_parser.parse_all_crates(str(subcrates))
    legacy = {"version": 3, "synced_at": "x", "crate_mtimes": crate_mtimes, "tracks": tracks}

    library_store.save_snapshot(library_store.legacy_v3_to_snapshot(legacy))
    upgraded = library_store.snapshot_summary("serato")
    assert library_store.save_snapshot(
        SeratoProvider().scan({"subcrates_dir": str(subcrates)}),
    ) is False  # identical content: a first sync after upgrade changes nothing
    fresh = library_store.snapshot_summary("serato")

    assert upgraded is not None and fresh is not None
    assert (upgraded.track_count, upgraded.crate_count) == (fresh.track_count, fresh.crate_count)
    assert fresh.crate_count == len(crate_mtimes) == 5
