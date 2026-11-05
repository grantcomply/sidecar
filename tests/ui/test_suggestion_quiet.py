"""Quiet suggestion re-render after a live refresh (Phase 3b review, items 3c and 4).

Needs a live Tk root; skips cleanly where no display is available.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from source.services.harmonic_tier import HarmonicTier
from source.services.suggestion_engine import ScoredTrack

tk = pytest.importorskip("tkinter")


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tk widget tests")
    root.withdraw()
    yield root
    root.destroy()


def _scored(make_track, n=3, score=0.8, title_prefix="T"):
    return [
        ScoredTrack(
            track=make_track(title=f"{title_prefix}{i}", full_file_path=f"/m/{i}.mp3"),
            total_score=score, key_score=1.0, energy_score=1.0, bpm_score=1.0,
            harmonic_tier=HarmonicTier.PERFECT,
        )
        for i in range(n)
    ]


@pytest.fixture
def panel(tk_root):
    from source.ui.suggestion_panel import SuggestionPanel

    p = SuggestionPanel(tk_root)
    p.grid()
    renders: list[int] = []
    real = p.set_suggestions

    def counting(scored):
        renders.append(len(scored))
        real(scored)

    p.set_suggestions = counting  # type: ignore[method-assign]
    p.renders = renders  # type: ignore[attr-defined]
    p._pointer_over_list = lambda: False  # type: ignore[method-assign]
    return p


def test_same_visible_content_does_not_rerender(panel, make_track):
    panel.set_suggestions(_scored(make_track))
    panel.renders.clear()

    panel.show_suggestions_quietly(_scored(make_track))  # equal by value, new objects

    assert panel.renders == []


def test_changed_content_rerenders(panel, make_track):
    panel.set_suggestions(_scored(make_track))
    panel.renders.clear()

    panel.show_suggestions_quietly(_scored(make_track, title_prefix="Edited"))

    assert panel.renders == [3]


def test_pointer_over_list_defers_until_it_leaves(panel, make_track, tk_root):
    panel.set_suggestions(_scored(make_track))
    panel.renders.clear()
    over = {"v": True}
    panel._pointer_over_list = lambda: over["v"]

    panel.show_suggestions_quietly(_scored(make_track, score=0.5))
    assert panel.renders == [] and panel.has_pending_quiet_render

    over["v"] = False
    panel._try_quiet_render()  # what the retry timer does
    assert panel.renders == [3] and not panel.has_pending_quiet_render


def test_preview_active_defers_until_preview_stops(panel, make_track, tk_root):
    panel.set_suggestions(_scored(make_track))
    panel.renders.clear()
    panel._playing_file = "/m/0.mp3"  # a preview is active (playing or paused)

    panel.show_suggestions_quietly(_scored(make_track, score=0.5))
    assert panel.renders == [] and panel.has_pending_quiet_render

    panel._reset_playback_ui()  # preview stopped or ended
    tk_root.update()            # run the after_idle re-render
    assert panel.renders == [3]


def test_explicit_render_cancels_deferred_one(panel, make_track):
    panel.set_suggestions(_scored(make_track))
    panel._playing_file = "/m/0.mp3"
    panel.show_suggestions_quietly(_scored(make_track, score=0.5))
    panel.set_suggestions(_scored(make_track, n=2))  # e.g. the DJ picked a new track
    assert not panel.has_pending_quiet_render


# ── Timer rules (pointer check and is_previewing stubbed) ──


class _Timers:
    """Track the panel's quiet-retry timers: scheduled minus cancelled/fired."""

    def __init__(self, panel) -> None:
        self.live: dict[str, Callable[[], object]] = {}
        self._n = 0
        self._panel = panel
        real_after, real_cancel = panel.after, panel.after_cancel

        def after(ms, func=None, *args):
            # after_idle is after("idle", ...): leave it to Tk; stub only the retry timer.
            if (
                ms != "idle" and func is not None
                and getattr(func, "__name__", "") == "_try_quiet_render"
            ):
                self._n += 1
                tid = f"quiet-{self._n}"
                self.live[tid] = func
                return tid
            return real_after(ms, func, *args)

        def after_cancel(tid):
            if str(tid).startswith("quiet-"):
                self.live.pop(tid, None)
                return None
            return real_cancel(tid)

        setattr(panel, "after", after)  # instance-level stub
        setattr(panel, "after_cancel", after_cancel)

    def fire_one(self) -> None:
        tid, func = next(iter(self.live.items()))
        del self.live[tid]
        func()


@pytest.fixture
def timed(panel, make_track):
    panel.set_suggestions(_scored(make_track))
    panel.renders.clear()
    state = {"over": True}
    panel._pointer_over_list = lambda: state["over"]
    timers = _Timers(panel)
    return panel, timers, state


def test_timer_defers_while_hovering(timed, make_track):
    panel, timers, _state = timed
    panel.show_suggestions_quietly(_scored(make_track, score=0.4))
    assert panel.renders == [] and len(timers.live) == 1
    timers.fire_one()               # still hovering: re-arms once
    assert panel.renders == [] and len(timers.live) == 1


def test_timer_renders_when_pointer_leaves(timed, make_track):
    panel, timers, state = timed
    panel.show_suggestions_quietly(_scored(make_track, score=0.4))
    state["over"] = False
    timers.fire_one()
    assert panel.renders == [3] and timers.live == {} and not panel.has_pending_quiet_render


def test_timer_renders_when_preview_stops(timed, make_track, tk_root):
    panel, timers, state = timed
    state["over"] = False
    panel._playing_file = "/m/0.mp3"
    panel.show_suggestions_quietly(_scored(make_track, score=0.4))
    assert panel.renders == [] and timers.live == {}  # waits for the preview, no polling
    panel._reset_playback_ui()
    tk_root.update()
    assert panel.renders == [3]


def test_explicit_render_cancels_pending_and_timer(timed, make_track):
    panel, timers, _state = timed
    panel.show_suggestions_quietly(_scored(make_track, score=0.4))
    panel.set_suggestions(_scored(make_track, n=2))
    assert timers.live == {} and not panel.has_pending_quiet_render


def test_clear_cancels_pending_and_timer(timed, make_track):
    panel, timers, state = timed
    panel.show_suggestions_quietly(_scored(make_track, score=0.4))
    panel.clear()
    assert timers.live == {} and not panel.has_pending_quiet_render
    state["over"] = False
    panel._try_quiet_render()  # nothing pending: no render
    assert panel.renders == []


def test_repeated_refreshes_never_stack_retry_timers(timed, make_track):
    panel, timers, _state = timed
    for score in (0.4, 0.3, 0.2, 0.1):
        panel.show_suggestions_quietly(_scored(make_track, score=score))
        assert len(timers.live) == 1
    timers.fire_one()
    assert len(timers.live) == 1


def test_cancel_quiet_render_public_for_shutdown(timed, make_track):
    panel, timers, _state = timed
    panel.show_suggestions_quietly(_scored(make_track, score=0.4))
    panel.cancel_quiet_render()
    assert timers.live == {} and not panel.has_pending_quiet_render
