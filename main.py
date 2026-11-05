import logging
import sys

# Logging is configured, and the secret-bearing loggers silenced, BEFORE any
# project import that could (directly or later) import pyrekordbox, whose
# logger emits the database key at DEBUG (ADR-015 D8).
from source.services.log_safety import silence_secret_loggers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
silence_secret_loggers()

import customtkinter as ctk  # noqa: E402 - after logging setup on purpose
from source.app import DJTrackSelectorApp  # noqa: E402
from source.services import diagnostics  # noqa: E402
from source.services.settings_migration import run_startup_migrations  # noqa: E402


def main():
    # Command-line diagnostics run before any Tk object exists (T3.12). The
    # frozen exe is windowed, so check-library's report file is the readable output.
    if "--self-check-rekordbox" in sys.argv:
        sys.exit(diagnostics.self_check_rekordbox())
    if "--check-rekordbox-library" in sys.argv:
        sys.exit(diagnostics.check_rekordbox_library())

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    run_startup_migrations()  # settings schema 2 + legacy cache conversion; never raises
    app = DJTrackSelectorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
