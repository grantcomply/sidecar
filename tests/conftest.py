"""Shared pytest fixtures for the Serato Sidecar test suite.

This is the project's first ``tests/`` directory — see
``plans/extended-camelot-matching-2026-05/`` and ``docs/testing-strategy.md``.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from source.models.library import TrackLibrary
from source.models.path_identity import path_key
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
    """Build a TrackLibrary populated with the given tracks (keyed by path_key, as the app)."""
    library = TrackLibrary()
    for track in tracks:
        library._tracks[path_key(track.full_file_path)] = track  # noqa: SLF001 - test setup
    return library


@pytest.fixture
def make_library() -> Callable[[list[Track]], TrackLibrary]:
    """Return a factory that builds a TrackLibrary from a list of tracks."""
    return _library_from


@pytest.fixture
def empty_library() -> TrackLibrary:
    """An empty TrackLibrary."""
    return TrackLibrary()


def _redirect_config_paths(mp: pytest.MonkeyPatch, data_dir, project_root) -> None:
    from source import config

    mp.setattr(config, "user_data_dir", lambda: data_dir)
    mp.setattr(config, "ENV_FILE", data_dir / "settings.env")
    mp.setattr(config, "PROJECT_ROOT", str(project_root))


@pytest.fixture(scope="session", autouse=True)
def _never_touch_real_user_data(tmp_path_factory):
    """Safety net: by default every test sees a throwaway data dir.

    Redirects ``config.user_data_dir``, ``config.ENV_FILE`` and
    ``config.PROJECT_ROOT`` for the whole session, so code that writes
    settings or snapshots during a test can't reach the real user files.
    Tests that write must still use ``isolated_data_dir``: this session dir is
    shared by every test, so writes here would leak between tests.
    (Importing ``source.config`` still creates the real data dir, as it
    always has; that happens at collection, before fixtures run.)
    """
    base = tmp_path_factory.mktemp("session_user_data")
    data_dir, project_root = base / "data", base / "project"
    data_dir.mkdir()
    project_root.mkdir()
    with pytest.MonkeyPatch.context() as mp:
        _redirect_config_paths(mp, data_dir, project_root)
        yield


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """Give this test its own empty data dir and project root under ``tmp_path``.

    Patches ``config.user_data_dir``, ``config.ENV_FILE`` and
    ``config.PROJECT_ROOT`` for this test only (on top of the session-wide
    redirect). Returns the fake user data directory.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    _redirect_config_paths(monkeypatch, data_dir, project_root)
    return data_dir


@pytest.fixture(scope="session", autouse=True)
def _silence_secret_loggers():
    """Hold pyrekordbox/SQLAlchemy loggers at their minimums for every test (key safety)."""
    from source.services.log_safety import silence_secret_loggers

    silence_secret_loggers()
    yield


@pytest.fixture(scope="session", autouse=True)
def _no_real_rekordbox(tmp_path_factory):
    """Point the rekordbox default DB location at a missing file under a temp folder.

    So no test touches master.db or its folder. Tests that
    need a database pass ``db_path`` explicitly or patch ``default_db_path``.
    """
    from source.providers.rekordbox import paths

    fake = tmp_path_factory.mktemp("no_rekordbox") / "master.db"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(paths, "default_db_path", lambda: fake)
        yield
