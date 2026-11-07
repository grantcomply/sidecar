"""Shared fixtures for Tk widget tests.

Test modules that define their own ``tk_root`` fixture keep using theirs.
"""

from __future__ import annotations

import sys

import pytest


@pytest.fixture
def tk_root():
    """A withdrawn Tk root; skips cleanly where Tk can't start (no display).

    Callback exceptions are recorded on ``root.callback_errors`` instead of being
    printed, so a test can assert that no Tk callback failed. On teardown the
    ``CopyButton`` one-flash-at-a-time reference is cleared.
    """
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tk widget tests")
    else:
        root.withdraw()
        errors: list[BaseException] = []
        root.report_callback_exception = lambda exc, val, tb: errors.append(val)
        root.callback_errors = errors  # type: ignore[attr-defined]
        yield root
        root.destroy()
        copy_button = sys.modules.get("source.ui.copy_button")
        if copy_button is not None:
            copy_button.CopyButton._flashing = None
