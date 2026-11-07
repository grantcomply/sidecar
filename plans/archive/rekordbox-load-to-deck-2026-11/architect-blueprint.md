# Architect Blueprint: rekordbox Load to Deck

> **Status:** Proposed. **Gated on the Phase 0 spike (§6, implementation-plan Phase 0).** No app code is written until the spike passes Gate A.
> **Date:** 2026-11-06
> **Author:** Architect agent
> **Plan folder:** `plans/rekordbox-load-to-deck-2026-11/`
> **Proposes:** **ADR-016** (next free number; ADR-014 is the rejected Serato MIDI loader, ADR-015 is library providers).
> **Amends:** ADR-015 D12 (adds a second deck capability; `DECK_LOAD` stays reserved).
> **Relates to:** ADR-014 (sets the bar: a deck-load mechanism must target a *specific* track), ADR-015 D8 (read-only towards rekordbox; never open its files; never log the key), ADR-009 (lazy import, degrade to no-op: `AudioPlayer`), ADR-008 (distribution: a new bundled native Tcl extension), ADR-001 (Tk single-thread rule).
> **Companion:** `implementation-plan.md` (same folder). A UI design brief follows from the ui-designer agent.
>
> **Path note:** the code lives under `source/` (`source/app.py`, `source/providers/rekordbox/...`). `CLAUDE.md`'s project tree omits the `source/` prefix. Every citation here uses the real path.

---

## 1. Context

### 1.1 The request
> "let's please implement the rekordbox load to deck feature. This won't work for Serato, only rekordbox"

The DJ picks a track in Sidecar (a suggestion, or the Now Playing track) and that **exact** track ends up on a rekordbox deck. It applies only to tracks Sidecar knows through the rekordbox provider. Serato-only setups don't get the control.

### 1.2 What is already in place
ADR-015 D12 reserved deck loading in the provider contract, and nothing uses it yet:
- `ProviderCapability.DECK_LOAD` (`source/providers/base.py:66`), `DeckLoadNotSupported` (`base.py:32-33`), and `LibraryProvider.load_to_deck(settings, track_path, deck)` (`base.py:170-175`). This is a **push** contract: Sidecar picks the deck, calls the method off the Tk thread, and the track appears.
- `RekordboxProvider.capabilities` does not declare it (`source/providers/rekordbox/provider.py:130-135`). `load_to_deck` raises (`provider.py:157-159`). Serato raises as well, per ADR-014.
- The single gate is `registry.first_deck_load_provider` (`source/providers/registry.py:35-53`), wrapped by `DJTrackSelectorApp.deck_load_provider_for` (`source/app.py:374-388`). It reads `settings.env` on every call (`app.py:382-384`), which is fine for one track but too slow to call per row.
- The UI rule (ADR-015 D12): deck-load controls stay **hidden** while the gate returns `None`.
- Tests: `tests/providers/test_contract.py:66-71`, `tests/ui/test_app_deck_load_gate.py`, `tests/providers/rekordbox/test_rekordbox_provider.py:201-212`.

### 1.3 The central question: what puts a *specific* track on a rekordbox deck?
ADR-014 (`docs/architecture-decisions.md:431-435`) rejected the Serato MIDI loader. A MIDI "Load" message loads whatever the DJ app's own browser has highlighted. It carries no track identity, so a Sidecar button would load the wrong track. ADR-014's consequence is that **any deck-load mechanism must show how it targets a specific track before it is accepted.** That is the bar this blueprint has to meet.

I have no web access and no rekordbox install. **Every statement below about how rekordbox, tkdnd or the OS behaves is an assumption (marked `[A#]`) until the Phase 0 spike checks it.** The spike's checks are listed against each assumption in §6.

| # | Mechanism | Targets a specific track? | Verdict |
|---|-----------|---------------------------|---------|
| M1 | **rekordbox MIDI Learn / keyboard "Load" mapping.** Virtual MIDI note or keystroke mapped to "Load Deck 1" | **No.** `[A1]` rekordbox's LOAD function loads the track selected in rekordbox's own browser, the same limit ADR-014 found in Serato | **Rejected.** Repeats ADR-014's mistake. The spike records evidence (S6, optional) for the ADR. |
| M2 | **OS file drag-and-drop.** Sidecar is a native drag *source*. The DJ drags a track from Sidecar and drops it on a rekordbox deck | **Yes.** The drag payload *is* the file path, and the DJ picks the deck by where they drop. `[A2]` rekordbox accepts file drops from Explorer/Finder onto a deck and loads that file. `[A3]` It matches the dropped file to its existing collection entry (analysis, beatgrid, cues), so it does not create a duplicate | **Recommended** (§2). Needs `[A2]`, `[A3]` and a working Tk drag source `[A5]–[A8]`. |
| M3 | **Anything keyed by rekordbox's own content ID.** We already read `djmdContent.ID` through pyrekordbox | Would, if rekordbox exposed a "load content ID" entry point. `[A9]` It has no documented one. Every route we know of means writing rekordbox's DB, playlists or XML inside its folder | **Rejected.** ADR-015 D8 and coding standard #5 (`docs/coding-standards.md:59`): never write in a DJ app's folder, never call pyrekordbox write APIs. |
| M4 | **OS keystroke / UI automation.** Focus rekordbox, type in its search, press the load shortcut. Also synthetic drags (`SendInput`, posting `WM_DROPFILES` to deck coordinates) | Approximately, through rekordbox's search matching | **Rejected.** It steals focus mid-set and can type into the wrong window. macOS needs the Accessibility permission, which is friction for an unsigned app (ADR-008). It depends on deck screen coordinates and breaks across Windows integrity levels. Fragile against every rekordbox layout change. |
| M5 | **Pro DJ Link** (beat-link style "load track" commands) | Yes, for **hardware CDJs** | **Out of scope.** `[A10]` rekordbox's software decks are not Pro DJ Link players. Large new protocol surface. |
| M6 | **Clipboard hand-off.** Copy "Artist Title"; the DJ pastes it into rekordbox's search and loads with rekordbox's own shortcut | **Not exactly.** rekordbox's search does the matching, and the DJ confirms it by eye | **Fallback 2** (§2 D11). Honest and cheap, with no dependency. Labelled as "copy", never "load". |
| M7 | **Reveal in Explorer/Finder.** Open a file-manager window with the file selected; the DJ drags it from there onto the deck | **Yes** (the same OS drop as M2, started from the file manager) | **Fallback 1** (§2 D11): used if `[A2]` holds but Sidecar can't be a reliable drag source. No new dependency. |
| M8 | Launch `rekordbox.exe <file>` / an "Open with" shell verb while rekordbox runs | Unknown `[A11]` | **Not planned.** It is undocumented and could start a second instance mid-set. The spike may try it once (S7, optional) purely for the record. |

