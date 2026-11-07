# Implementation Plan: rekordbox Drag to Deck

> **For:** Engineer agent
> **Companion:** `architect-blueprint.md` (same folder). Read §1.3 first (why this is a drag, not a click), then ADR-016 D1–D12 and §7 (live-set safety).
> **Principle:** Phases 1 and 2 change nothing a user can see. Phase 3 adds the control. **Nothing starts until Phase 0 passes Gate A and Gate B** (blueprint §6). If the spike picks a fallback, run Phase F1 or F2 instead of Phases 2–3.
> **Paths:** the code is under `source/`. `CLAUDE.md`'s tree omits that prefix. All citations below are against commit `3f15727`, so re-check line numbers after each phase because earlier tasks shift them.
> **Hard rules for this feature (review blockers):**
> - Only `source/ui/drag_source.py` imports `tkinterdnd2`, and only lazily.
> - Drag actions are **copy only**. Never move or link.
> - The payload is the `Track.full_file_path` of a track that passes `app.deck_drop_available_for`.
> - No synthetic input, no focusing or automating rekordbox, and nothing written to or opened in rekordbox's folder.
> - No bare `except Exception`.
> - The app must start normally with `tkinterdnd2` missing or broken.
> - Run `python -m pytest` after every phase. Each phase ends green.

