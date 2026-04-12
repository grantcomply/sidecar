import logging
import threading
import tkinter as tk
import webbrowser
from typing import Callable, Optional

import customtkinter as ctk
from source.config import _load_env, get_subcrates_dir, save_subcrates_dir
from source.models.track import Track
from source.models.library import TrackLibrary
from source.services.suggestion_engine import get_suggestions
from source.services.audio_player import AudioPlayer
from source.services.crate_sync import sync_crates
from source.services.updater import UpdateInfo
from source.ui.sync_panel import SettingsDialog
from source.ui.track_detail import NowPlayingDashboard
from source.ui.suggestion_panel import SuggestionPanel
from source.ui.session_panel import SessionPanel

logger = logging.getLogger(__name__)

SASH_COLOR = "#333333"
SASH_WIDTH = 5


class DJTrackSelectorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("DJ Track Selector")
        self.geometry("1300x850")
        self.minsize(1000, 650)

        self.library = TrackLibrary()
        self._current_track = None
        self._settings_dialog = None
        self._toast_after_id = None
        self._toast_action_btn: Optional[ctk.CTkButton] = None

        self._audio_player = AudioPlayer()

        self._build_ui()
        self._try_load_existing()
        self._check_for_updates_async()

        # Ensure clean shutdown of audio subsystem
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI construction ──

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)  # bottom pane expands

        # Row 0: Top bar — toast notification + settings button
        top_bar = ctk.CTkFrame(self, fg_color="transparent", height=32)
        top_bar.grid(row=0, column=0, sticky="ew", padx=10, pady=(5, 0))
        top_bar.grid_columnconfigure(0, weight=1)
        top_bar.grid_propagate(False)

        # Inner frame holds the toast label + optional action button side-by-side.
        self._toast_frame = ctk.CTkFrame(top_bar, fg_color="transparent")
        self._toast_frame.grid(row=0, column=0, sticky="w", padx=5)

        self.toast_label = ctk.CTkLabel(
            self._toast_frame, text="", font=ctk.CTkFont(size=12), anchor="w",
        )
        self.toast_label.grid(row=0, column=0, sticky="w")

        settings_btn = ctk.CTkButton(
            top_bar, text="\u2699", width=32, height=32,
            font=ctk.CTkFont(size=18),
            fg_color="transparent",
            hover_color=("gray75", "gray35"),
            text_color=("gray30", "gray70"),
            command=self._open_settings,
        )
        settings_btn.grid(row=0, column=1, sticky="e")

        # Row 1: Now Playing dashboard
        self.dashboard = NowPlayingDashboard(
            self, on_track_selected=self._on_track_selected,
        )
        self.dashboard.set_search_fn(lambda q: self.library.search(q, limit=15))
        self.dashboard.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 5))

        # Row 2: Bottom — suggestions (left) + setlist (right)
        self.bottom_pane = tk.PanedWindow(
            self, orient=tk.HORIZONTAL, sashwidth=SASH_WIDTH,
            bg=SASH_COLOR, sashrelief=tk.FLAT,
        )
        self.bottom_pane.grid(row=2, column=0, sticky="nsew", padx=5, pady=(0, 5))

        self.suggestion_panel = SuggestionPanel(
            self.bottom_pane,
            on_select=self._on_suggestion_selected,
            on_filter_change=self._on_crate_filter_changed,
            audio_player=self._audio_player,
        )
        self.bottom_pane.add(self.suggestion_panel, stretch="always")

        self.session_panel = SessionPanel(
            self.bottom_pane,
            on_clear=self._on_session_cleared,
            on_remove=self._on_session_track_removed,
        )
        self.bottom_pane.add(self.session_panel, stretch="always")

        # Set initial 50/50 split after render
        self.after(50, self._set_initial_sash)

    def _set_initial_sash(self):
        self.update_idletasks()
        w = self.bottom_pane.winfo_width()
        if w > 100:
            self.bottom_pane.sash_place(0, w // 2, 0)

    def _on_close(self) -> None:
        """Clean up resources and close the application."""
        self._audio_player.shutdown()
        self.destroy()

    # ── Startup ──

    def _try_load_existing(self):
        if self.library.load_from_cache():
            self.suggestion_panel.set_crates(self.library.crate_names)
            self.suggestion_panel.set_genres(self.library.genre_names)
            self._show_toast(
                f"Loaded {self.library.count} tracks from "
                f"{len(self.library.crate_names)} crates",
                "#28a745",
            )

    # ── Toast notifications ──

    def _show_toast(
        self,
        text: str,
        color: str = "#28a745",
        duration: int = 4000,
        action_label: Optional[str] = None,
        action_callback: Optional[Callable[[], object]] = None,
    ):
        """Show a transient message in the top bar.

        If ``action_label`` and ``action_callback`` are both provided, an
        inline button is rendered next to the message; clicking it invokes
        the callback. The button is removed when the toast expires or the
        next toast is shown.
        """
        if self._toast_after_id:
            self.after_cancel(self._toast_after_id)
            self._toast_after_id = None
        self._clear_toast_action()

        self.toast_label.configure(text=text, text_color=color)

        if action_label and action_callback is not None:
            btn = ctk.CTkButton(
                self._toast_frame,
                text=action_label,
                width=90,
                height=24,
                font=ctk.CTkFont(size=11),
                command=action_callback,
            )
            btn.grid(row=0, column=1, sticky="w", padx=(8, 0))
            self._toast_action_btn = btn

        self._toast_after_id = self.after(duration, self._clear_toast)

    def _clear_toast(self):
        self.toast_label.configure(text="")
        self._clear_toast_action()
        self._toast_after_id = None

    def _clear_toast_action(self):
        if self._toast_action_btn is not None:
            try:
                self._toast_action_btn.destroy()
            except tk.TclError:
                pass
            self._toast_action_btn = None

    # ── Auto-update check ──

    def _check_for_updates_async(self):
        """Kick off a background update check unless disabled in settings.

        Reads ``CHECK_FOR_UPDATES`` from ``settings.env``. The check is
        enabled by default; only the literal string ``"false"`` (case-
        insensitive) disables it. Network I/O runs on a daemon thread so a
        slow or offline DNS lookup never delays the UI.
        """
        env = _load_env()
        setting = env.get("CHECK_FOR_UPDATES", "").strip().lower()
        if setting == "false":
            logger.info("Update check disabled via CHECK_FOR_UPDATES=false")
            return

        def _run():
            # Imported inside the thread so a hypothetical import error in the
            # updater module never blocks app startup.
            from source import __version__
            from source.services.updater import check_for_update

            update = check_for_update(__version__)
            if update is not None:
                self.after(0, lambda: self._show_update_toast(update))

        thread = threading.Thread(target=_run, daemon=True, name="update-check")
        thread.start()

    def _show_update_toast(self, update: UpdateInfo):
        """Render the 'update available' toast with a Download button."""
        self._show_toast(
            f"Version {update.version} is available.",
            color="#4AB8D4",
            duration=15000,
            action_label="Download",
            action_callback=lambda: webbrowser.open(update.url),
        )

    # ── Settings dialog ──

    def _open_settings(self):
        if self._settings_dialog is not None:
            try:
                if self._settings_dialog.winfo_exists():
                    self._settings_dialog.focus()
                    return
            except tk.TclError:
                self._settings_dialog = None
        self._settings_dialog = SettingsDialog(
            self, default_path=get_subcrates_dir(), on_sync=self._on_sync,
        )

    # ── Sync ──

    def _on_sync(self, subcrates_path: str):
        save_subcrates_dir(subcrates_path)
        if self._settings_dialog:
            try:
                if self._settings_dialog.winfo_exists():
                    self._settings_dialog.set_syncing(True)
            except tk.TclError:
                self._settings_dialog = None

        def on_done(total_tracks, num_crates, error):
            self.after(0, lambda: self._sync_finished(total_tracks, num_crates, error))

        sync_crates(
            subcrates_dir=subcrates_path,
            done_callback=on_done,
        )

    def _sync_finished(self, total_tracks: int, num_crates: int, error):
        if error:
            msg, color = f"Sync failed: {error}", "#dc3545"
        else:
            # Stop any audio preview — the library is about to change
            self._audio_player.stop()
            self.library.load_from_cache()
            self.suggestion_panel.set_crates(self.library.crate_names)
            self.suggestion_panel.set_genres(self.library.genre_names)
            msg = f"Synced {self.library.count} tracks from {num_crates} crates"
            color = "#28a745"

        # Update dialog if still open
        if self._settings_dialog:
            try:
                if self._settings_dialog.winfo_exists():
                    self._settings_dialog.set_syncing(False)
                    self._settings_dialog.set_status(msg, color)
            except tk.TclError:
                self._settings_dialog = None

        self._show_toast(msg, color)

    # ── Track selection ──

    def _on_track_selected(self, track: Track):
        self._current_track = track
        self.dashboard.set_track(track)
        self.session_panel.add_track(track)
        self._update_suggestions()

    def _on_suggestion_selected(self, track: Track):
        self._current_track = track
        self.dashboard.set_track(track)
        self.session_panel.add_track(track)
        self._update_suggestions()

    def _on_session_cleared(self):
        self._update_suggestions()

    def _on_session_track_removed(self):
        self._update_suggestions()

    def _on_crate_filter_changed(self):
        self._update_suggestions()

    def _update_suggestions(self):
        if not self._current_track:
            self.suggestion_panel.clear()
            return

        allowed_crates = None
        if not self.suggestion_panel.all_crates_selected:
            allowed_crates = self.suggestion_panel.selected_crates

        allowed_genres = None
        if not self.suggestion_panel.all_genres_selected:
            allowed_genres = self.suggestion_panel.selected_genres

        scored = get_suggestions(
            self._current_track,
            self.library,
            exclude_paths=self.session_panel.played_paths,
            allowed_crates=allowed_crates,
            allowed_genres=allowed_genres,
        )
        self.suggestion_panel.set_suggestions(scored)
