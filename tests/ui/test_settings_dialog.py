"""Settings dialog behaviour (Phase 3c, T3c.5/T3c.9). Synthetic data only.

Needs a live Tk root; skips cleanly where no display is available.
"""

from __future__ import annotations

import pytest

from source.config import ERROR_COLOR, WARNING_COLOR
from source.providers.base import ProviderIssue, SettingKind, SettingSpec
from source.services.library_store import SnapshotSummary
from source.services.settings_model import ProviderSettingsView

tk = pytest.importorskip("tkinter")

SUMMARY = SnapshotSummary(synced_at="2026-11-05T10:00:00+00:00", track_count=740,
                          crate_count=75, change_token="t")


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tk widget tests")
    root.withdraw()
    yield root
    root.destroy()


def _view(pid="rb", *, enabled=True, values=None, issues=(), specs=None, summary=SUMMARY,
          detected=None):
    specs = specs if specs is not None else (
        SettingSpec("db_path", "X_DB", "Database", SettingKind.FILE, required=False,
                    placeholder="Choose the file named master.db", browse_title="Pick"),
        SettingSpec("auto", "X_AUTO", "Update automatically", SettingKind.CHOICE,
                    choices=("on", "off")),
    )
    return ProviderSettingsView(
        provider_id=pid, display_name=f"Name {pid}", crate_noun="playlist", enabled=enabled,
        specs=specs, values=values if values is not None else {"db_path": "", "auto": "on"},
        detected=detected or {}, capabilities=frozenset(), summary=summary,
        issues=tuple(issues), warnings=(), last_error=None,
    )


class _Calls:
    def __init__(self, issues_for=None):
        self.saved: list = []
        self.synced: list = []
        self._issues_for = issues_for or (lambda pid, values: [])

    def save(self, enabled, values) -> bool:
        self.saved.append((enabled, values))
        return True

    def sync(self, ids):
        self.synced.append(ids)

    def validate(self, pid, values):
        return self._issues_for(pid, values)


def _dialog(tk_root, views, calls=None):
    from source.ui.sync_panel import SettingsDialog

    calls = calls or _Calls()
    dlg = SettingsDialog(tk_root, views, on_save=calls.save, on_sync=calls.sync,
                         on_validate=calls.validate)
    dlg.withdraw()
    return dlg, calls


def _nn(widget):
    """The dialog builds these widgets in __init__; narrow Optional for the type checker."""
    assert widget is not None
    return widget


def _texts(widget) -> list[str]:
    out = []
    for child in widget.winfo_children():
        try:
            out.append(child.cget("text"))
        except (tk.TclError, ValueError):
            pass
        out.extend(_texts(child))
    return out


def test_zero_sources_disables_sync_and_shows_footer_message(tk_root):
    dlg, _ = _dialog(tk_root, [_view(enabled=False), _view("se", enabled=False)])
    assert dlg._sync_btn.cget("state") == "disabled"
    assert dlg._status.cget("text") == "Turn on at least one source to load tracks."
    assert dlg._status.cget("text_color") == WARNING_COLOR


def test_empty_field_error_is_amber_wrong_path_is_red_under_the_field(tk_root):
    def issues(pid, values):
        msg = "Database not found" if not values["db_path"] else "Choose the file named master.db"
        return [ProviderIssue("error", msg, "db_path")]

    dlg, _ = _dialog(tk_root, [_view()], _Calls(issues))
    card = dlg._cards["rb"]
    line = card.field_issue["db_path"]
    assert line.cget("text") == "Database not found"
    assert line.cget("text_color") == WARNING_COLOR
    assert line.grid_info()["row"] == 1  # between the entry (row 0) and the hint (row 2)

    card.entries["db_path"].insert(0, "C:/x/backup.db")
    dlg._after_edit("rb")
    assert line.cget("text") == "Choose the file named master.db"
    assert line.cget("text_color") == ERROR_COLOR
    assert line.cget("font").cget("weight") == "bold"
    assert line.cget("font").cget("size") == 12
    bottom = [w.cget("text") for w in _nn(card.status).winfo_children()]
    assert "Choose the file named master.db" not in bottom  # not repeated at the bottom


def test_disabled_card_shows_no_form(tk_root):
    dlg, _ = _dialog(tk_root, [_view(enabled=False)])
    card = dlg._cards["rb"]
    assert not _nn(card.rows).winfo_ismapped() and _nn(card.rows).grid_info() == {}
    assert _nn(card.off_label).cget("text") == "Off. Saved library kept."


def test_one_choice_spec_renders_no_tiles(tk_root):
    specs = (SettingSpec("mode", "X_MODE", "Mode", SettingKind.CHOICE, choices=("only",)),)
    dlg, _ = _dialog(tk_root, [_view(specs=specs, values={"mode": "only"})])
    assert dlg._cards["rb"].tiles == {}


