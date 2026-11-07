# Architect Blueprint: Copy a track's search text

> **Status:** Implemented (2026-11-07; reviewed and accepted by the user; recorded as ADR-016)
> **Date:** 2026-11-06 (revised the same day with the user's answers; see "User decisions applied" at the end)
> **Author:** Architect agent
> **Plan folder:** `plans/copy-track-search-text-2026-11/`
> **Companion:** `implementation-plan.md` and `ui-design-brief.md` (same folder). The ui-designer has reviewed: D3, D4 and D6 were revised in place (see the plan's `## UI revisions applied`).
> **Relates to:** ADR-014 (deck loading must target a specific track), ADR-015 D12 (`DECK_LOAD` stays reserved), ADR-001 (Tk single-thread rule), coding standards "DJ library providers" #2 and #10 (`docs/coding-standards.md:56`, `:64`).
>
> **Path note:** the code lives under `source/`. `CLAUDE.md`'s project tree leaves out the `source/` prefix. Every citation here uses the real path.

---

## 1. Context

### 1.1 The feature (agreed with the user)
Each suggestion row gets a **copy button** (icon only; the ui-designer sets the glyph). One click puts the track's search text on the OS clipboard (for example `Artist Title`). The DJ pastes it into the search box of rekordbox or Serato. That app's own search highlights the track, and the DJ loads it with their controller or the app's load shortcut.

It works for **every track from every provider**. Sidecar sends nothing to either DJ app: no MIDI, no synthesised keystrokes, no drag-and-drop, no focus changes.

User decisions already made:
- Copying **does not** add the track to the setlist and does not select it.
- The button sits in the **leftmost column** of the suggestion rows, and it is **icon-only**.
- **Suggestion rows only in v1.** No Now Playing control ("if it's now playing then I probably already have it in the software").
- **Less is more:** both DJ apps match substrings and words, so the query is stripped of mix names, bracketed text and `feat.` credits (D1).
- Every track is eligible. This blueprint decides the "no artist or title" case (D1).

### 1.2 How we got here (recorded, not re-opened)
| Route | Outcome | Where |
|---|---|---|
| Virtual MIDI "Load" note (Serato) | Rejected. A MIDI note can't say which track to load | ADR-014 (`docs/architecture-decisions.md:431-435`), `plans/virtual-midi-deck-loader-2026-09/` |
| OS file drag onto a rekordbox deck | Rejected by the user. Drag isn't the interaction they want | `plans/rekordbox-load-to-deck-2026-11/` (it proposed ADR-016; never accepted) |
| Keystroke automation (Sidecar types into rekordbox's search) | Rejected. If the search box isn't focused, the typed letters fire DJ shortcuts mid-set | User decision |
| **Clipboard hand-off** | **Chosen.** It was Fallback 2 (M6) in the drag plan (`plans/rekordbox-load-to-deck-2026-11/architect-blueprint.md:43`, `:165`) | This plan |

The clipboard route is **not exact**. The DJ app's search does the matching, and the DJ confirms the highlighted track by eye before loading it. The UI must never call this "Load" (drag brief §6, `plans/rekordbox-load-to-deck-2026-11/ui-design-brief.md:185`).

### 1.3 Facts in the code that shape the design
- **`Track` already has a field called `search_text`** (`source/models/track.py:25`). It is Sidecar's own lowercase search string, `f"{title} {artist} {file_name}".lower()` (`track.py:75`), used by `TrackLibrary.search`. The new value is a different thing, so it gets a different name: **paste query**. Reusing `search_text` would break Sidecar's search or confuse readers.
- **`Track` has no mix, version or remixer field** (`source/models/track.py:6-25`). rekordbox's mapping reads only `Title`, `ArtistName` and `AlbumName` (`source/providers/rekordbox/db_reader.py:140-142`; `mapping.py:16-34`). Serato reads `TIT2` and `TPE1`, first value only (`source/services/tag_reader.py:41-45`, `:130-131`). A mix name such as "(Extended Mix)" reaches Sidecar only as part of the title, which is the common tagging convention. Because D1 strips mix names, a separate mix field isn't needed.
- **For a track in rekordbox, the artist and title are rekordbox's own strings.** The merge takes rekordbox's non-empty value per field (ADR-015 D6, `docs/architecture-decisions.md:504-506`). For a Serato-only track they are the ID3 tags Serato itself reads. So the words we paste come from the fields the DJ app has indexed. With word and substring matching, **any subset of those words still matches**. That is why stripping is safe (D1): it only removes words, it never adds one.
- **`file_name` is the basename of the path** for both providers (`source/providers/rekordbox/mapping.py:19`; `source/services/tag_reader.py:92`, `:129`).
- **Clicking a suggestion row rebuilds the list.** `<Button-1>` on the row frame and on each cell label calls `_select_track` (`source/ui/suggestion_panel.py:587`, `:627`, `:643-647`). That goes to `app._on_suggestion_selected`, which adds the track to the setlist and re-renders (`source/app.py:699-704`, `:728-732`), and `set_suggestions` destroys every row (`suggestion_panel.py:524-525`). The copy control must not be one of those bound widgets.
- **The play button already proves a row button can avoid selection.** It is a `CTkButton` with a `command` and no `<Button-1>` binding (`suggestion_panel.py:592-603`). Tk delivers a click to the clicked widget's own bindtags, not its parent frame's, so the row's binding at `:627` doesn't fire. The copy button copies this pattern.
- **Quiet re-render is deferred while the pointer is over the list** (`suggestion_panel.py:466-477`, `:502-511`). A row can therefore show a track object from before a live refresh, which is exactly when the DJ's pointer is on a copy button. The app already has `_current_object(track)` for this (`source/app.py:695-697`).
- **The quiet-render signature** (`suggestion_panel.py:434-444`) includes `title`, `artist` and `full_file_path`. Everything the copy button depends on is covered by it (D5).
- **There is no clipboard code in `source/` today** (drag blueprint §1.4, `plans/rekordbox-load-to-deck-2026-11/architect-blueprint.md:55`).
- **Toasts:** `_show_toast(text, color, duration, ...)` (`source/app.py:500-534`), colours in `source/config.py:357-360`, a 75-character limit with no paths (`docs/ui-design-guide.md:154`). All user-visible strings go in `source/services/library_copy.py` (`:1-10`).

---

## 2. Decision

### Do we need an ADR? Yes, a short one, at ship time (ADR-016)
The feature is small, but two cross-cutting things need a durable record:
1. **The deck-loading question is now closed for the current ADR set.** ADR-014 records the MIDI rejection. The drag plan proposed ADR-016, and the user rejected it; keystroke automation was also rejected. Today those outcomes live only in plan folders (one of them untracked). Without an ADR entry, the next agent will propose drag or keystrokes again. ADR-014 set the precedent of recording a rejected deck-load approach.
2. **It adds a review-blocker rule:** Sidecar never synthesises input, focuses or automates another application, or sends a DJ app anything. The clipboard is passive: the DJ pastes. This rule belongs in `docs/coding-standards.md` next to the provider rules (`:51-64`).

ADR-016 is about ten lines: Context (§1.2 table), Decision (D1-D3 below in one paragraph each), Consequences. `DECK_LOAD` and `load_to_deck` stay reserved and unused. Debt #16 (`docs/architecture-overview.md:163`) is reworded so it no longer promises a "Phase 6". The text is in implementation-plan T4.1.

### D1: The paste query: a pure function in `source/services/paste_query.py`

```python
def paste_query(artist: str, title: str, file_name: str = "") -> str | None:
    """The text to paste into a DJ app's search box, or None when there is nothing to copy."""
```

It takes plain strings, not a `Track`, so the module imports nothing and is a leaf (like `comment_format.py`). The caller passes `track.artist, track.title, track.file_name`.

**Principle (user decision): less is more.** Both DJ apps find a track from any words or substrings it contains, so the query keeps the core artist and title words and drops the decorations. Every word left in the query comes from the track's own fields, so it still matches (§1.3).

**Rules (in order):**
1. **Normalise each field:** turn every run of whitespace and control characters (`\t`, `\r`, `\n`, `\x00`-`\x1f`, `\x7f`) into one space, then strip both ends. A field that is empty after this counts as missing.
2. **Strip decorations** from the artist and the title, each on its own, with one helper `_strip_decorations(s)`:
   1. **Bracketed segments:** remove every balanced `(…)`, `[…]` and `{…}` segment, innermost first, repeating until none is left (so nesting works). Examples: `(Extended Mix)`, `[Remix]`, `(feat. B)`, `{Free DL}`.
   2. **Unmatched brackets:** an opening bracket with no partner removes everything from it to the end of the field (for example a title tag cut off as `Song (Extended`). A stray closing bracket is replaced by a space, which step 4 then collapses, so it never glues two words together (`Track)One` → `Track One`).
   3. **`feat.` tail:** a standalone token `feat`, `feat.`, `ft`, `ft.` or `featuring` (any case; preceded by a space and followed by a space or the end of the field) removes itself **and everything after it**. For example `Song feat. B` becomes `Song`.
   4. **Tidy up:** collapse whitespace again, then strip leading and trailing separators and spaces. The separators are `-` `–` `—` `/` `,` `;` `:` `&` `+` `|` `~`. Separators *between* words stay (`Song - Radio Edit`): those characters are in the DJ app's own field.
   5. **Fallback:** if the result is empty (a title that is only `(Intro)`, or an artist that is only `feat. B`), use the field as normalised by rule 1, not stripped.
3. **Title present:** return `"{artist} {title}"`, or just `"{title}"` when the artist is missing. Both are stripped.
4. **Title missing, file name present:** return the file name **without its extension** (`PurePath(file_name).stem`), normalised and stripped by rules 1 and 2. The artist is **not** added. With no title tag, rekordbox and Serato typically show the file name in the title column `[A3]`, and the file name of a sparsely tagged file often already contains the artist.
5. **Title and file name missing, artist present:** return the stripped artist. This is a weak query, but it is not empty.
6. **Everything missing:** return `None`. The caller never puts an empty string on the clipboard.

In practice rule 6 cannot happen for a library track, because every track has a path and so a `file_name`. The `None` branch exists for correctness and for tests. The UI rule for it is in D4.

**Worked examples** (they become unit tests, implementation-plan T1.2):

| Artist | Title | Paste query |
|---|---|---|
| `Artist A` | `Track One (Extended Mix)` | `Artist A Track One` |
| `Artist A feat. Singer B` | `Track One` | `Artist A Track One` |
| `Artist A` | `Track One feat. Singer B [Club Mix]` | `Artist A Track One` |
| `Artist A` | `Track One (Original Mix) - Radio Edit` | `Artist A Track One - Radio Edit` |
| `Artist A & Artist B` | `Track One` | `Artist A & Artist B Track One` |
| `Artist A` | `(Intro)` | `Artist A (Intro)` (fallback, rule 2.5) |
| `Artist A (UK)` | `Track One` | `Artist A Track One` |
| `Artist A` | `Track)One` | `Artist A Track One` (stray closing bracket becomes a space, rule 2.2) |
| *(empty)* | *(empty)*, file `Artist A - Track One (Extended Mix).mp3` | `Artist A - Track One` |

**Choices made inside the rule, and why:**

| Question | Decision | Reason |
|---|---|---|
| Strip `feat.` from the **artist** as well as the title? | **Yes** | `A feat. B` → `A`. The featured artist is a decoration in the same sense, and `A` is still in the DJ app's artist field, so it matches. The rule is the same for both fields, which keeps it simple to explain and test |
| Split collaborations (`A & B`, `A, B`, `A x B`, `A vs. B`)? | **No** | These are often one act's name (`Chase & Status`-style duos). Cutting at `&` would turn a precise query into a vague one. Only the explicit `feat.`/`ft.`/`featuring` marker is cut |
| Separator between artist and title | **One space**, never `" - "` (`Track.display_name` uses ` - `, `track.py:100-103`) | A space adds nothing. A lone `-` is an extra word that might not match `[A1]` |
| Punctuation inside words (`'`, `&`, `.`, `!`) | **Kept** | It is part of the indexed field. Removing it could split or merge words |
| Case, NFC/NFD | **Unchanged** | Keep the DJ app's own string. DJ app searches are expected to be case-insensitive `[A2]` |
| Strip the file-name fallback too | **Yes** | File names often carry `(Extended Mix)` or `[Label]`. Same rule, same reason |
| Length cap | **No** | Titles are short. The toast truncates for display only (D3) |

**Consequence the user accepted:** an original and its extended mix now give the same query, so the DJ app lists both and the DJ picks by eye (R1).

**The format is a single function, so changing it is a small change.** If the Phase 0 paste check (§5) shows a problem, only `paste_query` and its tests change.

### D2: Clipboard mechanism: Tk's own clipboard, no new dependency

A new tiny UI-layer helper, `source/ui/clipboard.py`:

```python
def copy_to_clipboard(widget: tk.Misc, text: str) -> bool:
    """Replace the OS clipboard with ``text``. Tk thread only. False if Tk refused."""
```

It calls `widget.clipboard_clear()` and then `widget.clipboard_append(text)`. It catches **`tk.TclError` only**, logs `type(e).__name__` at WARNING, and returns `False` (`docs/coding-standards.md:39-43`). It **never logs the text** above DEBUG, because track titles are library data (`docs/coding-standards.md:64`). It lives in `ui/` because it calls Tk, and `services/` has no UI imports (`docs/architecture-overview.md:71`).

Why not `pyperclip` or a native API: Tk already owns a clipboard implementation on every target platform. A new dependency means a new packaging and licence check (ADR-008) for no gain.

**`update()`: do not call it.** The common advice to call `root.update()` after `clipboard_append` is for short scripts that destroy the Tk root straight after copying. Sidecar keeps its main loop running, and that loop serves the clipboard to other applications (below). `update()` inside a button handler also processes queued input events: a second click, the `_drain_ui_queue` pump (`source/app.py:202-215`) or a quiet re-render could then run in the middle of the handler. If manual check M2 shows the first paste coming up empty, add `update_idletasks()`, which doesn't process input events. Do not add `update()`.

**Cross-platform behaviour.** These points come from my reading of how Tk 8.6 implements its clipboard. I have not run them on a real machine for this plan, so each is an assumption that the manual checklist verifies.

| | Windows (shipped) | macOS (built, unverified) | Linux (dev only) |
|---|---|---|---|
| How Tk publishes the text | Takes ownership of the Windows clipboard and uses **delayed rendering**: the text is handed over when another app asks for it (`WM_RENDERFORMAT`), serviced by Sidecar's Tk event loop `[A4]` | Declares the text on the general `NSPasteboard`, possibly provided lazily on request `[A5]` | X11 `CLIPBOARD` selection, owned by Sidecar |
| Focus moves to rekordbox/Serato, DJ pastes | Works. The paste is served by Sidecar's running main loop `[A4]` | Expected to work while Sidecar runs `[A5]` | Works while Sidecar runs |
| Sidecar is busy when the DJ pastes | The paste waits until Sidecar's Tk thread is free. Sidecar's longest normal Tk work is a 60-row re-render (`source/config.py:342`), so the wait is a fraction of a second | Same, if the data is lazy | Same |
| Sidecar is closed after copying | Tk renders all formats on shutdown (`WM_RENDERALLFORMATS`), so the text should survive `[A4]` | May be lost on quit if the data was lazy `[A5]` | Lost unless a clipboard manager holds it |
| Sidecar crashes or is killed after copying | The text is lost. Acceptable: Sidecar runs for the whole set | Same | Same |
| Another app has the clipboard open at that moment (clipboard managers, remote desktop) | Tk may fail silently, without raising `TclError` `[A6]`. The DJ then pastes old text and the search finds the wrong track or none. The DJ sees this in the DJ app before loading (R2) | Not expected | n/a |
| Characters outside the Basic Multilingual Plane (emoji) | Tk 8.6 support is incomplete; such characters may paste as `?` or be dropped `[A7]`. Rare in DJ metadata. The other words still match, because the searches match words and substrings | Same | Same |

**Threading:** the click arrives on the Tk thread, and the copy runs there. No new thread (ADR-001).

### D3: Where the logic lives, and the call path

```
SuggestionPanel row [copy] ──command──▶ on_copy(track) -> bool  (panel callback, no services;
                                            │                    the CopyButton shows its copied/failed
                                            │                    state from the bool)
app.DJTrackSelectorApp._copy_track_text(track) -> bool
   track = self._current_object(track)                           # app.py:695-697 (fresh after a live refresh)
   text  = paste_query(track.artist, track.title, track.file_name)
   text is None        → return False, no toast (the button is disabled anyway; D4)
   copy_to_clipboard(self, text)
       True  → _show_toast(copy.format_copied_toast(text), SUCCESS_COLOR, duration=SHORT_TOAST_MS); return True
       False → _show_toast(copy.COPY_FAILED, ERROR_COLOR); return False
```

- **The panel gets a callback** (`on_copy`), as it does for `on_select` (`source/app.py:152-157`; `docs/coding-standards.md:68`). The action (clipboard, toast) is the app's, and the panel never imports the clipboard helper.
- **The panel may import `paste_query`** to decide whether the button is enabled and to give the tooltip its preview (D4: `paste_query(...) is not None`). It is a pure, import-free function, and `suggestion_panel.py` already imports pure services (`:11-13`), so this is not a new layering exception. The alternative, a `can_copy` callback from the app, adds a parameter for a state that practically never occurs. Decision: direct import.
- **The copy changes no Sidecar state.** It does not select the track, add it to the setlist, stop the audio preview, re-score or re-render. A DJ can preview a suggestion, copy it, paste it, and keep listening.
- **No provider involvement.** There is no capability flag and no provider-id branching (`docs/coding-standards.md:56`). The query uses only `Track` fields, which are provider-neutral.
- **The success toast shows the exact text that was copied** (the stripped query), so the DJ can see what they're about to paste. `library_copy.format_copied_toast(text)` truncates it so the whole toast stays within 75 characters. `library_copy` is a services module and cannot import `ui/utils.truncate` (`source/ui/utils.py:1-3`), so it truncates with its own two-line rule. That is a small, deliberate duplicate; note it under debt #4.

### D4: Placement and states (revised by the ui-designer; full detail in `ui-design-brief.md`)

| Surface | v1? | Notes |
|---|---|---|
| **Suggestion rows** | **Yes (user decision)** | New **leftmost** column. Data columns shift right by one. Rightmost would be invisible at the 1000x650 minimum window, because the grid is about 650 px wide and already clips (drag brief §0.4, `plans/rekordbox-load-to-deck-2026-11/ui-design-brief.md:15`) |
| Now Playing dashboard (`source/ui/track_detail.py`) | **No (user decision)** | "If it's now playing then I probably already have it in the software." Out of scope. If it's ever wanted, it is the same `on_copy` callback |
| Setlist rows (`source/ui/session_panel.py:106-136`) | Not in v1 | Re-loading an already-played track is rare. Adding it later is the same callback |
| Search dropdown rows (`track_detail.py:238-276`) | No | They select on press; needs its own design |

**Suggestion-row button, architectural constraints** (the look, glyph and width are the ui-designer's):
- A `CTkButton` with `command=lambda t=track: self._on_copy(t)`, built like the play button (`source/ui/suggestion_panel.py:594-601`). **It must not get a `<Button-1>` binding** and must not be added to the hover list at `:615-624` with anything that selects.
- A width constant `_COL["copy"]` (`:82-86`), not an inline number (`docs/coding-standards.md:71`). **`_COL["copy"] = 36`** (ui-designer, brief §3.1, §3.4): the button is 36 x 28, and the column takes 44 px with its padding. The estimate is that Key stays visible at 1000x650; M8 measures it. The first-column left padding rule `6 if col == 0 else 2` (`:169`, `:585`) moves to the copy column, so the existing cells keep their spacing.
- Header cell: the word **`Copy`** (`HEADER_COPY`, 10 bold), at width `_COL["copy"]` (brief §3.2, O7). Not blank, because the icon-only button has no label of its own.
- The column is always present. It does not depend on audio, providers or settings, so the header and rows never jump between renders.
- **Look:** a `CopyButton` widget (`source/ui/copy_button.py`, new), 36 x 28, font size 14. Glyphs `❐` (ready), `✓` (copied), `✕` (failed), `—` (disabled); fills `#2a2a2a`, `#1f6aa5` on hover, `#28a745`, `#dc3545`; existing tokens only (brief §3.1). The glyph choice is gated by a render check (plan T3.0a).
- **Icon-only means the tooltip carries the words.** The button has no visible text, so its tooltip (`format_copy_tooltip(query)`, D6) is how the DJ learns what it does and what it will copy. A disabled button keeps its `COPY_NOTHING` tooltip.
- **No-query state (D1 rule 6):** the button is rendered **disabled** (`state="disabled"`), not omitted, so the columns stay aligned, with tooltip `COPY_NOTHING`. In practice this state never appears.

**Feedback (decided; brief §5):**
- The button itself confirms: a copied state on a green fill, or a failed state on a red fill, for 1.5 s after the **last** click (the brief sets the glyph or label for each). Every click restarts the timer; only one button in the app shows the copied state at a time; the timer is cancelled when the button is destroyed (a re-render destroys rows, `suggestion_panel.py:524-525`). The tooltip is hidden on click.
- This needs the outcome: `on_copy` and `_copy_track_text` **return `bool`** (`True` = on the clipboard).
- Success toast: green (`SUCCESS_COLOR`, `source/config.py:357`) for `SHORT_TOAST_MS` (`source/app.py:48`) showing the copied text. Each click replaces the previous toast (`app.py:515-517`). With an icon-only button, the toast is also the clearest confirmation of *what* was copied.
- Failure (`copy_to_clipboard` returns `False`): a red toast `COPY_FAILED`.

### D5: Re-render safety
- Copying doesn't call `_select_track`, `set_suggestions` or `_update_suggestions`, so the list is not rebuilt. `_show_toast` only reconfigures the top-bar label (`source/app.py:520`).
- **No signature change** (`source/ui/suggestion_panel.py:434-444`). The button's variable state (enabled or disabled, tooltip text) depends on `title`, `artist` and `file_name`. `title` and `artist` are in the signature, and `file_name` is the basename of `full_file_path` (§1.3), which is too. A live refresh that changes a title re-renders the row as it does today.
- **A stale row copies fresh text.** When the pointer is over the list, a quiet re-render is deferred (`:475-477`). The row can show a pre-refresh `Track` while the DJ clicks copy. The app resolves the current object first (`_current_object`, `source/app.py:695-697`), so the clipboard gets the refreshed artist and title. The toast shows what was actually copied, so a visible mismatch with the stale row is self-explaining. If the track has left the library, the row's own object is used.

### D6: Strings (all in `source/services/library_copy.py`; set by the ui-designer, brief §8)

| Constant / function | Text | Rule |
|---|---|---|
| `BUTTON_COPY` | `"❐"` (❐), the ready glyph | Never "Load". Fallback ladder in brief §3.3 |
| `BUTTON_COPIED` | `"✓"` (✓), shown for 1.5 s after a good copy | |
| `BUTTON_COPY_FAILED` | `"✕"` (✕), shown for 1.5 s after a failed copy | |
| `BUTTON_COPY_DISABLED` | `"—"` (—) | The disabled glyph, so disabled differs by shape and not only by dimness |
| `HEADER_COPY` | `Copy` | Column header |
| `format_copied_tooltip(query)` | `Copied:` / the query / `Now paste it into your DJ software's search box.` | Tooltip during the 1.5 s copied state |
| `COPY_FAILED_TOOLTIP` | `Couldn't copy. Click to try again.` | Tooltip during the failed state |
| `format_copy_tooltip(query)` | Three lines: `Copy to the clipboard:` / the query / `Then paste it into your DJ software's search box.` | The middle line is the exact (stripped) text, so the tooltip is the preview. Provider-neutral, so no provider branching and no rule #2 problem. Named providers are brief O5; if chosen, build the names from the enabled providers' `display_name`s, never from literal ids |
| `COPY_NOTHING` | `Nothing to copy: this track has no artist or title` | Disabled-button tooltip |
| `format_copied_toast(text)` | `Copied "{text}"`, with `text` truncated with `…` so the whole toast is at most 75 characters (`text` at most 66) | `docs/ui-design-guide.md:154`. The file-name fallback (D1 rule 4) is a file name, not a path, so the "no paths" rule holds |
| `COPY_FAILED` | `Couldn't copy to the clipboard. Try again.` | Red toast |

`COPY_TOOLTIP` (the old single-line constant) is replaced by `format_copy_tooltip`.

---

## 3. Component design

```
services/paste_query.py   paste_query(artist, title, file_name) -> str | None     (NEW, pure, stdlib only)
services/library_copy.py  BUTTON_COPY/COPIED/COPY_FAILED, COPY_NOTHING, COPY_FAILED, format_copy_tooltip, format_copied_toast
ui/clipboard.py           copy_to_clipboard(widget, text) -> bool                (NEW, Tk only)
ui/copy_button.py         CopyButton: glyph/colour states, 1.5 s timer, one "copied" at a time   (NEW, ui-designer)
ui/tooltip.py             public Tooltip.hide()                                                  (tiny change)
ui/suggestion_panel.py    on_copy callback; leftmost copy column
app.py                    _copy_track_text(track); passes on_copy to the suggestion panel
```

Layering is unchanged: `ui → app → services`. `paste_query` imports only the standard library. `clipboard.py` is a UI leaf.

---

## 4. Affected files

| File | Change |
|---|---|
| `source/services/paste_query.py` | **New.** D1 |
| `source/services/library_copy.py` | New strings and `format_copied_toast` (D6), in a new `# ── Copy search text ──` section after the toasts (`:299-334`) |
| `source/ui/clipboard.py` | **New.** D2 |
| `source/ui/copy_button.py` | **New** (ui-designer). `CopyButton`; brief §3, §5 |
| `source/ui/tooltip.py` | Public `hide()` (the click must dismiss the tooltip; `_hide` is private, `:36`) |
| `source/ui/suggestion_panel.py` | `on_copy` parameter (`:92-103`); `_COL["copy"]` (`:82-86`); header cell at index 0 (`:154-169`); copy button at column 0 and cells shifted by one (`:565-613`) |
| `source/app.py` | Imports (`:11-41`); `_copy_track_text` beside `_current_object` (`:695-697`); pass `on_copy` at `:152-157` |
| `tests/services/test_paste_query.py` | **New** |
| `tests/services/test_library_copy.py` | Extended |
| `tests/ui/test_clipboard.py`, `tests/ui/test_suggestion_copy.py`, `tests/ui/test_app_copy_track.py` | **New** |
| `docs/architecture-decisions.md` | ADR-016 (short); ADR-015 D12 sentence "Phase 6 needs its own ADR" points to ADR-016 |
| `docs/architecture-overview.md` | Services/UI tables (`:70-104`); debt #16 (`:163`) reworded; debt #4 notes the `library_copy` truncation |
| `docs/coding-standards.md` | New rule: no input synthesis or app automation |
| `docs/cross-platform-guide.md` | New "Clipboard" section (the D2 table, with verified results) |
| `docs/testing-strategy.md` | Coverage and the manual checklist |
| `docs/ui-design-guide.md` | The ui-designer's updates (new control, strings) |
| `README.md` | One sentence on how to use the copy button |
| `CLAUDE.md` | Project tree: `paste_query.py`, `clipboard.py`, `copy_button.py` |

**Not changed:** `source/ui/track_detail.py` (no Now Playing control in v1), providers, models, config, packaging, CI and `requirements.txt`.

---

## 5. Phases (detail in `implementation-plan.md`)

| Phase | What | Visible? |
|---|---|---|
| **0** | 10-minute manual paste check in rekordbox and Serato. No code. It confirms the stripped query finds the track (D1) | No |
| **1** | `paste_query`, strings, unit tests | No |
| **2** | Clipboard helper, `app._copy_track_text`, tests | No |
| **3** | Suggestion-row copy column, UI tests, manual checklist | **Yes** |
| **4** | Docs, ADR-016, coding-standard rule | No |

Phase 0 does not block Phases 1-2 (the function is cheap to change), but its result must be in before Phase 3 merges.

---

## 6. Risks and open questions

### Assumptions the user should sanity-check (Phase 0 and the manual checklist)
- **[A1] Both DJ apps match words and substrings** across the searchable fields, in any order. **The user has confirmed this** for rekordbox and Serato; Phase 0 only spot-checks it with stripped queries. It is the basis of D1.
- **[A2] Both searches are case-insensitive** and treat punctuation in the query literally (no operators such as quotes or minus signs).
- **[A3] An untagged file shows its file name (without extension) as the title** in rekordbox and Serato, so the file-stem fallback matches.
- **[A4] Windows:** Tk serves the clipboard through delayed rendering from the running main loop, and renders it on clean shutdown.
- **[A5] macOS:** pasting works while Sidecar runs. Whether it survives quitting Sidecar is unknown and unimportant.
- **[A6] Windows:** a clipboard held open by another process can make Tk's copy fail without raising an error.
- **[A7] Emoji and other non-BMP characters** may not survive Tk 8.6's clipboard.

### Risks
- **R1 (medium, product, accepted): the search lists several versions.** Mix names are stripped (D1), so an original, an extended mix and a remix with the same artist and title give the same query. The DJ app lists all of them and the DJ picks the right one by eye. The user accepted this ("less is more"). It is inherent to the clipboard route and is why the UI never says "Load".
- **R2 (low): the copy fails silently** (`[A6]`) and the DJ pastes old text. Mitigation: the DJ app's search result is visibly wrong, so the DJ notices before loading. `TclError` failures show a red toast.
- **R3 (low): merged tracks pasted into Serato.** A track in both libraries shows rekordbox's artist and title (merge precedence). If the DJ edited them in rekordbox but not in the file tags, Serato's search may not find them. Stripping lowers this risk: edits to mix names or credits no longer matter. A per-app query would need provider-specific values, which `Track` doesn't keep. Not in v1.
- **R4 (low): the copy toast replaces a more important toast**, such as an amber refresh failure with an `Open settings` button (`source/app.py:447-452`). The DJ asked for the copy, so their own action wins. The ui-designer may decide otherwise.
- **R5 (low): one more column at the minimum window.** The copy column pushes the data columns right by its width, so at 1000x650 more of the right-hand columns clip. Icon-only keeps the column narrow; the ui-designer set the width at 36 px, and manual check M8 measures the result.
- **R6 (low): clipboard history and sync.** Windows clipboard history (Win+V) and cloud clipboard sync will keep the copied artist and title. This is normal OS behaviour for any copy. Worth one line in the README, no code.
- **R7 (low): an over-eager `feat` match.** A title with a standalone word `Ft` or `Featuring` that isn't a credit loses its tail. With word and substring matching, the shorter query still finds the track, just with more results. Accepted.

### Open questions (for the user, via the orchestrator)
- **O1: The brief's UI questions are closed** (brief §9): glyph, width, states and the O3-O7 defaults are decided. One check remains: the glyph render check (plan T3.0a), because the glyphs could not be rendered at design time.
- **O2: Phase 0 result.** If a stripped query unexpectedly fails to find a track in one of the apps, should the function keep more of the title for that case?
- **O4: Keyboard shortcut.** Not in v1. A global `Ctrl+C`/`Cmd+C` binding would clash with copying from the search box, and keyboard handling is known debt (`docs/ui-design-guide.md` §7.6).
- **O5: The rejected drag plan folder** `plans/rekordbox-load-to-deck-2026-11/` is untracked. Archive it with a "Rejected" status line, as was done for the MIDI plan? This plan doesn't touch it.

(O3, about mix names in a separate field, is closed: mix names are stripped, so no mix field is needed. O1 about Now Playing is closed: not in v1.)

---

## User decisions applied (2026-11-06)

1. **The query is stripped** ("Less is more. It will find things that contain the word"). D1 changed from verbatim to stripped: bracketed segments removed; an unbracketed `feat.`/`ft.`/`featuring` tail removed from the title **and** the artist; leftover whitespace and dangling separators tidied; if the stripped field is empty, the unstripped field is used. The mix-name open question (old O3) is closed. R1 is now accepted behaviour, and R7 was added.
2. **The button is icon-only.** The ui-designer sets the glyph and width. The architectural text no longer assumes the word "Copy" on the button or a fixed width; `_COL["copy"]` still exists as a named constant.
3. **No Now Playing control in v1.** It is out of scope (D4); `source/ui/track_detail.py` isn't changed.