**Conclusion.** Under the existing ADRs, only drag-and-drop (M2/M7) puts an exact file on a deck that the DJ chose. It does that **without Sidecar sending rekordbox anything.** The DJ's gesture carries the file path through the OS, exactly as if they had dragged it from Explorer. That is a deliberate property: Sidecar gets no outbound control channel, so it cannot load the wrong track on its own and cannot pick the wrong deck. The trade-off is honest. **This is "drag to deck", not "click to load".** A one-click "Load Deck 1" button is not achievable under the current ADRs (`[A9]`). The UI and the ADR say so.

### 1.4 What Sidecar is today (relevant facts)
- **Track identity is the path** (`source/models/path_identity.py`; ADR-015 D6). For a merged track, `full_file_path` is the highest-precedence record's path (`source/services/library_merge.py:18`, `:52`, `:89`). rekordbox comes first in `PROVIDERS` (`source/providers/registry.py:19-22`). So for any track whose `sources` contains `"rekordbox"`, `full_file_path` is the path rekordbox itself resolved (`OrgFolderPath` first, `source/providers/rekordbox/paths.py`). That is exactly the string to hand to rekordbox. This is an invariant we must lock with a test (T1.6), because the feature's correctness depends on it.
- `Track.sources` is set by the merge and never stored (`source/models/track.py:24`, `:74`).
- **Selecting a suggestion destroys every row.** A `<Button-1>` on a row or label calls `_select_track` (`source/ui/suggestion_panel.py:587`, `:627`, `:643-647`). That leads to `app._on_suggestion_selected` → `_update_suggestions` → `set_suggestions`, which destroys the grid (`suggestion_panel.py:524-525`; `source/app.py:699-704`, `:728-732`). It also appends the track to the setlist (`app.py:703`). **A drag cannot start from a widget that selects on press**, because the widget is gone before the pointer moves. The same applies to the search dropdown rows (`source/ui/track_detail.py:264-266`).
- **Live refresh can re-render the list** (`suggestion_panel.py:446-485`). It is deferred while the pointer is over the list or a preview is active (`:473-477`, `:502-511`). During a drag the pointer is over *rekordbox*, so without a new guard a quiet re-render could destroy the drag source mid-drag.
- Background threads never touch Tk. They post to `_ui_queue`, which is drained every 100 ms (`source/app.py:68-71`, `:197-215`).
- There is no drag-and-drop or clipboard code anywhere in `source/` today.
- Shipping is PyInstaller one-folder on bundled **Python 3.11**, on Windows and macOS (`serato-sidecar.spec`; `.github/workflows/release.yml:55`, `:157`). macOS is built but unverified on a real Mac (`docs/cross-platform-guide.md:10`).

---

## 2. Decision: ADR-016 (proposed)

### ADR-016: rekordbox "drag to deck" via an OS file drag (amends ADR-015 D12)

- **Status:** Proposed. Accepted only once Phase 0 Gate A passes.
- **Date:** 2026-11-06
- **Relates to:** ADR-014 (bar met: the payload is the exact file), ADR-015 D8/D12, ADR-009, ADR-008, ADR-001.

#### Context
See §1. The user wants deck loading for rekordbox. No push mechanism (`load_to_deck`) can target a specific track without writing to rekordbox's files or automating its UI (§1.3 M1, M3, M4). An OS file drag carries the exact file and leaves the deck choice and the final action with the DJ.

#### Decision

**D1: Mechanism: Sidecar is an OS file-drag source; rekordbox is the drop target.**
- The DJ presses on a drag handle for a track and drags it onto a rekordbox deck. The payload is **one absolute file path** in the OS file-list format: `CF_HDROP` on Windows, file URLs on macOS, both produced by tkdnd's `DND_FILES` type.
- **Sidecar sends rekordbox nothing.** It does not detect whether rekordbox is running, synthesise input, open rekordbox's files, or write anything. The read-only stance of ADR-015 D8 holds unchanged. Dropping onto rekordbox's browser or a playlist instead of a deck may make *rekordbox* write its own database (adding the track to a playlist). That is rekordbox acting on the DJ's gesture, the same as a drag from Explorer, and Sidecar's live refresh will pick it up.
- **Allowed drop action: copy only.** Never offer *move* or *link*. With *move*, an OLE drop target (Explorer, a folder) may move or delete the DJ's music file. With copy, an accidental drop onto the desktop only duplicates the file. This is a review blocker.

