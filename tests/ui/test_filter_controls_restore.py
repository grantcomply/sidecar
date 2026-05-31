"""Widget-level tests for the filter controls' snapshot/restore/tint logic.

Complements ``test_suggestion_filters.py`` (the pure value object) by exercising
the control-level deferred-apply machinery that previously had no automated
coverage: ``restore`` round-trips, ``commit_display``/``restore_display`` for the
date control, the manual-entry commit path that fixes the HIGH divergence bug,
and the staged-tint colour toggle.

Uses the same headless Tk pattern as ``test_filter_dropdown_clear.py``:
``importorskip`` plus a display-availability skip, so the pure suite still runs
everywhere.
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


# ── FilterDropdown.restore round-trips ──


def test_filter_dropdown_restore_subset(tk_root):
    from source.ui.filter_bar import ACCENT_BLUE, FilterDropdown

    dd = FilterDropdown(tk_root, host=tk_root, label="Crates")
    dd.set_items(["House", "Techno", "Disco"])

    dd.restore(frozenset({"House", "Disco"}))

    assert dd.selected == {"House", "Disco"}
    assert dd.all_selected is False
    assert dd.pill.cget("text") == "Crates: 2/3"
    # A narrowing (applied) state restored silently → full accent, not staged tint.
    assert dd.pill.cget("fg_color") == ACCENT_BLUE


def test_filter_dropdown_restore_none_is_no_filter(tk_root):
    from source.ui.filter_bar import NEUTRAL_PILL, FilterDropdown

    dd = FilterDropdown(tk_root, host=tk_root, label="Genres")
    dd.set_items(["House", "Techno"])
    dd.restore(frozenset({"House"}))  # narrow first
    assert dd.all_selected is False

    dd.restore(None)  # None == no filter == all selected

    assert dd.all_selected is True
    assert dd.selected == {"House", "Techno"}
    assert dd.pill.cget("text") == "Genres"
    assert dd.pill.cget("fg_color") == NEUTRAL_PILL


# ── KeyOffsetControl.restore + stepper enable/disable ──


def test_key_offset_restore_resyncs_steppers_at_limits(tk_root):
    from source.config import KEY_OFFSET_RANGE
    from source.ui.filter_bar import KeyOffsetControl, key_offset_label

    lo, hi = KEY_OFFSET_RANGE
    ctrl = KeyOffsetControl(tk_root)

    ctrl.restore(hi)
    assert ctrl.selected_key_offset == hi
    assert ctrl._value_lbl.cget("text") == key_offset_label(hi)  # noqa: SLF001
    # At the upper limit the increment button is disabled, decrement enabled.
    assert ctrl._inc_btn.cget("state") == "disabled"  # noqa: SLF001
    assert ctrl._dec_btn.cget("state") == "normal"  # noqa: SLF001

    ctrl.restore(lo)
    assert ctrl.selected_key_offset == lo
    assert ctrl._dec_btn.cget("state") == "disabled"  # noqa: SLF001
    assert ctrl._inc_btn.cget("state") == "normal"  # noqa: SLF001

    ctrl.restore(0)
    assert ctrl.is_default is True
    assert ctrl._inc_btn.cget("state") == "normal"  # noqa: SLF001
    assert ctrl._dec_btn.cget("state") == "normal"  # noqa: SLF001


# ── DateRangeControl commit_display → mutate → restore_display ──


def test_date_range_restore_display_round_trip_preset(tk_root):
    from source.ui.filter_bar import ACCENT_BLUE, DateRangeControl

    ctrl = DateRangeControl(tk_root, host=tk_root)
    # Apply a preset, then snapshot it as the committed display.
    ctrl._on_preset("Last month")  # noqa: SLF001
    committed_range = ctrl.selected_date_range
    ctrl.commit_display()

    # Mutate to a manual range (diverges from the committed preset).
    ctrl._from_entry.insert(0, "2024-01-01")  # noqa: SLF001
    ctrl._on_apply_manual()  # noqa: SLF001
    assert ctrl._active_preset is None  # noqa: SLF001
    assert ctrl.selected_date_range != committed_range

    # Cancel path: restore the committed preset display.
    ctrl.restore_display()

    assert ctrl.selected_date_range == committed_range
    assert ctrl._active_preset == "Last month"  # noqa: SLF001
    # Preset highlight restored.
    assert ctrl._preset_buttons["Last month"].cget("fg_color") == ACCENT_BLUE  # noqa: SLF001
    # Manual entries cleared (committed state was a preset).
    assert ctrl._from_entry.get() == ""  # noqa: SLF001
    assert ctrl.pill.cget("text") == "Added: last month"


def test_date_range_restore_display_round_trip_manual(tk_root):
    from source.ui.filter_bar import DateRangeControl

    ctrl = DateRangeControl(tk_root, host=tk_root)
    # Commit a manual range as the applied display.
    ctrl._from_entry.insert(0, "2024-01-01")  # noqa: SLF001
    ctrl._to_entry.insert(0, "2024-06-30")  # noqa: SLF001
    ctrl._on_apply_manual()  # noqa: SLF001
    committed_range = ctrl.selected_date_range
    ctrl.commit_display()

    # Mutate to a preset.
    ctrl._on_preset("This year")  # noqa: SLF001
    assert ctrl.selected_date_range != committed_range

    ctrl.restore_display()

    assert ctrl.selected_date_range == committed_range
    assert ctrl._active_preset is None  # noqa: SLF001
    assert ctrl._from_entry.get() == "2024-01-01"  # noqa: SLF001
    assert ctrl._to_entry.get() == "2024-06-30"  # noqa: SLF001
    assert ctrl.pill.cget("text") == "Added: 2024-01-01 – 2024-06-30"


# ── HIGH-bug regression: typed-but-uncommitted manual entry ──


def test_commit_pending_entry_applies_typed_valid_date(tk_root):
    """Type a valid From date WITHOUT clicking "Set dates" → commit applies it."""
    from source.services.dates import date_range_to_epoch
    from source.ui.filter_bar import DateRangeControl

    ctrl = DateRangeControl(tk_root, host=tk_root)
    # User types but does NOT click "Set dates": _range is still the default.
    ctrl._from_entry.insert(0, "2024-03-15")  # noqa: SLF001
    assert ctrl.selected_date_range == (None, None)

    ctrl.commit_pending_entry()

    expected = date_range_to_epoch(from_str="2024-03-15", to_str=None)
    assert ctrl.selected_date_range == expected
    assert ctrl._active_preset is None  # noqa: SLF001
    # The committed display now matches _range — snapshot + restore stays in sync.
    ctrl.commit_display()
    assert ctrl._committed_display[0] == expected  # noqa: SLF001
    assert ctrl._committed_display[2] == "2024-03-15"  # noqa: SLF001
    assert ctrl.pill.cget("text") == "Added: from 2024-03-15"


def test_commit_pending_invalid_text_keeps_range_and_no_cancel_resurrection(tk_root):
    """Invalid pending text must not apply garbage nor survive a later Cancel."""
    from source.ui.filter_bar import DateRangeControl

    ctrl = DateRangeControl(tk_root, host=tk_root)
    # A clean applied state (any time) is the committed display.
    ctrl.commit_display()
    before = ctrl.selected_date_range

    # User types garbage but never clicks "Set dates".
    ctrl._from_entry.insert(0, "not-a-date")  # noqa: SLF001
    ctrl.commit_pending_entry()

    # Range unchanged — no garbage applied.
    assert ctrl.selected_date_range == before
    # Stray text discarded so it can't disagree with _range...
    assert ctrl._from_entry.get() == ""  # noqa: SLF001

    # ...and a later snapshot + Cancel cannot resurrect it.
    ctrl.commit_display()
    ctrl._on_preset("Last month")  # stage an edit  # noqa: SLF001
    ctrl.restore_display()
    assert ctrl.selected_date_range == before
    assert ctrl._from_entry.get() == ""  # noqa: SLF001
    assert ctrl.pill.cget("text") == "Added: any time"


def test_commit_pending_to_without_from_discarded(tk_root):
    """To filled while From empty is out of scope → discard, keep range."""
    from source.ui.filter_bar import DateRangeControl

    ctrl = DateRangeControl(tk_root, host=tk_root)
    ctrl.commit_display()
    before = ctrl.selected_date_range

    ctrl._to_entry.insert(0, "2024-06-30")  # noqa: SLF001
    ctrl.commit_pending_entry()

    assert ctrl.selected_date_range == before
    assert ctrl._to_entry.get() == ""  # noqa: SLF001


def test_commit_pending_entry_noop_when_text_matches_range(tk_root):
    """An entry untouched since the last commit is a clean no-op."""
    from source.ui.filter_bar import DateRangeControl

    ctrl = DateRangeControl(tk_root, host=tk_root)
    ctrl._from_entry.insert(0, "2024-03-15")  # noqa: SLF001
    ctrl._on_apply_manual()  # noqa: SLF001
    ctrl.commit_display()
    committed = ctrl.selected_date_range

    # No new typing — commit should leave everything exactly as-is.
    ctrl.commit_pending_entry()

    assert ctrl.selected_date_range == committed
    assert ctrl._from_entry.get() == "2024-03-15"  # noqa: SLF001


# ── mark_staged toggles the pill colour between the tint constants ──


def test_filter_dropdown_mark_staged_toggles_tint(tk_root):
    from source.ui.filter_bar import ACCENT_BLUE, STAGED_TINT, FilterDropdown

    dd = FilterDropdown(tk_root, host=tk_root, label="Crates")
    dd.set_items(["House", "Techno", "Disco"])
    dd.restore(frozenset({"House"}))  # active (narrowing) filter
    assert dd.pill.cget("fg_color") == ACCENT_BLUE

    dd.mark_staged(True)
    assert dd.pill.cget("fg_color") == STAGED_TINT

    dd.mark_staged(False)
    assert dd.pill.cget("fg_color") == ACCENT_BLUE


def test_date_range_mark_staged_toggles_tint(tk_root):
    from source.ui.filter_bar import ACCENT_BLUE, STAGED_TINT, DateRangeControl

    ctrl = DateRangeControl(tk_root, host=tk_root)
    ctrl._on_preset("Last month")  # active range  # noqa: SLF001
    assert ctrl.pill.cget("fg_color") == ACCENT_BLUE

    ctrl.mark_staged(True)
    assert ctrl.pill.cget("fg_color") == STAGED_TINT

    ctrl.mark_staged(False)
    assert ctrl.pill.cget("fg_color") == ACCENT_BLUE
