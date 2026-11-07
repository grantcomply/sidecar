"""``ui/clipboard.copy_to_clipboard`` (copy-track-search-text plan T2.2).

The round-trip tests need a live Tk root and skip cleanly where no display is
available. They read Tk's own view of the clipboard (``clipboard_get``), not
another app's paste; the OS side is manual check M1. Note: they do replace
the clipboard of the machine running the tests.
"""

from __future__ import annotations

import logging

import pytest

tk = pytest.importorskip("tkinter")

from source.ui.clipboard import copy_to_clipboard  # noqa: E402 - after the tkinter skip

_SECRET_TEXT = "Artist A Track One"


class _RefusingWidget:
    """Stands in for a widget whose clipboard Tk refuses at ``fail_on``."""

    def __init__(self, fail_on: str) -> None:
        self.fail_on = fail_on
        self.calls: list[str] = []

    def clipboard_clear(self) -> None:
        self.calls.append("clipboard_clear")
        if self.fail_on == "clipboard_clear":
            raise tk.TclError("CLIPBOARD selection doesn't exist")

    def clipboard_append(self, text: str) -> None:
        self.calls.append("clipboard_append")
        if self.fail_on == "clipboard_append":
            raise tk.TclError("CLIPBOARD selection doesn't exist")


def test_copy_to_clipboard_round_trip_returns_true_and_holds_text(tk_root):
    assert copy_to_clipboard(tk_root, _SECRET_TEXT) is True
    assert tk_root.clipboard_get() == _SECRET_TEXT


def test_copy_to_clipboard_second_copy_replaces_first(tk_root):
    copy_to_clipboard(tk_root, "one")
    copy_to_clipboard(tk_root, "two")
    assert tk_root.clipboard_get() == "two"


@pytest.mark.parametrize("fail_on", ["clipboard_clear", "clipboard_append"])
def test_copy_to_clipboard_tcl_error_returns_false_and_logs_without_text(caplog, fail_on):
    widget = _RefusingWidget(fail_on)
    with caplog.at_level(logging.DEBUG):
        assert copy_to_clipboard(widget, _SECRET_TEXT) is False  # type: ignore[arg-type]
    assert widget.calls[-1] == fail_on
    records = [r for r in caplog.records if r.name == "source.ui.clipboard"]
    assert [r.levelno for r in records] == [logging.WARNING]
    assert "TclError" in records[0].getMessage()
    # No logger at any level may carry the copied text.
    assert all(_SECRET_TEXT not in r.getMessage() for r in caplog.records)
    assert _SECRET_TEXT not in caplog.text
