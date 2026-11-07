"""Put text on the OS clipboard through Tk's own clipboard (blueprint D2).

No new dependency: Tk owns a clipboard implementation on every platform, and
Sidecar's running main loop serves the text to other apps when they paste.

Tk thread only. The copied text is library data (track titles and artists),
so it is never logged (coding standards, providers rule 10).
"""

from __future__ import annotations

import logging
import tkinter as tk

logger = logging.getLogger(__name__)


def copy_to_clipboard(widget: tk.Misc, text: str) -> bool:
    """Replace the OS clipboard with ``text``. Tk thread only. False if Tk refused."""
    try:
        widget.clipboard_clear()
        widget.clipboard_append(text)
    except tk.TclError as e:
        logger.warning("Clipboard copy failed (%s)", type(e).__name__)
        return False
    # Deliberately no update() here (blueprint D2): the main loop keeps serving
    # the clipboard, and update() would run queued input events mid-handler.
    # If the first paste comes up empty (manual check M2), use update_idletasks().
    return True
