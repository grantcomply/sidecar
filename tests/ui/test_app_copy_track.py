"""``DJTrackSelectorApp._copy_track_text`` (copy-track-search-text plan T2.4).

No window is built: the method runs against a stub ``self`` with a real
``TrackLibrary``, a recording ``_show_toast`` and a monkeypatched clipboard.
Synthetic data only.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from source import app as app_module
from source.app import SHORT_TOAST_MS, DJTrackSelectorApp
from source.config import ERROR_COLOR, SUCCESS_COLOR
from source.models.library import TrackLibrary
from source.models.path_identity import path_key
from source.models.track import Track
from source.services import library_copy as copy


class _Clipboard:
    """Records what reaches the clipboard; returns a fixed outcome."""

    def __init__(self, ok: bool) -> None:
        self.ok = ok
        self.texts: list[str] = []

    def __call__(self, widget: object, text: str) -> bool:
        self.texts.append(text)
        return self.ok


def _library(*tracks: Track) -> TrackLibrary:
    library = TrackLibrary()
    library.replace_all({path_key(t.full_file_path): t for t in tracks}, {})
    return library


def _stub_app(library: TrackLibrary) -> SimpleNamespace:
    stub = SimpleNamespace(
        library=library,
        toasts=[],
        session_panel=Mock(),
        dashboard=Mock(),
        suggestion_panel=Mock(),
        _audio_player=Mock(),
        _current_track=None,
    )
    stub._current_object = (
        lambda t: DJTrackSelectorApp._current_object(stub, t)  # type: ignore[arg-type]
    )
    # No defaults: a toast that relies on _show_toast's own defaults records None,
    # so the tests prove the colour and SHORT_TOAST_MS are passed explicitly.
    stub._show_toast = lambda text, color=None, duration=None, **kw: stub.toasts.append(
        (text, color, duration)
    )
    return stub


def _copy(stub: SimpleNamespace, track: Track) -> bool:
    return DJTrackSelectorApp._copy_track_text(stub, track)  # type: ignore[arg-type]


@pytest.fixture
def clipboard_ok(monkeypatch: pytest.MonkeyPatch) -> _Clipboard:
    recorder = _Clipboard(ok=True)
    monkeypatch.setattr(app_module, "copy_to_clipboard", recorder)
    return recorder


@pytest.fixture
def clipboard_fail(monkeypatch: pytest.MonkeyPatch) -> _Clipboard:
    recorder = _Clipboard(ok=False)
    monkeypatch.setattr(app_module, "copy_to_clipboard", recorder)
    return recorder


def test_copy_track_text_success_copies_query_and_shows_green_toast(make_track, clipboard_ok):
    track = make_track()
    stub = _stub_app(_library(track))

    assert _copy(stub, track) is True
    assert clipboard_ok.texts == ["Test Artist Track 1"]
    assert stub.toasts == [('Copied "Test Artist Track 1"', SUCCESS_COLOR, SHORT_TOAST_MS)]


def test_copy_track_text_stripped_query_reaches_clipboard_and_toast(make_track, clipboard_ok):
    track = make_track(title="Track One (Extended Mix)")
    stub = _stub_app(_library(track))

    assert _copy(stub, track) is True
    assert clipboard_ok.texts == ["Test Artist Track One"]
    assert stub.toasts[0][0] == copy.format_copied_toast("Test Artist Track One")


def test_copy_track_text_stale_row_copies_library_current_object(make_track, clipboard_ok):
    stale = make_track(title="Old Title", full_file_path="/music/a.mp3")
    fresh = make_track(title="New Title", full_file_path="/music/a.mp3")
    stub = _stub_app(_library(fresh))

    assert _copy(stub, stale) is True
    assert clipboard_ok.texts == ["Test Artist New Title"]


def test_copy_track_text_track_gone_from_library_copies_row_object(make_track, clipboard_ok):
    track = make_track(title="Row Title")
    stub = _stub_app(_library())

    assert _copy(stub, track) is True
    assert clipboard_ok.texts == ["Test Artist Row Title"]


def test_copy_track_text_clipboard_failure_shows_red_toast_returns_false(
    make_track, clipboard_fail,
):
    track = make_track()
    stub = _stub_app(_library(track))

    assert _copy(stub, track) is False
    assert clipboard_fail.texts == ["Test Artist Track 1"]
    assert [(text, color) for text, color, _ in stub.toasts] == [(copy.COPY_FAILED, ERROR_COLOR)]


def test_copy_track_text_nothing_to_copy_no_clipboard_no_toast(clipboard_ok):
    empty = Track(full_file_path="")
    stub = _stub_app(_library())

    assert _copy(stub, empty) is False
    assert clipboard_ok.texts == []
    assert stub.toasts == []


@pytest.mark.parametrize("ok", [True, False])
def test_copy_track_text_changes_no_selection_setlist_preview_or_list(
    make_track, monkeypatch, ok,
):
    monkeypatch.setattr(app_module, "copy_to_clipboard", _Clipboard(ok=ok))
    track = make_track()
    stub = _stub_app(_library(track))

    before = dict(vars(stub))
    toasts_before = list(stub.toasts)

    _copy(stub, track)

    after = dict(vars(stub))
    assert after.keys() == before.keys()
    changed = {k for k in before if after[k] is not before[k]}
    assert changed == set()  # the toast recorder list is mutated in place, never replaced
    assert len(stub.toasts) == len(toasts_before) + 1  # only the toast recorder grew
    assert stub._current_track is None
    collaborators = (stub.session_panel, stub.dashboard, stub.suggestion_panel, stub._audio_player)
    for collaborator in collaborators:
        assert collaborator.mock_calls == []
