"""Suggestion-row copy column (copy-track-search-text plan T3.5).

Live Tk root; skips cleanly without a display. Labels are compared against the
``library_copy`` constants, never literal glyphs, so the brief can change them.
"""

from __future__ import annotations

import time
from unittest.mock import Mock

import pytest

tk = pytest.importorskip("tkinter")

# Project imports after the tkinter skip.
from source.models.track import Track  # noqa: E402
from source.services import library_copy as strings  # noqa: E402
from source.services.harmonic_tier import HarmonicTier  # noqa: E402
from source.services.paste_query import paste_query  # noqa: E402
from source.services.suggestion_engine import ScoredTrack  # noqa: E402
from source.ui import copy_button as copy_button_module  # noqa: E402
from source.ui.copy_button import CopyButton, CopyState  # noqa: E402
from source.ui.copy_button import _GLYPH_ON_FILL, _HOVER_FILL  # noqa: E402

FAST_FEEDBACK_MS = 300
_TIMER_SLACK_MS = 150


@pytest.fixture
def fast_feedback(monkeypatch):
    monkeypatch.setattr(copy_button_module, "COPY_FEEDBACK_MS", FAST_FEEDBACK_MS)


class _Recorder:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls: list[Track] = []

    def __call__(self, track: Track) -> bool:
        self.calls.append(track)
        return self.result


def _scored(tracks: list[Track]) -> list[ScoredTrack]:
    return [
        ScoredTrack(
            track=t, total_score=0.8, key_score=1.0, energy_score=1.0, bpm_score=1.0,
            harmonic_tier=HarmonicTier.PERFECT,
        )
        for t in tracks
    ]


def _three(make_track) -> list[Track]:
    return [
        make_track(title=f"Track {i} (Extended Mix)", full_file_path=f"/m/{i}.mp3")
        for i in range(3)
    ]


def _make_panel(tk_root, *, on_copy=None, audio_player=None):
    from source.ui.suggestion_panel import SuggestionPanel

    on_select = _Recorder()
    p = SuggestionPanel(tk_root, on_select=on_select, on_copy=on_copy, audio_player=audio_player)
    p.grid()
    renders: list[int] = []
    real = p.set_suggestions

    def counting(scored):
        renders.append(len(scored))
        real(scored)

    p.set_suggestions = counting  # type: ignore[method-assign]
    p.renders = renders  # type: ignore[attr-defined]
    p.on_select_recorder = on_select  # type: ignore[attr-defined]
    p._pointer_over_list = lambda: False  # type: ignore[method-assign]
    return p


def _rows(panel) -> list:
    return [w for w in panel.scroll_frame.winfo_children() if isinstance(w, tk.Frame)]


def _copy_button(panel, i: int) -> CopyButton:
    row = _rows(panel)[i]
    (btn,) = [w for w in row.winfo_children() if isinstance(w, CopyButton)]
    return btn


def _pump(root, ms: int) -> None:
    deadline = time.perf_counter() + ms / 1000
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.005)


# ── Click behaviour ──


def test_copy_click_calls_on_copy_without_selecting_or_rerendering(tk_root, make_track):
    on_copy = _Recorder()
    panel = _make_panel(tk_root, on_copy=on_copy)
    tracks = _three(make_track)
    panel.set_suggestions(_scored(tracks))
    panel.renders.clear()

    _copy_button(panel, 0).invoke()
    tk_root.update()

    assert on_copy.calls == [tracks[0]]
    assert panel.on_select_recorder.calls == []
    assert panel.renders == []


def test_copy_click_during_preview_does_not_stop_audio(tk_root, make_track):
    player = Mock(available=True, is_playing=True, is_paused=False)
    panel = _make_panel(tk_root, on_copy=_Recorder(), audio_player=player)
    tracks = _three(make_track)
    panel.set_suggestions(_scored(tracks))
    panel._playing_file = tracks[1].full_file_path  # a preview is active
    player.reset_mock()

    _copy_button(panel, 0).invoke()

    player.stop.assert_not_called()
    assert panel.is_previewing


def test_copy_click_without_on_copy_shows_failed(tk_root, make_track):
    panel = _make_panel(tk_root)
    panel.set_suggestions(_scored(_three(make_track)))
    btn = _copy_button(panel, 0)

    btn.invoke()

    assert btn.cget("text") == strings.BUTTON_COPY_FAILED


