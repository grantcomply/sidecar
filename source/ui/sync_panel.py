"""Settings dialog: one card per music source (Phase 3c; ui-design-brief.md §4, §5.1-§5.4).

Provider-agnostic: every card is rendered from a ``ProviderSettingsView``
(labels, hints, detected values, issues, chip inputs). Nothing here branches on
``provider_id``. Edits are staged until ``Save`` or ``Sync enabled sources``.
``update_status`` refreshes chips and status lines only, never the staged
entries, switches or tiles.
"""

from __future__ import annotations

import dataclasses
import tkinter as tk
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from source import __version__
from source.config import (
    ERROR_COLOR,
    INFO_COLOR,
    SECONDARY_TEXT_COLOR,
    SUCCESS_COLOR,
    WARNING_COLOR,
)
from source.providers.base import ProviderIssue, SettingKind, SettingSpec
from source.services import library_copy as copy
from source.services.settings_model import ProviderSettingsView, first_error_message
from source.ui.filter_bar import ACCENT_BLUE, NEUTRAL_HOVER, NEUTRAL_PILL, STAGED_TINT
from source.ui.tooltip import Tooltip

CARD_COLOR = "#2a2a2a"
CARD_RADIUS = 10
DEFAULT_SIZE = (640, 580)
MIN_SIZE = (540, 420)
MAX_SCREEN_FRACTION = 0.85
SYNC_GREEN_HOVER = "#218838"  # the fill is config.SUCCESS_COLOR (audit L1)
# Disabled primary buttons must not be the brightest thing in the footer (audit M1).
SYNC_DISABLED_FILL = "#2f3a32"  # low-chroma dark green
SAVE_DISABLED_FILL = "#2f3338"  # low-chroma dark blue-grey
HEADING_SIZE = 15  # decided: outranks the 13 bold card names (audit M3)
ISSUE_SIZE = 12  # field errors: 12 pt, bold for error tone (audit H2, decided O18)
VALIDATE_DEBOUNCE_MS = 400
TONE_COLORS = {"error": ERROR_COLOR, "warning": WARNING_COLOR}
PRIMARY_TEXT = ("gray10", "#DCE4EE")  # CTk's default label text colour
# Wrap widths follow the dialog width (minus margins), so nothing is clipped at 540 px.
HEADING_MARGIN, CARD_TEXT_MARGIN, CHIP_SHARE, CHIP_MIN = 40, 110, 0.45, 160

OnSave = Callable[[list[str], dict[str, dict[str, str]]], bool]
OnSync = Callable[[list[str]], None]
OnValidate = Callable[[str, dict[str, str]], list[ProviderIssue]]


class _Card:
    """Widgets and staged state for one provider."""

    def __init__(self, view: ProviderSettingsView) -> None:
        self.view = view
        self.enabled = tk.BooleanVar(value=view.enabled)
        # Entries are read directly: CTkEntry hides its placeholder when a
        # textvariable is attached, and the placeholder carries the detected path.
        self.entries: dict[str, ctk.CTkEntry] = {}
        self.choices: dict[str, str] = {}
        self.issues: list[ProviderIssue] = list(view.issues)
        self.frame: ctk.CTkFrame | None = None
        self.chip: ctk.CTkLabel | None = None
        self.rows: ctk.CTkFrame | None = None
        self.off_label: ctk.CTkLabel | None = None
        self.status: ctk.CTkFrame | None = None
        self.spec_rows: dict[str, ctk.CTkFrame] = {}
        self.controls: list[ctk.CTkBaseClass] = []
        self.tiles: dict[str, dict[str, ctk.CTkButton]] = {}
        self.name_label: ctk.CTkLabel | None = None
        self.field_issue: dict[str, ctk.CTkLabel] = {}  # issue line under each field (H2)
        self.validate_after: str | None = None

    def staged_values(self) -> dict[str, str]:
        values = dict(self.view.values)
        values.update({k: e.get().strip() for k, e in self.entries.items()})
        values.update(self.choices)
        return values


class SettingsDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        views: Sequence[ProviderSettingsView],
        *,
        on_save: OnSave,
        on_sync: OnSync,
        on_validate: OnValidate,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self.title(copy.dialog_title(__version__))
        self._on_save, self._on_sync, self._on_validate = on_save, on_sync, on_validate
        self._cards: dict[str, _Card] = {v.provider_id: _Card(v) for v in views}
        self._order = [v.provider_id for v in views]
        self._saved: dict[str, tuple[bool, dict[str, str]]] = {}
        self._busy = False
        self._footer_owned = False  # status text currently set by footer_state
        # (label, margin) pairs re-wrapped on resize; chips are sized separately.
        self._wrapped: list[tuple[ctk.CTkLabel, int]] = []
        self._last_width = 0

        self._set_geometry()
        self.transient(master)
        self.grab_set()
        self.bind("<Escape>", self._on_escape)
        self.protocol("WM_DELETE_WINDOW", self._cancel)  # acts as Cancel, no prompt

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_heading()
        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._body.grid(row=2, column=0, sticky="nsew", padx=12, pady=(4, 4))
        self._body.grid_columnconfigure(0, weight=1)
        for i, pid in enumerate(self._order):
            self._build_card(self._cards[pid], i)
        # After the cards exist: entries and tiles normalise values (e.g. an
        # unknown CHOICE value), so a snapshot taken earlier would open dirty.
        self._saved = self._snapshot_state()
        self._build_footer()
        self._apply_wraps()
        for pid in self._order:
            self._validate(pid)
        self._refresh_all()
        self.bind("<Configure>", self._on_configure, add="+")
        self._center(master)
        # No entry has focus on open, so the detected-path placeholder shows (audit M5).
        self.after(50, self._focus_frame)

    def _on_escape(self, _event: object = None) -> None:
        self._cancel()

    def destroy(self) -> None:
        """Cancel pending debounced validations first: they would touch dead widgets."""
        for card in self._cards.values():
            if card.validate_after is not None:
                try:
                    self.after_cancel(card.validate_after)
                except (ValueError, tk.TclError):
                    pass
                card.validate_after = None
        super().destroy()

    def _cancel(self) -> None:
        """Esc, the window's close button and Close/Cancel: drop staged edits, no prompt."""
        self.destroy()

    def _focus_frame(self) -> None:
        try:
            self.focus_set()
        except tk.TclError:
            pass

    # ── Geometry ──

    def _set_geometry(self) -> None:
        width, height = DEFAULT_SIZE
        height = min(height, int(self.winfo_screenheight() * MAX_SCREEN_FRACTION))
        self.geometry(f"{width}x{height}")
        self.minsize(*MIN_SIZE)
        self.resizable(True, True)

    def _center(self, parent) -> None:
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    # ── Building ──

    def _build_heading(self) -> None:
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 0))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text=copy.SECTION_HEADING, anchor="w",
                     font=ctk.CTkFont(size=HEADING_SIZE, weight="bold")).grid(
            row=0, column=0, sticky="w")
        sub = ctk.CTkLabel(head, text=copy.SECTION_SUBTEXT, anchor="w", justify="left",
                           text_color=SECONDARY_TEXT_COLOR, font=ctk.CTkFont(size=11))
        sub.grid(row=1, column=0, sticky="w")
        self._note = ctk.CTkLabel(self, text="", anchor="w", justify="left",
                                  text_color=SECONDARY_TEXT_COLOR, font=ctk.CTkFont(size=11))
        self._note.grid(row=1, column=0, sticky="w", padx=16)
        self._wrapped += [(sub, HEADING_MARGIN), (self._note, HEADING_MARGIN)]

    def _build_card(self, card: _Card, index: int) -> None:
        view = card.view
        frame = ctk.CTkFrame(self._body, fg_color=CARD_COLOR, corner_radius=CARD_RADIUS)
        frame.grid(row=index, column=0, sticky="ew", pady=(0, 10))
        frame.grid_columnconfigure(0, weight=1)
        card.frame = frame

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        header.grid_columnconfigure(2, weight=1)
        switch = ctk.CTkSwitch(header, text="", width=46, variable=card.enabled,
                               command=lambda pid=view.provider_id: self._on_toggle(pid))
        switch.grid(row=0, column=0, sticky="w")
        card.controls.append(switch)
        card.name_label = ctk.CTkLabel(header, text=view.display_name,
                                       font=ctk.CTkFont(size=13, weight="bold"))
        card.name_label.grid(row=0, column=1, sticky="w")
        card.chip = ctk.CTkLabel(header, text="", justify="right", anchor="e",
                                 text_color=SECONDARY_TEXT_COLOR, font=ctk.CTkFont(size=11))
        card.chip.grid(row=0, column=2, sticky="e", padx=(12, 0))

        card.rows = ctk.CTkFrame(frame, fg_color="transparent", height=1)
        card.rows.grid_columnconfigure(1, weight=1)
        for spec in view.specs:
            self._build_spec_row(card, spec)
        card.off_label = ctk.CTkLabel(frame, text="", anchor="w", text_color=SECONDARY_TEXT_COLOR,
                                      font=ctk.CTkFont(size=11))
        # height=1: an empty CTkFrame otherwise reserves 200 px.
        card.status = ctk.CTkFrame(frame, fg_color="transparent", height=1)

    def _build_spec_row(self, card: _Card, spec: SettingSpec) -> None:
        if spec.kind is SettingKind.CHOICE and len(spec.choices) < 2:
            return  # one choice: nothing to pick (brief §4)
        row = ctk.CTkFrame(card.rows, fg_color="transparent")
        row.grid_columnconfigure(1, weight=1)
        card.spec_rows[spec.key] = row
        ctk.CTkLabel(row, text=spec.label, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky="w", padx=(0, 8))
        value = card.view.values.get(spec.key, "")
        if spec.kind is SettingKind.CHOICE:
            self._build_tiles(card, spec, row, value)
        else:
            self._build_entry(card, spec, row, value)
        issue = ctk.CTkLabel(row, text="", anchor="w", justify="left",
                             font=ctk.CTkFont(size=ISSUE_SIZE))
        card.field_issue[spec.key] = issue  # gridded at row 1 only while an issue shows
        self._wrapped.append((issue, CARD_TEXT_MARGIN))
        if spec.hint:
            hint = ctk.CTkLabel(row, text=spec.hint, anchor="w", justify="left",
                                text_color=SECONDARY_TEXT_COLOR, font=ctk.CTkFont(size=11))
            hint.grid(row=2, column=0, columnspan=3, sticky="w", pady=(2, 0))
            self._wrapped.append((hint, CARD_TEXT_MARGIN))

    def _build_entry(self, card: _Card, spec: SettingSpec, row: ctk.CTkFrame, value: str) -> None:
        detected = card.view.detected.get(spec.key)
        placeholder = detected if (detected and not value) else spec.placeholder
        entry = ctk.CTkEntry(row, placeholder_text=placeholder or None,
                             show="•" if spec.secret else "")
        if value:
            entry.insert(0, value)
        entry.grid(row=0, column=1, sticky="ew")
        card.entries[spec.key] = entry
        pid = card.view.provider_id
        entry.bind("<FocusOut>", lambda _e: self._after_edit(pid))
        entry.bind("<Return>", lambda _e: self._after_edit(pid))
        entry.bind("<KeyRelease>", lambda _e: self._on_key(pid))
        card.controls.append(entry)
        if spec.kind in (SettingKind.FILE, SettingKind.DIRECTORY):
            browse = ctk.CTkButton(row, text=copy.BUTTON_BROWSE, width=80,
                                   command=lambda: self._browse(card, spec))
            browse.grid(row=0, column=2, padx=(8, 0))
            card.controls.append(browse)

    def _build_tiles(self, card: _Card, spec: SettingSpec, row: ctk.CTkFrame, value: str) -> None:
        card.choices[spec.key] = value if value in spec.choices else spec.choices[0]
        tiles = ctk.CTkFrame(row, fg_color="transparent")
        tiles.grid(row=0, column=1, sticky="w")
        buttons: dict[str, ctk.CTkButton] = {}
        for i, choice in enumerate(spec.choices):
            btn = ctk.CTkButton(tiles, text=choice.capitalize(), width=56, height=26,
                                hover_color=NEUTRAL_HOVER,
                                command=lambda c=choice: self._pick(card, spec, c))
            btn.grid(row=0, column=i, padx=(0, 4))
            buttons[choice] = btn
            card.controls.append(btn)
        card.tiles[spec.key] = buttons

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 14))
        footer.grid_columnconfigure(0, weight=1)
        self._status = ctk.CTkLabel(footer, text="", anchor="w", justify="left",
                                    font=ctk.CTkFont(size=12))
        self._wrapped.append((self._status, 200))  # room for "Unsaved changes"
        self._status.grid(row=0, column=0, sticky="w")
        self._unsaved = ctk.CTkLabel(footer, text="", text_color=STAGED_TINT,
                                     font=ctk.CTkFont(size=11))
        self._unsaved.grid(row=0, column=1, sticky="e", padx=(8, 0))
        buttons = ctk.CTkFrame(footer, fg_color="transparent")
        buttons.grid(row=1, column=0, columnspan=2, sticky="e", pady=(8, 0))
        self._close_btn = ctk.CTkButton(buttons, text=copy.BUTTON_CLOSE, width=90,
                                        fg_color=NEUTRAL_PILL, hover_color=NEUTRAL_HOVER,
                                        command=self._cancel)
        self._close_btn.grid(row=0, column=0, padx=(0, 8))
        self._save_btn = ctk.CTkButton(buttons, text=copy.BUTTON_SAVE, width=90,
                                       command=self._save)
        self._save_fill = self._save_btn.cget("fg_color")  # theme blue, restored on enable
        self._save_btn.grid(row=0, column=1, padx=(0, 8))
        self._sync_btn = ctk.CTkButton(buttons, text=copy.BUTTON_SYNC, width=200, height=36,
                                       fg_color=SUCCESS_COLOR, hover_color=SYNC_GREEN_HOVER,
                                       font=ctk.CTkFont(size=14, weight="bold"),
                                       command=self._sync)
        self._sync_btn.grid(row=0, column=2)

    # ── Staged state ──

    def _snapshot_state(self) -> dict[str, tuple[bool, dict[str, str]]]:
        return {pid: (c.enabled.get(), c.staged_values()) for pid, c in self._cards.items()}

    @property
    def is_dirty(self) -> bool:
        return self._snapshot_state() != self._saved

    def staged_enabled_ids(self) -> list[str]:
        return [pid for pid in self._order if self._cards[pid].enabled.get()]

    def staged_values(self) -> dict[str, dict[str, str]]:
        return {pid: self._cards[pid].staged_values() for pid in self._order}

    def _errors(self) -> dict[str, str]:
        out = {}
        for pid in self.staged_enabled_ids():
            first = first_error_message(self._cards[pid].issues)
            if first is not None:
                out[pid] = first
        return out

    def _validate_enabled(self) -> None:
        for pid in self.staged_enabled_ids():
            self._validate(pid)

    # ── Events ──

    def _on_toggle(self, pid: str) -> None:
        self._validate(pid)
        self._refresh_all()

    def _on_key(self, pid: str) -> None:
        """Typing or pasting: footer now, card issue lines ~400 ms after the last key."""
        self._refresh_footer()
        card = self._cards[pid]
        if card.validate_after is not None:
            self.after_cancel(card.validate_after)
        card.validate_after = self.after(VALIDATE_DEBOUNCE_MS, lambda: self._debounced(pid))

    def _debounced(self, pid: str) -> None:
        self._cards[pid].validate_after = None
        self._after_edit(pid)

    def _after_edit(self, pid: str) -> None:
        self._validate(pid)
        self._refresh_card(pid)
        self._refresh_footer()

    def _pick(self, card: _Card, spec: SettingSpec, choice: str) -> None:
        if self._busy:
            return
        card.choices[spec.key] = choice
        self._after_edit(card.view.provider_id)

    def _browse(self, card: _Card, spec: SettingSpec) -> None:
        entry = card.entries[spec.key]
        current = entry.get() or card.view.detected.get(spec.key, "")
        initial = str(Path(current).parent) if current else None
        if spec.kind is SettingKind.DIRECTORY:
            chosen = filedialog.askdirectory(title=spec.browse_title or None, initialdir=initial)
        else:
            chosen = filedialog.askopenfilename(
                title=spec.browse_title or None, initialdir=initial,
                filetypes=list(spec.file_patterns) or [("All files", "*.*")],
            )
        if chosen:
            entry.delete(0, "end")
            entry.insert(0, str(Path(chosen)))
        self._after_edit(card.view.provider_id)

    def _validate(self, pid: str) -> None:
        card = self._cards[pid]
        card.issues = list(self._on_validate(pid, card.staged_values()))

    def _save(self) -> bool:
        if self._busy or not self.is_dirty:
            return False
        if self._on_save(self.staged_enabled_ids(), self.staged_values()):
            self._saved = self._snapshot_state()
            self.set_footer_status(copy.SETTINGS_SAVED, SUCCESS_COLOR)
            self._refresh_all()
            return True
        return False

    def _sync(self) -> None:
        if self._busy:
            return
        # Entries may have changed with no focus-out (e.g. a paste): never sync
        # on issues computed for older values.
        self._validate_enabled()
        if self.is_dirty and not self._on_save(self.staged_enabled_ids(), self.staged_values()):
            return
        self._saved = self._snapshot_state()
        errors = self._errors()
        ids = [pid for pid in self.staged_enabled_ids() if pid not in errors]
        if ids:
            self._on_sync(ids)
        self._refresh_all()

    # ── Rendering ──

    def _refresh_all(self) -> None:
        for pid in self._order:
            self._refresh_card(pid)
        enabled = self.staged_enabled_ids()
        names = [self._cards[pid].view.display_name for pid in enabled]
        self._note.configure(text=copy.precedence_note(names[0]) if len(names) >= 2 else "")
        self._note.grid() if len(names) >= 2 else self._note.grid_remove()
        self._refresh_footer()

    def _refresh_card(self, pid: str) -> None:
        card = self._cards[pid]
        on = card.enabled.get()
        self._render_chip(card, on)
        if card.name_label is not None:
            card.name_label.configure(text_color=PRIMARY_TEXT if on else SECONDARY_TEXT_COLOR)
        if card.rows is None or card.off_label is None or card.status is None:
            return
        if on:
            card.off_label.grid_remove()
            card.rows.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 4))
            self._render_rows(card)
            self._render_status(card)
        else:
            card.rows.grid_remove()
            card.status.grid_remove()
            text = copy.OFF_WITH_SNAPSHOT if card.view.summary else copy.OFF
            card.off_label.configure(text=text)
            card.off_label.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 10))

    def _render_chip(self, card: _Card, on: bool) -> None:
        if card.chip is None:
            return
        if self._busy and on:
            card.chip.configure(text=copy.SYNCING, text_color=INFO_COLOR)
            return
        summary = card.view.summary
        lines = copy.status_chip(
            enabled=on, busy=False,
            synced_at=summary.synced_at if summary else None,
            track_count=summary.track_count if summary else 0,
            crate_count=summary.crate_count if summary else 0,
            noun=card.view.crate_noun, auto_updates=card.view.auto_updates,
            now=datetime.now(timezone.utc),
        )
        text = "" if not on else "\n".join(lines)
        card.chip.configure(text=text, text_color=SECONDARY_TEXT_COLOR)

    def _render_rows(self, card: _Card) -> None:
        values = card.staged_values()
        for i, spec in enumerate(card.view.specs):
            row = card.spec_rows.get(spec.key)
            if row is None:
                continue
            cond = spec.visible_when
            visible = cond is None or values.get(cond[0]) == cond[1]
            if visible:
                row.grid(row=i, column=0, columnspan=3, sticky="ew", pady=(0, 8))
            else:
                row.grid_remove()
            for choice, btn in card.tiles.get(spec.key, {}).items():
                active = card.choices.get(spec.key) == choice
                btn.configure(fg_color=ACCENT_BLUE if active else NEUTRAL_PILL)

    def _render_status(self, card: _Card) -> None:
        if card.status is None:
            return
        for w in card.status.winfo_children():
            w.destroy()
        values = card.staged_values()
        visible_fields = {k for k, row in card.spec_rows.items() if row.grid_info()}
        by_field: dict[str, ProviderIssue] = {}
        bottom: list[tuple[str, str, bool]] = []  # (text, colour, bold)
        shown: set[str] = set()
        for issue in card.issues:
            tone = copy.issue_tone(issue, values.get(issue.setting_key or "", ""))
            key = issue.setting_key
            if key in visible_fields and key in card.field_issue and key not in by_field:
                by_field[key] = issue
            else:
                bottom.append((issue.message, TONE_COLORS[tone], tone == "error"))
            shown.add(issue.message)
        self._render_field_issues(card, by_field, values)
        has_error = any(i.severity == "error" for i in card.issues)
        if card.view.last_error and card.view.last_error not in shown:
            bottom.append((card.view.last_error, ERROR_COLOR, True))
        if card.view.summary and (card.view.last_error or has_error):
            when = copy.absolute_time(card.view.summary.synced_at)
            if when:
                bottom.append((copy.fallback_line(when), SECONDARY_TEXT_COLOR, False))
        warnings: list[str] = list(card.view.warnings)
        if not bottom and not warnings:
            card.status.grid_remove()
            return
        card.status.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 10))
        for r, (text, color, bold) in enumerate(bottom):
            self._line(card.status, text, color, bold=bold).grid(row=r, column=0, sticky="w")
        if warnings:
            more = f" (+{len(warnings) - 1} more)" if len(warnings) > 1 else ""
            label = self._line(card.status, warnings[0] + more, WARNING_COLOR)
            label.grid(row=len(bottom), column=0, sticky="w")
            if len(warnings) > 1:
                Tooltip(label, "\n".join(warnings[1:]))

    def _render_field_issues(
        self, card: _Card, by_field: dict[str, ProviderIssue], values: dict[str, str],
    ) -> None:
        for key, label in card.field_issue.items():
            issue = by_field.get(key)
            if issue is None:
                label.grid_remove()
                continue
            tone = copy.issue_tone(issue, values.get(key, ""))
            label.configure(
                text=issue.message, text_color=TONE_COLORS[tone],
                font=ctk.CTkFont(size=ISSUE_SIZE, weight="bold" if tone == "error" else "normal"),
            )
            label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(3, 0))

    def _line(self, parent, text: str, color: str, *, bold: bool = False) -> ctk.CTkLabel:
        size = ISSUE_SIZE if bold or color in (ERROR_COLOR,) else 11
        return ctk.CTkLabel(parent, text=text, anchor="w", justify="left",
                            wraplength=self._wrap_for(CARD_TEXT_MARGIN), text_color=color,
                            font=ctk.CTkFont(size=size, weight="bold" if bold else "normal"))

    def _wrap_for(self, margin: int) -> int:
        width = self._last_width or DEFAULT_SIZE[0]
        return max(120, width - margin)

    def _on_configure(self, event) -> None:
        if event.widget is not self or event.width == self._last_width:
            return
        self._last_width = event.width
        self._apply_wraps()

    def _apply_wraps(self) -> None:
        for label, margin in self._wrapped:
            label.configure(wraplength=self._wrap_for(margin))
        chip = max(CHIP_MIN, int((self._last_width or DEFAULT_SIZE[0]) * CHIP_SHARE))
        for card in self._cards.values():
            if card.chip is not None:
                card.chip.configure(wraplength=chip)
            if card.status is not None:
                for line in card.status.winfo_children():
                    line.configure(wraplength=self._wrap_for(CARD_TEXT_MARGIN))

    def _refresh_footer(self) -> None:
        if self.is_dirty:
            self._validate_enabled()  # footer state follows what is typed now (cheap stat calls)
        names = {pid: c.view.display_name for pid, c in self._cards.items()}
        state = copy.footer_state(self.staged_enabled_ids(), self._errors(), names,
                                  dirty=self.is_dirty, busy=self._busy)
        self._close_btn.configure(text=state.close_label)
        self._save_btn.configure(
            state="normal" if state.save_enabled else "disabled",
            fg_color=self._save_fill if state.save_enabled else SAVE_DISABLED_FILL,
        )
        self._sync_btn.configure(
            text=copy.BUTTON_SYNCING if self._busy else copy.BUTTON_SYNC,
            state="normal" if state.sync_enabled else "disabled",
            fg_color=SUCCESS_COLOR if state.sync_enabled else SYNC_DISABLED_FILL,
        )
        self._unsaved.configure(text=copy.UNSAVED_CHANGES if self.is_dirty else "")
        if state.message:
            color = TONE_COLORS[state.tone or "warning"]
            self._status.configure(text=state.message, text_color=color)
            self._footer_owned = True
        elif self._footer_owned:
            self._status.configure(text="")  # the condition cleared; keep any sync/save text
            self._footer_owned = False

    # ── Public API (called by the app through _with_dialog) ──

    @property
    def is_busy(self) -> bool:
        return self._busy

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for card in self._cards.values():
            for widget in card.controls:
                widget.configure(state=state)
        self._refresh_all()
        if not busy:
            self._focus_frame()

    def set_footer_status(self, text: str, color: str) -> None:
        self._status.configure(text=text, text_color=color)
        self._footer_owned = False

    def update_status(self, views: Sequence[ProviderSettingsView]) -> None:
        """New sync/refresh results: chips, issue, warning and fallback lines only.

        Staged values, switches and tiles are untouched; issues are re-validated
        against the staged values.
        """
        for view in views:
            card = self._cards.get(view.provider_id)
            if card is None:
                continue
            card.view = dataclasses.replace(
                card.view, detected=view.detected, capabilities=view.capabilities,
                summary=view.summary, warnings=view.warnings, last_error=view.last_error,
            )
            self._validate(view.provider_id)
        self._refresh_all()