def test_two_choice_spec_renders_on_off_tiles(tk_root):
    dlg, _ = _dialog(tk_root, [_view()])
    tiles = dlg._cards["rb"].tiles["auto"]
    assert [b.cget("text") for b in tiles.values()] == ["On", "Off"]


def test_close_relabels_to_cancel_when_edited_and_save_enables(tk_root):
    dlg, _ = _dialog(tk_root, [_view()])
    assert dlg._close_btn.cget("text") == "Close"
    assert dlg._save_btn.cget("state") == "disabled"
    dlg._pick(dlg._cards["rb"], dlg._cards["rb"].view.specs[1], "off")
    assert dlg._close_btn.cget("text") == "Cancel"
    assert dlg._save_btn.cget("state") == "normal"
    assert dlg._unsaved.cget("text") == "Unsaved changes"


def test_update_status_keeps_staged_entries_and_switches(tk_root):
    dlg, _ = _dialog(tk_root, [_view(), _view("se")])
    card = dlg._cards["rb"]
    card.entries["db_path"].insert(0, "C:/staged/master.db")
    dlg._cards["se"].enabled.set(False)
    newer = SnapshotSummary(synced_at="2026-11-05T11:59:00+00:00", track_count=741,
                            crate_count=76, change_token="t2")

    dlg.update_status([_view(summary=newer), _view("se", summary=newer)])

    assert card.entries["db_path"].get() == "C:/staged/master.db"
    assert dlg._cards["se"].enabled.get() is False
    assert "741 tracks" in _nn(card.chip).cget("text")


def test_detected_value_shown_as_placeholder_not_value(tk_root):
    dlg, _ = _dialog(tk_root, [_view(detected={"db_path": "C:/found/master.db"})])
    entry = dlg._cards["rb"].entries["db_path"]
    assert entry.get() == ""  # nothing typed: stays automatic
    assert entry.cget("placeholder_text") == "C:/found/master.db"


def test_save_and_sync_skip_errored_provider(tk_root):
    def issues(pid, values):
        return [ProviderIssue("error", "Database not found", "db_path")] if pid == "rb" else []

    dlg, calls = _dialog(tk_root, [_view(), _view("se")], _Calls(issues))
    assert dlg._status.cget("text") == "Skipped Name rb: Database not found"
    assert dlg._sync_btn.cget("state") == "normal"
    dlg._sync()
    assert calls.synced == [["se"]]


def test_save_calls_back_and_clears_dirty(tk_root):
    dlg, calls = _dialog(tk_root, [_view(), _view("se")])
    dlg._cards["se"].enabled.set(False)
    dlg._on_toggle("se")
    assert dlg.is_dirty
    assert dlg._save() is True
    assert calls.saved[-1][0] == ["rb"]
    assert not dlg.is_dirty and dlg._status.cget("text") == "Settings saved"


def test_busy_disables_controls_and_shows_syncing(tk_root):
    dlg, _ = _dialog(tk_root, [_view()])
    dlg.set_busy(True)
    assert dlg._sync_btn.cget("text") == "Syncing…"
    assert dlg._sync_btn.cget("state") == "disabled"
    assert _nn(dlg._cards["rb"].chip).cget("text") == "Syncing…"
    assert all(w.cget("state") == "disabled" for w in dlg._cards["rb"].controls)
    assert dlg._close_btn.cget("state") == "normal"


def test_precedence_note_only_with_two_sources(tk_root):
    dlg, _ = _dialog(tk_root, [_view(), _view("se")])
    assert dlg._note.cget("text") == "When a track is in both, its details come from Name rb."
    dlg._cards["se"].enabled.set(False)
    dlg._on_toggle("se")
    assert dlg._note.cget("text") == ""


def test_playlist_provider_card_never_says_crate_or_shows_its_id(tk_root):
    import dataclasses

    view = dataclasses.replace(_view("provider_x"), display_name="Visible Name")
    dlg, _ = _dialog(tk_root, [view])
    card_text = " ".join(
        t for t in _texts(_nn(dlg._cards["provider_x"].frame)) if isinstance(t, str)
    ).lower()
    assert "75 playlists" in card_text
    assert "crate" not in card_text      # nothing in the card itself
    assert "provider_x" not in card_text  # the provider id never appears



# ── Review items 1, 2, 13 and audit fixes ──


