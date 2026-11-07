# UI Design Brief: Copy a track's search text

> **Author:** UI designer agent. **Date:** 2026-11-06 (revised the same day with the user's answers; see §9).
> **Companions:** `architect-blueprint.md`, `implementation-plan.md` (same folder). Both were revised in place to match this brief; see `## UI revisions applied` at the end of the plan.
> **Status:** Proposed. The open questions are closed (§9). One check remains before code: a 5-minute glyph render check on the user's Windows machine (§3.3, gate G).
> **Scope rule:** nothing outside this folder was changed. The `docs/ui-design-guide.md` updates are listed in §8 and applied at ship (plan T4.6).
> **Reused from** `plans/rekordbox-load-to-deck-2026-11/ui-design-brief.md` (never implemented): leftmost-column reasoning (§0.4 there), tile fill and accent-hover tokens (§3.2), the "tooltip must be hidden explicitly" lesson (§3.6), the "never say Load" rule (§6). **Not reused:** the grip glyph, the `Deck` header, the badge-tile Now Playing control and the hidden-versus-disabled availability matrix. Copy is a click, not a drag, and it works for every track.

---

## 0. Read this first: what the DJ must be able to trust

1. **The button copies; it does not load.** The words "Load", "Loaded" and "Sent" appear nowhere in this feature. The DJ's next two steps (paste, then load) happen in rekordbox or Serato, so the tooltip says "paste".
2. **Copy never selects.** Clicking it does not add the track to the setlist, re-score or rebuild the list (user decision). The one visible result is on the button itself, plus a toast.
3. **The tooltip is the label and the preview.** The button shows only a symbol, so the tooltip says what it does and shows the exact text that will land on the clipboard. That text is the stripped query (no brackets, no `feat.` credits; blueprint D1).
4. **State is never carried by colour alone.** Ready, copied, failed and disabled each have their own glyph as well as their own fill (§3.1).

## 1. User goal

**Put the track I'm looking at into my DJ software's search box with one click and one paste, without losing my place in Sidecar.**

## 2. Panels and components affected

```
┌ Row 0  top bar ──────────────────────────────────────────────┐
│  toast:  Copied "Artist A Track One"  (green)           ⚙   │
├ Row 1  Now Playing dashboard  (no change in v1)              │
├ Row 2  paned split ──────────────────┬───────────────────────┤
│  header:  Copy % Artist Title ...    │  Setlist              │
│  row:    [ ❐ ] 87% ...  ▶  +         │  (no change in v1)    │
│           ^ NEW leftmost column      │                       │
└──────────────────────────────────────┴───────────────────────┘
```

| Component | Change | Side of window |
|---|---|---|
| `SuggestionPanel` row grid | New leftmost column with an icon-only copy button; header cell reads `Copy` | Left pane of the split |
| New widget `source/ui/copy_button.py` (`CopyButton`) | One button with four visual states. Owns the "copied" timer. Only the row style exists in v1 | n/a |
| `Tooltip` (`source/ui/tooltip.py`) | A public `hide()` so a click can dismiss the tooltip | n/a |
| Top-bar toast | Green on success, red on failure | Row 0 |
| Now Playing, setlist, search dropdown | **No change in v1.** Now Playing is out by user decision ("if it's now playing then I probably already have it in the software") | n/a |

## 3. The suggestion-row button

### 3.1 Look, glyphs and states

All four states differ in **glyph and fill**, so none depends on hue alone. Glyphs are written as `\u` escapes in `library_copy.py`, as the play button does (`suggestion_panel.py:595`).

| State | Glyph (constant) | Fill / glyph colour | Meaning for the DJ |
|---|---|---|---|
| Ready | `❐` U+2750 (`BUTTON_COPY`) | `#2a2a2a` fill, `#999999` glyph | "Copy this track's search text" |
| Ready, pointer over | `❐` | `#1f6aa5` fill, `#ffffff` glyph | Same; confirms it is a button |
| Copied (1.5 s) | `✓` U+2713 (`BUTTON_COPIED`), bold | `#28a745` fill (also as hover fill), `#ffffff` glyph | It is on the clipboard |
| Failed (1.5 s) | `✕` U+2715 (`BUTTON_COPY_FAILED`), bold | `#dc3545` fill (also as hover fill), `#ffffff` glyph | It did not copy; click again |
| Disabled | `—` U+2014 (`BUTTON_COPY_DISABLED`) | `#2a2a2a` fill, `#555555` glyph, no hover change | Nothing to copy (never occurs in practice, blueprint D1 rule 6) |

- **Size:** glyph font size 14 (the size of the play and `+` glyphs, `suggestion_panel.py:598`, `:610`; no new size). Set no font family, so Tk's own fallback picks the symbol font (guide §4).
- **Hit size:** **36 wide x 28 tall.** The play and `+` buttons are 32 x 24 (`suggestion_panel.py:594-612`); the extra height is cheap, because the row height already comes from the 12 pt labels plus `pady=5` (`:579-585`), so rows do not grow.
- **Shape:** rounded tile, corner radius 6 (row radius 4, `:560`; badge radius 10, `track_detail.py:112`, scaled down).
- **Resting fill** `#2a2a2a` is the card-fill token (`track_detail.py:112`), darker than both row stripes, so it reads as a control and not as a cell. It differs from the transparent play and `+` buttons on purpose: with no visible word, a filled tile is the easiest thing in the row to find.
- **Hover fill** is set to the state fill while copied or failed. Otherwise the pointer, which is still over the button after the click, would repaint it blue and hide the state.
- **Always visible.** Not hover-reveal (guide §1).
- **Colour-blind fallback:** met by shape (`❐` / `✓` / `✕` / `—`) and by the tooltip (§8), not by hue.

### 3.2 The header cell

The header cell reads **`Copy`** (10 bold, like the other headers, `suggestion_panel.py:166-169`), at the column width. With the button reduced to a symbol, a one-word header is the only permanent label, and it costs nothing: `Copy` at 10 bold fits in 36 px (check at 150% scaling, M11). This reverses my earlier "blank header" default, which rested on the button carrying the word itself.

### 3.3 Glyph choice, and the fallback if it does not render

I could not render anything in this session, so the evidence below is precedent in the codebase and the structure of Tk's font fallback, not a screenshot. **Gate G** (below) makes it a 5-minute check before `CopyButton` is written.

| Candidate | Block | Verdict |
|---|---|---|
| **`❐` U+2750** | Dingbats | **Chosen.** Same block as the `✓` and `✕` used for the other states, and `✕` already ships in this app (`session_panel.py:132`), so Tk's fallback for that block is already proven here. Reads as two stacked pages, the common copy symbol. Has no colour-emoji presentation, so it takes the fill and glyph colours above |
| `⧉` U+29C9 | Miscellaneous Mathematical Symbols-B | Commonly used as a copy icon, but I cannot confirm that the default Windows symbol font covers this block. Second choice |
| `⎘` U+2398 | Miscellaneous Technical | Looks like a page, but its coverage in the default fonts is uncertain and it renders oddly in several fonts. Rejected |
| `📋` U+1F4CB | Emoji (outside the Basic Multilingual Plane) | **Rejected.** Tk 8.6 handles characters outside the BMP badly (blueprint `[A7]`), it renders as a fixed-colour emoji that ignores the fill tokens, and a coloured icon clashes with colour-as-data (guide §1) |
| `✔` U+2714, `❌` U+274C, `✅` U+2705 | Dingbats / emoji | Rejected for the copied and failed states. These have emoji presentations in the Windows symbol/emoji fonts and may render in fixed colours. Use the plain `✓` U+2713 and `✕` U+2715 |

**Gate G (before `CopyButton` is built; plan T3.0a):** a scratch Tk/CTk window shows `❐ ✓ ✕ —` at font size 14 on a `#2a2a2a` tile, at 100% and at 150% Windows scaling, next to the existing `▶` and `✕` (settings/setlist) glyphs. Pass = each shows as a recognisable symbol, not an empty box or `?`, and `❐` is roughly the same visual weight as `▶`.

**Fallback ladder (constants only: `library_copy.py`, plus `_COL["copy"]` for the last rung):**
1. `❐` shows as a box → try `⧉` U+29C9 for `BUTTON_COPY`.
2. Both fail → use `□` U+25A1 (in the standard Windows glyph set, so every default font has it) for `BUTTON_COPY`. It is a plain square, and the header `Copy` and the tooltip give it meaning.
3. `✓` or `✕` fail → there is no safe single-glyph substitute; go to rung 4.
4. **Last resort, text labels:** `Copy` / `Copied` / `Failed` / `—`, with `_COL["copy"]` raised to 56 px. That costs about 20 px more than the chosen design; Key would then be mostly clipped at 1000x650 (this was the earlier O1 option A).

### 3.4 Width and the minimum window

`_COL["copy"] = 36` (plus the first-column padding of 6 + 2, so the column takes 44 px). These are my estimates from the column widths, not measurements; manual check M8 measures them.

| Left-pane position (approx.) | Without Copy | With the 36 px column |
|---|---|---|
| Score, Artist, Title end at | 360 | 404 |
| Key spans | 360-412 | 404-456 |
| BPM starts at | 412 | 456 |
| Usable pane width at 1000x650 (50/50 split, after padding and scrollbar) | about 440-450 | about 440-450 |

So with the icon-only column, Key's text (about 24 px wide, starting near 406) should still be fully visible at the minimum window; BPM and the right-hand columns stay clipped as they are today. With the earlier 56 px label design, Key would have been mostly lost. At the default 1300 wide window nothing clips.

## 4. Feedback, including rapid repeated clicks

The toast is at the top of the window, a long way from the row. The button therefore carries its own confirmation:

| Moment | What the DJ sees |
|---|---|
| Pointer over the button | Blue fill; tooltip after 400 ms (`tooltip.py:7`) showing the exact text |
| Click, copy succeeded | Tooltip disappears. Button shows `✓` on green. Green toast shows the text. The row does not select or rebuild |
| Click, copy failed | Button shows `✕` on red. Red toast |
| 1.5 seconds after the **last** click | Button returns to `❐` |

**Rules that keep the feedback honest under rapid clicking** (built once, inside `CopyButton`):

1. **Every click restarts the 1.5 s timer.** Clicking twice on the same row (say, because rekordbox's search lost focus) keeps `✓` showing and gives a fresh 1.5 s. Clicks are never ignored or debounced: re-copying is harmless, and a DJ who re-clicks wants it to work.
2. **Only one button shows `✓` at a time.** Copying track B while track A still shows `✓` returns A to `❐` at once. At any moment, a green tick means "this is what is on the clipboard"; two ticks would not answer that. The class-level single-active reference follows the one-open-overlay registry in `FloatingOverlay` (guide §5).
3. **The timer cannot outlive the button.** A re-render destroys rows (`suggestion_panel.py:524-525`). The button cancels its timer when destroyed. A quiet re-render is deferred while the pointer is over the list (`:475-477`), so the DJ's own click does not normally destroy the button mid-flash.
4. **The toast also restarts.** `_show_toast` cancels the previous timer and replaces the text (`app.py:515-520`), so the toast always names the latest copy. When two successive copies have identical text, nothing changes in the toast; the button's restarted timer is the signal.
5. **A failed copy does not leave a green button.** The button learns the outcome from the callback's return value: `on_copy` returns `True` or `False` (plan T2.3, T3.1, T3.2).
6. **Hover colour is part of the state** (§3.1).
7. **The tooltip follows the state.** On click the tooltip is hidden, then its text is switched to the copied or failed wording (§8) with `Tooltip.update_text` (`tooltip.py:44`), and restored to the ready wording when the timer ends. A DJ who re-hovers during the 1.5 s reads what just happened, not "Copy to the clipboard".

## 5. Pattern precedent

| New component | Closest existing pattern | Cite |
|---|---|---|
| Copy column, `_COL["copy"]`, header cell | Play and `+` columns | `source/ui/suggestion_panel.py:82-86`, `:154-169`, `:592-613` |
| Click does not select | Play button: `command=`, no `<Button-1>` | `suggestion_panel.py:594-601`; blueprint §1.3 |
| Glyph button, size 14 | Play and `+` glyph buttons | `suggestion_panel.py:595`, `:598`, `:610` |
| `✕` glyph proven to render | Setlist remove button | `source/ui/session_panel.py:132` |
| `—` for "nothing here" | Empty-badge placeholder | `source/ui/track_detail.py:100`, guide §3 "Placeholder" |
| Tile fill, radius, hover | Stat-badge card; play-button hover | `track_detail.py:111-127`; `suggestion_panel.py:596` |
| Tooltip | `Tooltip` | `source/ui/tooltip.py:4-45` |
| One "active" state at a time | `FloatingOverlay._open` registry | guide §5 "Floating overlay panel" |
| Toast | `_show_toast` | `source/app.py:500-534` |
| Strings | `library_copy.py` | `source/services/library_copy.py:99-104` and the toast section |

**New pattern, named explicitly:** a *self-confirming action button* (glyph flips to `✓` for 1.5 s). The app has no precedent: the `+` and play buttons give no local confirmation, because their result is a visible list change. Copy changes nothing visible, so it needs one. It is built from existing tokens only.

## 6. States to handle

- **Loading** (guide §6): no special handling. Buttons exist only on rendered rows, and rows do not exist while the library is loading ("Reading your library…"). No spinner. The copy is instant.
- **Empty** (guide §6): no suggestions means no rows and no buttons; the existing empty messages are unchanged (`suggestion_panel.py:56-76`). The `Copy` header stays, like the other headers.
- **Error** (guide §6): `copy_to_clipboard` returns `False` on `TclError`. The button shows `✕` on red and a red toast says `Couldn't copy to the clipboard. Try again.` Nothing else breaks; the set continues (guide §1). The no-query case shows a disabled `—` button with a tooltip and no toast.
- **Success** (guide §6): the button shows `✓` on green; a green toast shows the copied text for `SHORT_TOAST_MS` (4000 ms). Guide §6 says successes are confirmed; here the confirmation is local as well as in the top bar.

## 7. Risks

1. **Glyph rendering (medium until gate G passes).** See §3.3. Mitigation: the ladder is constants-only for rungs 1-2.
2. **Minimum window.** Estimated fine for Key (§3.4); measure in M8. **Very narrow pane:** the copy button is the first column, so it stays visible however far the sash is dragged left; data clips to its right as today. **Very wide pane:** columns are fixed-width and left-aligned, so nothing changes.
3. **Tooltip left on screen.** The tooltip window is only dismissed on `<Leave>` (`tooltip.py:14`, `:36`). After a click it would sit over the next row. Hence the public `Tooltip.hide()` (plan T3.0).
4. **Stale tooltip text.** The row may show a pre-refresh `Track` while a live refresh waits (blueprint D5). The tooltip previews the row's text; the click copies the fresh text; the toast shows what was copied. A mismatch is visible and rare.
5. **Timer after destroy.** Covered by rule 3 in §4. Test it (plan T3.5).
6. **Scaling.** At 150% Windows scaling, the glyphs must still sit inside 36 x 28 and the header `Copy` inside 36 px (M11). If not, widen `_COL["copy"]`; it is one constant.
7. **Discoverability of an icon.** First use relies on the header word `Copy` and the tooltip. After one click the green `✓` and the toast teach the rest.
8. **`✕` means "remove" in the setlist** (`session_panel.py:132`). Here it means "failed", is red, transient and sits in a different panel, with the tooltip stating the meaning. Accepted.
9. **Mouse-only.** No keyboard path, consistent with known debt (guide §7.6, not re-flagged). The keyboard shortcut is out of scope (blueprint O4).
10. **Conflicts with the design guide or ADRs: none found.** Guide §3 tokens only. The meaning of the Success and Error tokens widens slightly (§8). No conflict with ADR-014 or ADR-015 D12.

## 8. Microcopy

All strings go in `source/services/library_copy.py` (guide §8). Sentence case. Provider names do not appear in this feature's strings.

| Where | Text | Notes |
|---|---|---|
| Button, ready | `❐` | `BUTTON_COPY` = `"❐"` |
| Button, copied | `✓` | `BUTTON_COPIED` = `"✓"` |
| Button, failed | `✕` | `BUTTON_COPY_FAILED` = `"✕"` |
| Button, disabled | `—` | `BUTTON_COPY_DISABLED` = `"—"` |
| Header cell | `Copy` | `HEADER_COPY`; sentence case, 10 bold like the other headers |
| Tooltip, ready (3 lines) | `Copy to the clipboard:` / `{query}` / `Then paste it into your DJ software's search box.` | Line 2 is the exact text. `format_copy_tooltip(query)`. Wraps at the tooltip's 400 px |
| Tooltip, copied (3 lines) | `Copied:` / `{query}` / `Now paste it into your DJ software's search box.` | `format_copied_tooltip(query)`. Shown only if the DJ re-hovers within the 1.5 s |
| Tooltip, failed | `Couldn't copy. Click to try again.` | `COPY_FAILED_TOOLTIP` |
| Tooltip, disabled | `Nothing to copy: this track has no artist or title` | `COPY_NOTHING` |
| Toast, success (green) | `Copied "{text}"` | `{text}` cut with `…` so the whole toast is at most 75 characters (text at most 66) |
| Toast, failure (red) | `Couldn't copy to the clipboard. Try again.` | 42 characters; says what to do (guide §8) |
| README | `Click the copy button next to a suggestion, then paste into your DJ software's search box.` | Plan T4.7 |

**Examples with the stripped query** (blueprint D1). For artist `Artist A feat. Singer B` and title `Track One (Extended Mix)`:
- tooltip middle line: `Artist A Track One`
- toast: `Copied "Artist A Track One"`

The tooltip and the toast show the same stripped text, so what the DJ previews is what they paste. A DJ who sees `(Extended Mix)` in the row and not in the tooltip is looking at the stripping, which is intended ("less is more").

Words to avoid in this feature: "Load", "Loaded", "Sent", "Send", "Deck", "Added", "Selected".

**Guide updates to apply at ship (plan T4.6):** §3 widen Success and Error (a copy completed or failed); §5 add a "Self-confirming action button" row (`CopyButton`, icon-only, with its glyph set) and note the leftmost copy column; §6 note the local-plus-toast success pattern; §8 add the "never say Load" rule, the new strings and a note that icon-only buttons carry their meaning in a tooltip and a column header; §9 record the answers below.

## 9. Decisions (formerly open questions)

Answered by the user:
- **O1 Icon-only button, about 36 px.** Glyph `❐`, width 36, states as in §3.1.
- **O2 No Now Playing control in v1.** Removed from this brief.
- **Stripped query.** Tooltip and toast examples updated (§8).

Closed with my recommended default, now **decided**:
- **O3 Confirmation time: 1.5 s**, restarted by each click. (The alternative, staying green until the next copy, goes stale if anything is copied outside Sidecar.)
- **O4 The button shows the failed state** (`✕` on red), not only the red toast, because the toast is far from the row.
- **O5 Tooltip wording is neutral** ("your DJ software's search box"), not named from the enabled providers. Named wording would need a new "or" joiner beside `join_names` (`library_copy.py:99-104`, which says "and").
- **O6 The success toast stays.** It is the only place the exact copied text stays visible after the tooltip is gone. It replaces any other toast, including a red one with an `Open settings` button (`sync_outcome.py:69`); the DJ asked for the copy, so theirs wins (blueprint R4).
- **O7 Header cell reads `Copy`.** My default changed: it was blank while the button carried the word; with an icon-only button, the header is the visible label (§3.2). The user can still choose blank, which is a one-string change.
