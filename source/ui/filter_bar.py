"""Filter bar controls for the suggestion panel.

Houses the four glanceable filter controls used live in the booth, plus the
single "Reset filters" affordance:

- ``FloatingOverlay`` — a reusable ``place()``-d panel that floats over the
  suggestion panel below its trigger pill. Only one is open at a time; it closes
  on an outside click or Escape (Finding 3 fix).
- ``FilterDropdown`` — a pill (grey = no filter, blue = narrowing) whose
  checklist lives in a floating overlay, with paired "Select all" / "Clear"
  actions. A fully-cleared filter is an intentional empty state — this reverses
  the earlier Finding 2 "no Deselect All" decision now that the suggestion panel
  frames the cleared result as a deliberate empty state rather than a bug.
- ``KeyOffsetControl`` — an inline ``[◀ Transition: … ▶]`` stepper for the
  Camelot offset (sub-feature 1).
- ``DateRangeControl`` — a pill opening an overlay with preset tiles + manual
  entry for the date-added filter (sub-feature 3).
- ``FilterBar`` — the container row plus the "Reset filters" link.

Design tokens, microcopy, and states follow
``plans/suggestion-filter-enhancements-2026-05/ui-design-brief.md`` and
``docs/ui-design-guide.md`` §5.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk

from source.config import KEY_OFFSET_RANGE
from source.services.dates import date_range_to_epoch
from source.ui.tooltip import Tooltip
from source.ui.utils import truncate

# ── Shared visual tokens (brief §Sub-feature 1 / §Finding 4) ──
ACCENT_BLUE = "#1f6aa5"
STAGED_TINT = "#3a88c8"  # lighter accent: filter edited but not yet applied (T3.9)
NEUTRAL_PILL = ("gray75", "gray35")
NEUTRAL_HOVER = ("gray65", "gray45")
PILL_TEXT = ("gray10", "gray90")
SECONDARY_GREY = "#999999"
PRIMARY_TEXT = "#ffffff"
ERROR_RED = "#dc3545"
SEPARATOR_GREY = "gray40"

PILL_HEIGHT = 32
PILL_CORNER = 16
OVERLAY_GAP = 4  # px below the pill before the overlay


# ── Pure microcopy helpers (testable; brief §Microcopy) ──


def key_offset_label(offset: int) -> str:
    """Return the Camelot-transition pill centre label for ``offset``.

    Offset 0 reads "Transition: same key"; non-zero offsets use an explicit
    ``+`` / U+2212 minus sign, e.g. "Transition: +1" / "Transition: −2".
    """
    if offset == 0:
        return "Transition: same key"
    sign = "+" if offset > 0 else "−"  # U+2212 MINUS SIGN, not hyphen
    return f"Transition: {sign}{abs(offset)}"


def date_pill_label(
    *,
    is_default: bool,
    preset: str | None = None,
    from_str: str | None = None,
    to_str: str | None = None,
) -> str:
    """Return the date-range pill label per the brief's microcopy table.

    - Default / no filter → "Added: any time".
    - Active preset → "Added: <preset lowercased>".
    - Manual from + to → "Added: <from> – <to>".
    - Manual from only → "Added: from <from>".

    A "to only" window is out of scope (the brief defines only from-only and
    from + to), so this helper never emits an "until …" label — callers must
    require a From date before applying a manual range.
    """
    if is_default:
        return "Added: any time"
    if preset is not None:
        return f"Added: {preset.lower()}"
    if from_str and to_str:
        return f"Added: {from_str} – {to_str}"  # U+2013 EN DASH
    return f"Added: from {from_str}"


def filter_pill_label(label: str, selected: int, total: int, *, only: str | None = None) -> str:
    """Return the ``FilterDropdown`` pill text for a given selection state.

    - All selected (or empty list) → the plain label ("Crates") — no filter active.
    - Zero selected while items exist → "Crates: none" — an intentional empty filter.
    - Exactly one → "Crates: <name>" (caller truncates ``only``).
    - A partial subset → "Crates: 3/9".
    """
    if total == 0 or selected == total:
        return label
    if selected == 0:
        return f"{label}: none"
    if selected == 1:
        return f"{label}: {only}"
    return f"{label}: {selected}/{total}"


# ── Floating overlay (T3.3) ──


class FloatingOverlay(ctk.CTkFrame):
    """A panel that floats over ``host`` via ``place()`` + ``lift()``.

    Positioned just below a trigger widget; does not displace the suggestion
    list (Finding 3). Closes on an outside click or Escape. The class keeps a
    single ``_open`` reference so opening any overlay closes the previous one —
    only one filter overlay is visible at a time (brief T3.3).
    """

    # The currently-open overlay across the whole app (one-at-a-time invariant).
    _open: "FloatingOverlay | None" = None

    def __init__(self, host: tk.Widget, trigger: tk.Widget, **kwargs) -> None:
        kwargs.setdefault("corner_radius", 8)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", SEPARATOR_GREY)
        super().__init__(host, **kwargs)
        self._host = host
        self._trigger = trigger
        self._click_binding: str | None = None
        self._escape_binding: str | None = None
        # Pending after_idle id for the deferred watcher registration (see open()).
        self._watcher_after: str | None = None

    @classmethod
    def close_open(cls) -> None:
        """Close whichever overlay is currently open, if any."""
        if cls._open is not None:
            try:
                cls._open.close()
            except tk.TclError:
                # The open overlay's widget was already destroyed out from under
                # us (e.g. panel rebuild). Clear the stale class pointer so a
                # later reset doesn't keep hitting a dead widget.
                cls._open = None

    @property
    def is_open(self) -> bool:
        return FloatingOverlay._open is self

    def open(self) -> None:
        """Show the overlay below its trigger and start outside-click watching."""
        # Close any other overlay first (one-at-a-time). The "another pill opening
        # closes the previous" behaviour relies on THIS deterministic call — not on
        # the outside-click watcher racing the opening click (Finding HIGH-1).
        if FloatingOverlay._open is not None and FloatingOverlay._open is not self:
            FloatingOverlay._open.close()
        if self.is_open:
            return

        x, y = self._placement()
        self.place(x=x, y=y)
        self.lift()
        FloatingOverlay._open = self

        # Defer registering the outside-click / Escape watchers until AFTER the
        # click that opened us has finished propagating. Binding them synchronously
        # here would let the very same <Button-1> that opened the overlay (or the
        # one that opened a second pill) immediately fire _on_root_click and close
        # us — the open-click race (Finding HIGH-1). after_idle runs once the event
        # queue drains, so the opening click is already consumed.
        self._watcher_after = self.after_idle(self._register_watchers)

    def _register_watchers(self) -> None:
        """Bind the outside-click and Escape watchers (deferred via after_idle)."""
        self._watcher_after = None
        if not self.is_open:
            return
        root = self.winfo_toplevel()
        # add="+" so we don't clobber other root-level bindings.
        self._click_binding = root.bind("<Button-1>", self._on_root_click, add="+")
        self._escape_binding = root.bind("<Escape>", lambda _e: self.close(), add="+")

    def close(self) -> None:
        """Hide the overlay and detach its watchers."""
        # Cancel a still-pending deferred watcher registration so we never leave a
        # dangling after_idle callback that would bind onto a closed overlay.
        if self._watcher_after is not None:
            self.after_cancel(self._watcher_after)
            self._watcher_after = None
        if not self.is_open:
            # Still ensure it's unplaced if it was shown without registering.
            self.place_forget()
            return
        root = self.winfo_toplevel()
        # NOTE: Tk's Misc.unbind(sequence, funcid) does not reliably remove a single
        # add="+" binding — on some Tk builds it tears down ALL bindings for the
        # sequence, on others it silently leaves the bound function in place. We
        # unbind here best-effort, but _on_root_click also no-ops when the overlay
        # is closed (the `if not self.is_open` guard) so a stale/orphaned binding
        # can never act on a closed overlay (Finding HIGH-2).
        if self._click_binding is not None:
            root.unbind("<Button-1>", self._click_binding)
            self._click_binding = None
        if self._escape_binding is not None:
            root.unbind("<Escape>", self._escape_binding)
            self._escape_binding = None
        self.place_forget()
        FloatingOverlay._open = None

    def destroy(self) -> None:
        """Clear the class-level open pointer if this overlay is being destroyed."""
        if FloatingOverlay._open is self:
            FloatingOverlay._open = None
        super().destroy()

    def _placement(self) -> tuple[int, int]:
        """Return (x, y) in ``host`` coordinates directly below the trigger."""
        self._trigger.update_idletasks()
        tx = self._trigger.winfo_rootx() - self._host.winfo_rootx()
        ty = (
            self._trigger.winfo_rooty()
            - self._host.winfo_rooty()
            + self._trigger.winfo_height()
            + OVERLAY_GAP
        )
        return max(0, tx), max(0, ty)

    def _on_root_click(self, event: tk.Event) -> None:
        """Close when the click lands outside the overlay and its trigger."""
        # Stale-binding safety (Finding HIGH-2): because Tk's unbind cannot reliably
        # remove a single add="+" binding, this handler may survive close(). Bail
        # out immediately if we're no longer the open overlay so an orphaned binding
        # can never act on a closed (or another) overlay.
        if not self.is_open:
            return
        widget = event.widget
        # Walk the widget's parent chain; if we hit the overlay or trigger, keep open.
        node = widget
        while node is not None:
            if node is self or node is self._trigger:
                return
            node = getattr(node, "master", None)
        self.close()


# ── Filter dropdown pill (T3.4) ──


class FilterDropdown(ctk.CTkFrame):
    """A pill button whose multi-select checklist lives in a floating overlay.

    Grey pill = all selected (no filter active). Blue pill = a subset is
    selected (results narrowed) — the at-a-glance signal of Finding 4. The
    ``selected`` / ``all_selected`` properties and the ``_on_change`` callback are
    unchanged from the previous inline implementation, preserving the engine's
    ``None``-means-no-filter contract.
    """

    def __init__(
        self,
        master,
        host: tk.Widget,
        label: str,
        on_change: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)
        self._on_change = on_change
        self._label = label
        self._host = host
        self._vars: dict[str, tk.BooleanVar] = {}
        self._is_staged = False  # staged-tint flag (T3.9)

        self.pill = ctk.CTkButton(
            self, text=label, height=PILL_HEIGHT, corner_radius=PILL_CORNER,
            font=ctk.CTkFont(size=12),
            fg_color=NEUTRAL_PILL, hover_color=NEUTRAL_HOVER, text_color=PILL_TEXT,
            command=self._toggle_overlay,
        )
        self.pill.pack()

        self._overlay = FloatingOverlay(host, self)
        self._overlay.grid_columnconfigure(0, weight=1)

        # "Select all" + "Clear" sit side by side at the top of the overlay.
        # "Clear" (deselect-all) is paired with an intentional empty-state message
        # in the suggestion panel so a fully-cleared filter no longer reads as a bug.
        actions = ctk.CTkFrame(self._overlay, fg_color="transparent")
        actions.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)

        self._select_all_btn = ctk.CTkButton(
            actions, text="Select all", height=24,
            font=ctk.CTkFont(size=11),
            fg_color=NEUTRAL_PILL, hover_color=NEUTRAL_HOVER, text_color=PILL_TEXT,
            command=self._select_all,
        )
        self._select_all_btn.grid(row=0, column=0, sticky="ew", padx=(0, 2))

        self._clear_btn = ctk.CTkButton(
            actions, text="Clear", height=24,
            font=ctk.CTkFont(size=11),
            fg_color=NEUTRAL_PILL, hover_color=NEUTRAL_HOVER, text_color=PILL_TEXT,
            command=self._deselect_all,
        )
        self._clear_btn.grid(row=0, column=1, sticky="ew", padx=(2, 0))

        self.checklist = ctk.CTkScrollableFrame(self._overlay, height=200, width=200)
        self.checklist.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 8))
        self.checklist.grid_columnconfigure(0, weight=1)

        self._empty_label: ctk.CTkLabel | None = None

    def set_items(self, names: list[str]):
        self._vars.clear()
        for w in self.checklist.winfo_children():
            w.destroy()
        self._empty_label = None
        if not names:
            self._empty_label = ctk.CTkLabel(
                self.checklist, text=f"No {self._label.lower()} loaded — sync your library first.",
                font=ctk.CTkFont(size=11), text_color=SECONDARY_GREY,
                wraplength=190, justify="left",
            )
            self._empty_label.grid(row=0, column=0, sticky="w", padx=5, pady=6)
            # No items → "Select all" / "Clear" are no-ops; disable rather than
            # let them silently fire a needless full re-score (review SHOULD-FIX 2).
            self._select_all_btn.configure(state="disabled")
            self._clear_btn.configure(state="disabled")
            self._update_label()
            return
        self._select_all_btn.configure(state="normal")
        self._clear_btn.configure(state="normal")
        for i, name in enumerate(names):
            var = tk.BooleanVar(value=True)
            self._vars[name] = var
            ctk.CTkCheckBox(
                self.checklist, text=name, variable=var,
                font=ctk.CTkFont(size=11),
                height=22, checkbox_width=18, checkbox_height=18,
                command=self._on_check_changed,
            ).grid(row=i, column=0, sticky="w", padx=5, pady=1)
        self._update_label()

    def _toggle_overlay(self):
        if self._overlay.is_open:
            self._overlay.close()
        else:
            self._overlay.open()

    def _select_all(self):
        for v in self._vars.values():
            v.set(True)
        self._update_label()
        self._fire()

    def _deselect_all(self):
        """Clear every item — an intentional empty filter (mirrors _select_all)."""
        for v in self._vars.values():
            v.set(False)
        self._update_label()
        self._fire()

    def _on_check_changed(self):
        self._update_label()
        self._fire()

    def _update_label(self):
        total = len(self._vars)
        selected = sum(1 for v in self._vars.values() if v.get())
        only = (
            truncate(next(n for n, v in self._vars.items() if v.get()), 10)
            if selected == 1
            else None
        )
        text = filter_pill_label(self._label, selected, total, only=only)
        # Grey for the no-filter default (all selected / empty list). When a
        # filter is active, the pill is staged-tint while edited-but-unapplied
        # and full accent once applied (T3.9).
        is_default = total == 0 or selected == total
        if is_default:
            fg = NEUTRAL_PILL
        elif self._is_staged:
            fg = STAGED_TINT
        else:
            fg = ACCENT_BLUE
        self.pill.configure(text=text, fg_color=fg)

    def mark_staged(self, is_staged: bool) -> None:
        """Set the staged-tint flag and repaint the pill (T3.9)."""
        if is_staged == self._is_staged:
            return
        self._is_staged = is_staged
        self._update_label()

    def _fire(self):
        if self._on_change:
            self._on_change()

    def reset(self):
        """Restore the all-selected (no-filter) default without firing change."""
        for v in self._vars.values():
            v.set(True)
        self._update_label()

    def restore(self, selected: frozenset[str] | None) -> None:
        """Push an applied snapshot back into the checkboxes without firing change.

        ``selected is None`` means "no filter" → every checkbox true. Otherwise
        each checkbox is set to ``name in selected``. Silent (no ``_fire``) so
        Cancel never marks itself dirty — mirrors ``reset()``.
        """
        for name, var in self._vars.items():
            var.set(True if selected is None else name in selected)
        self._update_label()

    @property
    def is_default(self) -> bool:
        return self.all_selected

    @property
    def selected(self) -> set[str]:
        return {n for n, v in self._vars.items() if v.get()}

    @property
    def all_selected(self) -> bool:
        return all(v.get() for v in self._vars.values())

    @property
    def is_cleared(self) -> bool:
        """True when items exist but none are selected — an intentional empty filter."""
        return not self.all_selected and not self.selected


# ── Key offset stepper (T3.1) ──


class KeyOffsetControl(ctk.CTkFrame):
    """An inline ``[◀ Transition: … ▶]`` stepper for the Camelot key offset.

    Grey pill at offset 0 (default), accent blue when non-zero. Buttons disable
    at ``KEY_OFFSET_RANGE`` limits. One tap per step (brief sub-feature 1).
    """

    _MIN, _MAX = KEY_OFFSET_RANGE

    def __init__(
        self, master, on_change: Callable[[], None] | None = None, **kwargs
    ) -> None:
        kwargs.setdefault("corner_radius", 6)
        kwargs.setdefault("fg_color", NEUTRAL_PILL)
        kwargs.setdefault("height", PILL_HEIGHT)
        super().__init__(master, **kwargs)
        self._on_change = on_change
        self._offset = 0
        self._is_staged = False  # staged-tint flag (T3.9)

        self._dec_btn = ctk.CTkButton(
            self, text="◄", width=24, height=28,
            fg_color="transparent", hover_color=NEUTRAL_HOVER, text_color=PILL_TEXT,
            font=ctk.CTkFont(size=12),
            command=lambda: self._step(-1),
        )
        self._dec_btn.grid(row=0, column=0, padx=(4, 0), pady=2)

        self._value_lbl = ctk.CTkLabel(
            self, text=self._label_text(), font=ctk.CTkFont(size=12),
            text_color=PILL_TEXT,
        )
        self._value_lbl.grid(row=0, column=1, padx=4, pady=2)

        self._inc_btn = ctk.CTkButton(
            self, text="►", width=24, height=28,
            fg_color="transparent", hover_color=NEUTRAL_HOVER, text_color=PILL_TEXT,
            font=ctk.CTkFont(size=12),
            command=lambda: self._step(1),
        )
        self._inc_btn.grid(row=0, column=2, padx=(0, 4), pady=2)

        Tooltip(
            self,
            "Shift harmonic matching up or down the Camelot wheel. At +1 same-key "
            "tracks are hidden and one-step-up tracks move to the top.",
        )
        self._refresh()

    def _label_text(self) -> str:
        return key_offset_label(self._offset)

    def _step(self, delta: int) -> None:
        new = max(self._MIN, min(self._MAX, self._offset + delta))
        if new == self._offset:
            return
        self._offset = new
        self._refresh()
        if self._on_change:
            self._on_change()

    def _refresh(self) -> None:
        self._value_lbl.configure(text=self._label_text())
        if self._offset == 0:
            fg = NEUTRAL_PILL
        elif self._is_staged:
            fg = STAGED_TINT
        else:
            fg = ACCENT_BLUE
        self.configure(fg_color=fg)
        self._dec_btn.configure(state="disabled" if self._offset <= self._MIN else "normal")
        self._inc_btn.configure(state="disabled" if self._offset >= self._MAX else "normal")

    def mark_staged(self, is_staged: bool) -> None:
        """Set the staged-tint flag and repaint (T3.9)."""
        if is_staged == self._is_staged:
            return
        self._is_staged = is_staged
        self._refresh()

    def reset(self) -> None:
        """Restore offset 0 without firing change."""
        self._offset = 0
        self._refresh()

    def restore(self, offset: int) -> None:
        """Restore an applied offset without firing change (mirrors ``reset``)."""
        self._offset = offset
        self._refresh()

    @property
    def is_default(self) -> bool:
        return self._offset == 0

    @property
    def selected_key_offset(self) -> int:
        return self._offset


# ── Date range control (T3.2) ──

_DATE_PRESETS = ["Any time", "Last month", "Last 3 months", "Last 6 months", "This year"]


class DateRangeControl(ctk.CTkFrame):
    """A pill opening an overlay of date presets + manual from/to entry.

    Grey pill = "any time" (no filter). Blue pill = an active range. Exposes
    ``selected_date_range`` as a ``(date_from, date_to)`` epoch tuple, default
    ``(None, None)`` (brief sub-feature 3).
    """

    def __init__(
        self,
        master,
        host: tk.Widget,
        on_change: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)
        self._on_change = on_change
        self._host = host
        self._range: tuple[float | None, float | None] = (None, None)
        self._active_preset: str | None = "Any time"
        self._preset_buttons: dict[str, ctk.CTkButton] = {}
        self._is_staged = False  # staged-tint flag (T3.9)

        self.pill = ctk.CTkButton(
            self, text="Added: any time", height=PILL_HEIGHT, corner_radius=PILL_CORNER,
            font=ctk.CTkFont(size=12),
            fg_color=NEUTRAL_PILL, hover_color=NEUTRAL_HOVER, text_color=PILL_TEXT,
            command=self._toggle_overlay,
        )
        self.pill.pack()

        self._build_overlay(host)

        # Committed (last-applied) DISPLAY snapshot for Cancel restoration (T2.4,
        # blueprint O1). The epoch tuple in SuggestionFilters alone can't
        # reconstruct the active preset highlight or the manual entry strings, so
        # the control owns its own richer display memory. Initialised to the
        # default "any time" state, matching the initial unfiltered render.
        self._committed_display: tuple[
            tuple[float | None, float | None], str | None, str, str
        ] = ((None, None), "Any time", "", "")

    def _build_overlay(self, host: tk.Widget) -> None:
        self._overlay = FloatingOverlay(host, self)

        preset_row = ctk.CTkFrame(self._overlay, fg_color="transparent")
        preset_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        for i, name in enumerate(_DATE_PRESETS):
            btn = ctk.CTkButton(
                preset_row, text=name, height=28,
                font=ctk.CTkFont(size=11),
                fg_color=NEUTRAL_PILL, hover_color=NEUTRAL_HOVER, text_color=PILL_TEXT,
                command=lambda n=name: self._on_preset(n),
            )
            btn.grid(row=0, column=i, padx=2)
            self._preset_buttons[name] = btn

        sep = ctk.CTkFrame(self._overlay, height=1, fg_color=SEPARATOR_GREY)
        sep.grid(row=1, column=0, sticky="ew", padx=8, pady=6)

        manual = ctk.CTkFrame(self._overlay, fg_color="transparent")
        manual.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 2))

        ctk.CTkLabel(manual, text="From", font=ctk.CTkFont(size=11)).grid(
            row=0, column=0, padx=(0, 4))
        self._from_entry = ctk.CTkEntry(
            manual, width=110, placeholder_text="YYYY-MM-DD", font=ctk.CTkFont(size=11))
        self._from_entry.grid(row=0, column=1, padx=(0, 8))
        # Capture the theme default border once so error/clear can restore it
        # without re-reading ThemeManager on every call (Finding Medium-5).
        self._default_border = self._from_entry.cget("border_color")

        ctk.CTkLabel(manual, text="To (optional)", font=ctk.CTkFont(size=11)).grid(
            row=0, column=2, padx=(0, 4))
        self._to_entry = ctk.CTkEntry(
            manual, width=110, placeholder_text="YYYY-MM-DD", font=ctk.CTkFont(size=11))
        self._to_entry.grid(row=0, column=3, padx=(0, 8))

        # "Set dates" (renamed from "Apply", blueprint R2): scoped — confirms the
        # manual entry into the STAGED date value. The global "Apply" bar commits
        # all four filters and re-scores. width 70 fits the two-word label at size 11.
        ctk.CTkButton(
            manual, text="Set dates", width=70, height=28,
            font=ctk.CTkFont(size=11),
            command=self._on_apply_manual,
        ).grid(row=0, column=4)

        self._error_lbl = ctk.CTkLabel(
            self._overlay, text="", font=ctk.CTkFont(size=11), text_color=ERROR_RED,
        )
        self._error_lbl.grid(row=3, column=0, sticky="w", padx=8)
        self._error_lbl.grid_remove()

        ctk.CTkLabel(
            self._overlay,
            text="Date added is the file's creation date on this computer.",
            font=ctk.CTkFont(size=11), text_color=SECONDARY_GREY,
        ).grid(row=4, column=0, sticky="w", padx=8, pady=(2, 8))

        self._refresh_preset_styles()

    def _toggle_overlay(self) -> None:
        if self._overlay.is_open:
            self._overlay.close()
        else:
            self._clear_error()
            self._overlay.open()

    def _on_preset(self, name: str) -> None:
        self._range = date_range_to_epoch(preset=name)
        self._active_preset = name
        self._from_entry.delete(0, "end")
        self._to_entry.delete(0, "end")
        self._clear_error()
        self._refresh_preset_styles()
        self._update_pill()
        self._overlay.close()
        self._fire()

    def _on_apply_manual(self) -> None:
        from_str = self._from_entry.get().strip() or None
        to_str = self._to_entry.get().strip() or None
        if from_str is None and to_str is None:
            # Empty manual entry behaves like "Any time".
            self._on_preset("Any time")
            return
        if from_str is None:
            # A From date is required: the brief only defines "from only" and
            # "from + to" windows — a to-only window is out of scope
            # (Finding Medium-4). Reject Apply with To filled but From empty.
            self._show_error()
            return
        try:
            self._range = date_range_to_epoch(from_str=from_str, to_str=to_str)
        except ValueError:
            self._show_error()
            return
        self._active_preset = None
        self._clear_error()
        self._refresh_preset_styles()
        self._update_pill(from_str=from_str, to_str=to_str)
        self._overlay.close()
        self._fire()

    def commit_pending_entry(self) -> None:
        """Commit (or discard) manual entry text not yet confirmed via "Set dates".

        The panel calls this on Apply BEFORE it snapshots, guaranteeing the
        invariant that ``_range`` and the committed display text never disagree
        (review HIGH fix). ``selected_date_range`` only reflects ``_range``, which
        previously updated solely on "Set dates" — typed-but-uncommitted text
        could be snapshotted by ``commit_display()`` while never reaching
        ``_range``, then resurrected by Cancel's ``restore_display()``.

        Behaviour, mirroring ``_on_apply_manual``'s validation path:

        - Entry text already matches ``_range`` (nothing pending) → no-op.
        - Pending VALID date(s) → commit into ``_range`` so Apply applies what
          the user typed.
        - Pending INVALID text (or To-without-From) → do NOT apply garbage: keep
          the last committed ``_range`` and clear the stray entry text so a later
          ``commit_display`` can't snapshot text that disagrees with ``_range``.
        """
        from_str = self._from_entry.get().strip() or None
        to_str = self._to_entry.get().strip() or None

        # Reconstruct the entry text that the current _range/_active_preset would
        # render, so an entry untouched since the last commit is a clean no-op.
        if self._active_preset is None and self._range != (None, None):
            committed_from = self._committed_display[2].strip() or None
            committed_to = self._committed_display[3].strip() or None
        else:
            committed_from = committed_to = None
        if (from_str, to_str) == (committed_from, committed_to):
            return

        if from_str is None and to_str is None:
            # Cleared entry over a manual range collapses to "any time".
            if self._active_preset is None and self._range != (None, None):
                self._range = (None, None)
                self._active_preset = "Any time"
                self._clear_error()
                self._refresh_preset_styles()
                self._update_pill()
            return

        if from_str is None:
            # To-without-From is out of scope: discard the stray text and keep
            # the last committed range rather than applying a one-sided window.
            self._discard_pending_entry()
            return

        try:
            new_range = date_range_to_epoch(from_str=from_str, to_str=to_str)
        except ValueError:
            # Invalid text: never apply garbage — restore the entry to whatever
            # the committed range reflects so _range and display stay in sync.
            self._discard_pending_entry()
            return

        self._range = new_range
        self._active_preset = None
        self._clear_error()
        self._refresh_preset_styles()
        self._update_pill(from_str=from_str, to_str=to_str)

    def _discard_pending_entry(self) -> None:
        """Drop stray entry text, restoring the entries to reflect ``_range``.

        Used when pending manual text is invalid at Apply time. Re-renders the
        entry strings from the committed display so no text survives that could
        disagree with ``_range`` (and be resurrected by Cancel).
        """
        committed_from = self._committed_display[2]
        committed_to = self._committed_display[3]
        # Only trust the committed entry strings when the committed state was a
        # manual range; otherwise (preset / default) the entries should be empty.
        if self._active_preset is not None or self._range == (None, None):
            committed_from = committed_to = ""
        self._from_entry.delete(0, "end")
        if committed_from:
            self._from_entry.insert(0, committed_from)
        self._to_entry.delete(0, "end")
        if committed_to:
            self._to_entry.insert(0, committed_to)
        self._clear_error()

    def _show_error(self) -> None:
        self._from_entry.configure(border_color=ERROR_RED)
        self._to_entry.configure(border_color=ERROR_RED)
        self._error_lbl.configure(text="Enter a From date as YYYY-MM-DD.")
        self._error_lbl.grid()

    def _clear_error(self) -> None:
        self._from_entry.configure(border_color=self._default_border)
        self._to_entry.configure(border_color=self._default_border)
        self._error_lbl.configure(text="")
        self._error_lbl.grid_remove()

    def _refresh_preset_styles(self) -> None:
        for name, btn in self._preset_buttons.items():
            active = name == self._active_preset
            btn.configure(fg_color=ACCENT_BLUE if active else NEUTRAL_PILL)

    def _update_pill(
        self, from_str: str | None = None, to_str: str | None = None
    ) -> None:
        # For a manual (no-preset) active range, fall back to the entry text so a
        # no-arg repaint (e.g. mark_staged) keeps the "from – to" label intact.
        if from_str is None and to_str is None and self._active_preset is None:
            from_str = self._from_entry.get().strip() or None
            to_str = self._to_entry.get().strip() or None
        label = date_pill_label(
            is_default=self._range == (None, None),
            preset=self._active_preset,
            from_str=from_str,
            to_str=to_str,
        )
        if self._range == (None, None):
            fg = NEUTRAL_PILL
        elif self._is_staged:
            fg = STAGED_TINT
        else:
            fg = ACCENT_BLUE
        self.pill.configure(text=label, fg_color=fg)

    def mark_staged(self, is_staged: bool) -> None:
        """Set the staged-tint flag and repaint the pill (T3.9)."""
        if is_staged == self._is_staged:
            return
        self._is_staged = is_staged
        self._update_pill()

    def _fire(self) -> None:
        if self._on_change:
            self._on_change()

    def reset(self) -> None:
        """Restore "any time" (no filter) without firing change."""
        self._range = (None, None)
        self._active_preset = "Any time"
        # The manual entries always exist (built in __init__ via _build_overlay),
        # so no existence guard is needed.
        self._from_entry.delete(0, "end")
        self._to_entry.delete(0, "end")
        self._clear_error()
        self._refresh_preset_styles()
        self.pill.configure(text="Added: any time", fg_color=NEUTRAL_PILL)

    def commit_display(self) -> None:
        """Snapshot the current display state as the last-applied display (T2.4).

        Called by the panel on Apply so a later Cancel can restore the exact
        visual state (preset highlight + manual entry text), not just the epochs.
        """
        self._committed_display = (
            self._range,
            self._active_preset,
            self._from_entry.get(),
            self._to_entry.get(),
        )

    def restore_display(self) -> None:
        """Restore the last-committed display state without firing change (T2.4).

        Reconstructs ``_range``, ``_active_preset``, the manual entry text, the
        preset highlights and the pill from ``_committed_display``. Silent (no
        ``_fire``) — Cancel must not mark itself dirty.
        """
        self._range, self._active_preset, from_text, to_text = self._committed_display
        self._from_entry.delete(0, "end")
        if from_text:
            self._from_entry.insert(0, from_text)
        self._to_entry.delete(0, "end")
        if to_text:
            self._to_entry.insert(0, to_text)
        self._clear_error()
        self._refresh_preset_styles()
        # A manual range (no active preset) needs the entry strings to label the
        # pill; a preset labels itself from _active_preset.
        if self._active_preset is None:
            self._update_pill(from_str=from_text or None, to_str=to_text or None)
        else:
            self._update_pill()

    @property
    def is_default(self) -> bool:
        return self._range == (None, None)

    @property
    def selected_date_range(self) -> tuple[float | None, float | None]:
        return self._range


# ── Filter bar container + reset affordance (T3.5) ──


class FilterBar(ctk.CTkFrame):
    """The single-row container for the four filter controls + "Reset filters".

    Controls sit left-to-right; "Reset filters" is right-anchored and only shown
    when at least one control deviates from its default (Finding 5). Pressing it
    STAGES all four controls back to defaults and fires a single
    ``on_filter_change`` — which, post-ADR-012, is the panel's dirty-recompute
    (``_on_staged_change``), not a re-score. Reset therefore surfaces Apply/Cancel
    and requires Apply to take effect.
    """

    def __init__(
        self,
        master,
        host: tk.Widget,
        on_filter_change: Callable[[], None] | None = None,
        **kwargs,
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)
        self._on_filter_change = on_filter_change
        self._host = host

        # Controls left, reset right.
        self.grid_columnconfigure(4, weight=1)  # spacer column before reset

        self.crate_filter = FilterDropdown(
            self, host, label="Crates", on_change=self._changed)
        self.crate_filter.grid(row=0, column=0, padx=(0, 6), pady=2)

        self.genre_filter = FilterDropdown(
            self, host, label="Genres", on_change=self._changed)
        self.genre_filter.grid(row=0, column=1, padx=(0, 6), pady=2)

        self.key_offset = KeyOffsetControl(self, on_change=self._changed)
        self.key_offset.grid(row=0, column=2, padx=(0, 6), pady=2)

        self.date_range = DateRangeControl(self, host, on_change=self._changed)
        self.date_range.grid(row=0, column=3, padx=(0, 6), pady=2)

        self._reset_lbl = ctk.CTkLabel(
            self, text="Reset filters", font=ctk.CTkFont(size=12),
            text_color=SECONDARY_GREY, cursor="hand2",
        )
        self._reset_lbl.grid(row=0, column=5, padx=(6, 4), pady=2, sticky="e")
        self._reset_lbl.bind("<Button-1>", lambda _e: self._reset_all())
        self._reset_lbl.bind(
            "<Enter>", lambda _e: self._reset_lbl.configure(text_color=PRIMARY_TEXT))
        self._reset_lbl.bind(
            "<Leave>", lambda _e: self._reset_lbl.configure(text_color=SECONDARY_GREY))
        self._reset_lbl.grid_remove()

    def _changed(self):
        self._update_reset_visibility()
        if self._on_filter_change:
            self._on_filter_change()

    def refresh_reset_visibility(self) -> None:
        """Public hook for the panel to re-evaluate "Reset filters" visibility.

        Wraps the private ``_update_reset_visibility`` so Apply/Cancel handlers in
        the suggestion panel don't reach into a private method (review MEDIUM
        layering fix). Symmetric: both Apply and Cancel call this.
        """
        self._update_reset_visibility()

    def _update_reset_visibility(self):
        any_active = not (
            self.crate_filter.is_default
            and self.genre_filter.is_default
            and self.key_offset.is_default
            and self.date_range.is_default
        )
        if any_active:
            self._reset_lbl.grid()
        else:
            self._reset_lbl.grid_remove()

    def _reset_all(self):
        FloatingOverlay.close_open()
        self.crate_filter.reset()
        self.genre_filter.reset()
        self.key_offset.reset()
        self.date_range.reset()
        self._update_reset_visibility()
        if self._on_filter_change:
            self._on_filter_change()
