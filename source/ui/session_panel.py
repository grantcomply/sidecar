import customtkinter as ctk
from source.models.track import Track
from source.config import CAMELOT_COLORS, energy_color
from source.ui.utils import truncate

# Column widths for the setlist grid
_COL = {"num": 30, "track": 200, "key": 45, "bpm": 45, "energy": 32, "remove": 28}


class SessionPanel(ctk.CTkFrame):
    """Setlist panel — shows played tracks with key metrics in columns."""

    def __init__(self, master, on_clear=None, on_remove=None, **kwargs):
        super().__init__(master, **kwargs)
        self._on_clear = on_clear
        self._on_remove = on_remove
        self._tracks: list[Track] = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # ── Header row ──
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        header.grid_columnconfigure(0, weight=1)

        self.header_label = ctk.CTkLabel(
            header, text="Setlist",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.header_label.grid(row=0, column=0, sticky="w")

        self.clear_btn = ctk.CTkButton(
            header, text="Clear", width=70, height=26,
            fg_color="#dc3545", hover_color="#c82333",
            font=ctk.CTkFont(size=11),
            command=self._clear,
        )
        self.clear_btn.grid(row=0, column=1, sticky="e")

        # ── Column headers ──
        col_hdr = ctk.CTkFrame(self, fg_color=("gray85", "gray20"), height=26)
        col_hdr.grid(row=1, column=0, sticky="ew", padx=5)
        col_hdr.grid_propagate(False)

        for col, (text, w) in enumerate([
            ("#", _COL["num"]), ("Track", _COL["track"]),
            ("Key", _COL["key"]), ("BPM", _COL["bpm"]),
            ("E", _COL["energy"]), ("", _COL["remove"]),
        ]):
            ctk.CTkLabel(
                col_hdr, text=text, width=w,
                font=ctk.CTkFont(size=10, weight="bold"), anchor="w",
            ).grid(row=0, column=col, padx=(6 if col == 0 else 2, 2), pady=3, sticky="w")

        # ── Scrollable track list ──
        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.grid(row=2, column=0, padx=5, pady=(0, 5), sticky="nsew")
        self.scroll_frame.grid_columnconfigure(0, weight=1)

        self._show_empty()

    # ── Public API ──

    def add_track(self, track: Track):
        # Don't add duplicates consecutively
        if self._tracks and self._tracks[-1].full_file_path == track.full_file_path:
            return
        self._tracks.append(track)
        self._rebuild()

    @property
    def played_paths(self) -> set:
        return {t.full_file_path for t in self._tracks}

    # ── Internal ──

    def _rebuild(self):
        for w in self.scroll_frame.winfo_children():
            w.destroy()

        if not self._tracks:
            self._show_empty()
            return

        self.header_label.configure(text=f"Setlist ({len(self._tracks)})")
        font = ctk.CTkFont(size=11)

        for display_idx, (actual_idx, track) in enumerate(
            reversed(list(enumerate(self._tracks)))
        ):
            row_bg = ("gray88", "gray22") if display_idx % 2 == 0 else ("gray82", "gray28")
            row = ctk.CTkFrame(self.scroll_frame, fg_color=row_bg, corner_radius=4)
            row.grid(row=display_idx, column=0, sticky="ew", pady=1)

            key_color = CAMELOT_COLORS.get(track.camelot_key, "#90caf9")
            e_color = energy_color(track.energy) if track.energy else "#999999"

            cells = [
                (f"{actual_idx + 1}.", _COL["num"], "#777777"),
                (truncate(track.display_name, 30), _COL["track"], None),
                (track.camelot_key, _COL["key"], key_color),
                (str(int(track.bpm)) if track.bpm else "", _COL["bpm"], None),
                (str(track.energy) if track.energy else "", _COL["energy"], e_color),
            ]

            for col, (text, width, color) in enumerate(cells):
                ctk.CTkLabel(
                    row, text=text, width=width, font=font, anchor="w",
                    text_color=color if color else ("gray10", "gray90"),
                ).grid(row=0, column=col, padx=(6 if col == 0 else 2, 2), sticky="w")

            # Remove button
            ctk.CTkButton(
                row, text="✕", width=_COL["remove"], height=22,
                fg_color="transparent", hover_color="#dc3545",
                text_color="#666666", font=ctk.CTkFont(size=11),
                command=lambda idx=actual_idx: self._remove_track(idx),
            ).grid(row=0, column=len(cells), padx=(0, 4), sticky="e")

    def _show_empty(self):
        self.header_label.configure(text="Setlist")
        ctk.CTkLabel(
            self.scroll_frame, text="No tracks in setlist",
            text_color="gray", font=ctk.CTkFont(size=11),
        ).grid(row=0, column=0, padx=10, pady=10)

    def _remove_track(self, index: int):
        if 0 <= index < len(self._tracks):
            self._tracks.pop(index)
            self._rebuild()
            if self._on_remove:
                self._on_remove()

    def _clear(self):
        self._tracks.clear()
        self._rebuild()
        if self._on_clear:
            self._on_clear()
