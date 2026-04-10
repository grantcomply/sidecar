import customtkinter as ctk
from tkinter import filedialog

from source import __version__


class SettingsDialog(ctk.CTkToplevel):
    """Modal settings dialog for Serato sync configuration."""

    def __init__(self, master, default_path: str, on_sync=None, **kwargs):
        super().__init__(master, **kwargs)
        self.title(f"Settings — Serato Sidecar v{__version__}")
        self.geometry("600x220")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self._on_sync = on_sync

        self.grid_columnconfigure(1, weight=1)

        # --- Serato path ---
        ctk.CTkLabel(
            self, text="Serato Subcrates:",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=(20, 10), pady=(25, 5), sticky="w")

        self.path_var = ctk.StringVar(value=default_path)
        self.path_entry = ctk.CTkEntry(
            self, textvariable=self.path_var,
            font=ctk.CTkFont(size=12),
        )
        self.path_entry.grid(row=0, column=1, padx=5, pady=(25, 5), sticky="ew")

        self.browse_btn = ctk.CTkButton(
            self, text="Browse", width=80,
            command=self._browse,
        )
        self.browse_btn.grid(row=0, column=2, padx=(5, 20), pady=(25, 5))

        # --- Sync button ---
        self.sync_btn = ctk.CTkButton(
            self, text="Sync Crates", width=160, height=38,
            fg_color="#28a745", hover_color="#218838",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._sync,
        )
        self.sync_btn.grid(row=1, column=0, columnspan=3, padx=20, pady=20)

        # --- Status ---
        self.status_label = ctk.CTkLabel(
            self, text="", text_color="gray",
            font=ctk.CTkFont(size=12),
        )
        self.status_label.grid(row=2, column=0, columnspan=3, padx=20, pady=(0, 15), sticky="w")

        # Center on parent after rendering
        self.after(10, lambda: self._center(master))

    def _center(self, parent):
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _browse(self):
        folder = filedialog.askdirectory(title="Select Serato Subcrates Folder")
        if folder:
            self.path_var.set(folder)

    def _sync(self):
        if self._on_sync:
            self._on_sync(self.path_var.get())

    def set_syncing(self, syncing: bool):
        if syncing:
            self.sync_btn.configure(state="disabled", text="Syncing...")
            self.status_label.configure(text="Syncing crates...", text_color="orange")
        else:
            self.sync_btn.configure(state="normal", text="Sync Crates")

    def set_status(self, text: str, color: str = "gray"):
        self.status_label.configure(text=text, text_color=color)
