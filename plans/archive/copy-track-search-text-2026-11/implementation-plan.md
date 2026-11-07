# Implementation Plan: Copy a track's search text

> **Companion:** `architect-blueprint.md` (same folder). Decisions are referenced as D1-D6, assumptions as `[A#]`, risks as R#.
> **Paths:** all code is under `source/`. Line numbers are from `main` at `3f15727`; re-check them if the files have moved on.
> **Rule for every phase:** `python -m pytest` is green before the phase is called done. Synthetic data only in tests (`docs/testing-strategy.md:17`): invented artists and titles, never anything from the user's library.
> The ui-designer has revised T1.3, T1.4, T2.3, T2.4 and Phase 3 (new T3.0 and T3.1). See `ui-design-brief.md` and "UI revisions applied" below. The user's answers (stripped query, icon-only button, no Now Playing) are applied; see "User decisions applied" at the end.

---

## Phase 0: Manual paste check (no code, about 10 minutes)

The user runs this on their Windows machine, in rekordbox 7.2.19 and in Serato DJ, before Phase 3 merges. The user has already said both apps match words and substrings (`[A1]`), so this only spot-checks the **stripped** query from D1 and `[A3]`. Pick about five tracks that cover the cases below. **Type** each query exactly as D1 would produce it; nothing in Sidecar is needed yet.

| # | Track | Query to type into the DJ app's search | Expected (D1) |
|---|---|---|---|
| P1 | A plain track | `<artist> <title>` (one space) | Highlights the track |
| P2 | A track whose title has a mix name, e.g. `Song (Extended Mix)`, where the original is also in the library | `<artist> Song` | Both versions are listed (accepted, R1) |
| P3 | An artist field with `feat. X`, or a title ending in `feat. X` | the artist and title with the `feat.` part removed | Highlights the track |
| P4 | Accented characters (`é`, `ü`) | verbatim | Highlights the track |
| P5 | A file with no title tag (if there is one) | the file name without `.mp3` and without any bracketed part | Highlights the track (`[A3]`) |

Record results below (no real titles or artists: write "P1 rekordbox: found" and so on).

**Decision rule:**
- P1-P4 pass in both apps → keep D1 as written.
- One of them fails → report it to the architect before Phase 3 (blueprint O2). Only `paste_query` and its tests would change.
- P5 fails → drop D1 rule 4 and fall back to the artist, or keep it and note it. Low stakes.

### Phase 0 findings
_(to be filled in by the user or orchestrator)_

---

## Phase 1: The paste query and its strings (pure, no UI)

**T1.1 Create `source/services/paste_query.py`** (D1).
- Module docstring: what the paste query is, the "less is more" principle, and that it is **not** `Track.search_text` (`source/models/track.py:25`, `:75`), which is Sidecar's own search haystack.
- Imports: `re`, `pathlib.PurePath` only.
- `_clean(s: str) -> str`: replaces runs of whitespace and control characters (`[\s\x00-\x1f\x7f]+`) with one space and strips the ends (rule 1).
- `_strip_decorations(s: str) -> str` (rule 2), in this order:
  1. Remove balanced `(…)`, `[…]`, `{…}` segments: apply `re.sub(r"\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}", " ", s)` in a loop until the string stops changing (handles nesting).
  2. Unmatched brackets: cut from the first remaining `(`, `[` or `{` to the end; then replace any remaining `)`, `]`, `}` with a space (collapsed in step 4), so words are never glued together.
  3. `feat.` tail: `re.sub(r"(?i)(?:^|\s)(?:feat|ft)\.?(?=\s|$).*$|(?:^|\s)featuring(?=\s|$).*$", "", s)`, or one equivalent pattern. Take care that `Aft`, `Left` and `Feather` do not match (standalone token only).
  4. `_clean` again, then strip leading and trailing separators and spaces: `s.strip(" -–—/,;:&+|~")`.
  5. If the result is empty, return the `_clean`ed input unchanged (rule 2.5).
- `paste_query(artist: str, title: str, file_name: str = "") -> str | None`: `_clean` each field, apply `_strip_decorations` to the artist, the title and the file stem (`PurePath(file_name).stem`), then rules 3-6 of D1. Use `PurePath`, not `Path`: no file system access.
- Put the separator set and the patterns in module-level named constants (`docs/coding-standards.md:71`).
- Type hints on the public function (`docs/coding-standards.md:25`).