def test_real_click_on_copy_button_never_reaches_row_select(tk_root, make_track):
    # A real press/release on the button's own parts: Tk delivers it to the
    # button's bindtags (CTk's own click handler), never to the row frame's
    # <Button-1> select binding.
    on_copy = _Recorder()
    panel = _make_panel(tk_root, on_copy=on_copy)
    panel.set_suggestions(_scored(_three(make_track)))
    tk_root.deiconify()
    tk_root.update()
    btn = _copy_button(panel, 0)

    for part in (btn._canvas, btn._text_label):
        part.event_generate("<Button-1>", x=5, y=5)
        part.event_generate("<ButtonRelease-1>", x=5, y=5)
    tk_root.update()

    assert len(on_copy.calls) == 2  # one press per part (canvas, text label)
    assert panel.on_select_recorder.calls == []
    assert panel.renders == [3]

    # Control: the same synthetic event on a cell label does reach row select.
    (score,) = _rows(panel)[0].grid_slaves(row=0, column=1)
    score._label.event_generate("<Button-1>", x=5, y=5)  # CTkLabel binds its inner label
    tk_root.update()
    assert len(panel.on_select_recorder.calls) == 1


# ── Layout ──


def test_copy_button_column_zero_score_column_one(tk_root, make_track):
    panel = _make_panel(tk_root, on_copy=_Recorder())
    panel.set_suggestions(_scored(_three(make_track)))
    row = _rows(panel)[0]

    assert int(_copy_button(panel, 0).grid_info()["column"]) == 0
    (score,) = row.grid_slaves(row=0, column=1)
    assert score.cget("text") == "80%"


def test_header_first_cell_is_copy_at_copy_width(tk_root):
    from source.ui.suggestion_panel import _COL

    panel = _make_panel(tk_root)
    (col_hdr,) = [
        w for w in panel.winfo_children()
        if w.winfo_manager() == "grid" and int(w.grid_info()["row"]) == 2
    ]
    (first,) = col_hdr.grid_slaves(row=0, column=0)

    assert first.cget("text") == strings.HEADER_COPY
    assert first.cget("width") == _COL["copy"]


# ── States and tooltips ──


def test_track_with_nothing_to_copy_has_disabled_button_with_tooltip(tk_root):
    panel = _make_panel(tk_root, on_copy=_Recorder())
    panel.set_suggestions(_scored([Track(full_file_path="/m/empty.mp3")]))
    btn = _copy_button(panel, 0)

    assert btn.cget("state") == "disabled"
    assert btn.cget("text") == strings.BUTTON_COPY_DISABLED
    assert btn.tooltip.text == strings.COPY_NOTHING


def test_ready_tooltip_previews_exact_stripped_query(tk_root, make_track):
    panel = _make_panel(tk_root, on_copy=_Recorder())
    tracks = _three(make_track)
    panel.set_suggestions(_scored(tracks))
    btn = _copy_button(panel, 2)
    query = paste_query(tracks[2].artist, tracks[2].title, tracks[2].file_name)

    assert query == "Test Artist Track 2"
    assert btn.cget("text") == strings.BUTTON_COPY
    assert btn.tooltip.text == strings.format_copy_tooltip(query)


def test_glyphs_and_tooltips_follow_state_then_return_to_ready(
    tk_root, make_track, fast_feedback,
):
    on_copy = _Recorder(result=True)
    panel = _make_panel(tk_root, on_copy=on_copy)
    panel.set_suggestions(_scored(_three(make_track)))
    btn = _copy_button(panel, 0)
    query = "Test Artist Track 0"
    glyphs = {
        strings.BUTTON_COPY, strings.BUTTON_COPIED,
        strings.BUTTON_COPY_FAILED, strings.BUTTON_COPY_DISABLED,
    }
    assert len(glyphs) == 4

    btn.invoke()
    assert btn.cget("text") == strings.BUTTON_COPIED
    assert btn.tooltip.text == strings.format_copied_tooltip(query)
    _pump(tk_root, FAST_FEEDBACK_MS + _TIMER_SLACK_MS)
    assert btn.cget("text") == strings.BUTTON_COPY
    assert btn.tooltip.text == strings.format_copy_tooltip(query)

    on_copy.result = False
    btn.invoke()
    assert btn.cget("text") == strings.BUTTON_COPY_FAILED
    assert btn.tooltip.text == strings.COPY_FAILED_TOOLTIP
    _pump(tk_root, FAST_FEEDBACK_MS + _TIMER_SLACK_MS)
    assert btn.cget("text") == strings.BUTTON_COPY
    assert btn.copy_state is CopyState.READY


