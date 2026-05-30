"""Shared pytest fixtures for the Serato Sidecar test suite.

This is the project's first ``tests/`` directory — see
``plans/extended-camelot-matching-2026-05/`` and ``docs/testing-strategy.md``.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from source.models.library import TrackLibrary
from source.models.track import Track

# Type alias for the make_track factory fixture.
MakeTrack = Callable[..., Track]


@pytest.fixture
def make_track() -> MakeTrack:
    """Return a factory that builds a ``Track`` with sensible defaults.

    Each call gets a unique ``full_file_path`` unless one is supplied, so a
    set of tracks built by the factory never collide on the library key.
    """
    counter = {"n": 0}

    def _make(
        camelot_key: str = "8A",
        bpm: float = 124.0,
        energy: int = 5,
        *,
        title: str | None = None,
        artist: str = "Test Artist",
        genre: str = "House",
        crates: list[str] | None = None,
        full_file_path: str | None = None,
        date_added: float = 0.0,
    ) -> Track:
        counter["n"] += 1
        n = counter["n"]
        path = full_file_path if full_file_path is not None else f"/music/track_{n}.mp3"
        return Track(
            file_name=f"track_{n}.mp3",
            title=title if title is not None else f"Track {n}",
            artist=artist,
            bpm=bpm,
            camelot_key=camelot_key,
            genre=genre,
            energy=energy,
            date_added=date_added,
            full_file_path=path,
            crates=list(crates) if crates is not None else [],
        )

    return _make


@pytest.fixture
def sample_track(make_track: MakeTrack) -> Track:
    """A single representative track (8A, 124 BPM, energy 5)."""
    return make_track()


def _library_from(tracks: list[Track]) -> TrackLibrary:
    """Build a TrackLibrary populated with the given tracks (keyed by path)."""
    library = TrackLibrary()
    for track in tracks:
        library._tracks[track.full_file_path] = track  # noqa: SLF001 - test setup
    return library


@pytest.fixture
def make_library() -> Callable[[list[Track]], TrackLibrary]:
    """Return a factory that builds a TrackLibrary from a list of tracks."""
    return _library_from


@pytest.fixture
def empty_library() -> TrackLibrary:
    """An empty TrackLibrary."""
    return TrackLibrary()