**T1.2 Create `tests/services/test_paste_query.py`.** Use invented names. Name tests `test_<what>_<condition>_<expected>` (`docs/coding-standards.md:101`). Parametrise the cases below.

*Basic shape*
- artist and title → `"Artist A Track One"`
- title only → `"Track One"`
- artist only, no title, no file name → `"Artist A"`
- all empty → `None`; whitespace-only fields (`"  "`, `"\t"`) are treated as empty → `None`
- tabs, newlines, `\x00` and repeated spaces inside a field collapse to one space; ends stripped
- the function adds no hyphen: `paste_query("A", "B") == "A B"`
- case and accented characters are kept

*Stripping, title* (rule 2)
- `"Track One (Extended Mix)"` → `"Track One"`
- `"Track One [Remix]"` and `"Track One {Free DL}"` → `"Track One"`
- `"Track One (feat. Singer B)"` → `"Track One"`
- nested: `"Track One (Mix (Edit))"` → `"Track One"`
- two segments: `"Track One (Original Mix) [Label]"` → `"Track One"`
- unbracketed tail: `"Track One feat. Singer B"`, `"Track One ft Singer B"`, `"Track One Ft. Singer B"`, `"Track One featuring Singer B"` → `"Track One"`
- tail plus brackets in either order: `"Track One feat. Singer B [Club Mix]"` and `"Track One (Club Mix) feat. Singer B"` → `"Track One"`
- not a credit: `"Aftermath"`, `"Left Feather"` are unchanged (standalone-token rule)
- inner separator kept: `"Track One (Original Mix) - Radio Edit"` → `"Track One - Radio Edit"`
- dangling separator removed: `"Track One - (Original Mix)"` → `"Track One"`; `"Track One / [Edit]"` → `"Track One"`
- unmatched opening bracket: `"Track One (Extended"` → `"Track One"`; stray `)` becomes a space: `"Track One)"` → `"Track One"` and `"Track)One"` → `"Track One"` (never `"TrackOne"`)
- **fallback:** `"(Intro)"` → `"(Intro)"`; `"feat. Singer B"` → `"feat. Singer B"` (stripping would leave nothing)
- punctuation inside words kept: `"Don't Stop!"` → `"Don't Stop!"`

*Stripping, artist* (rule 2, same helper)
- `"Artist A feat. Singer B"` → `"Artist A"`; `"Artist A ft. Singer B"` → `"Artist A"`
- `"Artist A (UK)"` → `"Artist A"`
- collaborations kept: `"Artist A & Artist B"`, `"Artist A, Artist B"`, `"Artist A x Artist B"`, `"Artist A vs. Artist B"` are unchanged
- combined: artist `"Artist A feat. Singer B"`, title `"Track One (Extended Mix)"` → `"Artist A Track One"`

*File-name fallback* (rule 4)
- empty title, file name `"Artist A - Track One.mp3"` → `"Artist A - Track One"` (no artist prefix)
- empty title, file name `"Artist A - Track One (Extended Mix).mp3"` → `"Artist A - Track One"` (stripped)
- file name with several dots: `"a.b.c.flac"` → `"a.b.c"` (only the last extension is removed, as `PurePath.stem` does)

Every row of the worked-examples table in blueprint D1 must appear as a case.

**T1.3 Add strings to `source/services/library_copy.py`** (D6; exact text in `ui-design-brief.md` §8).
- New section `# ── Copy search text ──` after the toast formatters (`source/services/library_copy.py:299-334`).
- Glyph constants, written as `\u` escapes (as the play button does, `suggestion_panel.py:595`): `BUTTON_COPY = "❐"` (❐), `BUTTON_COPIED = "✓"` (✓), `BUTTON_COPY_FAILED = "✕"` (✕), `BUTTON_COPY_DISABLED = "—"` (—). If gate G (T3.0a) fails, follow the fallback ladder in brief §3.3; only these constants change.
- `HEADER_COPY = "Copy"` (the column header).
- `COPY_NOTHING` (`Nothing to copy: this track has no artist or title`), `COPY_FAILED` (`Couldn't copy to the clipboard. Try again.`), `COPY_FAILED_TOOLTIP` (`Couldn't copy. Click to try again.`).
- `format_copy_tooltip(query: str) -> str`: three lines joined with `\n`: `Copy to the clipboard:`, the query unchanged, `Then paste it into your DJ software's search box.` (no `COPY_TOOLTIP` constant). The button is icon-only, so this tooltip is its label.
- `format_copied_tooltip(query: str) -> str`: `Copied:`, the query unchanged, `Now paste it into your DJ software's search box.` (shown only if the DJ re-hovers during the 1.5 s copied state).
- `COPIED_TOAST_MAX = 75` and `format_copied_toast(text: str) -> str`: `f'Copied "{shown}"'`, where `shown` is `text` cut to fit (`text[:n-1] + "…"` when too long), so the whole result is at most `COPIED_TOAST_MAX` characters. A comment explains why this doesn't use `ui/utils.truncate` (`source/ui/utils.py:1-3`): services can't import ui (blueprint D3).

