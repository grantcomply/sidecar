import customtkinter as ctk
from source.models.track import Track
from source.config import CAMELOT_COLORS, energy_color
from source.ui.utils import truncate


class NowPlayingDashboard(ctk.CTkFrame):
    """Combined search + now-playing dashboard with large stat badges."""

    _COL_W = {
        "artist": 200, "title": 250, "key": 50,
        "bpm": 55, "energy": 40, "genre": 80,
    }

    def __init__(self, master, on_track_selected=None, **kwargs):
        super().__init__(master, **kwargs)
        self._on_track_selected = on_track_selected
        self._search_fn = None
        self._debounce_id = None

        self.grid_columnconfigure(0, weight=1)

        # ── Search entry ──
        self.search_var = ctk.StringVar()
        self.search_entry = ctk.CTkEntry(
            self, textvariable=self.search_var,
            placeholder_text="Search tracks...",
            height=42, font=ctk.CTkFont(size=15),
        )
        self.search_entry.grid(row=0, column=0, padx=15, pady=(12, 0), sticky="ew")
        self.search_entry.bind("<KeyRelease>", self._on_key)
        self.search_entry.bind("<Escape>", lambda e: self._hide_dropdown())

        # ── Search dropdown (hidden by default) ──
        self._dropdown_visible = False
        self.dropdown_container = ctk.CTkFrame(self, fg_color="transparent")
        self.dropdown_container.grid(row=1, column=0, padx=15, pady=(2, 0), sticky="ew")
        self.dropdown_container.grid_columnconfigure(0, weight=1)
        self.dropdown_container.grid_remove()

        # Column header
        hdr = ctk.CTkFrame(
            self.dropdown_container,
            fg_color=("gray85", "gray20"), height=26,
        )
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        for col, (text, w) in enumerate([
            ("Artist", self._COL_W["artist"]),
            ("Title", self._COL_W["title"]),
            ("Key", self._COL_W["key"]),
            ("BPM", self._COL_W["bpm"]),
            ("E", self._COL_W["energy"]),
            ("Genre", self._COL_W["genre"]),
        ]):
            ctk.CTkLabel(
                hdr, text=text, width=w,
                font=ctk.CTkFont(size=10, weight="bold"), anchor="w",
            ).grid(row=0, column=col, padx=(8 if col == 0 else 2, 2), pady=3, sticky="w")

        self.dropdown_scroll = ctk.CTkScrollableFrame(
            self.dropdown_container, height=180,
        )
        self.dropdown_scroll.grid(row=1, column=0, sticky="ew")

        # ── Track display area ──
        self.track_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.track_frame.grid(row=2, column=0, padx=15, pady=(8, 12), sticky="ew")
        self.track_frame.grid_columnconfigure(0, weight=1)

        self.artist_label = ctk.CTkLabel(
            self.track_frame, text="",
            font=ctk.CTkFont(size=15), text_color="#999999", anchor="w",
        )
        self.artist_label.grid(row=0, column=0, sticky="w")

        self.title_label = ctk.CTkLabel(
            self.track_frame, text="Search for a track to begin",
            font=ctk.CTkFont(size=24, weight="bold"), anchor="w",
        )
        self.title_label.grid(row=1, column=0, sticky="w", pady=(0, 10))

        # Stat badges
        self.badges_frame = ctk.CTkFrame(self.track_frame, fg_color="transparent")
        self.badges_frame.grid(row=2, column=0, sticky="w")

        self._badges = {}
        for i, (key, lbl) in enumerate([
            ("key", "KEY"), ("bpm", "BPM"),
            ("energy", "ENERGY"), ("genre", "GENRE"),
        ]):
            self._badges[key] = self._make_badge(self.badges_frame, lbl, "—", i)

        # Extra info line
        self.info_label = ctk.CTkLabel(
            self.track_frame, text="",
            font=ctk.CTkFont(size=11), text_color="#666666", anchor="w",
        )
        self.info_label.grid(row=3, column=0, sticky="w", pady=(8, 0))

    # ── Badge builder ──

    def _make_badge(self, parent, label_text, value_text, col):
        frame = ctk.CTkFrame(parent, corner_radius=10, fg_color="#2a2a2a")
        frame.grid(row=0, column=col, padx=(0, 12), sticky="w")

        label = ctk.CTkLabel(
            frame, text=label_text,
            font=ctk.CTkFont(size=9, weight="bold"), text_color="#666666",
        )
        label.grid(row=0, column=0, padx=16, pady=(8, 0))

        value = ctk.CTkLabel(
            frame, text=value_text,
            font=ctk.CTkFont(size=26, weight="bold"), text_color="#555555",
        )
        value.grid(row=1, column=0, padx=16, pady=(2, 8))

        return {"frame": frame, "label": label, "value": value}

    # ── Public API ──

    def set_search_fn(self, fn):
        """Set the search function: fn(query) -> list[Track]."""
        self._search_fn = fn

    def set_track(self, track: Track):
        """Update the dashboard to display the given track."""
        self.search_var.set(track.display_name)
        self._hide_dropdown()

        self.artist_label.configure(text=track.artist)
        self.title_label.configure(text=track.title or track.file_name)

        # Key badge — Camelot colored
        key_color = CAMELOT_COLORS.get(track.camelot_key, "#ffffff")
        self._badges["key"]["value"].configure(
            text=track.camelot_key or "—", text_color=key_color,
        )

        # BPM badge
        self._badges["bpm"]["value"].configure(
            text=str(int(track.bpm)) if track.bpm else "—",
            text_color="#ffffff",
        )

        # Energy badge — heat-mapped
        e_color = energy_color(track.energy) if track.energy else "#555555"
        self._badges["energy"]["value"].configure(
            text=str(track.energy) if track.energy else "—",
            text_color=e_color,
        )

        # Genre badge
        self._badges["genre"]["value"].configure(
            text=track.genre or "—", text_color="#ffffff",
        )

        # Info line
        parts = []
        if track.comments:
            parts.append(track.comments)
        if track.play_count:
            parts.append(f"Plays: {track.play_count}")
        if track.crates:
            crate_str = ", ".join(track.crates[:3])
            if len(track.crates) > 3:
                crate_str += f" (+{len(track.crates) - 3})"
            parts.append(f"Crates: {crate_str}")
        self.info_label.configure(text="  ·  ".join(parts))

    # ── Search logic ──

    def _on_key(self, event):
        if self._debounce_id:
            self.after_cancel(self._debounce_id)
        self._debounce_id = self.after(150, self._do_search)

    def _do_search(self):
        query = self.search_var.get()
        if not query or not self._search_fn:
            self._hide_dropdown()
            return
        results = self._search_fn(query)
        self._populate_dropdown(results)

    def _populate_dropdown(self, tracks: list):
        for w in self.dropdown_scroll.winfo_children():
            w.destroy()
        if not tracks:
            self._hide_dropdown()
            return

        cw = self._COL_W
        font = ctk.CTkFont(size=12)

        for i, track in enumerate(tracks):
            row = ctk.CTkFrame(
                self.dropdown_scroll, fg_color="transparent", cursor="hand2",
            )
            row.grid(row=i, column=0, sticky="ew", pady=0)

            key_color = CAMELOT_COLORS.get(track.camelot_key)

            cells = [
                (truncate(track.artist, 28), cw["artist"], None),
                (truncate(track.title, 32), cw["title"], None),
                (track.camelot_key, cw["key"], key_color),
                (str(int(track.bpm)) if track.bpm else "", cw["bpm"], None),
                (str(track.energy) if track.energy else "", cw["energy"], None),
                (track.genre, cw["genre"], None),
            ]

            for col, (text, width, color) in enumerate(cells):
                lbl = ctk.CTkLabel(
                    row, text=text, width=width, font=font, anchor="w",
                    text_color=color if color else ("gray10", "gray90"),
                )
                lbl.grid(
                    row=0, column=col,
                    padx=(8 if col == 0 else 2, 2), sticky="w",
                )
                lbl.bind("<Button-1>", lambda e, t=track: self._select(t))

            row.bind("<Button-1>", lambda e, t=track: self._select(t))

            # Hover
            def on_enter(e, f=row):
                f.configure(fg_color=("gray80", "gray30"))

            def on_leave(e, f=row):
                f.configure(fg_color="transparent")

            row.bind("<Enter>", on_enter)
            row.bind("<Leave>", on_leave)

        self._show_dropdown()

    def _show_dropdown(self):
        if not self._dropdown_visible and self.dropdown_scroll.winfo_children():
            self.dropdown_container.grid()
            self._dropdown_visible = True

    def _hide_dropdown(self):
        if self._dropdown_visible:
            self.dropdown_container.grid_remove()
            self._dropdown_visible = False

    def _select(self, track: Track):
        self._hide_dropdown()
        if self._on_track_selected:
            self._on_track_selected(track)
