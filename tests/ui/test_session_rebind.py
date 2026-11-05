"""SessionPanel.rebind_tracks keeps the setlist across a live refresh (T3b.4).

Needs a live Tk root; skips cleanly where no display is available.
"""

from __future__ import annotations

import pytest

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


def test_rebind_replaces_objects_keeps_order_and_missing(tk_root, make_track):
    from source.ui.session_panel import SessionPanel

    panel = SessionPanel(tk_root)
    a = make_track(title="A", full_file_path="/m/a.mp3")
    b = make_track(title="B", full_file_path="/m/b.mp3")
    c = make_track(title="C", full_file_path="/m/c.mp3")
    for t in (a, b, c):
        panel.add_track(t)
    a2 = make_track(title="A v2", full_file_path="/m/a.mp3")
    c2 = make_track(title="C v2", full_file_path="/m/c.mp3")
    fresh = {"/m/a.mp3": a2, "/m/c.mp3": c2}  # b no longer in the library

    panel.rebind_tracks(fresh.get)

    assert panel._tracks == [a2, b, c2]  # noqa: SLF001
    assert panel.played_paths == {"/m/a.mp3", "/m/b.mp3", "/m/c.mp3"}


def test_rebind_equal_by_value_skips_rebuild(tk_root, make_track):
    from source.ui.session_panel import SessionPanel

    panel = SessionPanel(tk_root)
    a = make_track(title="A", full_file_path="/m/a.mp3")
    panel.add_track(a)
    rebuilds: list[int] = []
    panel._rebuild = lambda: rebuilds.append(1)  # type: ignore[method-assign]
    same = make_track(title="A", full_file_path="/m/a.mp3")
    same.file_name = a.file_name

    panel.rebind_tracks({"/m/a.mp3": same}.get)

    assert rebuilds == []
    assert panel._tracks[0] is same  # noqa: SLF001 - objects still swapped