**T1.4 Extend `tests/services/test_library_copy.py`.**
- A short text is shown in full, inside quotes.
- A 200-character text gives a toast of exactly 75 characters, ending `…"`.
- Boundary: a text of exactly 66 characters is not truncated; 67 is.
- `COPY_FAILED` is at most 75 characters. None of the new strings contains the word "Load" (a guard against drift; the blueprint and the drag brief both forbid it), including the tooltip with a query that has none.
- `format_copy_tooltip("Artist A Track One")` has the query as its exact second line, and the query is not altered or truncated.
- `BUTTON_COPY`, `BUTTON_COPIED`, `BUTTON_COPY_FAILED` and `BUTTON_COPY_DISABLED` are each a single character and all four are distinct (state is never colour alone). None is an emoji-presentation or non-BMP character: every code point is below `0x10000`.
- `format_copied_tooltip("Artist A Track One")` has the query as its exact second line.

**Done when:** both test files are green; nothing imports the new module yet.

---

## Phase 2: Clipboard helper and the app action

**T2.1 Create `source/ui/clipboard.py`** (D2).
- `copy_to_clipboard(widget: tk.Misc, text: str) -> bool`: `widget.clipboard_clear()`, `widget.clipboard_append(text)`, return `True`.
- `except tk.TclError as e:` log `logger.warning("Clipboard copy failed (%s)", type(e).__name__)` and return `False`. No other exception types; no bare `except` (`docs/coding-standards.md:39-43`).
- **Never** log `text` above DEBUG (`docs/coding-standards.md:64`). Simplest: don't log it at all.
- **No `update()` call.** Add a comment pointing to blueprint D2 so nobody adds the "usual" `root.update()` later. `update_idletasks()` only if manual check M2 needs it.

**T2.2 Create `tests/ui/test_clipboard.py`.**
- Use the skip-without-display root fixture pattern from `tests/ui/test_suggestion_quiet.py:18-26`.
- Round trip: `copy_to_clipboard(root, "Artist A Track One")` returns `True` and `root.clipboard_get() == "Artist A Track One"`. Note in a comment that this reads Tk's own copy, not the OS clipboard; the OS side is manual check M1.
- A second copy replaces the first (no appending): copy `"one"`, then `"two"` → `clipboard_get() == "two"`.
- Failure path: a stub widget whose `clipboard_clear` raises `tk.TclError` → returns `False`, logs one WARNING whose message does not contain the text (`caplog`).