**D2: Contract: a new capability, `ProviderCapability.DECK_FILE_DROP = "deck_file_drop"`** (`source/providers/base.py:61-66`).
- Meaning: *"this provider's DJ app loads an audio file dropped from the OS onto one of its decks, matched to the track already in its library."* It is DJ-software knowledge, so it belongs to the provider (`docs/coding-standards.md:55-56`). No provider-id branching appears outside `source/providers/`.
- There is **no new provider method.** The payload is `Track.full_file_path`, which for a track in rekordbox's `sources` is rekordbox's own resolved path (§1.4; locked by test T1.6). The DJ app does the drop, so there is nothing for the provider to execute.
- **`DECK_LOAD` / `load_to_deck` stay reserved and unimplemented.** Both providers still raise `DeckLoadNotSupported`. This ADR records that a push-load for rekordbox was evaluated and rejected (§1.3). The contract test at `tests/providers/test_contract.py:66-71` is unchanged.
- **rekordbox** declares `DECK_FILE_DROP` while its setting `deck_drag` is `on` (D8). **Serato** does not declare it, per the user's scope. If Serato accepts file drops too (`[A12]`, untested), enabling it later is one line plus an ADR note after its own spike (O3).

**D3: Gate: one pure rule, cached per reload.**
- `registry.first_provider_with(capability, provider_ids, settings_for)` generalises `first_deck_load_provider` (`source/providers/registry.py:35-53`). The old name stays as a one-line wrapper so its tests (`tests/providers/test_serato_provider.py:161-175`) keep passing.
- New pure module `source/services/deck_drop.py`:
  - `drop_capable_ids(enabled_ids, capabilities_for) -> frozenset[str]`: the enabled providers that declare `DECK_FILE_DROP`.
  - `can_drag(track_sources, capable_ids) -> bool`: true when **`track_sources[0]`** is in `capable_ids`. `sources[0]` is the provider whose record supplied `full_file_path`: the merge appends sources in snapshot order and keeps the first record's path (`source/services/library_merge.py:52`, `:59-84`, `:89`). Keying on `sources[0]`, rather than "any source", means the payload is always the capable provider's own path string, even if registry order changes later. **A Serato-only track in a mixed library is not draggable.** Dropping it would make rekordbox import a new, unanalysed collection entry mid-set (`[A4]`). Tracks present in both providers have `sources == ("rekordbox", "serato")`, so they are draggable and their path is rekordbox's.
  - `drag_refusal(path, is_file) -> DropRefusal | None`: run at drag start. Refuses with `FILE_MISSING` when the file is not on disk. This covers rekordbox snapshot tracks "with no file on this computer" (`source/providers/rekordbox/provider.py:296-297`, `:310-311`) and files moved since the last sync.
- `app.py` computes `self._deck_drop_ids` once in `_reload_library` (`source/app.py:300-325`). That runs at startup, after every sync and after Settings → Save (`app.py:640`), so enable/disable and setting changes are covered and no per-row call reads `settings.env` (the cost noted at `app.py:382-384`). `deck_drop_available_for(track)` mirrors `deck_load_provider_for` (`app.py:374-388`) and adds the drag-source availability check (D4).
- **The single source of truth for showing a drag control is `app.deck_drop_available_for(track)`.** Panels receive it as a callback (`docs/coding-standards.md:68`) and never inspect providers.

**D4: Drag-source adapter: `source/ui/drag_source.py`, the only module that imports `tkinterdnd2`.**
- It lives in `ui/` because it registers Tk widgets. `services/` has no UI imports (`docs/architecture-overview.md:71`).
- **Library: `tkinterdnd2`** (Python wrapper plus bundled **tkdnd 2.9.x** Tcl extension binaries, MIT/BSD-style licences). `[A5]` It provides a drag *source* on Windows (OLE `DoDragDrop`). `[A6]` macOS drag-source support in the bundled tkdnd is uncertain (historically drop-target only, with later versions adding a source). `[A7]` It can be loaded into an existing `ctk.CTk` root with `TkinterDnD._require(root)`, so `DJTrackSelectorApp` keeps its base class (`source/app.py:54-56`). `[A8]` Its binaries work in a PyInstaller one-folder build with `collect_all("tkinterdnd2")`.
- **Shape (mirrors `AudioPlayer`, ADR-009; `source/services/audio_player.py:16-70`):**
  ```python
  class FileDragSource:
      def __init__(self, root: tk.Misc, *, platforms: tuple[str, ...], loader=None) -> None: ...
      @property
      def available(self) -> bool: ...            # tkdnd loaded AND sys.platform in platforms
      def make_draggable(
          self,
          widgets: Sequence[tk.Misc],             # the handle's real Tk widgets (CTk is compound)
          path_for_drag: Callable[[], str | None],# None = refuse (app already toasted why)
          on_drag_start: Callable[[], None] | None = None,
          on_drag_end: Callable[[], None] | None = None,
      ) -> bool: ...                              # False = not registered (unavailable); no-op
  def file_list_payload(tcl: tk.Misc, paths: Sequence[str]) -> str: ...  # Tcl-list quoting
  def self_check() -> int: ...                     # for --self-check-drag (D9)
  ```
