from __future__ import annotations

import logging
import tkinter as tk
from typing import TYPE_CHECKING

import customtkinter as ctk

from source.config import CAMELOT_COLORS, energy_color
from source.services.waveform import WaveformGenerator
from source.ui.tooltip import Tooltip
from source.ui.utils import truncate
from source.ui.waveform_widget import WaveformWidget

if TYPE_CHECKING:
    from source.services.audio_player import AudioPlayer

logger = logging.getLogger(__name__)


def _score_color(score: float) -> str:
    """Return a color based on match score (0-1)."""
    if score >= 0.75:
        return "#28a745"
    if score >= 0.55:
        return "#ffc107"
    return "#fd7e14"


# ── Generic filter dropdown ──


class FilterDropdown(ctk.CTkFrame):
    """Dropdown with checkboxes, plus Select All / Deselect All."""

    def __init__(self, master, label: str, on_change=None, **kwargs):
        super().__init__(master, **kwargs)
        self._on_change = on_change
        self._label = label
        self._vars: dict[str, tk.BooleanVar] = {}

        self.grid_columnconfigure(0, weight=1)

        self.toggle_btn = ctk.CTkButton(
            self, text=f"Filter {label}: All Selected", height=28,
            font=ctk.CTkFont(size=12),
            fg_color=("gray75", "gray35"),
            hover_color=("gray65", "gray45"),
            text_color=("gray10", "gray90"),
            anchor="w", command=self._toggle,
        )
        self.toggle_btn.grid(row=0, column=0, sticky="ew", padx=5, pady=(0, 2))

        self.dropdown = ctk.CTkFrame(self)
        self.dropdown.grid(row=1, column=0, sticky="ew", padx=5)
        self.dropdown.grid_columnconfigure(0, weight=1)
        self.dropdown.grid_remove()
        self._open = False

        btn_frame = ctk.CTkFrame(self.dropdown, fg_color="transparent")
        btn_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=(5, 2))
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            btn_frame, text="Select All", height=24,
            font=ctk.CTkFont(size=11),
            fg_color="#28a745", hover_color="#218838",
            command=self._select_all,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 2))

        ctk.CTkButton(
            btn_frame, text="Deselect All", height=24,
            font=ctk.CTkFont(size=11),
            fg_color="#dc3545", hover_color="#c82333",
            command=self._deselect_all,
        ).grid(row=0, column=1, sticky="ew", padx=(2, 0))

        self.checklist = ctk.CTkScrollableFrame(self.dropdown, height=200)
        self.checklist.grid(row=1, column=0, sticky="ew", padx=2, pady=(2, 5))
        self.checklist.grid_columnconfigure(0, weight=1)

    def set_items(self, names: list[str]):
        self._vars.clear()
        for w in self.checklist.winfo_children():
            w.destroy()
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

    def _toggle(self):
        if self._open:
            self.dropdown.grid_remove()
        else:
            self.dropdown.grid()
        self._open = not self._open

    def _select_all(self):
        for v in self._vars.values():
            v.set(True)
        self._update_label()
        self._fire()

    def _deselect_all(self):
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
        if selected == total:
            self.toggle_btn.configure(text=f"Filter {self._label}: All Selected ({total})")
        elif selected == 0:
            self.toggle_btn.configure(text=f"Filter {self._label}: None Selected")
        else:
            self.toggle_btn.configure(text=f"Filter {self._label}: {selected} of {total} selected")

    def _fire(self):
        if self._on_change:
            self._on_change()

    @property
    def selected(self) -> set[str]:
        return {n for n, v in self._vars.items() if v.get()}

    @property
    def all_selected(self) -> bool:
        return all(v.get() for v in self._vars.values())


# ── Suggestion panel ──

# Column widths for the suggestion grid
_COL = {
    "score": 48, "artist": 140, "title": 160,
    "key": 48, "bpm": 48, "energy": 32, "genre": 68,
    "play": 32, "add": 32,
}


