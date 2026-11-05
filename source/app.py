import logging
import queue
import threading
import time
import tkinter as tk
import webbrowser
from collections.abc import Sequence
from typing import Callable, Optional

import customtkinter as ctk
from source.config import (
    ERROR_COLOR,
    INFO_COLOR,
    REFRESH_FOCUS_FLOOR_SECONDS,
    REFRESH_MAX_INTERVAL_SECONDS,
    REFRESH_MIN_INTERVAL_SECONDS,
    REFRESH_POLL_SECONDS,
    REFRESH_SETTLE_SECONDS,
    SUCCESS_COLOR,
    _load_env,
    get_provider_settings,
    save_library_settings,
)
from source.models.track import Track
from source.models.library import TrackLibrary
from source.services.suggestion_engine import get_suggestions
from source.services.audio_player import AudioPlayer
from source.providers.base import LibraryProvider, ProviderCapability, ProviderIssue
from source.providers.registry import all_providers, first_deck_load_provider, get_provider
from source.services import library_copy as copy
from source.services import library_merge, library_store
from source.services.settings_migration import effective_enabled_providers
from source.services.settings_model import ProviderSettingsView, build_provider_views
from source.services.library_sync import SyncCoordinator, SyncReport, SyncRequest
from source.services.library_watcher import LibraryWatcher, Targets
from source.services.sync_outcome import sync_outcome
from source.services.updater import UpdateInfo
from source.ui.sync_panel import SettingsDialog
from source.ui.track_detail import NowPlayingDashboard
from source.ui.suggestion_panel import SuggestionPanel
from source.ui.session_panel import SessionPanel

logger = logging.getLogger(__name__)

SASH_COLOR = "#333333"
SASH_WIDTH = 5
UI_QUEUE_POLL_MS = 100  # how often the Tk thread runs work posted by background threads
SHORT_TOAST_MS = 4000
INFO_TOAST_MS = 15000
CLOSE_WAIT_FOR_SYNC_SECONDS = 2.0  # let an in-flight snapshot write finish on close
FOCUS_CHECK_MIN_GAP_SECONDS = 2.0  # <FocusIn> fires per widget; one check per burst


class DJTrackSelectorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(copy.WINDOW_TITLE)
        self.geometry("1300x850")
        self.minsize(1000, 650)

        self.library = TrackLibrary()
        self._current_track = None
        self._settings_dialog = None
        self._toast_after_id = None
        self._toast_action_btn: Optional[ctk.CTkButton] = None
        self._closing = False
        # Background threads never touch Tk: they post callables here and the
        # Tk thread runs them (_drain_ui_queue).
        self._ui_queue: queue.SimpleQueue[Callable[[], object]] = queue.SimpleQueue()
        self._ui_pump_id: Optional[str] = None
        self._sync = SyncCoordinator()  # single-flight: manual sync + live refresh
        self._refresh_errors: dict[str, str] = {}  # provider id -> last refresh error shown
        # Last sync/refresh warnings per provider, this session (not persisted; brief §5.3).
        self._provider_warnings: dict[str, tuple[str, ...]] = {}
        self._noun = "crate"
        self._multi_provider = False  # 2+ enabled: per-provider crate lines in tooltips (T5.4)
        # Provider ids from a newer version found in settings: warned about once,
        # not on every watcher tick (the watcher re-reads the enabled list each poll).
        self._warned_unknown_providers: set[str] = set()
        self._last_focus_check = 0.0

        self._audio_player = AudioPlayer()

        self._build_ui()
        self._drain_ui_queue()
        self._try_load_existing()
        self._watcher = LibraryWatcher(
            self._watch_targets,
            self._stored_change_token,
            lambda pid: self._post(lambda: self._request_refresh(pid)),
            poll_s=REFRESH_POLL_SECONDS,
            settle_s=REFRESH_SETTLE_SECONDS,
            min_interval_s=REFRESH_MIN_INTERVAL_SECONDS,
            max_interval_s=REFRESH_MAX_INTERVAL_SECONDS,
            focus_floor_s=REFRESH_FOCUS_FLOOR_SECONDS,
        )
        self._watcher.start()
        # Coming back from rekordbox: refresh promptly if its library changed.
        self.bind("<FocusIn>", self._on_focus_in, add="+")
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
        self.dashboard.set_crate_label_fn(self.library.crate_label)
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
        self.suggestion_panel.set_crate_lines_fn(self._crate_tooltip_lines)
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
        self._closing = True
        # Wakes the sleeping watcher at once; it's a daemon thread anyway.
        self._watcher.stop()
        # Let an in-flight sync finish its atomic snapshot write (bounded wait).
        if not self._sync.wait_idle(CLOSE_WAIT_FOR_SYNC_SECONDS):
            logger.info("Closing while a sync is still running")
        self.suggestion_panel.cancel_quiet_render()
        if self._ui_pump_id is not None:
            try:
                self.after_cancel(self._ui_pump_id)
            except tk.TclError:
                pass
            self._ui_pump_id = None
        self._audio_player.shutdown()
        self.destroy()

    # ── Work posted from background threads (run on the Tk thread) ──

    def _post(self, fn: Callable[[], object]) -> None:
        """Queue ``fn`` to run on the Tk thread. Safe to call from any thread."""
        if not self._closing:
            self._ui_queue.put(fn)

    def _drain_ui_queue(self) -> None:
        while True:
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            if self._closing:
                return
            try:
                fn()
            except Exception:  # noqa: BLE001 - one failed callback must not stop the pump
                logger.exception("Background UI callback failed")
        if not self._closing:
            self._ui_pump_id = self.after(UI_QUEUE_POLL_MS, self._drain_ui_queue)

    # ── Startup ──

    def _try_load_existing(self):
        self._reload_library()
        if self.library.count:
            loaded_ids = [
                pid for pid in self._enabled_registered_providers()
                if library_store.snapshot_summary(pid) is not None
            ]
            # One loaded source: its own noun ("75 crates"), even if another
            # enabled source (with a different noun) hasn't imported yet.
            noun = get_provider(loaded_ids[0]).crate_noun if len(loaded_ids) == 1 else self._noun
            self._show_toast(
                copy.format_load_toast(
                    self.library.count, self.library.crate_count, noun,
                    [self._provider_name(pid) for pid in loaded_ids],
                ),
                SUCCESS_COLOR,
            )
        self._update_empty_state(startup=True)

    def _crate_filter_items(self) -> list[tuple[str, str, str | None, str]]:
        """``(crate id, label, provider name, leaf name)``, providers in registry order.

        The filter shows a header per provider when two or more contribute
        (T3c.10) and the leaf name on a single-selection pill (T5.3). A crate
        of unknown provider gets group ``None`` (no header) and sorts last.
        """
        order = {p.id: i for i, p in enumerate(all_providers())}
        items = self.library.crate_items  # already sorted by casefolded path
        keyed = [(order.get(self.library.crate_provider(cid) or "", len(order)), i, cid, label)
                 for i, (cid, label) in enumerate(items)]
        result: list[tuple[str, str, str | None, str]] = []
        for _o, _i, cid, label in sorted(keyed):
            pid = self.library.crate_provider(cid)
            group = self._provider_name(pid) if pid is not None else None
            result.append((cid, label, group, self.library.crate_leaf(cid)))
        return result

    def _update_empty_state(self, *, startup: bool = False) -> None:
        """Dashboard placeholder for an empty library (brief §5.8); toast on startup only."""
        if self.library.count:
            self.dashboard.set_empty_message(None)
            return
        enabled = self._enabled_registered_providers()
        pending = [
            pid for pid in enabled
            if ProviderCapability.CHANGE_DETECTION
            in get_provider(pid).capabilities(self._provider_settings(pid))
            and library_store.snapshot_summary(pid) is None
        ]
        state = copy.empty_library_state(enabled, pending, self._refresh_errors.keys())
        self.dashboard.set_empty_message(state.placeholder)
        if startup and state.toast_text:
            self._show_toast(
                state.toast_text, INFO_COLOR, duration=INFO_TOAST_MS,
                action_label=copy.ACTION_OPEN_SETTINGS, action_callback=self._open_settings,
            )

    def _apply_noun(self) -> None:
        """"crate" (Serato only) or "playlist" (any rekordbox, or a mix): brief §5.6."""
        enabled = self._enabled_registered_providers()
        self._multi_provider = len(enabled) > 1
        self._noun = copy.crate_noun_for([get_provider(pid).crate_noun for pid in enabled])
        self.suggestion_panel.set_noun(self._noun)
        self.dashboard.set_crate_noun(self._noun)

    def _crate_tooltip_lines(self, crate_ids: Sequence[str]) -> list[str]:
        """Suggestion tooltip crate lines (brief §5.10, T5.4).

        One provider enabled: ``Playlists: A, B``. More: one line per provider
        holding the track, registry order (``rekordbox: Club / Peak``).
        """
        if not self._multi_provider:
            labels = [self.library.crate_label(cid) for cid in crate_ids]
            return copy.crate_tooltip_lines([(None, labels)], self._noun)
        order = [p.id for p in all_providers()]
        groups = [
            (self._provider_name(pid) if pid is not None else None, labels)
            for pid, labels in self.library.crates_by_provider(crate_ids, order)
        ]
        return copy.crate_tooltip_lines(groups, self._noun)

    def _reload_library(self, preserve_state: bool = False) -> None:
        """Load every enabled provider's stored snapshot into the library.

        ``preserve_state=True`` (quiet live refresh) keeps the current track,
        the setlist, the filter selections and any audio preview.
        """
        old_crates = frozenset(cid for cid, _label in self.library.crate_items)
        old_genres = frozenset(self.library.genre_names)
        enabled = self._enabled_registered_providers()
        snapshots = [
            snapshot for pid in enabled
            if (snapshot := library_store.load_snapshot(pid)) is not None
        ]
        native = {
            pid for pid in enabled
            if ProviderCapability.NATIVE_PLAY_COUNT
            in get_provider(pid).capabilities(self._provider_settings(pid))
        }
        tracks, crates = library_merge.merge(snapshots, native_play_count=native)
        self.library.replace_all(tracks, crates)
        keep = preserve_state
        self.suggestion_panel.set_crates(self._crate_filter_items(), preserve_selection=keep)
        self.suggestion_panel.set_genres(self.library.genre_names, preserve_selection=keep)
        self._apply_noun()
        if preserve_state:
            self._restore_state_after_refresh(old_crates, old_genres)

    def _restore_state_after_refresh(
        self, old_crates: frozenset[str], old_genres: frozenset[str],
    ) -> None:
        """Rebind the current track and setlist to the refreshed library (T3b.4)."""
        self.suggestion_panel.reconcile_applied_filters(
            old_crates=old_crates,
            new_crates=frozenset(cid for cid, _label in self.library.crate_items),
            old_genres=old_genres,
            new_genres=frozenset(self.library.genre_names),
        )
        self.session_panel.rebind_tracks(self.library.track_by_path)
        playing = self.suggestion_panel.preview_path
        if playing is not None and self.library.track_by_path(playing) is None:
            self.suggestion_panel.stop_preview()  # its file is no longer in the library
        if self._current_track is None:
            return
        fresh = self.library.track_by_path(self._current_track.full_file_path)
        on_rendered = None
        if fresh is not None:  # if it disappeared, keep showing the old object
            if fresh != self._current_track:  # value comparison: skip a no-op re-render
                # Badges update at the same moment as the (possibly deferred) list,
                # so the two never disagree (brief §5.5). Badges only, never the search box.
                on_rendered = lambda: self.dashboard.refresh_track(fresh)  # noqa: E731
            self._current_track = fresh
        # Re-renders only if the visible list changed; deferred while the pointer
        # is over the list or a preview is active (see SuggestionPanel).
        self.suggestion_panel.show_suggestions_quietly(
            self._score_suggestions(self._current_track), on_rendered=on_rendered,
        )

    # ── Provider settings ──

    def _provider_settings(self, provider_id: str) -> dict[str, str]:
        """Current settings for a provider: persisted values over its defaults."""
        provider = get_provider(provider_id)
        return get_provider_settings(provider.setting_specs(), provider.default_settings())

    def _enabled_registered_providers(self) -> list[str]:
        """Enabled provider ids in registry order, skipping (and logging) unknown ids."""
        enabled = effective_enabled_providers()
        known = [p.id for p in all_providers()]
        for pid in enabled:
            if pid not in known and pid not in self._warned_unknown_providers:
                self._warned_unknown_providers.add(pid)  # once, not every watcher tick
                logger.warning("Unknown library provider %r in settings; skipped", pid)
        return [pid for pid in known if pid in enabled]

    def deck_load_provider_for(self, track: Track) -> LibraryProvider | None:
        """The provider that can load ``track`` to a deck, or ``None`` (T4.4, blueprint D12).

        The single gate any future load-to-deck control must use: the first
        enabled provider holding the track (precedence order) that declares
        ``DECK_LOAD``. No provider declares it yet, so this returns ``None``
        and nothing in the UI calls it in this feature.

        Cost: every call reads ``settings.env`` from disk (enabled providers,
        then each candidate's settings). Fine for one track on demand; cache
        the enabled list and settings before Phase 6 calls it per row.
        """
        enabled = set(self._enabled_registered_providers())
        candidates = [pid for pid in track.sources if pid in enabled]
        return first_deck_load_provider(candidates, self._provider_settings)

    # ── Live refresh (ADR-015 D11) ──

    def _watch_targets(self) -> Targets:
        """Enabled providers that declare CHANGE_DETECTION, with settings. Watcher thread; no Tk."""
        targets: Targets = []
        for pid in self._enabled_registered_providers():
            provider = get_provider(pid)
            settings = self._provider_settings(pid)
            if ProviderCapability.CHANGE_DETECTION in provider.capabilities(settings):
                targets.append((provider, settings))
        return targets

    @staticmethod
    def _stored_change_token(provider_id: str) -> str | None:
        summary = library_store.snapshot_summary(provider_id)
        return summary.change_token if summary is not None else None

    def _request_refresh(self, provider_id: str) -> None:
        """Quiet sync of one provider (Tk thread); merged into any running sync."""
        try:
            request = SyncRequest(get_provider(provider_id), self._provider_settings(provider_id))
            self._sync.request([request], silent=True, done_callback=self._on_sync_done)
        except (OSError, UnicodeDecodeError, KeyError, RuntimeError) as e:
            logger.warning("Live refresh of %s could not start (%s)", provider_id, type(e).__name__)

    def _on_focus_in(self, _event: object = None) -> None:
        now = time.monotonic()
        if now - self._last_focus_check >= FOCUS_CHECK_MIN_GAP_SECONDS:
            self._last_focus_check = now
            self._watcher.request_focus_check()  # stat-only check on the watcher thread

    def _on_sync_done(self, report: SyncReport, silent: bool) -> None:
        """Sync-thread callback: hand the result to the Tk thread."""
        self._post(lambda: self._sync_done_on_ui(report, silent))

    def _sync_done_on_ui(self, report: SyncReport, silent: bool) -> None:
        for result in report.results:
            self._provider_warnings[result.provider_id] = tuple(result.warnings)
            if result.error is None:
                # Manual syncs count too: the baseline moves to what was stored,
                # and a manual sync resets the adaptive backoff.
                self._watcher.mark_refreshed(
                    result.provider_id, result.change_token,
                    changed=result.changed, manual=not silent,
                )
        library_was_empty = self.library.count == 0
        outcome = sync_outcome(
            self._refresh_errors, report, silent=silent, provider_name=self._provider_name,
            library_was_empty=library_was_empty,
        )
        self._refresh_errors = outcome.errors
        if outcome.stop_audio:
            self._audio_player.stop()  # manual sync: the library is about to change
        if outcome.reload:
            self._reload_library(preserve_state=outcome.preserve_state)
        elif silent:
            logger.info("Live refresh: nothing visible changed; library not reloaded")
        for toast in outcome.toasts:
            self._show_toast(
                toast.text, toast.color, duration=toast.duration_ms,
                action_label=toast.action_label,
                action_callback=self._open_settings if toast.action_label else None,
            )
        names = [self._provider_name(pid) for pid in outcome.ok_provider_ids]
        if outcome.import_candidate and self.library.count:
            self._show_toast(copy.format_import_toast(self.library.count, names),
                             SUCCESS_COLOR, duration=SHORT_TOAST_MS)
        self._update_empty_state()
        self._with_dialog(lambda d: d.update_status(self._build_views()))
        if silent:
            # A dialog opened while only quiet work ran must not stay "Syncing…".
            if not self._sync.manual_in_progress:
                self._with_dialog(lambda d: d.set_busy(False) if d.is_busy else None)
            return  # never the dialog's footer
        if outcome.success_toast:
            msg = self._sync_success_text(report, names)
            color = SUCCESS_COLOR
            self._show_toast(msg, color)
        else:
            msg = outcome.toasts[0].text if outcome.toasts else ""
            color = outcome.toasts[0].color if outcome.toasts else ERROR_COLOR
        # Leave "Syncing" only if nothing is queued behind this run: neither a
        # follow-up the coordinator knew of when the run finished, nor one merged
        # in since (checked now, on the Tk thread). Deliberately not
        # `not self._sync.is_running`: the finishing run is still marked running
        # when its report is posted, so that test would keep "Syncing" up forever.
        if outcome.clear_dialog_syncing and not self._sync.has_pending:
            def _done(dialog) -> None:
                dialog.set_busy(False)
                dialog.set_footer_status(msg, color)

            self._with_dialog(_done)

    def _sync_success_text(self, report: SyncReport, names: list[str]) -> str:
        """One provider: its own track count and noun; several: merged count + names."""
        if len(report.results) == 1:
            result = report.results[0]
            noun = get_provider(result.provider_id).crate_noun
            return copy.format_sync_success(result.track_count, result.crate_count, noun, names)
        return copy.format_sync_success(self.library.count, report.total_crates, self._noun, names)

    @staticmethod
    def _provider_name(provider_id: str) -> str:
        try:
            return get_provider(provider_id).display_name
        except KeyError:
            return provider_id

    # ── Toast notifications ──

    def _show_toast(
        self,
        text: str,
        color: str = SUCCESS_COLOR,
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
                self._post(lambda: self._show_update_toast(update))

        thread = threading.Thread(target=_run, daemon=True, name="update-check")
        thread.start()

    def _show_update_toast(self, update: UpdateInfo):
        """Render the 'update available' toast with a Download button."""
        self._show_toast(
            f"Version {update.version} is available.",
            color=INFO_COLOR,
            duration=INFO_TOAST_MS,
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
            self,
            self._build_views(),
            on_save=self._on_settings_save,
            on_sync=self._on_settings_sync,
            on_validate=self._on_settings_validate,
        )
        if self._sync.manual_in_progress:  # quiet refreshes don't make the dialog busy
            self._settings_dialog.set_busy(True)

    def _build_views(self) -> list[ProviderSettingsView]:
        return build_provider_views(
            all_providers(),
            self._enabled_registered_providers(),
            self._provider_settings,
            library_store.snapshot_summary,
            self._provider_warnings,
            self._refresh_errors,
        )

    @staticmethod
    def _on_settings_validate(provider_id: str, values: dict[str, str]) -> list[ProviderIssue]:
        return list(get_provider(provider_id).validate(values))

    def _on_settings_save(self, enabled_ids: list[str], values: dict[str, dict[str, str]]) -> bool:
        """Persist the dialog's staged state, then reload from stored snapshots (no scan)."""
        providers = all_providers()
        try:
            save_library_settings(
                [p.id for p in providers if p.id in enabled_ids],  # registry order
                [(p.setting_specs(), values[p.id]) for p in providers if p.id in values],
            )
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Could not save settings (%s)", type(e).__name__)
            # strerror ("Access is denied"), never str(e), which carries the path.
            reason = getattr(e, "strerror", None) or type(e).__name__
            self._with_dialog(lambda d: d.set_footer_status(
                f"Settings not saved: {reason}", ERROR_COLOR,
            ))
            return False
        # Preserved reload (review decision): filters reconciled, setlist and current
        # track rebound, suggestions re-rendered; a turned-off provider's tracks leave.
        self._reload_library(preserve_state=True)
        self._update_empty_state()
        # Saved values change capabilities (e.g. auto-update off → manual chip form).
        self._with_dialog(lambda d: d.update_status(self._build_views()))
        # The watcher picks up enable/disable and auto-update changes on its next tick.
        return True

    def _on_settings_sync(self, provider_ids: list[str]) -> None:
        # Single-flight: if a sync (manual or live refresh) is running, this
        # request is merged into one follow-up run instead of running alongside.
        try:
            requests = [
                SyncRequest(get_provider(pid), self._provider_settings(pid))
                for pid in provider_ids
            ]
            started = self._sync.request(requests, silent=False, done_callback=self._on_sync_done)
        except (OSError, UnicodeDecodeError, KeyError, RuntimeError) as e:
            # Settings unreadable, unknown provider, or the thread couldn't
            # start: no callback will fire, so report and reset here.
            logger.warning("Could not start sync: %s", e)
            self._report_sync_start_failure(str(e) or type(e).__name__)
            return
        if not started:
            logger.info("Sync queued behind the running one")
        self._with_dialog(lambda d: d.set_busy(True))

    def _report_sync_start_failure(self, error: str) -> None:
        msg, color = f"Sync failed: {error}", ERROR_COLOR

        def _reset(dialog) -> None:
            dialog.set_busy(False)
            dialog.set_footer_status(msg, color)

        self._with_dialog(_reset)
        self._show_toast(msg, color)

    def _with_dialog(self, action: Callable[[SettingsDialog], object]) -> None:
        """Run ``action`` on the settings dialog if it is still open."""
        if not self._settings_dialog:
            return
        try:
            if self._settings_dialog.winfo_exists():
                action(self._settings_dialog)
        except tk.TclError:
            self._settings_dialog = None

    # ── Track selection ──

    def _on_track_selected(self, track: Track):
        track = self._current_object(track)
        self._current_track = track
        self.dashboard.set_track(track)
        self.session_panel.add_track(track)
        self._update_suggestions()

    def _current_object(self, track: Track) -> Track:
        """The library's current object for this file (lists may predate a live refresh)."""
        return self.library.track_by_path(track.full_file_path) or track

    def _on_suggestion_selected(self, track: Track):
        track = self._current_object(track)
        self._current_track = track
        self.dashboard.set_track(track)
        self.session_panel.add_track(track)
        self._update_suggestions()

    def _on_session_cleared(self):
        self._update_suggestions()

    def _on_session_track_removed(self):
        self._update_suggestions()

    def _on_crate_filter_changed(self):
        # Fired ONLY when the user clicks Apply in the suggestion panel (ADR-012).
        # Filter edits no longer reach here — they stage in the panel.
        self._update_suggestions()

    def _score_suggestions(self, current: Track) -> list:
        # Re-score with the APPLIED filter snapshot (ADR-012). A track/session
        # change reuses the last-applied filters; staged-but-unapplied edits live
        # in the widgets and don't affect results until Apply.
        return get_suggestions(
            current,
            self.library,
            exclude_paths=self.session_panel.played_paths,
            filters=self.suggestion_panel.applied_filters,
        )

    def _update_suggestions(self):
        if not self._current_track:
            self.suggestion_panel.clear()
            return
        self.suggestion_panel.set_suggestions(self._score_suggestions(self._current_track))
