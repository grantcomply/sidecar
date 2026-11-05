"""Synthetic stand-ins for pyrekordbox's MasterDatabase (no real library data)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

SYNTHETIC_KEY = "SYNTHETIC-KEY-123"


def content(
    cid: str,
    *,
    title: str = "Synthetic Title",
    artist: str = "Synthetic Artist",
    bpm: int | None = 12400,
    scale: str | None = "Am",
    comment: str = "",
    org: str = "",
    folder: str = "",
    local: str = "",
    plays: int = 0,
    year: int = 0,
    **extra: Any,
) -> SimpleNamespace:
    """A ``djmdContent``-shaped row with the attribute names db_reader reads."""
    return SimpleNamespace(
        ID=cid, Title=title, ArtistName=artist, AlbumName="Synthetic Album",
        GenreName="House", BPM=bpm,
        Key=SimpleNamespace(ScaleName=scale) if scale is not None else None,
        Commnt=comment, DJPlayCount=plays, ReleaseYear=year,
        OrgFolderPath=org, FolderPath=folder, rb_LocalFolderPath=local, **extra,
    )


def playlist(pid: str, name: str, *, parent: str = "root", attribute: int = 0) -> SimpleNamespace:
    return SimpleNamespace(ID=pid, Name=name, ParentID=parent, Attribute=attribute)


def song(pid: str, cid: str, track_no: int) -> SimpleNamespace:
    return SimpleNamespace(PlaylistID=pid, ContentID=cid, TrackNo=track_no)


@dataclass
class FakeMasterDb:
    contents: list[Any]
    playlists: list[Any]
    songs: list[Any]
    quick_check: str = "ok"
    smart_contents: dict[str, list[Any]] | None = None
    raise_on: str | None = None  # name of a read method that should raise
    raise_with: BaseException = field(default_factory=lambda: RuntimeError("boom"))
    calls: list[str] = field(default_factory=list)
    closed: bool = False
    disposed: bool = False

    def __post_init__(self) -> None:
        db = self

        class _Result:
            def scalar(self) -> str:
                return db.quick_check

        class _Session:
            def execute(self, _stmt: Any) -> _Result:
                db._maybe_raise("execute")
                return _Result()

        class _Engine:
            def dispose(self) -> None:
                db.disposed = True

        self.session = _Session()
        self.engine = _Engine()

    def _maybe_raise(self, name: str) -> None:
        self.calls.append(name)
        if self.raise_on == name:
            raise self.raise_with

    def get_content(self) -> Iterable[Any]:
        self._maybe_raise("get_content")
        return list(self.contents)

    def get_playlist(self) -> Iterable[Any]:
        self._maybe_raise("get_playlist")
        return list(self.playlists)

    def get_playlist_songs(self) -> Iterable[Any]:
        self._maybe_raise("get_playlist_songs")
        return list(self.songs)

    def get_playlist_contents(self, pl: Any) -> Iterable[Any]:
        self._maybe_raise("get_playlist_contents")
        if self.smart_contents is None or pl.ID not in self.smart_contents:
            raise RuntimeError("smart playlist evaluation not supported")
        return list(self.smart_contents[pl.ID])

    def close(self) -> None:
        self.closed = True

    # Write methods: must never be called.
    def commit(self, *_a: Any, **_k: Any) -> None:
        self.calls.append("commit")

    def add(self, *_a: Any, **_k: Any) -> None:
        self.calls.append("add")

    def delete(self, *_a: Any, **_k: Any) -> None:
        self.calls.append("delete")

    def flush(self, *_a: Any, **_k: Any) -> None:
        self.calls.append("flush")

    @property
    def write_calls(self) -> list[str]:
        return [c for c in self.calls if c in ("commit", "add", "delete", "flush")]


def fake_factory(db: FakeMasterDb, opened: list[dict[str, Any]] | None = None):
    """A ``db_factory`` returning ``db`` and recording its keyword arguments."""

    def _factory(**kw: Any) -> FakeMasterDb:
        if opened is not None:
            opened.append(kw)
        return db

    return _factory
