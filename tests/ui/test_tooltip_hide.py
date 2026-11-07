"""``Tooltip.hide()`` (copy-track-search-text plan T3.0). Needs a live Tk root."""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")

from source.ui.tooltip import Tooltip  # noqa: E402 - after the tkinter skip


def test_tooltip_hide_pending_show_is_cancelled(tk_root):
    widget = tk.Label(tk_root, text="x")
    tip = Tooltip(widget, "Tip text", delay=10)
    tip._schedule(None)
    assert tip._after_id is not None

    tip.hide()
    tk_root.after(50)
    tk_root.update()

    assert tip._after_id is None
    assert tip._tip_window is None


def test_tooltip_hide_shown_tip_is_destroyed(tk_root):
    widget = tk.Label(tk_root, text="x")
    tip = Tooltip(widget, "Tip text")
    tip._show()
    shown = tip._tip_window
    assert shown is not None

    tip.hide()

    assert tip._tip_window is None
    assert not shown.winfo_exists()


def test_tooltip_hide_nothing_shown_is_harmless(tk_root):
    tip = Tooltip(tk.Label(tk_root, text="x"), "Tip text")
    tip.hide()
    assert tip._tip_window is None


def test_tooltip_schedule_twice_keeps_only_one_pending_show(tk_root):
    # Two <Enter>s without a <Leave> (e.g. canvas -> label inside a CTkButton)
    # must not leave an orphan timer that hide() can no longer cancel.
    widget = tk.Label(tk_root, text="x")
    tip = Tooltip(widget, "Tip text", delay=10)
    shows: list[bool] = []
    tip._show = lambda: shows.append(True)  # type: ignore[method-assign]

    tip._schedule(None)
    tip._schedule(None)
    tip.hide()
    tk_root.after(60)
    tk_root.update()

    assert shows == []
