from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import customtkinter as ctk

from source.config import CAMELOT_COLORS, energy_color
from source.services.suggestion_filters import SuggestionFilters, build_filters
from source.services.waveform import WaveformGenerator
from source.ui.filter_bar import FilterBar, FloatingOverlay
from source.ui.tooltip import Tooltip
from source.ui.utils import truncate
from source.ui.waveform_widget import WaveformWidget

if TYPE_CHECKING:
    from source.services.audio_player import AudioPlayer

logger = logging.getLogger(__name__)


def _score_color(score: float) -> str:
    """Return a colour for a blended ``total_score`` (0-1), in five bands.

    Keyed off the blended ``total_score`` (key + energy + bpm), not the raw key
    score, so a loose-key track with strong energy/BPM can still read as usable.
    See ADR-010 and `docs/ui-design-brief.md` Decision 1.

        >= 0.75  green  — strong match (Perfect / Adjacent)
        >= 0.60  teal   — good match (Relative / Diagonal)
        >= 0.48  yellow — usable (Energy ±2)
        >= 0.38  orange — loose (Semitone)
        else     red    — stretch (Related)
    """
    if score >= 0.75:
        return "#28a745"
    if score >= 0.60:
        return "#20c997"
    if score >= 0.48:
        return "#ffc107"
    if score >= 0.38:
        return "#fd7e14"
    return "#dc6060"


