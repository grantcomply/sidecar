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
from collections.abc import Sequence
from typing import Callable

import customtkinter as ctk

from source.services import library_copy as copy
from source.services.library_copy import overlay_empty_text

from source.config import KEY_OFFSET_RANGE
from source.services.dates import date_range_to_epoch
from source.ui.tooltip import Tooltip
from source.ui.utils import truncate, truncate_start

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


def _singular(label: str) -> str:
    """``"Playlists"`` → ``"playlist"``, ``"Genres"`` → ``"genre"``."""
    word = label.lower()
    return word[:-1] if word.endswith("s") else word


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

    def __init__(
        self,
        host: tk.Widget,
        trigger: tk.Widget,
        on_close: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("corner_radius", 8)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", SEPARATOR_GREY)
        super().__init__(host, **kwargs)
        self._host = host
        self._trigger = trigger
        self._on_close = on_close
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
        if self._on_close is not None:
            self._on_close()
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


DEFAULT_OVERLAY_SIZE = (200, 200)
CRATE_OVERLAY_SIZE = (300, 320)  # playlist filter at scale (UI audit H1)
SEARCH_DEBOUNCE_MS = 150  # as the dashboard search (track_detail.py)
LABEL_TRUNCATE_AT = 38
MIN_OVERLAY_WIDTH = 200
MIN_LIST_HEIGHT = 120
_OVERLAY_EDGE = 8
_OVERLAY_CHROME = 110  # search box + buttons + paddings above the list


FilterItem = str | tuple[str | None, ...]  # see FilterDropdown.set_items


def _normalise_item(item: FilterItem) -> tuple[str, str, str | None, str]:
    """``(key, label, group, short)`` from any ``FilterDropdown.set_items`` item form."""
    if isinstance(item, str):
        return (item, item, None, item)
    key, label = str(item[0]), str(item[1])
    group = item[2] if len(item) > 2 else None
    short = item[3] if len(item) > 3 and item[3] else label
    return (key, label, group, short)


class _Row:
    """One checklist row (or group header), built once and hidden/shown by search."""

    __slots__ = ("key", "label", "group", "widget")

    def __init__(self, key: str | None, label: str, group: str | None, widget) -> None:
        self.key, self.label, self.group, self.widget = key, label, group, widget


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
        *,
        searchable: bool = False,
        overlay_size: tuple[int, int] = DEFAULT_OVERLAY_SIZE,
        **kwargs,
    ) -> None:
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)
        self._searchable = searchable
        self._overlay_size = overlay_size
        self._rows: list[_Row] = []
        self._search_after: str | None = None
        self._no_match: ctk.CTkLabel | None = None
        self._on_change = on_change
        self._label = label
        self._host = host
        self._vars: dict[str, tk.BooleanVar] = {}  # keyed by item key (e.g. crate id)
        self._labels: dict[str, str] = {}  # item key -> display label
        self._short: dict[str, str] = {}  # item key -> single-selection pill name (leaf)
        self._items: list[tuple[str, str, str | None, str]] = []  # (key, label, group, short)
        self._is_staged = False  # staged-tint flag (T3.9)

        self.pill = ctk.CTkButton(
            self, text=label, height=PILL_HEIGHT, corner_radius=PILL_CORNER,
            font=ctk.CTkFont(size=12),
            fg_color=NEUTRAL_PILL, hover_color=NEUTRAL_HOVER, text_color=PILL_TEXT,
            command=self._toggle_overlay,
        )
        self.pill.pack()

        # Decided: the search text clears on close, so the list always reopens unfiltered.
        self._overlay = FloatingOverlay(host, self, on_close=self._clear_search)
        self._overlay.grid_columnconfigure(0, weight=1)

        # Optional search box (type-to-filter, T3c.10) above the buttons.
        self._search: ctk.CTkEntry | None = None
        if searchable:
            self._search = ctk.CTkEntry(
                self._overlay, height=26, font=ctk.CTkFont(size=11),
                placeholder_text=copy.find_placeholder(_singular(label)),
            )
            self._search.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 0))
            self._search.bind("<KeyRelease>", lambda _e: self._schedule_search())

        # "Select all" + "Clear" sit side by side at the top of the overlay.
        # "Clear" (deselect-all) is paired with an intentional empty-state message
        # in the suggestion panel so a fully-cleared filter no longer reads as a bug.
        actions = ctk.CTkFrame(self._overlay, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=8, pady=(8, 4))
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

        width, height = overlay_size
        self.checklist = ctk.CTkScrollableFrame(self._overlay, height=height, width=width)
        self.checklist.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 8))
        self.checklist.grid_columnconfigure(0, weight=1)

        self._empty_label: ctk.CTkLabel | None = None

    def set_items(
        self,
        items: Sequence[FilterItem],
        *,
        preserve_selection: bool = False,
    ):
        """Rebuild the checklist.

        Each item is a plain string (key and label), a ``(key, label)`` pair, a
        ``(key, label, group)`` triple or a ``(key, label, group, short)``
        quadruple. With two or more groups, a non-interactive header precedes
        each group (in the order given); one group renders flat. ``selected`` /
        ``restore`` work on keys; checkboxes show labels; a single-selection pill
        shows ``short`` (e.g. a playlist's leaf name, T5.3), else the label.

        By default every item starts checked. With ``preserve_selection`` (live
        refresh), existing keys keep their checked state, new keys start
        checked and removed keys are dropped; ``on_change`` is not fired.
        """
        rows = [_normalise_item(item) for item in items]
        if preserve_selection and rows == self._items:
            return  # live refresh with nothing new: no rebuild, no flicker in an open list
        self._items = rows
        previous = {key: var.get() for key, var in self._vars.items()} if preserve_selection else {}
        self._vars.clear()
        self._labels.clear()
        self._short.clear()
        self._rows.clear()
        for w in self.checklist.winfo_children():
            w.destroy()
        self._empty_label = None
        self._no_match = None
        if not rows:
            self._empty_label = ctk.CTkLabel(
                self.checklist, text=overlay_empty_text(_singular(self._label)),
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
        groups = list(dict.fromkeys(g for _k, _l, g, _s in rows if g is not None))
        grouped = len(groups) >= 2
        if grouped:  # ungrouped rows (unknown provider) go above the first header
            rows = sorted(rows, key=lambda row: row[2] is not None)  # stable
        row_index = 0
        current_group: object = object()
        for key, label, group, short in rows:
            if grouped and group != current_group and group is not None:
                current_group = group
                header = ctk.CTkLabel(
                    self.checklist, text=copy.group_header(group or ""), anchor="w",
                    font=ctk.CTkFont(size=10, weight="bold"), text_color=SECONDARY_GREY,
                )
                header.grid(row=row_index, column=0, sticky="w", padx=5, pady=(6, 1))
                self._rows.append(_Row(None, "", group, header))
                row_index += 1
            var = tk.BooleanVar(value=previous.get(key, True))
            self._vars[key] = var
            self._labels[key] = label
            self._short[key] = short
            # Decided: cut from the start, keeping the leaf name (rows differ at the end).
            shown = truncate_start(label, LABEL_TRUNCATE_AT)
            box = ctk.CTkCheckBox(
                self.checklist, text=shown, variable=var,
                font=ctk.CTkFont(size=11),
                height=22, checkbox_width=18, checkbox_height=18,
                command=self._on_check_changed,
            )
            box.grid(row=row_index, column=0, sticky="w", padx=5, pady=1)
            if shown != label:
                Tooltip(box, label)  # full label only where it was cut
            self._rows.append(_Row(key, label, group, box))
            row_index += 1
        self._no_match = ctk.CTkLabel(
            self.checklist, text="", font=ctk.CTkFont(size=11), text_color=SECONDARY_GREY,
            wraplength=190, justify="left",
        )
        self._no_match.grid(row=row_index, column=0, sticky="w", padx=5, pady=6)
        self._no_match.grid_remove()
        self._apply_search()
        self._update_label()

    # ── Type-to-filter (T3c.10) ──

    @property
    def search_text(self) -> str:
        return self._search.get().strip() if self._search is not None else ""

    def _clear_search(self) -> None:
        if self._search is None or not self._search.get():
            return
        self._search.delete(0, "end")
        self._flush_search()

    def _flush_search(self) -> None:
        """Apply any pending debounced search now, so actions see the rows shown."""
        if self._search_after is not None:
            self.after_cancel(self._search_after)
            self._search_after = None
        self._apply_search()

    def _schedule_search(self) -> None:
        if self._search_after is not None:
            self.after_cancel(self._search_after)
        self._search_after = self.after(SEARCH_DEBOUNCE_MS, self._apply_search)

    def _visible_keys(self) -> list[str]:
        text = self.search_text.casefold()
        return [r.key for r in self._rows
                if r.key is not None and (not text or text in r.label.casefold())]

    def _apply_search(self) -> None:
        """Hide and show rows (never rebuild), so ticks survive typing."""
        self._search_after = None
        text = self.search_text
        visible = set(self._visible_keys())
        groups_with_rows = {r.group for r in self._rows if r.key in visible}
        for row in self._rows:
            show = (row.key in visible) if row.key is not None else (row.group in groups_with_rows)
            if show:
                row.widget.grid()
            else:
                row.widget.grid_remove()
        if self._no_match is not None:
            if text and not visible:
                self._no_match.configure(text=copy.no_match_text(_singular(self._label), text))
                self._no_match.grid()
            else:
                self._no_match.grid_remove()
        searching = bool(text)
        self._select_all_btn.configure(
            text=copy.BUTTON_SELECT_SHOWN if searching else copy.BUTTON_SELECT_ALL)
        self._clear_btn.configure(text=copy.BUTTON_CLEAR_SHOWN if searching else copy.BUTTON_CLEAR)

    def _fit_overlay(self) -> None:
        """Clamp the overlay to the host's width and the window bottom (T3c.10)."""
        if self._overlay_size == DEFAULT_OVERLAY_SIZE:
            return
        x, y = self._overlay._placement()  # noqa: SLF001 - same module
        host_w, host_h = self._host.winfo_width(), self._host.winfo_height()
        want_w, want_h = self._overlay_size
        room_w = max(MIN_OVERLAY_WIDTH, host_w - x - _OVERLAY_EDGE)
        width = want_w if host_w <= 1 else min(want_w, room_w)
        height = want_h if host_h <= 1 else min(
            want_h, max(MIN_LIST_HEIGHT, host_h - y - _OVERLAY_CHROME))
        self.checklist.configure(width=width, height=height)

    def set_label(self, label: str) -> None:
        """Change the pill label (e.g. ``"Crates"`` → ``"Playlists"``) and its empty text."""
        if label == self._label:
            return
        self._label = label
        if self._empty_label is not None:
            self._empty_label.configure(text=overlay_empty_text(_singular(label)))
        if self._search is not None:
            self._search.configure(placeholder_text=copy.find_placeholder(_singular(label)))
        self._apply_search()
        self._update_label()

    def _toggle_overlay(self):
        if self._overlay.is_open:
            self._overlay.close()
        else:
            self._fit_overlay()
            self._overlay.open()
            if self._search is not None:
                self.after(10, self._search.focus_set)  # type straight away

    def _select_all(self):
        """Tick every item, or only the shown ones while a search is active."""
        self._flush_search()
        for key in self._visible_keys():
            self._vars[key].set(True)
        self._update_label()
        self._fire()

    def _deselect_all(self):
        """Clear every item (or the shown ones while searching): an intentional empty filter."""
        self._flush_search()
        for key in self._visible_keys():
            self._vars[key].set(False)
        self._update_label()
        self._fire()

    def _on_check_changed(self):
        self._update_label()
        self._fire()

    def _update_label(self):
        total = len(self._vars)
        selected = sum(1 for v in self._vars.values() if v.get())
        only = (
            truncate(self._short[next(k for k, v in self._vars.items() if v.get())], 10)
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
            self, host, label="Crates", on_change=self._changed,
            searchable=True, overlay_size=CRATE_OVERLAY_SIZE)
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