def test_typed_value_is_validated_on_sync_without_focus_out(tk_root):
    def issues(pid, values):
        ok = values["db_path"].endswith("master.db")
        return [] if ok else [ProviderIssue("error", "Database not found", "db_path")]

    dlg, calls = _dialog(tk_root, [_view()], _Calls(issues))
    assert dlg._sync_btn.cget("state") == "disabled"   # empty field: error, nothing can sync
    dlg._cards["rb"].entries["db_path"].insert(0, "C:/pasted/master.db")  # paste, no Tab
    dlg._sync()
    assert calls.synced == [["rb"]]


def test_footer_follows_typing_and_card_validates_after_debounce(tk_root):
    def issues(pid, values):
        ok = values["db_path"].endswith("master.db")
        return [] if ok else [ProviderIssue("error", "Database not found", "db_path")]

    dlg, _ = _dialog(tk_root, [_view()], _Calls(issues))
    card = dlg._cards["rb"]
    card.entries["db_path"].insert(0, "C:/pasted/master.db")
    dlg._on_key("rb")
    assert dlg._sync_btn.cget("state") == "normal"      # footer re-validated at once
    assert card.validate_after is not None              # card lines wait ~400 ms
    dlg._debounced("rb")
    assert not card.field_issue["db_path"].grid_info()   # issue line cleared


def test_escape_and_cancel_never_save(tk_root):
    dlg, calls = _dialog(tk_root, [_view()])
    dlg._pick(dlg._cards["rb"], dlg._cards["rb"].view.specs[1], "off")
    assert "_on_escape" in dlg.bind("<Escape>")  # Esc is bound to Cancel
    dlg._on_escape()
    assert calls.saved == []
    dlg2, calls2 = _dialog(tk_root, [_view()])
    dlg2._pick(dlg2._cards["rb"], dlg2._cards["rb"].view.specs[1], "off")
    assert dlg2._close_btn.cget("text") == "Cancel"
    dlg2._close_btn.invoke()
    assert calls2.saved == []


def test_failed_save_keeps_dirty_and_never_syncs(tk_root):
    class Failing(_Calls):
        def save(self, enabled, values) -> bool:
            self.saved.append((enabled, values))
            return False

    calls = Failing()
    dlg, _ = _dialog(tk_root, [_view()], calls)
    dlg._pick(dlg._cards["rb"], dlg._cards["rb"].view.specs[1], "off")
    dlg._sync()
    assert calls.synced == [] and dlg.is_dirty
    assert dlg._save() is False and dlg.is_dirty
    assert dlg._status.cget("text") != "Settings saved"


def test_dialog_opens_clean_even_with_an_unknown_choice_value(tk_root):
    dlg, _ = _dialog(tk_root, [_view(values={"db_path": "", "auto": "maybe"})])
    assert not dlg.is_dirty and dlg._close_btn.cget("text") == "Close"


def test_disabled_buttons_get_low_chroma_fill_and_restore(tk_root):
    from source.config import SUCCESS_COLOR
    from source.ui.sync_panel import SAVE_DISABLED_FILL, SYNC_DISABLED_FILL

    dlg, _ = _dialog(tk_root, [_view(enabled=False)])
    assert dlg._sync_btn.cget("fg_color") == SYNC_DISABLED_FILL
    assert dlg._save_btn.cget("fg_color") == SAVE_DISABLED_FILL
    dlg._cards["rb"].enabled.set(True)
    dlg._on_toggle("rb")
    assert dlg._sync_btn.cget("fg_color") == SUCCESS_COLOR
    assert dlg._save_btn.cget("fg_color") != SAVE_DISABLED_FILL  # dirty: Save enabled


def test_off_card_name_is_dimmed(tk_root):
    from source.config import SECONDARY_TEXT_COLOR

    dlg, _ = _dialog(tk_root, [_view(enabled=False), _view("se")])
    assert _nn(dlg._cards["rb"].name_label).cget("text_color") == SECONDARY_TEXT_COLOR
    assert _nn(dlg._cards["se"].name_label).cget("text_color") != SECONDARY_TEXT_COLOR


def test_cant_sync_wording_when_nothing_can_sync(tk_root):
    def issues(pid, values):
        return [ProviderIssue("error", "Database not found", "db_path")]

    dlg, _ = _dialog(tk_root, [_view()], _Calls(issues))
    assert dlg._status.cget("text") == "Can't sync Name rb: Database not found"


def test_destroy_cancels_pending_debounced_validation(tk_root):
    import time

    dlg, _ = _dialog(tk_root, [_view()])
    dlg._cards["rb"].entries["db_path"].insert(0, "C:/x")
    dlg._on_key("rb")                       # schedules the 400 ms validation
    assert dlg._cards["rb"].validate_after is not None
    dlg.destroy()
    time.sleep(0.5)
    tk_root.update()                        # past the debounce: must not raise TclError
    tk_root.update_idletasks()