def empty_state_message(
    *,
    crates_active_empty: bool,
    genres_active_empty: bool,
    date_filter_active: bool,
) -> str:
    """Return the suggestion-panel empty-state copy for a zero-result state.

    Precedence (first match wins): a fully-cleared crate filter, then a
    fully-cleared genre filter, then an active date range, then the generic
    fallback. A fully-cleared filter is "active but empty" — the user
    deliberately deselected everything via Clear — so the copy frames it as
    intentional, not a failure.
    """
    if crates_active_empty:
        return "No crates selected — pick at least one crate to see suggestions."
    if genres_active_empty:
        return "No genres selected — pick at least one genre to see suggestions."
    if date_filter_active:
        return (
            "No tracks found in this date range. "
            "Try a wider window or reset the date filter."
        )
    return "No compatible tracks found"


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

        # Deferred-apply state (ADR-012): the last-applied filter snapshot. The
        # live widgets are the staged source; this is the committed value the
        # rendered list reflects and what Cancel reverts the controls to.
        # Default = no filters, matching the initial unfiltered render.
        self._applied_filters: SuggestionFilters = SuggestionFilters()

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
        # Keep the filter bar from collapsing below its usable height (brief T3.5).
        self.grid_rowconfigure(1, minsize=36)

        # Header
        self.header = ctk.CTkLabel(
            self, text="Suggestions",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.header.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")

        # Filter bar — Crates | Genres | Transition | Added | Reset (brief T3.5).
        # Overlays float over this SuggestionPanel (host), so the list doesn't move.
        self.filter_bar = FilterBar(self, host=self, on_filter_change=self._on_staged_change)
        self.filter_bar.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 3))

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

        # Apply/Cancel bar (Row 4) — deferred-apply affordance (ADR-012, T3.3).
        # Hidden by default via grid_remove(); shown when staged != applied. Row 4
        # has no weight, so it slides in below the list without pushing it up.
        self._build_apply_bar()

        self._show_empty("Select a track to see suggestions")

    def _build_apply_bar(self) -> None:
        """Construct the hidden Apply/Cancel bar in Row 4 (UI brief §Apply/Cancel)."""
        self._apply_bar = ctk.CTkFrame(
            self, fg_color=("gray20", "gray20"),
            border_width=1, border_color="#333333",
        )
        self._apply_bar.grid(
            row=4, column=0, sticky="ew", padx=5, pady=(0, 5),
        )
        self._apply_bar.grid_columnconfigure(1, weight=1)  # spacer

        self._apply_bar_label = ctk.CTkLabel(
            self._apply_bar, text="Filters changed",
            font=ctk.CTkFont(size=12), text_color="#999999",
        )
        self._apply_bar_label.grid(row=0, column=0, padx=(8, 0), pady=6, sticky="w")

        self._cancel_btn = ctk.CTkButton(
            self._apply_bar, text="Cancel", height=30, width=80, corner_radius=6,
            fg_color=("gray35", "gray35"), hover_color=("gray45", "gray45"),
            text_color="#ffffff", font=ctk.CTkFont(size=12),
            command=self._cancel_filters,
        )
        self._cancel_btn.grid(row=0, column=2, padx=(0, 6), pady=6)

        self._apply_btn = ctk.CTkButton(
            self._apply_bar, text="Apply", height=30, width=80, corner_radius=6,
            fg_color="#1f6aa5", hover_color="#2980c0", text_color="#ffffff",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._apply_filters,
        )
        self._apply_btn.grid(row=0, column=3, padx=(0, 8), pady=6)

        # Hidden until the first dirty change.
        self._apply_bar.grid_remove()

    @property
    def _audio_available(self) -> bool:
        return self._audio_player is not None and self._audio_player.available

    # ── Public API ──

    def set_crates(self, crate_names: list[str]):
        self.filter_bar.crate_filter.set_items(crate_names)

    def set_genres(self, genre_names: list[str]):
        self.filter_bar.genre_filter.set_items(genre_names)

    @property
    def selected_crates(self) -> set[str]:
        return self.filter_bar.crate_filter.selected

    @property
    def all_crates_selected(self) -> bool:
        return self.filter_bar.crate_filter.all_selected

    @property
    def crates_cleared(self) -> bool:
        return self.filter_bar.crate_filter.is_cleared

    @property
    def selected_genres(self) -> set[str]:
        return self.filter_bar.genre_filter.selected

    @property
    def all_genres_selected(self) -> bool:
        return self.filter_bar.genre_filter.all_selected

    @property
    def genres_cleared(self) -> bool:
        return self.filter_bar.genre_filter.is_cleared

    @property
    def selected_key_offset(self) -> int:
        return self.filter_bar.key_offset.selected_key_offset

    @property
    def selected_date_range(self) -> tuple[float | None, float | None]:
        return self.filter_bar.date_range.selected_date_range

    # ── Staged / applied filter state (ADR-012) ──

    def current_staged_filters(self) -> SuggestionFilters:
        """Assemble an engine-ready snapshot from the live control widgets.

        The ``None``-means-no-filter normalisation lives here (moved out of
        ``app._update_suggestions``) so every snapshot is engine-ready and dirty
        comparison is a plain dataclass ``==``.
        """
        return build_filters(
            all_crates_selected=self.all_crates_selected,
            selected_crates=self.selected_crates,
            all_genres_selected=self.all_genres_selected,
            selected_genres=self.selected_genres,
            key_offset=self.selected_key_offset,
            date_range=self.selected_date_range,
        )

    @property
    def applied_filters(self) -> SuggestionFilters:
        """The last-applied snapshot — what the rendered list reflects."""
        return self._applied_filters

    @property
    def is_dirty(self) -> bool:
        """True when the staged controls differ from the applied snapshot."""
        return self.current_staged_filters() != self._applied_filters

    def _on_staged_change(self):
        """Terminus of a filter edit: recompute dirty + update affordances.

        Does NOT re-score (ADR-012 D3). The only filter-driven re-score path is
        Apply (``_apply_filters``). On every staged change we (a) show/hide the
        Apply/Cancel bar based on dirty, and (b) push per-control staged-tint
        flags so changed pills read the lighter tint until Apply.
        """
        staged = self.current_staged_filters()
        applied = self._applied_filters
        dirty = staged != applied

        if dirty:
            self._show_apply_bar()
        else:
            self._hide_apply_bar()

        self._update_staged_tints(staged, applied)

    def _update_staged_tints(
        self, staged: SuggestionFilters, applied: SuggestionFilters
    ) -> None:
        """Mark each control staged when its field differs from the applied snapshot."""
        self.filter_bar.crate_filter.mark_staged(
            staged.allowed_crates != applied.allowed_crates
        )
        self.filter_bar.genre_filter.mark_staged(
            staged.allowed_genres != applied.allowed_genres
        )
        self.filter_bar.key_offset.mark_staged(
            staged.key_offset != applied.key_offset
        )
        self.filter_bar.date_range.mark_staged(
            (staged.date_from, staged.date_to) != (applied.date_from, applied.date_to)
        )

    # ── Apply / Cancel (the sole filter-driven re-score trigger) ──

    def _show_apply_bar(self) -> None:
        self._apply_bar.grid()

    def _hide_apply_bar(self) -> None:
        self._apply_bar.grid_remove()

    def _apply_filters(self) -> None:
        """Commit the staged controls and trigger exactly one re-score."""
        FloatingOverlay.close_open()
        # Force the date control to commit any typed-but-unconfirmed manual entry
        # BEFORE we read the staged snapshot or evaluate dirty (review HIGH fix).
        # This guarantees _range and the committed display text never disagree, so
        # commit_display() below can't snapshot text that a later Cancel resurrects.
        # Must run before the dirty guard, or a clean-looking snapshot could skip
        # it and re-open the divergence (review LOW).
        self.filter_bar.date_range.commit_pending_entry()
        staged = self.current_staged_filters()
        if staged == self._applied_filters:  # guarded no-op (blueprint §4)
            self._hide_apply_bar()
            return
        self._applied_filters = staged
        self.filter_bar.date_range.commit_display()
        self._clear_all_staged_tints()
        self.filter_bar.refresh_reset_visibility()
        self._hide_apply_bar()
        if self._on_filter_change:  # app re-score callback — fired ONLY here
            self._on_filter_change()

    def _cancel_filters(self) -> None:
        """Revert every control to the last-applied snapshot. No re-score."""
        FloatingOverlay.close_open()
        f = self._applied_filters
        self.filter_bar.crate_filter.restore(f.allowed_crates)
        self.filter_bar.genre_filter.restore(f.allowed_genres)
        self.filter_bar.key_offset.restore(f.key_offset)
        self.filter_bar.date_range.restore_display()
        self.filter_bar.refresh_reset_visibility()
        self._clear_all_staged_tints()
        self._hide_apply_bar()
        # No re-score: the rendered list already reflects _applied_filters.

    def _clear_all_staged_tints(self) -> None:
        self.filter_bar.crate_filter.mark_staged(False)
        self.filter_bar.genre_filter.mark_staged(False)
        self.filter_bar.key_offset.mark_staged(False)
        self.filter_bar.date_range.mark_staged(False)

    def set_suggestions(self, scored_tracks: list):
        """Populate the panel with scored track suggestions."""
        self._stop_playback()
        self._play_buttons.clear()

        for w in self.scroll_frame.winfo_children():
            w.destroy()

        if not scored_tracks:
            # Frame a fully-cleared crate/genre filter as an intentional empty
            # state, then the date-range copy, else the generic fallback. Reads
            # the APPLIED snapshot (ADR-012 R5/T3.7) — the rendered list reflects
            # applied filters, so a staged-but-unapplied edit must not reword it.
            # A cleared filter normalises to an empty frozenset() (not None).
            applied = self._applied_filters
            self._show_empty(empty_state_message(
                crates_active_empty=applied.allowed_crates == frozenset(),
                genres_active_empty=applied.allowed_genres == frozenset(),
                date_filter_active=(applied.date_from, applied.date_to) != (None, None),
            ))
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

            # Tooltip: harmonic tier name, then score breakdown, then crates.
            tip_lines = [
                scored.harmonic_tier.value,
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

