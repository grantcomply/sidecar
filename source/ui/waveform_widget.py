"""Canvas-based waveform display with seek-on-click and playhead.

Renders amplitude bars on a tkinter Canvas.  The played portion (left
of the playhead) is drawn in the accent colour; the unplayed portion in
dark grey.  Clicking on the canvas fires the *on_seek* callback with a
normalised 0.0-1.0 fraction so the caller can translate it to seconds.
"""

import tkinter as tk
from typing import Callable

import customtkinter as ctk

# ── Visual constants ──

_BAR_COLOR_UNPLAYED = "#555555"
_BAR_COLOR_PLAYED = "#1f6aa5"
_PLAYHEAD_COLOR = "#ffffff"
_CANVAS_HEIGHT = 44
_BAR_GAP = 1  # px gap between bars
_MIN_BAR_HEIGHT = 2


class WaveformWidget(ctk.CTkFrame):
    """Canvas-based waveform display with seek-on-click."""

    def __init__(
        self,
        master: tk.Misc,
        on_seek: Callable[[float], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        bg_color: str = "#1a1a1a",
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color=bg_color, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        self._on_seek = on_seek
        self._on_stop = on_stop
        self._amplitudes: list[float] = []
        self._duration: float = 0.0
        self._position: float = 0.0  # current playback position in seconds
        self._bar_coords: list[tuple[int, int, int, int]] = []  # cached (x1,y1,x2,y2)

        # Canvas for waveform bars — explicit height so it's visible in scrollable frames
        self._canvas = tk.Canvas(
            self, height=_CANVAS_HEIGHT, bg=bg_color,
            highlightthickness=0, cursor="hand2",
        )
        self._canvas.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))
        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<Configure>", self._on_resize)

        # Bottom row: time label + stop button
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 4))
        bottom.grid_columnconfigure(0, weight=1)

        self._time_label = ctk.CTkLabel(
            bottom, text="0:00 / 0:00",
            font=ctk.CTkFont(size=10), text_color="#aaaaaa", anchor="w",
        )
        self._time_label.grid(row=0, column=0, sticky="w", padx=(4, 0))

        stop_btn = ctk.CTkButton(
            bottom, text="\u25A0 Stop", width=56, height=18,
            font=ctk.CTkFont(size=10),
            fg_color="transparent", hover_color="#dc3545",
            text_color="#aaaaaa",
            command=self._stop_clicked,
        )
        stop_btn.grid(row=0, column=1, sticky="e", padx=(0, 2))

        # Loading state
        self._loading_text_id: int | None = None

    # ── Public API ──

    def set_data(self, amplitudes: list[float], duration_seconds: float) -> None:
        """Set waveform amplitude data and total duration.  Triggers a full redraw."""
        self._amplitudes = amplitudes
        self._duration = duration_seconds
        self._position = 0.0
        self._clear_loading()
        self._render_bars()

    def set_position(self, seconds: float) -> None:
        """Update the playhead position.  Called periodically by the parent."""
        self._position = seconds
        self._update_colors()
        self._update_time_label()

    def set_loading(self) -> None:
        """Show a loading indicator while waveform data is being generated."""
        self._canvas.delete("all")
        self._bar_coords.clear()
        self._loading_text_id = self._canvas.create_text(
            self._canvas.winfo_width() // 2 or 200,
            _CANVAS_HEIGHT // 2,
            text="Generating waveform\u2026",
            fill="#888888",
            font=("TkDefaultFont", 10),
        )

    # ── Drawing ──

    def _render_bars(self, _retries: int = 0) -> None:
        """Full redraw of all bars from amplitude data."""
        self._canvas.delete("all")
        self._bar_coords.clear()

        if not self._amplitudes:
            return

        # Force geometry update so winfo_width() reflects actual layout
        self.update_idletasks()
        canvas_w = self._canvas.winfo_width()
        canvas_h = _CANVAS_HEIGHT
        if canvas_w < 10:
            if _retries < 10:
                self.after(50, lambda: self._render_bars(_retries + 1))
            return

        num_bars = len(self._amplitudes)
        bar_width = max((canvas_w - _BAR_GAP * num_bars) / num_bars, 1)
        step = bar_width + _BAR_GAP

        mid_y = canvas_h / 2.0

        for i, amp in enumerate(self._amplitudes):
            x1 = int(i * step)
            x2 = int(x1 + bar_width)
            half_h = max(amp * mid_y, _MIN_BAR_HEIGHT / 2)
            y1 = int(mid_y - half_h)
            y2 = int(mid_y + half_h)
            self._bar_coords.append((x1, y1, x2, y2))
            color = self._bar_color(x2, canvas_w)
            self._canvas.create_rectangle(
                x1, y1, x2, y2, fill=color, outline="", tags="bar",
            )

        # Draw initial playhead
        self._draw_playhead()
        self._update_time_label()

    def _update_colors(self) -> None:
        """Recolor bars based on current playhead position (played vs unplayed)."""
        if not self._bar_coords:
            return
        canvas_w = self._canvas.winfo_width()
        items = self._canvas.find_withtag("bar")
        for item, coords in zip(items, self._bar_coords):
            color = self._bar_color(coords[2], canvas_w)
            self._canvas.itemconfig(item, fill=color)
        self._draw_playhead()

    def _bar_color(self, bar_right_x: int, canvas_width: int) -> str:
        """Return played or unplayed colour based on playhead fraction."""
        if self._duration <= 0 or canvas_width <= 0:
            return _BAR_COLOR_UNPLAYED
        frac = self._position / self._duration
        playhead_x = frac * canvas_width
        return _BAR_COLOR_PLAYED if bar_right_x <= playhead_x else _BAR_COLOR_UNPLAYED

    def _draw_playhead(self) -> None:
        """Draw (or redraw) the vertical playhead line."""
        self._canvas.delete("playhead")
        if self._duration <= 0:
            return
        canvas_w = self._canvas.winfo_width()
        frac = min(self._position / self._duration, 1.0)
        x = int(frac * canvas_w)
        self._canvas.create_line(
            x, 0, x, _CANVAS_HEIGHT,
            fill=_PLAYHEAD_COLOR, width=2, tags="playhead",
        )

    def _update_time_label(self) -> None:
        current = _format_time(self._position)
        total = _format_time(self._duration)
        self._time_label.configure(text=f"{current} / {total}")

    def _clear_loading(self) -> None:
        if self._loading_text_id is not None:
            self._canvas.delete(self._loading_text_id)
            self._loading_text_id = None

    # ── Event handlers ──

    def _on_click(self, event: tk.Event) -> str:
        """Handle click-to-seek on the canvas."""
        canvas_w = self._canvas.winfo_width()
        if canvas_w <= 0 or self._duration <= 0:
            return "break"
        fraction = max(0.0, min(event.x / canvas_w, 1.0))
        if self._on_seek:
            self._on_seek(fraction)
        return "break"

    def _on_resize(self, _event: tk.Event) -> None:
        """Redraw bars when the canvas width changes."""
        if self._amplitudes:
            self._render_bars()

    def _stop_clicked(self) -> None:
        if self._on_stop:
            self._on_stop()


def _format_time(seconds: float) -> str:
    """Format seconds as M:SS."""
    if seconds < 0:
        seconds = 0.0
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}:{s:02d}"
