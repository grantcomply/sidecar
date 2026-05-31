"""Widget-level test for FilterDropdown's Clear (deselect-all) contract.

This is the one test here that needs a live Tk root (the checklist state lives
in ``tk.BooleanVar``s). It skips cleanly on a headless box where no display is
available, so the pure-logic suite still runs everywhere.
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


def test_deselect_all_clears_selection_and_all_selected(tk_root):
    # Imported lazily so collection never imports customtkinter on headless CI
    # before the display check has had a chance to skip.
    from source.ui.filter_bar import ACCENT_BLUE, FilterDropdown

    dd = FilterDropdown(tk_root, host=tk_root, label="Crates")
    dd.set_items(["House", "Techno", "Disco"])

    # Starts all-selected (no filter active).
    assert dd.all_selected is True
    assert dd.selected == {"House", "Techno", "Disco"}

    dd._deselect_all()  # noqa: SLF001 - exercising the Clear handler directly

    assert dd.selected == set()
    assert dd.all_selected is False
    # An intentional empty filter — these lock in the "not a bug" presentation:
    assert dd.is_cleared is True
    # Drives the bar-level "Reset filters" affordance visibility.
    assert dd.is_default is False
    # Pill reads the explicit empty-state microcopy, not the plain label.
    assert dd.pill.cget("text") == "Crates: none"
    # And it shows accent blue (a narrowing state), not the grey default.
    assert dd.pill.cget("fg_color") == ACCENT_BLUE


def test_select_all_after_clear_restores_no_filter(tk_root):
    from source.ui.filter_bar import FilterDropdown

    dd = FilterDropdown(tk_root, host=tk_root, label="Genres")
    dd.set_items(["House", "Techno"])

    dd._deselect_all()  # noqa: SLF001
    assert dd.all_selected is False

    dd._select_all()  # noqa: SLF001
    assert dd.all_selected is True
    assert dd.selected == {"House", "Techno"}
