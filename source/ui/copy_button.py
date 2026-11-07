"""Icon-only "copy search text" button with self-confirming states (brief §3, §5).

Four looks, each with its own glyph so state never depends on colour alone:
ready, copied (1.5 s), failed (1.5 s) and disabled (nothing to copy). The
tooltip carries the words, because the button has no visible label.

Rules (brief §5):
- every click restarts the 1.5 s timer; clicks are never ignored;
- only one button in the app shows a copied/failed flash at a time;
- no timer survives the button (a re-render destroys rows).

Uses ``command=`` only; it never binds ``<Button-1>``, so a click cannot reach
the row's select handler (blueprint D4).
"""

from __future__ import annotations

import enum
import logging
import tkinter as tk
from collections.abc import Callable
from typing import ClassVar

import customtkinter as ctk

from source.config import ERROR_COLOR, SECONDARY_TEXT_COLOR, SUCCESS_COLOR
from source.services import library_copy as strings
from source.ui.tooltip import Tooltip

logger = logging.getLogger(__name__)

COPY_BUTTON_WIDTH = 36
COPY_BUTTON_HEIGHT = 28
COPY_BUTTON_CORNER_RADIUS = 6
COPY_BUTTON_FONT_SIZE = 14
COPY_FEEDBACK_MS = 1500

# Colours: existing ui-design-guide §3 tokens only (no new colour).
_FILL = "#2a2a2a"  # card fill
_HOVER_FILL = "#1f6aa5"  # accent blue
_SUCCESS_FILL = SUCCESS_COLOR
_ERROR_FILL = ERROR_COLOR
_GLYPH = SECONDARY_TEXT_COLOR
_GLYPH_ON_FILL = "#ffffff"
_GLYPH_DISABLED = "#555555"


class CopyState(enum.Enum):
    READY = "ready"
    COPIED = "copied"
    FAILED = "failed"
    DISABLED = "disabled"


# Enabled looks: (glyph, fill, hover fill, bold). Copied/failed hover with their own
# fill so the pointer resting on the button after a click never repaints it blue.
_LOOKS: dict[CopyState, tuple[str, str, str, bool]] = {
    CopyState.READY: (strings.BUTTON_COPY, _FILL, _HOVER_FILL, False),
    CopyState.COPIED: (strings.BUTTON_COPIED, _SUCCESS_FILL, _SUCCESS_FILL, True),
    CopyState.FAILED: (strings.BUTTON_COPY_FAILED, _ERROR_FILL, _ERROR_FILL, True),
}


class CopyButton(ctk.CTkButton):
    """A row's copy button. ``command`` returns True when the text reached the clipboard."""

    _flashing: ClassVar[CopyButton | None] = None  # the one button showing copied/failed

    def __init__(self, master, *, query: str | None, command: Callable[[], bool], **kwargs):
        super().__init__(
            master,
            text=strings.BUTTON_COPY,
            width=COPY_BUTTON_WIDTH,
            height=COPY_BUTTON_HEIGHT,
            corner_radius=COPY_BUTTON_CORNER_RADIUS,
            fg_color=_FILL,
            hover_color=_HOVER_FILL,
            text_color=_GLYPH,
            text_color_disabled=_GLYPH_DISABLED,
            font=ctk.CTkFont(size=COPY_BUTTON_FONT_SIZE),
            command=self._on_click,
            **kwargs,
        )
        self._query = query
        self._copy_command = command
        self._regular_font = self.cget("font")
        self._bold_font = ctk.CTkFont(size=COPY_BUTTON_FONT_SIZE, weight="bold")
        self._after_id: str | None = None
        self._hovering = False
        self.copy_state = CopyState.READY
        self.tooltip = Tooltip(self, "")
        self.bind("<Enter>", self._on_pointer_enter, add="+")
        self.bind("<Leave>", self._on_pointer_leave, add="+")
        self._set_state(CopyState.READY if query is not None else CopyState.DISABLED)

    # ── Click and timer ──

    def _on_click(self) -> None:
        self.tooltip.hide()
        ok = bool(self._copy_command())
        previous = CopyButton._flashing
        if previous is not None and previous is not self:
            previous._return_to_ready()
        self._cancel_timer()
        self._set_state(CopyState.COPIED if ok else CopyState.FAILED)
        CopyButton._flashing = self
        self._after_id = self.after(COPY_FEEDBACK_MS, self._on_timer)

    def _on_timer(self) -> None:
        self._after_id = None
        if not self.winfo_exists():
            return
        self._return_to_ready()

    def _return_to_ready(self) -> None:
        self._cancel_timer()
        if CopyButton._flashing is self:
            CopyButton._flashing = None
        self._set_state(CopyState.READY)

    def _cancel_timer(self) -> None:
        if self._after_id is None:
            return
        after_id, self._after_id = self._after_id, None
        try:
            self.after_cancel(after_id)
        except (ValueError, tk.TclError) as e:  # already fired, or the widget is gone
            logger.debug("Copy feedback timer already gone (%s)", type(e).__name__)

    def destroy(self) -> None:
        self._cancel_timer()
        self.tooltip.hide()  # a pending 400 ms show must not fire on a dead widget
        if CopyButton._flashing is self:
            CopyButton._flashing = None
        super().destroy()

    # ── Looks ──

    def _set_state(self, state: CopyState) -> None:
        self.copy_state = state
        if state is CopyState.DISABLED:
            self.configure(
                state="disabled", text=strings.BUTTON_COPY_DISABLED, fg_color=_FILL,
                hover_color=_FILL, font=self._regular_font,
            )
            self.tooltip.update_text(strings.COPY_NOTHING)
            return
        glyph, fill, hover, bold = _LOOKS[state]
        self.configure(
            state="normal", text=glyph, fg_color=fill, hover_color=hover,
            text_color=self._glyph_colour(),
            font=self._bold_font if bold else self._regular_font,
        )
        self.tooltip.update_text(self._tooltip_text(state))
        if self._hovering:
            self._on_enter()  # repaint the hover fill under a resting pointer

    def _tooltip_text(self, state: CopyState) -> str:
        query = self._query or ""
        if state is CopyState.COPIED:
            return strings.format_copied_tooltip(query)
        if state is CopyState.FAILED:
            return strings.COPY_FAILED_TOOLTIP
        return strings.format_copy_tooltip(query)

    def _glyph_colour(self) -> str:
        if self.copy_state is CopyState.READY and not self._hovering:
            return _GLYPH
        return _GLYPH_ON_FILL

    def _on_pointer_enter(self, _event: tk.Event | None = None) -> None:
        self._hovering = True
        if self.copy_state is not CopyState.DISABLED:
            # configure() redraws with fg_color, wiping the hover fill CTk just painted;
            # repaint it. _on_enter is private CTk API (checked against 5.2.2).
            self.configure(text_color=self._glyph_colour())
            self._on_enter()

    def _on_pointer_leave(self, _event: tk.Event | None = None) -> None:
        self._hovering = False
        if self.copy_state is not CopyState.DISABLED:
            # The redraw paints fg_color, which is the resting look CTk's _on_leave wants.
            self.configure(text_color=self._glyph_colour())
