"""Merge provider snapshots into the in-memory library (ADR-015 D6).

Pure functions. Snapshots are given in precedence order (registry order,
rekordbox first). Tracks are identified by ``path_key`` only (the user's
libraries share file paths). For a file found in several snapshots:

- ``crates`` is the ordered union of every snapshot's crate ids;
- ``sources`` is the ordered tuple of provider ids that contain it;
- every other field takes the first non-empty value in precedence order
  (``""``, ``0``, ``0.0`` and ``None`` count as empty), so rekordbox's key,
  BPM, comments and energy win and Serato only fills fields rekordbox leaves
  empty. Two exceptions (Phase 3c review):
  - ``key`` and ``camelot_key`` are taken as a pair from the first record with
    a non-empty ``camelot_key``, so a track never shows one provider's key
    beside the other's Camelot value;
  - ``play_count``: if the highest-precedence record's provider declares
    ``NATIVE_PLAY_COUNT`` (``native_play_count``), its value wins even when 0;
- ``full_file_path`` is the highest-precedence record's path.

The crate index is the union of all snapshots' crates; ids are
provider-namespaced, so a collision means a bug (logged, first kept).
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Sequence
from typing import Any

from source.models.path_identity import path_key
from source.models.track import Track
from source.providers.base import CrateInfo, ProviderSnapshot

logger = logging.getLogger(__name__)

__all__ = ["merge", "merge_records", "path_key"]  # path_key re-exported from models.path_identity

_NOT_MERGED_AS_SCALARS = frozenset({"crates", "full_file_path", "sources"})
_KEY_PAIR = ("key", "camelot_key")


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, (int, float)) and value == 0)


class _Group:
    """One file's records across snapshots, in precedence order."""

    __slots__ = ("path", "fields", "crates", "sources", "key_pair_set", "play_count_locked")

    def __init__(self, path: str) -> None:
        self.path = path  # highest-precedence record's path
        self.fields: dict[str, Any] = {}
        self.crates: list[str] = []
        self.sources: list[str] = []
        self.key_pair_set = False
        self.play_count_locked = False

    def add(self, provider_id: str, record: dict[str, Any], native_play_count: bool) -> None:
        first_record = not self.sources
        if first_record and native_play_count and "play_count" in record:
            self.fields["play_count"] = record["play_count"]  # authoritative, even 0
            self.play_count_locked = True
        if not self.key_pair_set and not _is_empty(record.get("camelot_key")):
            self.fields["key"] = record.get("key", "")
            self.fields["camelot_key"] = record["camelot_key"]
            self.key_pair_set = True
        for name, value in record.items():
            if name in _NOT_MERGED_AS_SCALARS:
                continue
            if (name in _KEY_PAIR and self.key_pair_set) or (
                name == "play_count" and self.play_count_locked
            ):
                self.fields.setdefault(name, value)
                continue
            if _is_empty(self.fields.get(name)) and not _is_empty(value):
                self.fields[name] = value
            else:
                self.fields.setdefault(name, value)
        for crate_id in record.get("crates", []) or []:
            if crate_id not in self.crates:
                self.crates.append(crate_id)
        if provider_id not in self.sources:
            self.sources.append(provider_id)

    def as_record(self) -> dict[str, Any]:
        return {
            **self.fields,
            "full_file_path": self.path,
            "crates": list(self.crates),
            "sources": tuple(self.sources),
        }


def merge_records(
    snapshots: Sequence[ProviderSnapshot],
    native_play_count: Collection[str] = (),
) -> dict[str, dict[str, Any]]:
    """Merged track dicts keyed by ``path_key`` (pure; the record-level half of ``merge``).

    ``native_play_count``: provider ids that declare ``NATIVE_PLAY_COUNT``.
    """
    groups: dict[str, _Group] = {}
    for snapshot in snapshots:
        for path, record in snapshot.tracks.items():
            if not isinstance(record, dict):
                logger.error("Error loading track %s from %s: not a record", path,
                             snapshot.provider_id)
                continue
            key = path_key(path)
            group = groups.get(key)
            if group is None:
                group = groups[key] = _Group(path)
            group.add(snapshot.provider_id, dict(record),
                      snapshot.provider_id in native_play_count)
    return {key: group.as_record() for key, group in groups.items()}


def _merge_crates(snapshots: Sequence[ProviderSnapshot]) -> dict[str, CrateInfo]:
    crates: dict[str, CrateInfo] = {}
    for snapshot in snapshots:
        for crate_id, info in snapshot.crates.items():
            if crate_id in crates:
                logger.error(
                    "Crate id %r appears in more than one snapshot (%s); keeping the first",
                    crate_id, snapshot.provider_id,
                )
                continue
            crates[crate_id] = info
    return crates


def merge(
    snapshots: Sequence[ProviderSnapshot],
    native_play_count: Collection[str] = (),
) -> tuple[dict[str, Track], dict[str, CrateInfo]]:
    """Build ``Track`` objects keyed by ``path_key`` plus the combined crate index."""
    tracks: dict[str, Track] = {}
    for key, record in merge_records(snapshots, native_play_count).items():
        try:
            tracks[key] = Track.from_dict(record, record["full_file_path"])
        except (TypeError, ValueError, AttributeError) as e:
            logger.error("Error loading track %s: %s", record.get("full_file_path"), e)
    crates = _merge_crates(snapshots)
    logger.info(
        "Loaded %d tracks from %s",
        len(tracks), ", ".join(s.provider_id for s in snapshots) or "no snapshots",
    )
    return tracks, crates