- **Lazy import, degrade to no-op.** `tkinterdnd2` is imported inside the constructor and only when `sys.platform` is in `config.DECK_DRAG_PLATFORMS`. A failure (`ImportError`, `OSError`, `tk.TclError` from `package require tkdnd`) is logged as a warning and leaves `available=False`. Every method is then a no-op, and no drag control is ever shown. **The app must start normally with `tkinterdnd2` missing or broken.** Use these specific exception types, not a bare `except Exception` (`docs/coding-standards.md:39-43`).
- **CTk widgets are compound.** A `CTkLabel` or `CTkButton` draws through an inner `tk.Canvas` plus a `tk.Label`, and the pointer hits those, not the outer frame. `make_draggable` takes the list of real widgets. A small helper in the same module collects a CTk widget's children. `[A7]` is checked in the spike.
- **Payload quoting.** tkdnd expects a Tcl list of paths. Paths with spaces, braces, `&`, or non-ASCII characters (including NFD names on macOS) must be quoted with the interpreter's own `list` command (`tcl.tk.call("list", *paths)`), never with string formatting. This is pure and can be tested with `tkinter.Tcl()` and no display.
- **No Tk calls from other threads.** Drag events arrive on the Tk thread. There is no worker thread (contrast the MIDI plan's D4).

**D5: Where the drag starts: a dedicated handle, never a press-to-select surface.** *(UI direction applied; see `ui-design-brief.md` §3.)*
- Architectural constraint (§1.4): any widget that selects on `<Button-1>` destroys the list on press, so it cannot be a drag source. The drag starts from a **dedicated handle widget with no select binding.** Tk delivers an event to the child widget's own bindtags, so a handle inside a row does not fire the row's `<Button-1>`. The handle must not bind `<Button-1>` to anything that re-renders.
- **Surfaces (UI designer, decided in the brief):**
  1. **Suggestion rows** (`source/ui/suggestion_panel.py:559-627`): a new grid column, **leftmost by recommendation** (brief O1; rightmost is the alternative). The column is 32 px wide and the handle 32x28, filling the row height. Rightmost is invisible at the 1000x650 minimum window because the grid already clips there (brief §0.4). A header cell `Deck` labels the column (`:154-169`).
  2. **Now Playing dashboard**: a badge-shaped tile `DRAG TO DECK` as the fifth badge in `badges_frame` (`source/ui/track_detail.py:92-100`, built like `_make_badge` `:111-127`). It is the only place a track found by search can be dragged from.
  3. Search dropdown rows (`track_detail.py:238-276`) and setlist rows (`source/ui/session_panel.py:106-136`): **not in v1** (brief O3).
- **Shared widget:** both surfaces use one `source/ui/drag_handle.py` with five states (resting, hover, dragging, ineligible, unavailable-hidden) so the panels cannot drift.
- **Whole-row drag: rejected** by the UI designer. It changes the core click (select on press) in the most-used interaction in the app.
- **Dragging changes no Sidecar state.** It does not select the track, add it to the setlist, or stop a preview. Sidecar cannot know whether the drop landed on a deck (D7), so it must not act as if it did. The UI designer agrees and recommends keeping it (brief O8); the cost is one extra click when the DJ makes the track live. The one visual state a drag does change is local and temporary: the source row is tinted until drag end (brief §3.6), because there is no OS drag ghost showing which track is in flight.

**D6: Live-refresh and render safety during a drag.**
- `SuggestionPanel` gains `_dragging: bool`, set by `on_drag_start` / `on_drag_end`. `_try_quiet_render` returns early while dragging, as it does while previewing (`source/ui/suggestion_panel.py:473-474`). Drag end schedules `after_idle(self._try_quiet_render)`, mirroring `:795-797`.
- `_signature` (`suggestion_panel.py:435-444`) adds the per-track `can_drag` flag. Otherwise a Settings → Save that turns the feature on or off would leave stale handles: the quiet render would see an unchanged signature and skip.
- On Windows `[A13]` tkdnd's `DoDragDrop` runs a modal OLE loop. Tk `after` callbacks (UI-queue pump, preview playhead poll at `suggestion_panel.py:754-768`) pause until the drop and then catch up. `_ui_queue` is an unbounded `SimpleQueue` (`source/app.py:70`), so nothing is lost. Audio preview runs inside pygame and keeps playing.

**D7: No claim of success.** *(UI direction applied; brief §3.6, §6.)*
Sidecar learns at most the drop *effect* the target reported (`<<DragEndCmd>>`). `[A14]` That effect is unreliable as "loaded on a deck". The UI never says "Loaded" (nor "Load", "Sent"). While dragging it shows only local state: the handle held blue and the source row tinted (there is no drag ghost). It gives explicit feedback only when it **refuses** a drag (file missing): one **red** toast through `_show_toast` (`source/app.py:500-534`), 6000 ms, text `Can't drag this track: its file is missing or moved`, from `source/services/library_copy.py` (colour is brief O6). Drop on a deck, drop on nothing and Esc produce no message.

**D8: Settings and availability.**
- New rekordbox `SettingSpec`: `key="deck_drag"`, `env_key="REKORDBOX_DECK_DRAG"`, `kind=CHOICE`, `choices=("on", "off")`, default `"on"`. It goes into `setting_specs`/`default_settings` (`source/providers/rekordbox/provider.py:82-112`), and `capabilities` adds `DECK_FILE_DROP` when it is `on` (`:130-135`), exactly like `auto_refresh` → `CHANGE_DETECTION`. The settings dialog renders it without provider branching. It is a kill switch for a DJ who finds the handles in the way. **UI designer: keep it** (brief §7.1; it returns the 32 px column at the minimum window). Label `Drag tracks to decks`; hint `Adds a grip to each track. Drag it onto a rekordbox deck to load that track.` On macOS (outside `DECK_DRAG_PLATFORMS`) the spec should be omitted rather than shown inert (brief §7.3, O7); this needs the architect to decide where the platform check lives, since `providers/rekordbox/provider.py` does not import `config` today.
- **The drag control is shown only when all of these hold:**
  1. `FileDragSource.available`: tkdnd loaded, and `sys.platform` is in `config.DECK_DRAG_PLATFORMS`. That is `("win32",)` until macOS passes the spike, after which `"darwin"` is added (D10).
  2. An enabled provider declares `DECK_FILE_DROP`: rekordbox enabled with `deck_drag=on`.
  3. The track's `sources[0]` is that provider (D3).
  
  If condition 1 or 2 fails (the *feature* is unavailable), the whole column and tile are **hidden**, per ADR-015 D12's hidden-UI rule. If conditions 1 and 2 hold but condition 3 fails for one track (a Serato-only track in a mixed library), the UI designer proposes the handle is shown **disabled with a reason** (a `—` tile, tooltip `Not in your rekordbox library, so it can't be dragged to a deck`), because an unexplained gap in one row reads as a broken app mid-set. This refines D12 from "feature hidden" to "feature hidden, row ineligible shown disabled" and needs sign-off (brief §8 item 1, O2). `can_drag` still returns False for these rows and **no drag is registered on them**.
- A missing file is checked **at drag start only** (one `os.path.isfile` on the Tk thread). Checking per row at render time would stat up to 60 files per re-render (`config.MAX_SUGGESTIONS`, `source/config.py:342`). A sleeping USB or network drive could stall that stat, which is risk R6.

**D9: Packaging (ADR-008).**
- `requirements.txt` gets `tkinterdnd2==<pin>`. The pin is chosen in the spike: the newest release whose wheel bundles tkdnd for `win-x64`, `osx-arm64` and `osx-x64` on CPython 3.11 (`[A8]`).
- `serato-sidecar.spec` gets `collect_all("tkinterdnd2")` (beside `:38-42`; merged at `:47`, `:51`, `:100`) and hidden imports for `source.ui.drag_source` and `source.services.deck_drop` (list `:59-99`).
- New frozen check **`--self-check-drag`** (`main.py:24-27` pattern). It creates a withdrawn Tk root, loads tkdnd, prints the tkdnd version, and exits 0 or 1. CI runs it after the rekordbox self-check on both runners (`.github/workflows/release.yml:102-109`, `:216-220`). `[A15]` GitHub's Windows and macOS runners can create a Tk root. If macOS cannot, the mac step only asserts that the tkdnd library file is in the bundle.
- No installer, entitlement or permission changes. Drag-and-drop needs no macOS Accessibility permission, which is a key advantage over M4.

**D10: Platforms.**

| | Windows | macOS |
|---|---|---|
| Drag source | tkdnd OLE `DoDragDrop`, `CF_HDROP` `[A5]` | tkdnd Cocoa drag source `[A6]`, **unverified** |
| rekordbox as drop target | `[A2]`, `[A3]`, spike on the user's rekordbox 7.2.19 | `[A2-mac]`, unverified (no Mac yet) |
| Path form | rekordbox `OrgFolderPath` → `normpath` (backslashes) | POSIX; NFC/NFD as stored by rekordbox (the file is checked with `isfile`) |
| Known hazard | **UIPI:** drag-and-drop between processes at different integrity levels is blocked. If rekordbox runs as administrator and Sidecar doesn't (or the other way round), drops fail silently (R5) | Finder-style drops are standard; no permissions needed |
| Initial state | Enabled (`DECK_DRAG_PLATFORMS = ("win32",)`) | **Disabled** until a Mac spike passes; then add `"darwin"` |

Linux is dev only. tkdnd supports XDND, but there is no rekordbox, so it is not in the allowlist.

**D11: Fallbacks, chosen by the spike outcome (§6).**
- **Fallback 1: "Show in Explorer / Finder"** (M7). Use it if Gate A passes (rekordbox accepts drops) but Sidecar can't be a reliable drag source (S2 fails). New pure module `source/services/file_reveal.py` builds `["explorer", f"/select,{path}"]` on Windows or `["open", "-R", path]` on macOS, and runs it with `subprocess.Popen`: an argument list, `shell=False`. `explorer.exe` returns exit code 1 even on success, so ignore the code and log `OSError`. The track stays exact, and the DJ drags from the file-manager window. It opens a window and takes focus, but only on a click. The capability, gate and placement stay the same (D2, D3, D5). Only the control's action changes. **UI:** a 48 px text button `Show` (a click, so not a grip), header cell `File`, in the same column and Now Playing position as the handle; tooltip `Show this file in Explorer. Drag it from there onto a rekordbox deck.` (`Finder` on macOS); failure toast `Couldn't open the folder`. The button binds no select and changes no state (brief §6 fallback table).
- **Fallback 2: "Copy search text"** (M6). Use it if Gate A fails (rekordbox doesn't load file drops onto decks). Tk `clipboard_clear` / `clipboard_append` of `"Artist Title"`, with no dependency. It is **not exact**, so it must never be labelled "Load". If the spike lands here, the architect returns to the user before building it. It has no rekordbox-specific value, so it would not use `DECK_FILE_DROP`, and it could be offered to every provider. **UI:** a `Copy` button, header cell `Name`, tooltip `Copy artist and title, then paste into rekordbox's search`, green toast `Copied "{artist} - {title}"` (each truncated to 25 characters). Never labelled "Load". Because it is inexact, the setting hint says `check it before you load`. Note this contradicts the user's "only rekordbox" scope if offered to Serato users, so the user must confirm that (brief §6).
- If neither is acceptable to the user, record ADR-016 as **Rejected**, like ADR-014.

**D12: New review-blocker rules** (added to `docs/coding-standards.md` at merge).
1. Only `source/ui/drag_source.py` imports `tkinterdnd2`, lazily.
2. Drag actions are **copy only**. Never move or link.
3. The drag payload is `Track.full_file_path` of a track that passes `deck_drop_available_for`. Never a path built by hand, and never a Serato-only path.
4. Sidecar never synthesises input events, focuses or automates another application, or writes in a DJ app's folder to cause a deck load.

#### Consequences
- Pro: Meets ADR-014's bar. The exact file goes to the deck the DJ chose. Sidecar has no outbound channel that could load the wrong track by itself.
- Pro: No change to the read-only stance, no key involvement, no rekordbox file opened.
- Pro: No new thread, and no permissions on either OS. It degrades to "no control shown" if tkdnd fails.
- Pro: It reuses the capability/gate shape from ADR-015 D12. The UI stays provider-agnostic.
- Con: **A drag, not a click.** It needs both windows visible: a second screen, or Sidecar beside rekordbox. On one cramped laptop screen it may be awkward (O1).
- Con: A new bundled native Tcl extension (`tkdnd`) whose PyInstaller behaviour and macOS support are unverified.
- Con: No confirmation that the track loaded (D7).
- Con: rekordbox's drop handling is undocumented behaviour that a rekordbox update could change. The manual check moves into the rekordbox upgrade runbook (`docs/deployment-guide.md`).
- Neutral: `DECK_LOAD` stays a reserved, unimplemented contract member (ADR-015 "Con" unchanged).

---

## 3. Component design

```
main.py
 └─ --self-check-drag ─────────────▶ ui/drag_source.self_check()        (frozen CI check)

app.py (DJTrackSelectorApp)
 ├─ __init__: self._drag = FileDragSource(self, platforms=DECK_DRAG_PLATFORMS)   # lazy tkdnd
 ├─ _reload_library: self._deck_drop_ids = deck_drop.drop_capable_ids(enabled, caps_for)
 ├─ deck_drop_available_for(track) -> bool        # _drag.available and can_drag(track.sources, ids)
 ├─ _drag_path_for(track) -> str | None           # current library object, isfile, toast refusal
 ├─ SuggestionPanel(..., drag_source=self._drag,
 │                   can_drag=self.deck_drop_available_for, drag_path=self._drag_path_for)
 └─ NowPlayingDashboard(..., same three)          # one DRAG TO DECK badge tile (brief §3.4)

ui/drag_handle.py        DragHandle: shared tile widget; states resting/hover/dragging/ineligible   (new, brief §3.2)

providers/base.py        ProviderCapability.DECK_FILE_DROP
providers/registry.py    first_provider_with(capability, ids, settings_for); first_deck_load_provider wraps it
providers/rekordbox/provider.py   deck_drag SettingSpec; capabilities() adds DECK_FILE_DROP when on
services/deck_drop.py    drop_capable_ids, can_drag, drag_refusal, DropRefusal   (pure, stdlib + base)
services/library_copy.py refusal toast text, setting label/hint                  (UI-designer owns copy)
ui/drag_source.py        FileDragSource, file_list_payload, ctk_hit_widgets, self_check  (only tkinterdnd2 importer)
config.py                DECK_DRAG_PLATFORMS
```

**Why panels get `drag_source`:** registering a widget needs the adapter, the same way `SuggestionPanel` gets `AudioPlayer` (ADR-009; `source/app.py:152-157`). The *decisions* (`can_drag`, `drag_path`) are callbacks owned by the app, so panels never see providers. This follows the existing documented ADR-009 precedent. It is not a new exception.

**Drag sequence (Windows, assumed):**
```
DJ presses on handle ──B1-Motion past threshold──▶ tkdnd <<DragInitCmd>>
   handler: path = drag_path()          # app: track_by_path → isfile → refusal toast → None
            None  → return refuse (no drag)
            path  → on_drag_start(); return (COPY, DND_FILES, file_list_payload([path]))
OS modal drag loop ──drop on rekordbox deck──▶ rekordbox loads the file   [A2, A3]
tkdnd <<DragEndCmd>> ──▶ on_drag_end() → panel clears _dragging → after_idle(_try_quiet_render)
```

---

## 4. Affected files

| File | Change |
|------|--------|
| `source/providers/base.py` | `DECK_FILE_DROP` in `ProviderCapability` (`:61-66`); update the docstring at `:5-9`. |
| `source/providers/registry.py` | `first_provider_with` (`:35-53`); `first_deck_load_provider` becomes a wrapper. |
| `source/providers/rekordbox/provider.py` | Declare `DECK_FILE_DROP` (`:130-135`); `deck_drag` spec and default (`:82-112`, Phase 3); `load_to_deck` docstring (`:157-159`) points to ADR-016. |
| `source/services/deck_drop.py` | **New.** Pure gate rules (D3). |
| `source/ui/drag_source.py` | **New.** tkdnd adapter (D4), `self_check`. |
| `source/config.py` | `DECK_DRAG_PLATFORMS` after the refresh constants (`:347-354`). |
| `source/app.py` | Imports (`:24-41`); create `FileDragSource` beside `AudioPlayer` (`:83`); `_deck_drop_ids` in `_reload_library` (`:300-325`); `deck_drop_available_for` + `_drag_path_for` beside `deck_load_provider_for` (`:374-388`); pass callbacks at `:138-143`, `:152-157`. |
| `source/ui/drag_handle.py` | **New.** Shared handle tile with its visual states (brief §3.2). |
| `source/ui/suggestion_panel.py` | Leftmost handle column and `Deck` header cell (`:82-86`, `:154-169`, `:559-613`; all data columns shift right by one); source-row tint during a drag; `_dragging` guard (`:466-477`); signature (`:435-444`). |
| `source/ui/track_detail.py` | `DRAG TO DECK` badge tile in `badges_frame` (`:92-100`); show/hide/disable in `_render` (`:172-211`). |
| `source/ui/tooltip.py` | A public `hide()` so a visible tooltip can be dismissed at drag start. |
| `source/services/library_copy.py` | All new strings (brief §6): header cell, tooltips, refusal toast, setting label and hint, Now Playing label. |
| `main.py` | `--self-check-drag` (`:24-27`). |
| `requirements.txt` | `tkinterdnd2==<pin>`. |
| `serato-sidecar.spec` | `collect_all("tkinterdnd2")` (`:38-51`), hidden imports (`:59-99`). |
| `.github/workflows/release.yml` | Frozen `--self-check-drag` after `:102-109` and `:216-220`. |
| `tests/services/test_deck_drop.py`, `tests/ui/test_drag_source.py`, `tests/ui/test_app_deck_drop_gate.py` | **New.** |
| `tests/providers/rekordbox/test_rekordbox_provider.py`, `tests/providers/test_serato_provider.py`, `tests/services/test_library_merge.py`, `tests/providers/test_contract.py` | Extended (capabilities, wrapper, path-precedence invariant, setting defaults). |
| `docs/architecture-decisions.md` | ADR-016; ADR-015 D12 table row amended. |
| `docs/architecture-overview.md` | Tables (`:55-104`), debt #16 (`:163`) reworded, new debt entry for the import-boundary scan covering `tkinterdnd2`. |
| `docs/coding-standards.md` | D12 rules under "DJ library providers" (`:51-64`). |
| `docs/cross-platform-guide.md` | New "Drag to deck" section (D10 table, UIPI note); native dependency matrix (`:174-185`) gains tkdnd. |
| `docs/testing-strategy.md` | Coverage and manual checklist. |
| `docs/deployment-guide.md` | rekordbox upgrade runbook gains "re-check drag to deck". |
| `README.md`, `docs/install-guide-for-friends.md` | How to use it, and "don't run rekordbox as administrator". |
| `CLAUDE.md` | Project tree: `deck_drop.py`, `drag_source.py`. |

---

## 5. Phases (detail in `implementation-plan.md`)

| Phase | What | Visible? | Gate to start |
|---|---|---|---|
| **0** | Manual spike against real rekordbox, plus a throwaway tkinterdnd2 script, source and frozen (no repo code) | No | — |
| **1** | Contract, gate and pure rules (`DECK_FILE_DROP`, `first_provider_with`, `deck_drop.py`, app gate, path-invariant test) | No (nothing renders a control) | Gate A **and** Gate B passed |
| **2** | Drag-source adapter, dependency, spec, `--self-check-drag`, CI | No (adapter loaded, no widgets registered) | Phase 1 green |
| **3** | UI: handles, drag guard, refusal toast, `deck_drag` setting | **Yes** | Phase 2 green; UI design brief delivered |
| **4** | Docs, ADR-016 accepted, manual live rehearsal, macOS verification (flip the allowlist only if it passes) | — | Phase 3 green |
| **F1 / F2** | Fallbacks replace Phases 2–3 if the spike chooses them (D11) | Yes | Spike outcome; F2 needs user sign-off |

---

## 6. Phase 0 spike: what exactly it must verify

Run on the user's Windows machine with rekordbox 7.2.19 in **Performance** mode, both apps **not elevated**, using a throwaway playlist and tracks the DJ doesn't mind touching. Record the results in `implementation-plan.md` → "Phase 0 findings". Record no real titles or paths (`docs/testing-strategy.md:17`).

| Check | Verifies | Pass = |
|---|---|---|
| **S1a** Drag an MP3 that is *in* the rekordbox collection from Explorer onto stopped Deck 1, then Deck 2 | `[A2]` | That exact file loads on the deck it was dropped on |
| **S1b** Same, then inspect the deck and the collection count | `[A3]` | Existing beatgrid, cues and key are shown; collection count unchanged (no duplicate entry) |
| **S1c** Drop onto a **playing** deck, with and without rekordbox's playing-deck load-lock preference (find its exact name) | R1 worst case | Record behaviour. With the lock on, the load is refused |
| **S1d** Drop a file that is **not** in the collection | `[A4]` | Record behaviour (imported? analysed? added?). This justifies the "rekordbox tracks only" gate |
| **S1e** Paths with spaces, `&`, braces and accented characters | Payload quoting | All load |
| **S1f** Drop onto the browser or a playlist pane instead of a deck | R7 | Record behaviour (adds to the playlist?) |
| **S1g** Export mode, and 4-deck mode | O4 | Record behaviour |
| **S2a** Throwaway `ctk.CTk` + `TkinterDnD._require(root)`; a `CTkLabel` handle registered as a `DND_FILES` source (copy only) → drag onto a rekordbox deck | `[A5]`, `[A7]` | Same result as S1a/S1b |
| **S2b** A plain click on the handle does not start a drag; a drag past the threshold does | D5 | Yes |
| **S2c** Drag the same handle onto an Explorer folder | D1 copy-only | The file is **copied**, the original is untouched |
| **S2d** Repeat S2a from a PyInstaller one-folder build of the throwaway script | `[A8]` | Works; note the tkdnd binary path inside `_internal` |
| **S2e** While dragging, check whether a Tk `after` timer keeps ticking | `[A13]` | Record (modal or not) |
| **S2f** Read the `<<DragEndCmd>>` action after a deck drop vs a drop on nothing | `[A14]` | Record (informs D7 only) |
| **S3** rekordbox elevated, Sidecar not | R5 | Expected to fail; record it for the docs |
| **S4** macOS (only if a Mac is available): S1a–S1b with Finder, S2a–S2d | `[A2-mac]`, `[A6]` | Pass → add `"darwin"` in Phase 4 |
| **S5** rekordbox shortcuts: focus search; load the selected track to Deck 1/2. Does pasting "Artist Title" find the track? | Fallback 2 input | Record |
| **S6** (optional) MIDI Learn "Load" → loads the browser-selected track? | `[A1]` (ADR record) | Record |
| **S7** (optional, **not mid-set**) `rekordbox.exe <file>` while running | `[A11]` | Record only; no plan depends on it |
| **S8** pip: which `tkinterdnd2` version ships tkdnd for win-x64 / osx-arm64 / osx-x64 on cp311; licence files | `[A8]`, D9 | Pin chosen |

**Gates:**
- **Gate A** (S1a + S1b): rekordbox loads the exact dropped file, matched to its existing collection entry. **Fail → Fallback 2 path; return to the user.**
- **Gate B** (S2a + S2b + S2c + S2d): Sidecar can be a safe, copy-only drag source in a frozen Windows build. **Fail with A passing → Fallback 1 ("Show in Explorer").**
- macOS (S4) does not gate Windows. It only decides the allowlist.
- If the spike shows rekordbox **can** be told to load a specific track by some push mechanism, without writing to its files (S7 or something unexpected): stop and return to the architect. That would be a `DECK_LOAD` implementation instead.

---

## 7. Live-set safety: the worst case is the wrong track on a deck

| Failure | How it could happen | Mitigation |
|---|---|---|
| Wrong **track** | Sidecar sends a path that isn't the track the DJ saw | The payload is the row's own `Track.full_file_path` (rekordbox's string, T1.6), resolved at drag start through `library.track_by_path` so a pre-refresh row can't go stale. No browser-selection dependency (contrast ADR-014). Copy-only. |
| Wrong **track**, file moved | The snapshot path no longer exists, or points to a re-used name | `isfile` at drag start refuses a missing file with a toast. A *different* file now at the same path is indistinguishable, which is accepted: the same is true of rekordbox's own collection. |
| Wrong **deck** (onto the playing deck) | The DJ drops on the deck that's on air | This is the DJ's gesture, and Sidecar can't see rekordbox's decks. Recommend rekordbox's own playing-deck load lock in the README (S1c names it). |
| Accidental drag | A press on the handle with a small movement | tkdnd's motion threshold (S2b). The handle is separate from select; dropping on nothing does nothing. |
| Accidental drop elsewhere | Onto the desktop or a folder: a file copy. Onto rekordbox's browser: added to a playlist | Copy-only (no move or delete). The playlist add is rekordbox's own action; Sidecar's live refresh shows it. |
| Serato-only track imported mid-set | A Serato-only path dropped on rekordbox | Not draggable (D3 `can_drag`). |
| Sidecar UI stalls during a drag | Modal OLE loop `[A13]` | Only Sidecar's timers pause; rekordbox and audio are unaffected. The queue drains afterwards. |
| List re-renders under a drag | Live refresh during the drag | The `_dragging` guard (D6). |

---

## 8. Risks

- **R1 (critical, product): `[A2]`/`[A3]` false.** rekordbox may not accept file drops on decks, or may create duplicate collection entries. *Mitigation:* Gate A, before any code. Fallbacks D11.
- **R2 (high): tkdnd drag source unreliable with CTk** (compound widgets, click vs drag, frozen build). *Mitigation:* Gate B covers all four. Fallback 1 needs no dependency.
- **R3 (medium): macOS unverified** (`[A6]`, `[A2-mac]`, and the Mac build as a whole). *Mitigation:* platform allowlist, disabled by default on macOS.
- **R4 (medium): a bundled native Tcl extension** in a PyInstaller build (ADR-008), plus a pin that must ship binaries for all targets. *Mitigation:* S8 pin choice; `collect_all`; frozen `--self-check-drag` in CI on both runners; lazy degrade.
- **R5 (medium, Windows): UIPI integrity-level mismatch** silently blocks drops. *Mitigation:* README / install guide; S3 records it. Sidecar can't detect it.
- **R6 (low): `isfile` on a sleeping drive** stalls the Tk thread at drag start. *Mitigation:* one stat, only at drag start, never per row.
- **R7 (low): dropping into rekordbox's browser** adds to a playlist. *Mitigation:* documented; rekordbox's own behaviour.
- **R8 (medium): rekordbox updates** may change drop handling. *Mitigation:* add it to the upgrade runbook's manual checks.
- **R9 (low): user expectation.** "Load to deck" may mean a button to the user. *Mitigation:* O1 asked up front; the ADR states plainly that a click-to-load can't be built under current ADRs.
- **R10 (low): Tk `after` from other threads during a modal drag.** Background threads only `put` into `_ui_queue` (`source/app.py:197-200`) and never call Tk. No change is needed.

---

## 9. Open questions (for the user, via the orchestrator)

- **O1 (top): is "drag to deck" acceptable instead of "click to load"?** A click that loads a *specific* track isn't possible without writing to rekordbox's files or automating its UI. Both are ruled out (§1.3). Does the DJ have Sidecar and rekordbox visible at once (two screens or side by side)? If not, the drag route is far less useful, and Fallback 1 ("Show in Explorer") has the same problem.
- **O2: should a successful-looking drag also add the track to Sidecar's setlist / make it Now Playing?** The default is **no** (D5, D7), because Sidecar can't tell whether the drop landed on a deck. **UI designer agrees:** a wrong or aborted drag would write a false setlist entry. The cost is one extra click when the DJ makes the track live. If the user wants automation, it should be a separate explicit step (brief O8).
- **O3: Serato.** The user says Serato is out of scope. If Serato DJ also accepts file drops on decks (`[A12]`), the same mechanism would work there with a one-line capability change. Should a 2-minute Serato check go into the spike for the record?
- **O4: decks.** A drop picks the deck by itself, so there is no deck-number setting. Confirm that 4-deck mode and Export mode don't matter to the user (S1g).
- **O5: the `deck_drag` setting.** Is a kill switch wanted, or is "always on when rekordbox is enabled" enough? **UI designer: keep the setting, default On** (brief §7.1). It costs one spec and no dialog code, and it is the only way to reclaim the 32 px column at the minimum window.
- **O6 (UI, new): where does the macOS platform check for the setting live?** Brief §7.3 wants the `deck_drag` spec omitted on platforms outside `DECK_DRAG_PLATFORMS`, so the dialog never shows an inert toggle. The provider does not import `config`. Options: the provider checks `sys.platform` itself, or the app passes the allowlist in. The architect decides.
- **O7 (UI, new): ADR-015 D12 refinement.** Accept "feature hidden, ineligible row shown disabled with a reason" (brief §5.2, §8)? If not, fall back to a blank spacer.
- **UI open questions O1-O8** (handle position, searched tracks, announcing the column, tkdnd-failure signal, toast colour) are in `ui-design-brief.md` §10.