def test_copied_and_failed_states_hover_with_their_own_fill(tk_root, make_track):
    on_copy = _Recorder(result=True)
    panel = _make_panel(tk_root, on_copy=on_copy)
    panel.set_suggestions(_scored(_three(make_track)))
    btn = _copy_button(panel, 0)
    ready_fill, ready_hover = btn.cget("fg_color"), btn.cget("hover_color")
    assert ready_fill != ready_hover

    btn.invoke()
    assert btn.cget("hover_color") == btn.cget("fg_color") != ready_fill
    on_copy.result = False
    btn.invoke()
    assert btn.cget("hover_color") == btn.cget("fg_color") != ready_fill


def test_copy_click_hides_tooltip(tk_root, make_track):
    panel = _make_panel(tk_root, on_copy=_Recorder())
    panel.set_suggestions(_scored(_three(make_track)))
    btn = _copy_button(panel, 0)
    hides: list[bool] = []
    btn.tooltip.hide = lambda: hides.append(True)  # type: ignore[method-assign]

    btn.invoke()

    assert hides == [True]


# ── Timer rules ──


def test_rapid_clicks_restart_the_timer(tk_root, make_track):
    # Timing-free: the second click replaces the timer; the first never fires.
    panel = _make_panel(tk_root, on_copy=_Recorder())
    panel.set_suggestions(_scored(_three(make_track)))
    btn = _copy_button(panel, 0)

    btn.invoke()
    first_id = btn._after_id
    btn.invoke()
    second_id = btn._after_id

    assert first_id is not None and second_id is not None
    assert second_id != first_id
    assert first_id not in tk_root.tk.splitlist(tk_root.tk.call("after", "info"))
    assert btn.cget("text") == strings.BUTTON_COPIED

    btn._on_timer()  # the restarted timer firing
    assert btn.cget("text") == strings.BUTTON_COPY
    assert CopyButton._flashing is None


def test_only_one_button_flashes_at_a_time(tk_root, make_track):
    panel = _make_panel(tk_root, on_copy=_Recorder())
    panel.set_suggestions(_scored(_three(make_track)))
    first, second = _copy_button(panel, 0), _copy_button(panel, 1)

    first.invoke()
    second.invoke()

    assert first.cget("text") == strings.BUTTON_COPY
    assert first._after_id is None
    assert second.cget("text") == strings.BUTTON_COPIED
    assert CopyButton._flashing is second


def test_rerender_destroys_flashing_button_without_stale_timer(
    tk_root, make_track, fast_feedback,
):
    panel = _make_panel(tk_root, on_copy=_Recorder())
    panel.set_suggestions(_scored(_three(make_track)))
    _copy_button(panel, 0).invoke()

    panel.set_suggestions(_scored([make_track(full_file_path="/m/new.mp3")]))
    _pump(tk_root, FAST_FEEDBACK_MS + _TIMER_SLACK_MS)

    assert CopyButton._flashing is None
    assert tk_root.callback_errors == []
    assert _copy_button(panel, 0).cget("text") == strings.BUTTON_COPY


def test_failed_flash_cleared_by_another_buttons_copy(tk_root, make_track):
    on_copy = _Recorder(result=False)
    panel = _make_panel(tk_root, on_copy=on_copy)
    panel.set_suggestions(_scored(_three(make_track)))
    first, second = _copy_button(panel, 0), _copy_button(panel, 1)

    first.invoke()
    assert first.cget("text") == strings.BUTTON_COPY_FAILED
    on_copy.result = True
    second.invoke()

    assert first.cget("text") == strings.BUTTON_COPY
    assert first.copy_state is CopyState.READY
    assert second.cget("text") == strings.BUTTON_COPIED


def test_destroy_cancels_pending_tooltip_show(tk_root, make_track):
    panel = _make_panel(tk_root, on_copy=_Recorder())
    panel.set_suggestions(_scored(_three(make_track)))
    btn = _copy_button(panel, 0)
    tip = btn.tooltip
    tip.delay = 20
    tip._schedule(None)
    assert tip._after_id is not None

    btn.destroy()
    _pump(tk_root, 120)

    assert tip._after_id is None
    assert tip._tip_window is None
    assert tk_root.callback_errors == []


# -- Hover look --


def test_ready_hover_paints_accent_fill_and_white_glyph(tk_root, make_track):
    panel = _make_panel(tk_root, on_copy=_Recorder())
    panel.set_suggestions(_scored(_three(make_track)))
    tk_root.deiconify()
    tk_root.update()
    btn = _copy_button(panel, 0)

    btn._canvas.event_generate("<Enter>")
    tk_root.update()

    assert btn._canvas.itemcget("inner_parts", "fill").lower() == _HOVER_FILL
    assert str(btn._text_label.cget("fg")).lower() == _GLYPH_ON_FILL

    btn._canvas.event_generate("<Leave>")
    tk_root.update()
    assert btn._canvas.itemcget("inner_parts", "fill").lower() != _HOVER_FILL