UI direction: all layout, look, state and copy choices are now settled in `ui-design-brief.md` (same folder). Where this plan and the brief disagree, follow the brief. Open UI questions (brief §10) are marked **[O#]** where they change a task; the defaults used below are the designer's recommendations and need the user's confirmation before Phase 3 starts.

---

## Phase 0: Validation spike (no repo code, about 45 min). Gates everything

Do this on the user's Windows machine with rekordbox 7.2.19 in Performance mode. Run both apps **not** as administrator. Use a throwaway playlist. Put all scripts and the scratch venv in the session scratchpad, never in the repo.

### T0.1: rekordbox as a drop target (Explorer → deck)
Run blueprint §6 checks **S1a–S1g**. For S1b, note the collection track count shown in rekordbox before and after the drops. For S1c, find rekordbox's preference that locks a playing deck against loads and record its exact name and location.

### T0.2: Throwaway drag source
In a scratch venv: `pip install customtkinter tkinterdnd2 pyinstaller`. Script (scratchpad only):
```python
import sys, customtkinter as ctk
from tkinterdnd2 import TkinterDnD, DND_FILES, COPY
PATH = sys.argv[1]                       # a test file that is in the rekordbox collection
root = ctk.CTk(); print("tkdnd", TkinterDnD._require(root))
handle = ctk.CTkLabel(root, text="DRAG ME", width=160, height=60)
handle.pack(padx=40, pady=40)
targets = [handle] + list(handle.winfo_children())      # CTk is compound: register the inner widgets
def init(event):
    print("drag init"); return (COPY, DND_FILES, root.tk.call("list", PATH))
def end(event):
    print("drag end, action =", event.action)
for w in targets:
    w.drag_source_register(1, DND_FILES)
    w.dnd_bind("<<DragInitCmd>>", init)
    w.dnd_bind("<<DragEndCmd>>", end)
tick = lambda: (print("tick"), root.after(500, tick)); tick()      # S2e: does it pause mid-drag?
root.mainloop()
```
Run blueprint §6 checks **S2a–S2f**, first from source and then from `pyinstaller --onedir --collect-all tkinterdnd2 --collect-all customtkinter spike.py` (S2d). Then run S3. Run S4 on a Mac if one is available.

### T0.3: Fallback inputs and record checks
Run S5, S8, and optionally S6 and S7 (S7 never during a set). For S8, choose the `tkinterdnd2` pin: the newest release whose wheel bundles tkdnd for win-x64, osx-arm64 and osx-x64 on CPython 3.11. Note where its licence files are.

### T0.4: Record findings
Append a **"Phase 0 findings"** section at the end of this file. Give one line per check ID (S1a…S8), the chosen pin, the name of the playing-deck lock preference, and whether the drag loop is modal (S2e). **Synthetic names only. No real titles or paths** (`docs/testing-strategy.md:17`).

**Gate A** (S1a + S1b pass) and **Gate B** (S2a–S2d pass) → Phase 1.
A passes, B fails → Phase 1, then **Phase F1** instead of Phases 2–3.
A fails → stop. The orchestrator takes blueprint O1 and Fallback 2 (D11) to the user.
Anything that loads a *specific* track by a push mechanism without writing rekordbox files → stop and return to the architect.

---

## Phase 1: Contract, gate and pure rules (invisible)

**Exit:** all tests pass. Nothing renders a drag control. `deck_load_provider_for` behaves exactly as before.

### T1.1: Capability
`source/providers/base.py:61-66`: add `DECK_FILE_DROP = "deck_file_drop"` after `DECK_LOAD`, with the comment `# DJ app loads a file dropped from the OS onto a deck (ADR-016)`. Update the module docstring's capability list (`:6-9`) to mention it. `base.py` stays stdlib-only, and `tests/providers/test_base_isolation.py` must stay green.

### T1.2: Generic registry lookup
`source/providers/registry.py:35-53`: add
```python
def first_provider_with(
    capability: ProviderCapability,
    provider_ids: Iterable[str],
    settings_for: Callable[[str], Mapping[str, str]],
) -> LibraryProvider | None:
```
Move the current loop body into it unchanged (unknown id → `logger.warning`, skip). Then make `first_deck_load_provider` `return first_provider_with(ProviderCapability.DECK_LOAD, provider_ids, settings_for)`, and update its docstring (no longer "always the case in this feature"; still `None` for every real provider).
Tests: `tests/providers/test_serato_provider.py:161-175` must pass unchanged. Add `test_first_provider_with_returns_first_declaring_in_order` and `test_first_provider_with_skips_unknown_ids` beside them, using the existing fake pattern at `:158`.

### T1.3: rekordbox declares the capability
`source/providers/rekordbox/provider.py:130-135`: add `ProviderCapability.DECK_FILE_DROP` to `caps`. It is unconditional in Phase 1; T3.6 makes it depend on the setting. Update the comment at `:134` to `# Not SMART_PLAYLISTS (unverified) and not DECK_LOAD (push-load rejected, ADR-016).` Change the `load_to_deck` docstring at `:158` to cite ADR-016, and leave the raise and its message as they are.
Tests: in `tests/providers/rekordbox/test_rekordbox_provider.py`, next to `:200-202`, assert `DECK_FILE_DROP in caps` and `DECK_LOAD not in caps`. Keep `:210-212`. In `tests/providers/test_serato_provider.py:116-119`, assert `DECK_FILE_DROP not in caps`.

### T1.4: Pure gate module
**New** `source/services/deck_drop.py`. Imports: stdlib plus `source.providers.base` only. No Tk, no `config`, no registry.
```python
class DropRefusal(str, Enum):
    FILE_MISSING = "file_missing"

def drop_capable_ids(
    enabled_ids: Sequence[str],
    capabilities_for: Callable[[str], frozenset[ProviderCapability]],
) -> frozenset[str]: ...                      # enabled ids whose capabilities include DECK_FILE_DROP

def can_drag(track_sources: Sequence[str], capable_ids: frozenset[str]) -> bool:
    """True when sources[0] (the provider whose path full_file_path is) is capable (ADR-016 D3)."""

def drag_refusal(path: str, *, is_file: Callable[[str], bool]) -> DropRefusal | None: ...
```
`capabilities_for` must not raise: the caller catches. An empty `path` → `FILE_MISSING`.
**New** `tests/services/test_deck_drop.py`:
- `can_drag`: empty sources → False; `("serato",)` → False; `("rekordbox",)` → True; `("rekordbox", "serato")` → True; `("serato", "rekordbox")` → False (path is Serato's).
- `drop_capable_ids`: filters by the capability; ignores providers that are not enabled; empty when none declare it.
- `drag_refusal`: an existing `tmp_path` file → `None`; a missing file → `FILE_MISSING`; `""` → `FILE_MISSING`.

### T1.5: App gate (cached)
`source/app.py`:
- Imports `:28-29`: add `first_provider_with` only if needed (it isn't if you use `deck_drop`). Add `from source.services import deck_drop` near `:30-31`.
- `__init__` (`:62-81`): `self._deck_drop_ids: frozenset[str] = frozenset()`.
- `_reload_library` (`:300-325`): after `enabled` is computed (`:308`), set
  `self._deck_drop_ids = deck_drop.drop_capable_ids(enabled, lambda pid: get_provider(pid).capabilities(self._provider_settings(pid)))`.
  `_provider_settings` reads `settings.env`. Wrap the call in `except (OSError, UnicodeDecodeError) as e` → `logger.warning(... type(e).__name__)` and `frozenset()`, the same pattern as `:411-413`.
- After `deck_load_provider_for` (`:374-388`), add:
  ```python
  def deck_drop_available_for(self, track: Track) -> bool:
      """Single gate for a drag-to-deck control (ADR-016 D3/D8). No I/O."""
      drag = getattr(self, "_drag", None)          # Phase 2 sets it; absent → False
      return bool(drag is not None and drag.available
                  and deck_drop.can_drag(track.sources, self._deck_drop_ids))
  ```
  Until Phase 2 this always returns `False`, which keeps the feature invisible.
**New** `tests/ui/test_app_deck_drop_gate.py`, modelled on `tests/ui/test_app_deck_load_gate.py:28-42` (stub `self`, no window). Use a fake `_drag` with `available=True/False`. Cases: rekordbox enabled + `sources=("rekordbox","serato")` → True; `_drag.available=False` → False; rekordbox not enabled → False; Serato-only track → False; no `_drag` attribute → False.

### T1.6: Lock the path invariant
`tests/services/test_library_merge.py`, near `:69-84`: add `test_merge_full_file_path_and_sources_first_come_from_first_snapshot`. Build a rekordbox snapshot with `C:/Music/A.mp3` (forward slashes, already normpathed per platform as the provider does) and a Serato snapshot with the same file in a different case or separator form. `merge([rb, serato])` → `track.sources == ("rekordbox", "serato")` and `track.full_file_path` is the rekordbox record's key string. The gate's correctness depends on this test (blueprint §1.4, D3). Mark it with a comment saying so.

---

## Phase 2: Drag-source adapter, packaging and CI (invisible)

**Exit:** the frozen Windows build passes `--self-check-drag`. The app starts with `tkinterdnd2` uninstalled. No widget is registered, so the UI is unchanged.

### T2.1: Dependency
`requirements.txt:1-8`: add `tkinterdnd2==<pin from T0.3>` (alphabetical placement is not required, so append after `:8`). If T0.3 found that the wheel needs a source build anywhere, stop and return to the architect.

### T2.2: Platform allowlist
`source/config.py`, after the refresh constants (`:347-354`):
```python
# Drag to deck (ADR-016 D10): platforms where the tkdnd drag source + rekordbox drop are verified.
DECK_DRAG_PLATFORMS: tuple[str, ...] = ("win32",)  # add "darwin" only after a Mac spike passes
```

### T2.3: Adapter
**New** `source/ui/drag_source.py` (blueprint D4):
- Module-level lazy loader `_load_tkdnd(root) -> str | None` (the tkdnd version). It runs `from tkinterdnd2 import TkinterDnD` inside the function, then `TkinterDnD._require(root)`. It catches `(ImportError, OSError, tk.TclError)`, logs `logger.warning("Drag to deck unavailable (%s)", type(e).__name__)`, and returns `None`. Mirror `source/services/audio_player.py:16-35`.
- `class FileDragSource`, constructed as `FileDragSource(root, *, platforms, loader=_load_tkdnd)`. `loader` is the test seam. If `sys.platform not in platforms`, do not call the loader at all: log at INFO once and set `available=False`.
- `make_draggable(widgets, path_for_drag, on_drag_start=None, on_drag_end=None) -> bool`. If unavailable, return `False` and do nothing. Otherwise, for each widget, call `drag_source_register(1, DND_FILES)` and bind `<<DragInitCmd>>` / `<<DragEndCmd>>`.
  - Init handler: `path = path_for_drag()`. If `None`, return the refuse value. **Check tkdnd's refuse convention in the spike and record it in T0.4.** The usual value is `"refuse_drop"`, or an empty action. Otherwise call `on_drag_start` and return `(COPY, DND_FILES, file_list_payload(widget, [path]))`. **`COPY` only.**
  - End handler: call `on_drag_end`.
  - Wrap registration in `except tk.TclError` → log and return `False`.
- `ctk_hit_widgets(widget) -> list[tk.Misc]`: the widget plus its descendants (`winfo_children`, recursive). This covers the inner canvas and label that CTk draws with.
- `file_list_payload(tcl, paths) -> str`: `tcl.tk.call("list", *paths)`, returned as `str`.
- `self_check() -> int`: create `tk.Tk()`, `withdraw()`, `_load_tkdnd(root)`, print `tkdnd <version>` or the failure type, `destroy()`, return 0 or 1. It must not touch `config.user_data_dir()`.
**New** `tests/ui/test_drag_source.py`:
- `file_list_payload` with `tkinter.Tcl()` (no display needed). Paths with spaces, `{}`, `&`, NFC and NFD accents round-trip through `tcl.tk.splitlist` to the same single path.
- Loader returning `None` → `available is False`, and `make_draggable(...)` returns `False` without touching the widgets (use a fake object that fails if called).
- Platform not in `platforms` → the loader is never called.
- With a display (skip on `tk.TclError`, the existing pattern at `tests/ui/test_app_sync_wiring.py:21`) and `pytest.importorskip("tkinterdnd2")`: a real `ctk.CTk` with a `CTkLabel` → `make_draggable` returns `True`. Do not simulate a drop.

### T2.4: App owns the adapter
`source/app.py`:
- Import `from source.ui.drag_source import FileDragSource` (`:38-41` block) and `DECK_DRAG_PLATFORMS` from config (`:11-23`).
- In `__init__`, right after `self._audio_player = AudioPlayer()` (`:83`) and **before** `_build_ui()` (`:85`): `self._drag = FileDragSource(self, platforms=DECK_DRAG_PLATFORMS)`. `_reload_library` runs inside `_try_load_existing` (`:87`), after this, so the gate has both inputs.
- `_on_close` (`:177-193`): nothing to shut down. tkdnd goes with the interpreter.

### T2.5: Frozen self-check
- `main.py:24-27`: add `if "--self-check-drag" in sys.argv: from source.ui.drag_source import self_check; sys.exit(self_check())`. Put it before the Tk app is created and after the rekordbox checks.
- `serato-sidecar.spec`: beside `:41-42`, add `dnd_datas, dnd_binaries, dnd_hiddenimports = collect_all("tkinterdnd2")`. Merge them at `:47` (datas), `:51` (binaries) and `:100` (hiddenimports). Add `"source.services.deck_drop"` and `"source.ui.drag_source"` to the list at `:59-99`. That list is already incomplete (blueprint, prior plan §7); don't fix the drift here.
- `.github/workflows/release.yml`: after `:102-109` (Windows), add a "Frozen drag self-check" step with the same `Start-Process … -ArgumentList "--self-check-drag" -Wait -PassThru` pattern. After `:216-220` (macOS), add `dist/DJSidecar.app/Contents/MacOS/DJSidecar --self-check-drag`. If the macOS runner can't create a Tk root (blueprint `[A15]`), replace the mac step with an existence check of the tkdnd dylib under `DJSidecar.app/Contents/` and note why in the step comment.
- **Manual (record here):** build locally with `pyinstaller serato-sidecar.spec --noconfirm`, run `dist\DJSidecar\DJSidecar.exe --self-check-drag`, and expect exit 0. Then uninstall `tkinterdnd2` in a dev venv and run `python main.py`. The app must start normally (gate False).

---

## Phase 3: The control (first visible change)

**Start only after** the ui-designer's brief exists in this folder. It owns placement, look, states, copy and tooltips. The structure below is what the architecture requires. Where the brief and this plan disagree on anything *not* marked as a blocker, follow the brief.

### T3.1: Panel inputs (callbacks + adapter)
`source/ui/suggestion_panel.py:92-98`: add keyword arguments
`drag_source: FileDragSource | None = None`, `can_drag: Callable[[Track], bool] | None = None`, `drag_path: Callable[[Track], str | None] | None = None`.
Store them. `self._drag_enabled = drag_source is not None and drag_source.available and can_drag is not None`. Import `FileDragSource` under `TYPE_CHECKING` (`:19-20`).
`source/ui/track_detail.py:18`: the same three keyword arguments on `NowPlayingDashboard.__init__`.
`source/app.py:138-143` and `:152-157`: pass `drag_source=self._drag, can_drag=self.deck_drop_available_for, drag_path=self._drag_path_for`.

### T3.2: Drag path + refusal (app)
`source/app.py`, beside `deck_drop_available_for`:
```python
def _drag_path_for(self, track: Track) -> str | None:
    """Drag start (Tk thread): current object, gate re-checked, one isfile; toast on refusal."""
    track = self._current_object(track)              # app.py:695-697 — rows may predate a refresh
    if not self.deck_drop_available_for(track):
        return None
    refusal = deck_drop.drag_refusal(track.full_file_path, is_file=os.path.isfile)
    if refusal is not None:
        self._show_toast(copy.TOAST_DRAG_FILE_MISSING, ERROR_COLOR, duration=6000)   # brief §6, O6
        logger.info("Drag to deck refused (%s)", refusal.value)  # no path in logs above DEBUG
        return None
    return track.full_file_path
```
Add `import os`. `TOAST_DRAG_FILE_MISSING` goes in `source/services/library_copy.py` (T3.8) with the text `Can't drag this track: its file is missing or moved`. Red (`ERROR_COLOR`) and 6000 ms are the designer's recommendation [O6]; if the user chooses amber, use `WARNING_COLOR`.

### T3.2a: Shared `DragHandle` widget (new, UI)
**New** `source/ui/drag_handle.py`: one tile widget used by both panels so their states cannot drift (brief §3.2, §3.4). Not a drag-and-drop module: it imports no `tkinterdnd2`; registration still goes through `FileDragSource.make_draggable`.
- A `CTkLabel`-based tile with `corner_radius` 6, `cursor="fleur"`, and a method to set one of four states:
  - **resting**: fill `#2a2a2a`, glyph `⠿` in `#999999`;
  - **hover**: fill `#1f6aa5`, glyph `#ffffff` (the tile binds its own `<Enter>`/`<Leave>`; the row's hover bindings are not shared);
  - **dragging**: fill `#1f6aa5`, glyph `#ffffff`, held until `reset()`;
  - **ineligible**: fill `#2a2a2a`, glyph `—` in `#555555`, default cursor, no hover change, and **no drag registered**.
- Size: 32x28 in a suggestion row (brief §3.2). Now Playing uses a larger badge wrapper (T3.5).
- It exposes `hit_widgets()` (the tile plus its CTk children) for `make_draggable`, and takes a tooltip text per state from the caller.
- If `⠿` renders as a box at 100% or 150% scaling, switch the glyph constant to `≡` (U+2261). Do not use an emoji.
- A **public `Tooltip.hide()`** is added to `source/ui/tooltip.py` (today only the private `_hide` exists, `:36`) so drag start can dismiss a tooltip that would otherwise stay on screen during the OS modal loop.
Tests: state changes configure the expected fill and glyph (display required, skip on `tk.TclError`); the ineligible state does not register a drag (assert `make_draggable` is never called with a fake source).

### T3.3: Suggestion-row handle
`source/ui/suggestion_panel.py`, following the brief:
- `_COL` (`:82-86`): add `"drag": 32`. **Position [O1]: leftmost column (recommended).** This shifts every cell and header column right by one: the header builder uses `col == 0` for its left padding (`:169`) and the cells use `col == 0` the same way (`:585`), so move that padding rule to the first *data* cell and give the handle column `padx=(6, 2)`. If the user picks rightmost instead, put the handle at `next_col` after the add button (`:613`) and expect it to be clipped at the minimum window (brief §0.4, O1).
- Headers (`:154-169`): when `self._drag_enabled`, insert `("Deck", _COL["drag"])` as the first header. Show it whenever the feature is available, even if every visible row is ineligible, so the grid does not jump between renders.
- Rows (`:559-613`): when `self._drag_enabled`, always create a `DragHandle` (T3.2a). If `self._can_drag(track)` is true it is **active** and registered with
  `self._drag_source.make_draggable(handle.hit_widgets(), lambda t=track: self._drag_path(t), lambda r=row, h=handle: self._on_drag_start(r, h), lambda r=row, b=row_bg, h=handle: self._on_drag_end(r, b, h))`.
  If it is false, the handle is **ineligible** [O2: disabled with reason is recommended; the blank spacer is the fallback if the user prefers it] and nothing is registered. When `self._drag_enabled` is false, no column, no header, no handle.
  **The handle binds nothing to `<Button-1>`, and in particular not `_select_track`.**
- Tooltips on the handle (own `Tooltip`, not the row's): active `Drag onto a rekordbox deck to load this track`; ineligible `Not in your rekordbox library, so it can't be dragged to a deck` (T3.8 constants).
- The row's hover bindings (`:615-624`) are not attached to the handle. Entering the handle may drop the row tint; that is acceptable because the handle has its own hover fill.

### T3.4: Drag guard and signature
`source/ui/suggestion_panel.py`:
- `__init__` state (`:108-113`): `self._dragging = False`.
- `_on_drag_start(row, handle)`: `self._dragging = True`; hide any visible tooltip (`Tooltip.hide()`); set the handle to **dragging**; tint the source `row` with the existing hover background (`hover_bg`, `:554`); then call `update_idletasks()` so the tint paints before tkdnd enters the OS modal loop (there is no OS drag ghost, so the tinted row is the only record of which track is in flight; brief §3.6).
- `_on_drag_end(row, base_bg, handle)`: `self._dragging = False`; restore the row's `base_bg` and the handle to resting; then `if self._pending_quiet is not None: self.after_idle(self._try_quiet_render)` (mirror `:795-797`). Guard against a destroyed row (`winfo_exists()`), because a render may have replaced it.
- Safety reset: if T3.7 shows `<<DragEndCmd>>` does not fire on Esc or a drop on nothing, add a reset on the next `<ButtonRelease-1>` or `<Motion>` over the panel, so the row cannot stay tinted and `_dragging` cannot block rendering.
- `_try_quiet_render` (`:466-477`): after the `is_previewing` early return (`:473-474`), add `if self._dragging: return  # resumed from _on_drag_end`.
- `_signature` (`:435-444`): append `self._drag_enabled and self._can_drag(s.track)` to each tuple. A setting change then re-renders the rows (blueprint D6).
- Do **not** stop the audio preview on drag start. Dragging changes no state (blueprint D5).
Tests, new in `tests/ui/test_suggestion_drag.py` (display required; skip on `tk.TclError`; use a fake `FileDragSource` with `available=True` that records `make_draggable` calls):
- a **drag-registered** handle is created only for tracks where `can_drag` is True; other rows get an ineligible handle with no registration;
- no handle and no `Deck` header column when the fake is unavailable;
- drag start tints the source row and sets the handle to dragging; drag end restores both;
- `_try_quiet_render` does nothing while `_dragging`, and renders after `_on_drag_end`;
- changing `can_drag`'s answer changes `_signature`;
- the handle has no `<Button-1>` binding that calls `on_select` (invoke `event_generate("<Button-1>")` on it and assert `on_select` was not called).

### T3.5: Now Playing tile
`source/ui/track_detail.py`:
- Build a badge-shaped tile as the **fifth badge** in `badges_frame` (`:92-100`), using the `_make_badge` look (`:111-127`): `#2a2a2a` card, label `DRAG TO DECK` (9 bold, `#666666`), value a `DragHandle` glyph at 22 bold. On hover or drag the card fills `#1f6aa5` with a white glyph. It is about 80x70 px, so no extra hit padding is needed. Hidden by default (`grid_remove`). Register it once in `__init__`, with a `path_for_drag` that reads `self._shown_track` at drag time, so it never holds a stale track.
- In `_render` (`:172-211`): feature available and `self._can_drag(track)` → active; feature available but not capable → **ineligible** (`—` in `#555555`, tooltip `Not in your rekordbox library, so it can't be dragged to a deck`) [O2]; feature unavailable → `grid_remove()`. `set_empty_message` (`:142-149`) and the no-track state never show it.
- A drag from this tile changes no dashboard state and does not select anything. No source-row tint here (only the tile is held in the dragging fill).
Test: extend `tests/ui/test_dashboard_empty_message.py` or add `tests/ui/test_dashboard_drag.py`. The tile is hidden with no track or an unavailable feature, active for a capable track, and ineligible (not registered) for a Serato-only track.

### T3.6: The `deck_drag` setting (kept: UI designer recommends it, brief §7.1 / blueprint O5)
`source/providers/rekordbox/provider.py`:
- `setting_specs` (`:82-109`): append
  `SettingSpec(key="deck_drag", env_key="REKORDBOX_DECK_DRAG", label=<copy>, kind=SettingKind.CHOICE, choices=("on", "off"), hint=<copy>)` with the label `Drag tracks to decks` and the hint `Adds a grip to each track. Drag it onto a rekordbox deck to load that track.` (T3.8 constants, same pattern as `auto_refresh`, `:98-108`).
- **macOS [O7, blueprint O6]:** the designer wants this spec omitted when the platform is outside `DECK_DRAG_PLATFORMS`, so the dialog (which never branches on provider id) does not show a toggle that does nothing. The provider does not import `config` today, so the architect must decide where the check lives. Until decided, keep the spec and append `Windows only for now.` to the hint on non-Windows builds.
- `default_settings` (`:111-112`): add `"deck_drag": "on"`.
- `capabilities` (`:130-135`): add `DECK_FILE_DROP` only `if settings.get("deck_drag", "on") == "on"`.
Tests: in `test_rekordbox_provider.py`, `deck_drag=off` → no `DECK_FILE_DROP`; the default → declared. `tests/providers/test_contract.py:41-48` covers env-key uniqueness and default keys automatically. The settings dialog needs no change; check that `tests/ui/test_settings_dialog.py` stays green. Settings → Save already calls `_reload_library(preserve_state=True)` (`source/app.py:640`), which recomputes `_deck_drop_ids` (T1.5), and the signature change (T3.4) re-renders the handles.

### T3.7: Manual check (record here)
On Windows with real rekordbox: drag from a suggestion and from Now Playing onto Deck 1 and Deck 2, and confirm the exact track appears with its analysis. A Serato-only track shows no handle. Rename a test file on disk and drag it: you get the refusal toast and no drag. A live refresh during a drag does not destroy the row. Turn `deck_drag` off: the handles disappear without a restart. Check 150% scaling and the 1000x650 minimum window.
Also check (UI): the glyph renders (not a box) at 100% and 150%; a press-and-release on the handle does not select the row; while dragging, the source row stays tinted and no tooltip is left on screen; Esc and a drop on nothing both un-tint the row and let the list re-render afterwards; with a Serato-only track in a mixed library the handle shows `—` with its tooltip and cannot be dragged; with rekordbox disabled or `deck_drag` off there is no `Deck` header; the handle is visible with the default 50/50 split at the minimum window (if the user chose the rightmost position it will not be, which is the known cost).

### T3.8: Copy constants (UI)
`source/services/library_copy.py`: add the strings below beside the existing constants (`:19-46`) and extend `tests/services/test_library_copy.py` to pin them (length of the toast under 75 characters, no path, no word "Load" as a Sidecar action in any string).

| Constant | Text |
|---|---|
| `DRAG_COLUMN_HEADER` | `Deck` |
| `DRAG_TIP` | `Drag onto a rekordbox deck to load this track` |
| `DRAG_TIP_INELIGIBLE` | `Not in your rekordbox library, so it can't be dragged to a deck` |
| `DRAG_BADGE_LABEL` | `DRAG TO DECK` |
| `TOAST_DRAG_FILE_MISSING` | `Can't drag this track: its file is missing or moved` |
| `SETTING_DECK_DRAG_LABEL` | `Drag tracks to decks` |
| `SETTING_DECK_DRAG_HINT` | `Adds a grip to each track. Drag it onto a rekordbox deck to load that track.` |

The word "rekordbox" is written in lower case. If Serato later gains `DECK_FILE_DROP`, parametrise the tooltips with the provider display name at that point.

---

## Phase 4: Docs, ADR and rehearsal

### T4.1: ADR-016
`docs/architecture-decisions.md`: append ADR-016 after ADR-015 (file end, `:557`), summarising blueprint §2 as built. Status **Accepted**, with the Phase 0 evidence summarised (check IDs only). In ADR-015's capability table (`:476-484`), add a `DECK_FILE_DROP` row (`no` for Serato, `yes while REKORDBOX_DECK_DRAG=on` for rekordbox, rule: see ADR-016). Add a "see ADR-016" note to D12 (`:541`).

### T4.2: Other docs
- `docs/architecture-overview.md`: add `deck_drop.py` to the services table (`:73-92`) and `drag_source.py` to the UI table (`:97-104`). Update the `base.py`/`registry.py` rows (`:60-61`). Reword debt #16 (`:163`) to describe both gates. Extend debt #17 (`:164`) so the boundary scan also covers `tkinterdnd2` → `ui/drag_source.py`.
- `docs/coding-standards.md:51-64`: add the four rules from blueprint D12 (renumber as 11–14). Update rule 9 (`:63`) to say drag events run on the Tk thread.
- `docs/cross-platform-guide.md`: new section "Drag to deck (ADR-016)" with the D10 table and the UIPI note. Add a tkdnd row to the native dependency table (`:178-183`) and a sentence on the `--self-check-drag` step (`:166`).
- `docs/testing-strategy.md`: add the new test files under "What must be tested", the T3.7 checks under "Manual-only checks" (`:78`), and replace the deck-load-gate gap line (`:77`) with both gate test files.
- `docs/deployment-guide.md`: add "re-run the T3.7 drag check" to the rekordbox upgrade runbook.
- `README.md`, `docs/install-guide-for-friends.md`: how to drag; turn on rekordbox's playing-deck lock (name from S1c); don't run rekordbox as administrator. Add the tkinterdnd2/tkdnd licence attribution wherever third-party notices live. User-facing wording (brief §6): lead with "Drag the grip next to a track onto a rekordbox deck. Keep rekordbox and Sidecar visible side by side or on two screens, and don't run rekordbox as administrator." Then the playing-deck-lock tip with the real preference name from S1c. Lead with "drag" so nobody looks for a Load button. Add a troubleshooting line for "no grip appears" (tkdnd failed to load; run `--self-check-drag`), since the app shows no on-screen signal for that (brief O5).
- `CLAUDE.md` project tree: add `deck_drop.py` and `drag_source.py`.

### T4.5: Design guide (UI designer, at ship)
Update `docs/ui-design-guide.md` once Phase 3 is accepted: §5 add a "Drag handle" row and a "badge-shaped action tile" note; §5 Settings dialog row mentions the new rekordbox setting; §6 records that drag success is silent by design; §8 adds "never say Load for a drag" and the new strings; §9 records the user's answers to the brief's O1-O8; bump "Last updated".

### T4.3: Live rehearsal (record here)
A 20-minute mock set using only drag to deck for every load. Count the loads and note any wrong deck, wrong track, or drag that didn't start. Any wrong *track* is a release blocker.

### T4.4: macOS (only when a Mac is available)
Run blueprint §6 S4 with the release `.app`. If it passes, add `"darwin"` to `DECK_DRAG_PLATFORMS` (`source/config.py`, T2.2) in its own commit and update the cross-platform table. If it fails, leave macOS off and record why.

---

## Phase F1 (instead of Phases 2–3 if Gate B fails): "Show in Explorer / Finder"

The capability, gate and Phase 1 stay as they are. The control's action changes from "drag" to "reveal".
**UI (brief §6):** a 48 px text button `Show` (not a grip, because it is a click), header cell `File`, in the same column and Now Playing position as the handle (T3.3/T3.5), with the same rule: hidden when the feature is unavailable, disabled `—` with a reason for an ineligible row [O2]. Tooltip `Show this file in Explorer. Drag it from there onto a rekordbox deck.` (`Finder` on macOS). Failure toast, red: `Couldn't open the folder`. The button changes no Sidecar state and never selects the row. No tint and no `_dragging` guard. The setting hint becomes `Adds a Show button to each track. It opens the file's folder so you can drag it onto a rekordbox deck.` Honest cost for the user: opening a file-manager window mid-set takes focus and adds two steps, so this is a weaker control than the drag.
- **TF1.1** **New** `source/services/file_reveal.py`, pure: `reveal_command(path, platform) -> list[str] | None` returns `["explorer", f"/select,{path}"]` (win32), `["open", "-R", path]` (darwin), or `None`. Add `reveal(path) -> bool`, which runs `subprocess.Popen(cmd, shell=False)`, ignores the exit code (Explorer returns 1 on success), catches `OSError`, and logs the type only. Tests check the command lists, including paths with spaces and commas. Do not run Explorer in tests.
- **TF1.2** In `app.py`, `deck_drop_available_for` drops the `_drag.available` term, and `_reveal_for(track)` follows the same refusal logic as T3.2. Panels get `can_drag` and `on_reveal: Callable[[Track], None]`. The button is a normal click button with no select binding. It uses the same column and Now Playing placement as T3.3/T3.5, and the same signature rule (T3.4 signature bullet only; no drag guard is needed).
- **TF1.3** The `deck_drag` setting (T3.6) and docs (Phase 4) still apply. There is no `tkinterdnd2`, spec change or self-check.

## Phase F2 (only with the user's sign-off, if Gate A fails): "Copy search text"

The architect revises ADR-016 first, because this is not rekordbox-specific and does not use `DECK_FILE_DROP`. Sketch: Tk `clipboard_clear()` / `clipboard_append(f"{track.artist} {track.title}".strip())` on the Tk thread, a "Copied" toast, and copy that never says "Load".
**UI (brief §6):** a text button `Copy`, header cell `Name`, tooltip `Copy artist and title, then paste into rekordbox's search`, green toast `Copied "{artist} - {title}"` with each part truncated to 25 characters (`source/ui/utils.py` `truncate`). Setting hint: `Adds a Copy button to each track. rekordbox finds the track from the pasted name; check it before you load.` It is not exact, so it must say "paste" and "check", never "load". The user must also confirm whether Serato users may see it, since they asked for rekordbox only.

---

## Phase 0 findings

_(Engineer: fill in after T0.1–T0.3. One line per check ID S1a–S8, the tkinterdnd2 pin, the tkdnd refuse convention, the playing-deck lock preference name, and whether the drag loop is modal. Synthetic names only.)_

---

## UI revisions applied

By the UI designer, 2026-11-06. Full reasoning is in `ui-design-brief.md`. Nothing outside this folder was changed.

**Replaced every `<!-- UI-designer to revise -->` placeholder** in the blueprint (D5, D7, D8 twice, D11 twice, component diagram, affected-files table, O2, O5) and in this plan (T3.2, T3.3, T3.5, T3.6, T4.2, F1, F2, legend).

**Tasks added or changed, and why:**
- **T3.2a added (shared `DragHandle` widget + public `Tooltip.hide()`).** The handle appears in two panels with five visual states. One widget stops them drifting, and a visible tooltip would otherwise stay on screen during the OS modal drag.
- **T3.3 rewritten.** Position is leftmost by recommendation, because the grid already clips on the right at the minimum window (about 650 px of columns in a roughly 470 px pane) and a rightmost handle would be invisible there. Handle is 32x28 (the existing 32x24 buttons are too small for a drag). A `Deck` header cell is added. The "blank spacer" for ineligible rows becomes a disabled `—` tile with a reason.
- **T3.4 extended.** Because Windows shows no drag ghost, the source row is tinted for the whole drag, restored on drag end, with a `update_idletasks()` before the modal loop and a safety reset if `<<DragEndCmd>>` is unreliable.
- **T3.5 rewritten.** The Now Playing control is a badge-shaped `DRAG TO DECK` tile in `badges_frame`, not a loose handle.
- **T3.6 kept** (the designer recommends the setting), with a label and hint, and a flagged macOS point: a toggle that does nothing should not be shown.
- **T3.7 extended** with UI checks (glyph rendering, press-without-select, tooltip left on screen, Esc cancel, ineligible tile, minimum window).
- **T3.8 added (copy constants)** because all user-visible strings belong in `library_copy.py`, with a test that no string says "Load" as a Sidecar action.
- **T4.5 added (design guide update at ship)** so `docs/ui-design-guide.md` stays the source of truth.
- **T3.2 changed:** the refusal toast is red, 6000 ms, with final text (was a placeholder).
- **F1 and F2** now have labels, tooltips, failure/success copy and settings hints. F2 is flagged as contradicting the "rekordbox only" scope if shown to Serato users.

**Decisions that need the user (brief §10):** O1 handle position, O2 disabled-with-reason versus blank for ineligible rows, O3 searched tracks, O4 announcing the new column, O5 tkdnd-failure signal, O6 toast colour, O7 macOS toggle, O8 whether a drag also selects the track.

**Needs the architect:** ADR-015 D12 refinement (hide the feature, show an ineligible row disabled), and where the macOS platform check for the `deck_drag` spec lives (the provider does not import `config`).

**Not changed:** the capability, gate, adapter, packaging, CI and spike tasks (Phases 0-2) need no UI input. Setlist and search-dropdown handles stay out of v1.