**T2.3 Add `DJTrackSelectorApp._copy_track_text(self, track: Track) -> bool`** (`True` only when the text reached the clipboard; the `CopyButton` uses it to show its copied or failed state) in `source/app.py`, in the "Track selection" section beside `_current_object` (`source/app.py:695-697`). Follow D3:
1. `track = self._current_object(track)` (fresh after a live refresh, blueprint D5).
2. `text = paste_query(track.artist, track.title, track.file_name)`; return `False` if `None` (no toast).
3. `copy_to_clipboard(self, text)`; on `True`, `self._show_toast(copy.format_copied_toast(text), SUCCESS_COLOR, duration=SHORT_TOAST_MS)` (`app.py:48`, `:500-534`) and return `True`; on `False`, `self._show_toast(copy.COPY_FAILED, ERROR_COLOR)` and return `False`.
4. It must **not** touch `_current_track`, the dashboard, `session_panel`, the audio player or the suggestion panel. Add a one-line docstring saying so (user decision: copying doesn't select or add to the setlist).
- Imports: `from source.services.paste_query import paste_query` and `from source.ui.clipboard import copy_to_clipboard`, in the existing import blocks (`source/app.py:24-41`).

**T2.4 Create `tests/ui/test_app_copy_track.py`.** Use the stub-`self` pattern from `tests/ui/test_app_deck_load_gate.py:28-42`, so no window is built.
- The stub has `library` (a `TrackLibrary` or a stub with `track_by_path`), `_current_object` bound to the real method, and a recording `_show_toast`. Monkeypatch `app_module.copy_to_clipboard` with a recorder that returns `True` or `False`.
- Success: the recorder gets `"Test Artist Track 1"` (from `make_track`, `tests/conftest.py:52-63`); one green toast whose text starts with `Copied "`; the method returns `True`.
- Stripped text reaches the clipboard: a track titled `"Track One (Extended Mix)"` → the recorder gets `"Test Artist Track One"`, and the toast shows the same text.
- Fresh object: the library holds an updated `Track` for the same path with a new title → the **new** title is copied.
- Track no longer in the library → the row's own object is copied.
- Failure: the recorder returns `False` → one red toast with `COPY_FAILED`; the method returns `False`.
- `None` query (all fields empty) → no clipboard call, no toast, returns `False`.
- No side effects: the stub has `session_panel`, `dashboard` and `suggestion_panel` as `Mock()`s, and none of them is called.

**Done when:** green; still nothing visible.

---

## Phase 3: UI (revised by the ui-designer; look, glyph, width, states and strings in `ui-design-brief.md`)

Suggestion rows only. There is no Now Playing control in v1 (user decision; see "Not in scope").

**T3.0a Gate G: glyph render check (5 minutes, on the user's Windows machine, before T3.1).** I could not render glyphs when designing this, so the glyph choice is unverified. Run a scratch Tk/CTk window (not committed) showing `❐`, `✓`, `✕`, `—` at font size 14 on a `#2a2a2a` tile, at 100% and 150% Windows scaling, beside the existing `▶` and the setlist `✕`. Pass = each is a recognisable symbol (no empty box, no `?`), and `❐` looks about as heavy as `▶`. On failure follow the fallback ladder in brief §3.3 (constants only for the first two rungs). Record the result here: **Passed (2026-11-06, engineer, Windows dev machine).** A scratch CTk window rendered `❐` `✓` `✕` `—` plus the fallbacks `⧉` and `□` as 36 x 28 buttons (font size 14, no family; state fills `#2a2a2a`/`#28a745`/`#dc3545`), beside reference copies of the `▶` play and `✕` remove buttons, at CTk widget scaling 100% and 150%, captured with PIL `ImageGrab`. Every glyph rendered as a recognisable symbol (no tofu box, no `?`, no emoji colour), `❐` reads at about the weight of `▶`, and all fit the tile. `❐` kept; no fallback rung needed. Not covered: real Windows 150% *display* scaling (CTk scaling only), which stays manual check M11.

**T3.0 `Tooltip`: add a public `hide()`** (`source/ui/tooltip.py:36`). It does what `_hide` does, with no event argument needed. The copy click calls it, so the tooltip does not sit over the next row and contradict the copied state (brief §10 risk 3). Keep `_hide` as the `<Leave>` handler. Test: `tests/ui/` with a live root; `hide()` cancels a pending show and destroys a shown tip.

**T3.1 Create `source/ui/copy_button.py` with `CopyButton`** (a `ctk.CTkButton` subclass or a thin wrapper; the engineer's choice). Keeping it as its own widget keeps the state logic out of the panel and leaves it ready for any later surface (brief §2). Behaviour:
- **Icon-only.** Size 36 wide x 28 tall, corner radius 6, font size 14 with no family set (Tk falls back to a symbol font; `✓` and `✕` bold). Put them in module constants. There is only the row style in v1.
- Four looks, all from existing tokens (brief §3.1); each has its own glyph, so none relies on colour alone:
  - **ready** `BUTTON_COPY`: fill `#2a2a2a`, glyph `#999999`; hover fill `#1f6aa5`, glyph `#ffffff`.
  - **copied** `BUTTON_COPIED`: fill and hover fill `#28a745`, glyph `#ffffff`.
  - **failed** `BUTTON_COPY_FAILED`: fill and hover fill `#dc3545`, glyph `#ffffff`.
  - **disabled** `BUTTON_COPY_DISABLED`: fill `#2a2a2a`, `text_color_disabled` `#555555`, no hover change.
- **Tooltip follows the state:** ready → `format_copy_tooltip(query)`; for the 1.5 s after a good copy → `format_copied_tooltip(query)`; after a failed copy → `COPY_FAILED_TOOLTIP`; disabled → `COPY_NOTHING`. Switch with `Tooltip.update_text` (`tooltip.py:44`) and restore the ready text when the timer ends.
- Constructed with `command: Callable[[], bool]` (a closure over the track), the query text (`str | None`) and the tooltip strings. `None` query → disabled with `COPY_NOTHING`; otherwise the tooltip is `format_copy_tooltip(query)`. The widget attaches its own `Tooltip`. The button has no visible text, so the tooltip must always be attached, including when disabled.
- On click: call `Tooltip.hide()`; call `command()`; show **copied** if it returns `True`, **failed** otherwise; (re)start a 1500 ms `after` timer that returns it to **ready**. A click while already copied restarts the timer; clicks are never ignored (brief §5 rule 1).
- **One copied at a time:** a class-level reference to the button currently flashing. Starting a flash on another button first returns the previous one to **ready** and cancels its timer (brief §5 rule 2).
- **No timer survives the button:** cancel the `after` id and clear the class-level reference when the widget is destroyed (override `destroy`), and guard the timer callback with `winfo_exists()` (a re-render destroys rows, `suggestion_panel.py:524-525`).
- Must not bind `<Button-1>` on itself or its parent chain beyond what `CTkButton` does for `command=` (blueprint D4).
- Constants for 1500 ms and the colours at the top of the module, with a comment naming the guide §3 tokens. No new colour.

**T3.2 `SuggestionPanel`: accept the callback.**
- Add `on_copy: Callable[[Track], bool] | None = None` to `__init__` (`source/ui/suggestion_panel.py:92-103`) and store it as `self._on_copy`. The `TYPE_CHECKING` block (`:19-20`) gains `Track` for the hint.
- Import `paste_query` (allowed, blueprint D3) and the new `library_copy` constants with the existing import at `:11`.

**T3.3 `SuggestionPanel`: the leftmost column.**
- `_COL["copy"] = 36` in the width table (`:82-86`). The button is 36 x 28; the column takes 44 px with its padding. Recheck at 150% scaling (M11).
- Header (`:154-169`): put `(HEADER_COPY, _COL["copy"])` **first** in `headers` (the word `Copy`, 10 bold; it is the only permanent label of the icon-only button; brief §3.2, O7). The `6 if col == 0 else 2` padding (`:169`) then applies to the copy header automatically; check the existing headers still line up with their cells after the shift.
- Row (`:565-613`): before the cells loop, create a `CopyButton` and grid it at `column=0`, `padx=(6, 2)`. Then grid each cell at `column=col + 1` with `padx=(2, 2)` (the `6 if col == 0` rule at `:585` no longer applies to cells). Set `next_col = len(cells) + 1` (`:590`) so the play and `+` buttons follow.
- The button's query is `paste_query(track.artist, track.title, track.file_name)`; its command is `lambda t=track: self._copy(t)`.
- `self._copy(track) -> bool` returns `self._on_copy(track)` if set, else `False`. It does **not** call `_select_track` or `_stop_playback` (preview keeps playing, blueprint D3).
- **Do not** bind `<Button-1>` on the button, and don't add it to the hover loop (`:615-624`) with anything that selects.
- The disabled look and the tooltip text come from `CopyButton` (T3.1); the panel passes the query, nothing else.
- Before destroying rows in `set_suggestions` (`:524-525`) nothing extra is needed: `CopyButton.destroy` cancels its own timer (T3.1).
- No change to `_signature` (`:434-444`); blueprint D5 explains why. Add a one-line comment there saying the copy column depends only on `title`/`artist`/path, which are already in it.

**T3.4 Wire it in `source/app.py`.**
- `SuggestionPanel(..., on_copy=self._copy_track_text)` (`source/app.py:152-157`). `NowPlayingDashboard` (`:138-140`) is unchanged.

**T3.5 Create `tests/ui/test_suggestion_copy.py`.** Use the panel fixture pattern from `tests/ui/test_suggestion_quiet.py:18-56` (live Tk root, skip without a display). Compare labels against the `library_copy` constants, never literal glyphs, so the brief can change them.
- Render three suggestions with `on_select` and `on_copy` recorders. Find row 0's copy button (the `CTkButton` gridded at column 0 of the row frame) and call `.invoke()`. Then `on_copy` got that row's track, **`on_select` was not called**, and the render count is unchanged (no rebuild).
- With a fake `AudioPlayer` in a playing state, invoking copy doesn't call `stop()`.
- A track with empty `artist`, `title` and `file_name` → its copy button's `cget("state") == "disabled"`, and it still has a tooltip (`COPY_NOTHING`).
- Column order: the button is at grid column 0 and the score label at column 1 (`grid_info()["column"]`).
- Header: the first header label has the copy column width and the text `HEADER_COPY`.
- Glyph states are all different: the four `BUTTON_*` glyphs are distinct, and the button's text after a good copy is `BUTTON_COPIED`, after a failed copy `BUTTON_COPY_FAILED` (assert on text, not on colour).
- Tooltip text follows the state: ready shows the query, copied shows `format_copied_tooltip`, failed shows `COPY_FAILED_TOOLTIP`, and it returns to the ready text after the timer.
- Feedback (use the live root and call `update()`, or drive the timer by lowering the 1500 ms constant via monkeypatch): after invoking, the button shows `BUTTON_COPIED`; with `on_copy` returning `False` it shows `BUTTON_COPY_FAILED`; after the timer it shows `BUTTON_COPY` again.
- Rapid clicks: invoke the same button twice before the timer fires; it still shows the copied state after the first timer's original deadline, and returns to ready once, one interval after the second click.
- One at a time: invoke button 0, then button 1; button 0 is ready at once, button 1 shows copied.
- Timer safety: invoke, then call `set_suggestions` with new rows (destroying the button), let the timer interval pass; no exception, and no stale class-level reference remains.
- The tooltip text of a ready button contains the exact (stripped) `paste_query` text; a disabled button's tooltip is `COPY_NOTHING`. `Tooltip.hide()` is called on click (record it).

**T3.6 Manual checklist** (Windows, user's machine; macOS when one is available). Record the results here. They also go in `docs/cross-platform-guide.md` (T4.4).

| # | Check | Verifies | Pass = |
|---|---|---|---|
| M1 | Click a suggestion's copy button, switch to rekordbox, click its search box, `Ctrl+V` | `[A4]`, D2 | The text shown in the toast is pasted; the track is in the results |
| M2 | Same as M1, but paste **immediately** (within half a second) | `update()` question, D2 | Pastes. If it's empty, add `update_idletasks()` in `copy_to_clipboard` and recheck |
| M3 | Same as M1 in Serato DJ | `[A1]` in Serato | The track is in the results |
| M4 | Copy, then close Sidecar, then paste into Notepad | `[A4]` shutdown render | Record (expected: pastes) |
| M5 | Copy while a preview is playing | D3 | Preview keeps playing; row not selected; setlist unchanged |
| M6 | Copy on a row, move the pointer straight back to the row | D5 | Row isn't selected; no rebuild flicker |
| M7 | Copy two different tracks quickly | toast replacement, brief §5 rule 2 | The second toast replaces the first; the clipboard holds the second; only the second row shows the copied state |
| M8 | Window at 1000x650 with the default 50/50 split, then with the sash dragged fully left and fully right | D4, R5, brief §3.4 | Copy column visible at every sash position. **Key fully visible at 1000x650** (the brief's estimate); record how much of BPM and Energy is visible |
| M9 | A track with accented characters, one with CJK characters, and (if one exists) one with an emoji | `[A7]` | Record what pastes |
| M10 | A track whose title has `(Extended Mix)` and `feat. X` | D1 | The toast and the paste show the stripped query; the DJ app lists the track |
| M11 | 150% Windows scaling | look | The four glyphs fit the 36 x 28 button and the header `Copy` fits 36 px; the row does not grow taller |
| M12 (macOS, later) | M1, M4 with rekordbox or Serato for Mac | `[A5]` | Record |
| M13 | Click the same row's copy button five times in a second, in a dark room at normal brightness | brief §5 | It stays in the copied state the whole time, returns to ready about 1.5 s after the last click, and nothing flickers blue while the pointer rests on it |
| M14 | Hover for the tooltip, then click | brief §10 risk 3 | The tooltip disappears on the click and does not reappear until the pointer leaves and re-enters |
| M15 | Hover a row's copy button, then a different row's | tooltip | Each tooltip previews that row's own text |
| M16 | Break the clipboard on purpose if a way exists (e.g. a tool that holds it open), or temporarily force `copy_to_clipboard` to return `False` in a dev build | error state | The button shows the failed state (red) and a red toast shows; the next good copy recovers |

**Done when:** gate G passed; T3.5 green; M1-M8, M10 and M13-M14 pass on Windows; M9 recorded.

---

## Phase 4: Docs

**T4.1 `docs/architecture-decisions.md`: add ADR-016** after ADR-015 (`:439-556`). Short form:
- *Title:* Track hand-off to DJ software by clipboard (no deck loading).
- *Status:* Accepted. *Date:* ship date. *Relates to:* ADR-014, ADR-015 D12.
- *Context:* the user wants to get a Sidecar suggestion onto a deck. Rejected routes: MIDI (ADR-014), OS file drag (user rejected; `plans/rekordbox-load-to-deck-2026-11/`, or its archived location if O5 moves it), keystroke automation (fires DJ shortcuts if the search box isn't focused).
- *Decision:* a copy button on each suggestion row puts `paste_query(...)` on the clipboard via Tk. The query is the artist and title stripped of bracketed segments and `feat.` credits ("less is more": the DJ apps match words and substrings). The DJ pastes into the DJ app's search and loads with that app's own controls. Every track, every provider, no capability flag. Copy changes no Sidecar state. Sidecar sends the DJ apps nothing.
- *Consequences:* not exact (the DJ app's search matches, and several versions of a track may be listed; the DJ confirms by eye); no dependency; `DECK_LOAD` / `load_to_deck` stay reserved and unimplemented.
- In ADR-015 D12 (`:541`), change "Phase 6 needs its own ADR that meets ADR-014's bar" to also point at ADR-016.

**T4.2 `docs/coding-standards.md`:** under "DJ library providers — review blockers" (`:51-64`), add rule 11: *Sidecar never synthesises input events, focuses or automates another application, or sends a DJ app anything to cause a deck load. Handing a track over is passive (the clipboard; ADR-016).* Under "UI Code" (`:66-71`), add: *Clipboard writes go through `ui/clipboard.copy_to_clipboard`; never call `update()` after a clipboard write.*

**T4.3 `docs/architecture-overview.md`:**
- Services table (`:73-92`): a `paste_query.py` row ("stripped artist + title for a DJ app's search"). UI table (`:97-104`): `clipboard.py` and `copy_button.py` rows; `suggestion_panel.py` mentions the copy column.
- Debt #16 (`:163`): say the deck-load gate stays unused by design (ADR-016), with no Phase 6 planned.
- Debt #4 (`:151`): note `library_copy.format_copied_toast`'s own truncation (services can't import `ui/utils`).
- Bump "Last updated" (`:4`).

**T4.4 `docs/cross-platform-guide.md`:** a new "Clipboard" section after "UI Considerations" (`:122-134`), with the D2 table, updated with the M1-M12 results.

**T4.5 `docs/testing-strategy.md`:** list the new tests and the manual checklist M1-M16.

**T4.6 `docs/ui-design-guide.md`:** the ui-designer's updates, listed in `ui-design-brief.md` §8: §3 widen the Success and Error rows (a copy completed or failed); §5 add a "Self-confirming action button" row (`CopyButton`, icon-only) and note the leftmost copy column; §6 note the local-plus-toast success pattern; §8 add the "never say Load" rule and the new strings; §9 record the answers to brief O1-O7. Bump "Last updated".

**T4.7 `README.md`:** one sentence: *Click the copy button next to a suggestion, then paste into rekordbox's or Serato's search to find it.* Optionally one line on clipboard history (R6).

**T4.8 `CLAUDE.md`:** add `paste_query.py` to the services list and `clipboard.py` and `copy_button.py` to the UI list in the project tree.

**Done when:** docs merged with the code; the full suite is green.

---

## Not in scope
- **A Now Playing copy control** (user decision: "if it's now playing then I probably already have it in the software"). `source/ui/track_detail.py` isn't changed. Adding it later would reuse `on_copy` and `CopyButton`.
- Setlist and search-dropdown copy buttons (blueprint D4).
- A keyboard shortcut (blueprint O4).
- A separate mix-name field: not needed, because mix names are stripped (D1).
- Splitting collaborations (`A & B`, `A x B`) in the query (D1).
- Any change to providers, the snapshot schema, packaging or CI.
- Touching `plans/rekordbox-load-to-deck-2026-11/` (blueprint O5).

---

## UI revisions applied

By the ui-designer, 2026-11-06. Full reasoning and the open questions (O1-O7) are in `ui-design-brief.md`. Nothing outside this folder was changed. (Items about Now Playing, the 56 px width and the text labels are superseded by "User decisions applied" below.)

- **Strings (T1.3, T1.4):** `COPY_TOOLTIP` replaced by `format_copy_tooltip(query)` (shows the exact text); added `BUTTON_COPIED`, `BUTTON_COPY_FAILED`; `COPY_FAILED` now ends `Try again.`; guards for the 6-character button labels.
- **Return value (T2.3, T2.4):** `_copy_track_text` and the `on_copy` callbacks return `bool`, so the button can show `Copied` or `Failed` instead of confirming a failed copy.
- **New T3.0:** public `Tooltip.hide()`, so a click dismisses the tooltip.
- **New T3.1:** shared `source/ui/copy_button.py` (`CopyButton`): four looks from existing tokens, 1.5 s `Copied` label, every click restarts the timer, one `Copied` at a time across both panels, timer cancelled on destroy.
- **Suggestion column (T3.3):** width fixed at 56 px (not 44) so `Copied` fits; blank header cell; button is a filled `#2a2a2a` tile, not a ghost button.
- **Now Playing (T3.4):** decided in favour, placed at the right edge of `track_frame` (not a fifth badge, which would move with the genre text), as a badge-styled `CTkButton`. Pending the user's answer to brief O2.
- **Tests and manual checks (T3.6-T3.8):** feedback, rapid-click, one-at-a-time and timer-safety tests; M8 now records the Key/BPM/Energy clipping; added M13-M16. Tasks renumbered: old T3.4 to T3.5, T3.5 to T3.6, T3.6 to T3.7, T3.7 to T3.8.
- **Docs (T4.6, T4.8):** guide updates itemised; `copy_button.py` added to the project tree.
- **Conflicts:** none with `docs/ui-design-guide.md` or the ADRs. The Success and Error colour tokens gain a meaning (T4.6).
- **Second pass, after the user's answers (icon-only, no Now Playing, stripped query):**
  - Glyph set chosen: `❐` U+2750 ready, `✓` U+2713 copied, `✕` U+2715 failed, `—` U+2014 disabled. All in the Basic Multilingual Plane; the first three are in the Dingbats block, whose `✕` already ships (`session_panel.py:132`). `📋`, `⎘` and the emoji ticks were rejected (brief §3.3). Not rendered in this session, so **new gate G (T3.0a)** checks them on the user's machine, with a constants-only fallback ladder.
  - Constants filled in: `_COL["copy"] = 36` (button 36 x 28; Key should stay visible at 1000x650, to be measured in M8); the state constants in T1.3; the look and colours in T3.1. Each state differs by glyph as well as fill.
  - Header cell now reads `Copy` (was blank), because the icon-only button has no label of its own. New string `HEADER_COPY`.
  - Tooltip follows the state (new `format_copied_tooltip`, `COPY_FAILED_TOOLTIP`), since the tooltip carries the meaning.
  - Brief O3-O7 decided with my defaults (1.5 s; failed state on the button; neutral wording; success toast kept; header word). Now Playing removed from the brief. Tooltip and toast examples use the stripped query.

---

## User decisions applied (2026-11-06, by the architect)

1. **Stripped query** ("Less is more"). T1.1 now specifies `_strip_decorations` (balanced and unmatched brackets, a `feat.`/`ft.`/`featuring` tail on the title and the artist, dangling separators, and a fallback to the unstripped field when nothing would be left). T1.2 has the new cases, grouped by title, artist and file name. Phase 0 checks stripped queries. Added M10 (stripped query end to end) and a T2.4 case. Mix-name field removed from the open questions.
2. **Icon-only button.** T1.3, T1.4, T3.1, T3.3, T3.5 and the manual checks no longer assume a `Copy` text label or a 56 px width. The glyph and width come from `ui-design-brief.md`, and tests compare against the `library_copy` constants.
3. **No Now Playing in v1.** Removed the old T3.4 (dashboard button), the old T3.7 (dashboard tests), the dashboard wiring in T3.5 (now T3.4) and old M10, plus the `"tile"` style in T3.1. Recorded under "Not in scope". Phase 3 renumbered: T3.4 wiring, T3.5 panel tests, T3.6 manual checklist.