class SuggestionPanel(ctk.CTkFrame):
    """Grid-aligned suggestion list with Camelot key coloring."""

    def __init__(
        self,
        master,
        on_select=None,
        on_filter_change=None,
        audio_player: AudioPlayer | None = None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self._on_select = on_select
        self._on_filter_change = on_filter_change
        self._audio_player = audio_player
        self._waveform_gen = WaveformGenerator()

        # Playback UI state
        self._playing_file: str | None = None
        self._playing_row_idx: int | None = None
        self._play_buttons: dict[int, ctk.CTkButton] = {}  # row_idx -> button
        self._waveform_widget: WaveformWidget | None = None
        self._poll_id: str | None = None

        # Wire track-end callback
        if self._audio_player is not None and self._audio_player.available:
            self._audio_player.set_on_track_end(self._on_track_end)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # Header
        self.header = ctk.CTkLabel(
            self, text="Suggestions",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.header.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")

        # Filter row — crates and genres side by side
        filter_row = ctk.CTkFrame(self, fg_color="transparent")
        filter_row.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 3))
        filter_row.grid_columnconfigure(0, weight=1)
        filter_row.grid_columnconfigure(1, weight=1)

        self.crate_filter = FilterDropdown(filter_row, label="Crates", on_change=self._filter_changed)
        self.crate_filter.grid(row=0, column=0, sticky="ew", padx=(0, 3))

        self.genre_filter = FilterDropdown(filter_row, label="Genres", on_change=self._filter_changed)
        self.genre_filter.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        # Column headers
        col_hdr = ctk.CTkFrame(self, fg_color=("gray85", "gray20"), height=26)
        col_hdr.grid(row=2, column=0, sticky="ew", padx=5)
        col_hdr.grid_propagate(False)

        headers = [
            ("%", _COL["score"]), ("Artist", _COL["artist"]),
            ("Title", _COL["title"]), ("Key", _COL["key"]),
            ("BPM", _COL["bpm"]), ("E", _COL["energy"]),
            ("Genre", _COL["genre"]),
        ]
        # Add play column header only when audio is available
        if self._audio_available:
            headers.append(("", _COL["play"]))
        headers.append(("", _COL["add"]))

        for col, (text, w) in enumerate(headers):
            ctk.CTkLabel(
                col_hdr, text=text, width=w,
                font=ctk.CTkFont(size=10, weight="bold"), anchor="w",
            ).grid(row=0, column=col, padx=(6 if col == 0 else 2, 2), pady=3, sticky="w")

        # Scrollable results
        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.grid(row=3, column=0, padx=5, pady=(0, 5), sticky="nsew")
        self.scroll_frame.grid_columnconfigure(0, weight=1)

        self._show_empty("Select a track to see suggestions")

    @property
    def _audio_available(self) -> bool:
        return self._audio_player is not None and self._audio_player.available

    # ── Public API ──

    def set_crates(self, crate_names: list[str]):
        self.crate_filter.set_items(crate_names)

    def set_genres(self, genre_names: list[str]):
        self.genre_filter.set_items(genre_names)

    @property
    def selected_crates(self) -> set[str]:
        return self.crate_filter.selected

    @property
    def all_crates_selected(self) -> bool:
        return self.crate_filter.all_selected

    @property
    def selected_genres(self) -> set[str]:
        return self.genre_filter.selected

    @property
    def all_genres_selected(self) -> bool:
        return self.genre_filter.all_selected

    def _filter_changed(self):
        if self._on_filter_change:
            self._on_filter_change()

    def set_suggestions(self, scored_tracks: list):
        """Populate the panel with scored track suggestions."""
        self._stop_playback()
        self._play_buttons.clear()

        for w in self.scroll_frame.winfo_children():
            w.destroy()

        if not scored_tracks:
            self._show_empty("No compatible tracks found")
            self.header.configure(text="Suggestions (0)")
            return

        self.header.configure(text=f"Suggestions ({len(scored_tracks)})")

        # Each suggestion takes two grid rows: row content + waveform slot
        for i, scored in enumerate(scored_tracks):
            track = scored.track
            score_pct = int(scored.total_score * 100)
            s_color = _score_color(scored.total_score)
            key_color = CAMELOT_COLORS.get(track.camelot_key, "#ffffff")
            e_color = energy_color(track.energy) if track.energy else "#999999"

            row_bg = ("gray88", "gray22") if i % 2 == 0 else ("gray82", "gray28")
            hover_bg = ("gray75", "gray32")

            # Grid row index: 2 rows per suggestion (content + waveform slot)
            grid_row = i * 2

            row = ctk.CTkFrame(
                self.scroll_frame, fg_color=row_bg,
                corner_radius=4, cursor="hand2",
            )
            row.grid(row=grid_row, column=0, sticky="ew", padx=2, pady=2)

            cells = [
                (f"{score_pct}%", _COL["score"], s_color, "bold"),
                (truncate(track.artist, 20), _COL["artist"], None, "normal"),
                (truncate(track.title, 22), _COL["title"], None, "normal"),
                (track.camelot_key, _COL["key"], key_color, "bold"),
                (str(int(track.bpm)) if track.bpm else "", _COL["bpm"], None, "normal"),
                (str(track.energy) if track.energy else "", _COL["energy"], e_color, "normal"),
                (track.genre or "", _COL["genre"], None, "normal"),
            ]

            labels = []
            for col, (text, width, color, weight) in enumerate(cells):
                lbl = ctk.CTkLabel(
                    row, text=text, width=width,
                    font=ctk.CTkFont(size=12, weight=weight),
                    text_color=color if color else ("gray10", "gray90"),
                    anchor="w",
                )
                lbl.grid(
                    row=0, column=col,
                    padx=(6 if col == 0 else 2, 2), pady=5, sticky="w",
                )
                lbl.bind("<Button-1>", lambda e, t=track: self._select_track(t))
                labels.append(lbl)

            next_col = len(cells)

            # Play/pause button (only when audio backend is available)
            if self._audio_available:
                play_btn = ctk.CTkButton(
                    row, text="\u25B6", width=_COL["play"], height=24,
                    fg_color="transparent", hover_color="#1f6aa5",
                    text_color="#888888",
                    font=ctk.CTkFont(size=14),
                    command=lambda t=track, idx=i: self._on_play(t, idx),
                )
                play_btn.grid(row=0, column=next_col, padx=(0, 2), sticky="e")
                self._play_buttons[i] = play_btn
                next_col += 1

            # Small + button
            add_btn = ctk.CTkButton(
                row, text="+", width=_COL["add"], height=24,
                fg_color="transparent", hover_color="#28a745",
                text_color="#888888",
                font=ctk.CTkFont(size=14, weight="bold"),
                command=lambda t=track: self._select_track(t),
            )
            add_btn.grid(row=0, column=next_col, padx=(0, 4), sticky="e")

            # Hover effect on row + labels
            for widget in [row] + labels:
                widget.bind(
                    "<Enter>",
                    lambda e, r=row, h=hover_bg: r.configure(fg_color=h),
                )
                widget.bind(
                    "<Leave>",
                    lambda e, r=row, b=row_bg: r.configure(fg_color=b),
                )

            # Row click
            row.bind("<Button-1>", lambda e, t=track: self._select_track(t))

            # Tooltip with score breakdown + crates
            tip_lines = [
                f"Key: {int(scored.key_score * 100)}%   "
                f"Energy: {int(scored.energy_score * 100)}%   "
                f"BPM: {int(scored.bpm_score * 100)}%",
            ]
            if track.crates:
                tip_lines.append(f"\nCrates: {', '.join(track.crates)}")
            Tooltip(row, "\n".join(tip_lines))

    # ── Track selection ──

    def _select_track(self, track):
        # Selecting a track stops any active preview
        self._stop_playback()
        if self._on_select:
            self._on_select(track)

    # ── Audio preview ──

    def _on_play(self, track, row_idx: int) -> str:
        """Handle play button click for a suggestion row."""
        if self._audio_player is None:
            return "break"

        file_path = track.full_file_path

        # If clicking the same track that's playing, toggle pause
        if self._playing_file == file_path:
            if self._audio_player.is_paused:
                self._audio_player.resume()
                self._set_button_icon(row_idx, "\u23F8")
                self._start_polling()
            elif self._audio_player.is_playing:
                self._audio_player.pause()
                self._set_button_icon(row_idx, "\u25B6")
                self._stop_polling()
            return "break"

        # Stop any previous playback
        self._stop_playback()

        # Start new playback
        if not self._audio_player.play(file_path):
            logger.warning("Cannot play: %s", track.display_name)
            return "break"

        self._playing_file = file_path
        self._playing_row_idx = row_idx
        self._set_button_icon(row_idx, "\u23F8")

        # Show waveform below this row
        self._show_waveform(track, row_idx)
        self._start_polling()

        return "break"

    def _show_waveform(self, track, row_idx: int) -> None:
        """Create a WaveformWidget below the given row."""
        self._destroy_waveform()

        waveform_grid_row = row_idx * 2 + 1
        logger.info("Showing waveform at grid row %d for %s", waveform_grid_row, track.display_name)

        self._waveform_widget = WaveformWidget(
            self.scroll_frame,
            on_seek=self._on_waveform_seek,
            on_stop=self._stop_playback,
        )
        self._waveform_widget.grid(
            row=waveform_grid_row, column=0, sticky="ew", padx=4, pady=(0, 2),
        )
        self._waveform_widget.set_loading()

        # Request waveform data (async if not cached)
        file_path = track.full_file_path
        cached = self._waveform_gen.get_waveform(
            file_path,
            callback=lambda data, fp=file_path: self._on_waveform_ready(fp, data),
        )
        if cached is not None:
            duration = self._audio_player.get_duration() if self._audio_player else 0.0
            self._waveform_widget.set_data(cached, duration)

    def _on_waveform_ready(self, file_path: str, data: list[float]) -> None:
        """Callback from WaveformGenerator (may arrive on a background thread)."""
        # Schedule on the main thread
        try:
            self.after(0, lambda: self._apply_waveform_data(file_path, data))
        except Exception:
            pass  # widget may have been destroyed

    def _apply_waveform_data(self, file_path: str, data: list[float]) -> None:
        """Apply waveform data to the widget (main thread only)."""
        if self._waveform_widget is None:
            logger.debug("Waveform data arrived but widget is gone")
            return
        if self._playing_file != file_path:
            logger.debug("Waveform data arrived for stale file")
            return
        duration = self._audio_player.get_duration() if self._audio_player else 0.0
        logger.info("Applying waveform data: %d bars, duration=%.1fs", len(data), duration)
        self._waveform_widget.set_data(data, duration)

    def _on_waveform_seek(self, fraction: float) -> None:
        """Handle click-to-seek on the waveform."""
        if self._audio_player is None or not self._audio_player.is_playing:
            return
        duration = self._audio_player.get_duration()
        if duration > 0:
            self._audio_player.seek(fraction * duration)

    # ── Playhead polling ──

    def _start_polling(self) -> None:
        self._stop_polling()
        self._poll_playhead()

    def _stop_polling(self) -> None:
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None

    def _poll_playhead(self) -> None:
        """Update waveform playhead position every 100ms."""
        if self._audio_player is None:
            return

        # Check if track ended naturally
        if self._audio_player.check_track_ended():
            return  # _on_track_end callback handles cleanup

        if self._audio_player.is_playing and self._waveform_widget is not None:
            pos = self._audio_player.get_position()
            self._waveform_widget.set_position(pos)

        if self._audio_player.is_playing or self._audio_player.is_paused:
            self._poll_id = self.after(100, self._poll_playhead)

    # ── Playback state management ──

    def _on_track_end(self) -> None:
        """Called when a track finishes playing naturally."""
        # Schedule on main thread (callback may fire from poll context)
        try:
            self.after(0, self._reset_playback_ui)
        except Exception:
            pass

    def _stop_playback(self) -> None:
        """Stop audio and reset all playback UI state."""
        if self._audio_player is not None:
            self._audio_player.stop()
        self._reset_playback_ui()

    def _reset_playback_ui(self) -> None:
        """Reset buttons and waveform without stopping audio (already stopped)."""
        self._stop_polling()
        if self._playing_row_idx is not None:
            self._set_button_icon(self._playing_row_idx, "\u25B6")
        self._playing_file = None
        self._playing_row_idx = None
        self._destroy_waveform()

    def _destroy_waveform(self) -> None:
        if self._waveform_widget is not None:
            try:
                self._waveform_widget.destroy()
            except Exception:
                pass
            self._waveform_widget = None

    def _set_button_icon(self, row_idx: int, icon: str) -> None:
        btn = self._play_buttons.get(row_idx)
        if btn is not None:
            try:
                btn.configure(text=icon)
            except Exception:
                pass

    # ── Existing public API ──

    def clear(self):
        self._stop_playback()
        self._play_buttons.clear()
        for w in self.scroll_frame.winfo_children():
            w.destroy()
        self._show_empty("Select a track to see suggestions")
        self.header.configure(text="Suggestions")

    def _show_empty(self, text: str):
        ctk.CTkLabel(
            self.scroll_frame, text=text,
            text_color="gray", font=ctk.CTkFont(size=12),
        ).grid(row=0, column=0, padx=10, pady=20)

