# UI Audit: Phase 3c settings dialog and related UI

> **Author:** UI designer agent. **Date:** 2026-11-05.
> **Against:** `ui-design-brief.md` (revised for 3c) and `docs/ui-design-guide.md` (last updated 2026-05-30, not yet carrying the 3c tokens).
> **Evidence:** the 12 screenshots in the session scratchpad (`...\scratchpad\screenshots\`, cited by file name) and `source/ui/sync_panel.py`, `source/services/library_copy.py`, `source/services/settings_model.py`, `source/ui/filter_bar.py`, `source/app.py`.
> **Not re-flagged:** guide §7 debt (no token module, ad hoc spacing, dead theme tuples, no keyboard story, colour-as-data fallback).
> **Severity here:** **High** = a DJ can misread or miss something that matters, or the control fails at the user's real data size. **Medium** = drift from the brief/guide, or a weak signal. **Low** = polish.

## Overall

The dialog is a faithful build of the brief. Structure (cards, scrolling body, pinned footer), sizes (640x580, min 540x420, `sync_panel.py:36-37`), staged save with `Close`/`Cancel`, `Save`, green primary, `STAGED_TINT` "Unsaved changes", cyan `Syncing…`, amber Warning, `#999999` hints and every string in `library_copy.py` match brief §4, §5 and §7. The dialog never branches on provider id. The 540x420 screenshot (`both_6_min_540x420.png`) holds: the footer is pinned, the body scrolls and the chip wraps cleanly. The findings below are what the screenshots and data scale expose, not build errors.

## Findings

### High

**H1. The playlist filter does not work at the user's data size (both providers on).**
`filter_bar.py:326` (checklist 200x200, one flat `CTkCheckBox` per item `:374-383`) with 148 items, 73 rekordbox playlists plus 75 Serato crates, many with identical names. Four compounding problems: about 9 rows visible at once; identical names with no way to tell the provider apart (and the two lists are different curation, so choosing the wrong one changes the result); " / " and " - " labels clipped at 200 px so the distinguishing leaf is cut off; no search. This is the core "pick the next track" loop, not a settings screen. **Canonical:** brief §5.10 (grouped, wider, type-to-filter), currently parked in T5.3. **Divergent:** flat list. See decision (a), new task T3c.10.

**H2. An error is shown far from the field it is about, in the weakest colour contrast in the dialog.**
`rekordbox_2_wrong_file.png`: the red `Choose the file named master.db` sits about 110 px below the `Database` entry, under the `Update automatically` row, then a second grey line. Code: issues render in one block at the bottom of the card (`sync_panel.py:429`, `_render_status`). Red `#dc3545` at 11 pt on the `#2a2a2a` card is about 3.2:1, below the 4.5:1 floor, and it is the one line the DJ must read. Amber (about 10:1) and success green (about 5:1) are fine. The brief placed issue lines last (§5.3 item 4); the screenshot shows that was a weak call by me.
**Recommendation (T3c.11):** render an issue directly under the row whose `setting_key` it names (replace the hint while an issue shows, or sit between the entry and the hint); issues without a `setting_key` stay at the bottom. Raise issue lines to 12 pt (existing size, guide §4) and bold for error tone. No new colour token. Open question O18 offers a lighter red tint instead.

### Medium

**M1. Disabled primary buttons still look live.** `neither_1_open.png`, `both_5_all_off.png`, `rekordbox_2_wrong_file.png`: the disabled `Sync enabled sources` keeps its saturated green fill (only the label dims); `Save` keeps its blue. In a dark booth a bright green button that does nothing reads as pressable. Code `sync_panel.py:254-258` (disabled state is never styled). **Recommendation:** on disable, swap the fill to a low-chroma dark (the `NEUTRAL_PILL` family, or `#2f3a32`-style desaturated green) and restore on enable. Taste call on the exact colour; the principle is "disabled must not be the brightest thing in the footer".

**M2. Startup toast mixes counts when both sources are on.** `app.py:221`: `format_load_toast(self.library.count, self.library.crate_count, self._noun)` gives `Loaded 740 tracks from 148 playlists`. 148 is the union (with duplicates by name) of 73 playlists and 75 crates, and neither card chip says 148 (75 playlists, 82 crates). Brief §5.5 rule: for both sources, name the providers and drop the second number (as `format_sync_success` already does, `library_copy.py:267-270`). **Recommendation:** a both-source form `Loaded 740 tracks from rekordbox and Serato DJ`; the one-source form stays.

**M3. Heading is the same size and weight as the card titles, and 13 pt is not in the type scale.** `sync_panel.py:143` (heading) and `:167` (card name) are both 13 bold; guide §4 has no 13 (scale is 26/24/18/15/12/11/10/9). In `both_1_open.png` the section heading `Music sources` does not outrank `rekordbox`. **Recommendation:** heading 15 (exists, guide §4), card names stay at 13 only if the user accepts a new size; otherwise 12 bold. Taste call (O19). Record whichever is chosen in guide §4.

**M4. Chip and issue contradict while edits are staged.** `rekordbox_2_wrong_file.png` shows the chip `Updates automatically · 740 tracks · 75 playlists / Last updated just now` directly above a red error and `Using your library from 5 Nov, 17:30.`; `rekordbox_3_unsaved_auto_off.png` shows `Updates automatically` while the `Off` tile is selected. This is by design (the chip follows saved state, the issue follows staged state, `app.py:557-558`) and "Unsaved changes" is visible, but the reader gets two stories in one card. **Recommendation:** no change. Adding a "(saved)" tag is extra text to read mid-mix. Revisit only if testing shows confusion. Listed so the choice is conscious.

**M5. `Database` field looks empty with no cue in `rekordbox_3` and `rekordbox_4`.** In `rekordbox_1_open.png` the detected path shows as a grey placeholder ("found, not typed", brief §5.3). In `_3` and `_4` the field is blank and the focus ring is lit. `CTkEntry` hides its placeholder while the entry has focus (`sync_panel.py:203-208` relies on it). Probably the harness left focus in the entry; if so, a DJ who clicks into the empty field sees a blank box and loses the "automatic" cue. **Verify** with real keyboard focus. If confirmed, the cheapest fix is to make sure focus does not land in an entry on open or after a sync (focus the dialog frame), so the placeholder is visible by default; clicking into the field will still blank it, which is standard.

### Low

**L1. `SYNC_GREEN` duplicates the Success hex.** `sync_panel.py:39`: `#28a745` equals `SUCCESS_COLOR` (`config.py`, guide §3); only the hover `#218838` is new. Import the token and keep one local hover constant. Not a new debt item, just one fewer literal.

**L2. "Unsaved changes" is small and far from `Save`.** `sync_panel.py:242-244`: 11 pt `#3a88c8` on the `#212121` window is about 4.2:1, just under 4.5:1, and sits on the status row (`both_2_both_unsaved.png`), a row above and apart from the buttons. Acceptable; nudge to 12 pt if M3 is touched anyway.

**L3. Footer wording before the DJ acts.** `rekordbox_2_wrong_file.png`: `Skipped rekordbox: Choose the file named master.db` reads as something that already happened, and here it is the only provider, so Sync is simply disabled. Brief §4.2 set the text. Suggested tweak: when **no** provider can sync, `Can't sync rekordbox: …`; when others can, keep `Skipped …`. Copy only (`library_copy.py:252`).

**L4. Footer total beside card counts.** `both_4_after_sync.png`: `Synced 740 tracks from rekordbox and Serato DJ` under chips `740 tracks` and `735 tracks`. A DJ who adds them gets 1475. It is correct (shared files counted once) but unexplained. No change recommended unless the user asks; candidate wording `Synced 740 tracks (shared files counted once)`.

**L5. At 540x420 the fixed heading block eats height.** `both_6_min_540x420.png`: heading, two-line sub-text and the precedence note use about 110 px of 420, so the Serato switch is half-clipped until the body is scrolled. Within brief ("cards scroll"). Hint text wraps early (the `CARD_TEXT_MARGIN` of 110 is cautious), leaving an orphan `it.` on line 2. Optional: move the precedence note inside the scroll body, margin 110 to 90.

**L6. Off cards have the same weight as on cards.** `both_5_all_off.png`, `serato_1_open.png`. The off card is correct (header plus one grey line) but the name is full white. See decision (b); optional dimmer name in secondary grey (O20).

**L7. Entry text styling differs between providers by design.** Serato's default is a real value (white), rekordbox's detected path is a placeholder (grey). Matches brief §5.3 and §5.4; the difference is subtle in a dim room. No action.

## Decisions on the engineer's two questions

### (a) Playlist filter at scale: pull forward now, minimal version

**Decision: pull forward. Do grouping and type-to-filter now, in a new task T3c.10, and keep the rest of T5.3 in Phase 5.**

Why now: Phase 4 is done, so two providers are live and the data is real (148 items). Both gates that parked T5.3 are cleared. Grouping alone does not fix scale, and search alone leaves two indistinguishable "House" rows. The release gate is Phase 3c, so this ships with it.

**Minimal version (all of it, nothing more):**
1. **Provider group headers.** When two or more providers contribute crates, a non-interactive header row per provider (`REKORDBOX`, `SERATO DJ`), registry order. One provider = flat list, no header (today's look). A provider with no crates gets no header. **Header style revised:** 10 bold uppercase in **secondary `#999999`**, not the brief's tertiary `#666666` (about 2.4:1; same reason as brief §4 for hints). Size 10 bold exists (guide §4, `track_detail.py:58`).
2. **Wider and taller overlay**, crate pill only: about 300 wide by 320 tall (was 200x200, `filter_bar.py:326`), clamped to the left pane and window bottom, 200 px fallback at the narrowest pane. Truncate near 38 characters with a tooltip only when truncated.
3. **Type-to-filter.** A search entry at the top of the overlay, focused on open, placeholder `Find a {noun}` (`Find a playlist` / `Find a crate`), 150 ms debounce (`track_detail.py:24-64`), case-insensitive substring match on the **full label** so a folder name finds its children. Rows are hidden and shown, never rebuilt, so selection survives typing. Headers with no matching rows are hidden. While text is present the action buttons read **`Select shown`** and **`Clear shown`** and act on visible rows only (otherwise `Select all` would silently tick hidden rows). Clearing the text restores `Select all` / `Clear`. No match: `No {nouns} match "{text}"` in the empty-label style.
4. **Case-insensitive sort inside each group** (`casefold` on the path; required anyway once rows are grouped).

**Deferred to Phase 5 (unchanged):** leaf-name single-selection pill, per-provider tooltip lines (T5.4), collapsible folder tree (tier 3).

**Not decided, user's call (O17):** making a group header clickable to select or clear that whole provider's rows ("only Serato crates" in one click). It is a new interaction on a header, not in the existing pill/overlay patterns; I left it out of the minimal version.

**State coverage (guide §6):** Loading: none, the list is in memory. Empty: unchanged, `No {nouns} loaded. Sync a source in Settings.`. Error: none. No-match: new line above. Success: grouped, searchable list. Extreme panes: 200 px fallback; the search entry shrinks, rows truncate.

### (b) Rekordbox-only user still sees the switched-off "Serato DJ" card

**Decision: adjust the criterion, keep the design.**

The exit criterion's intent was that a rekordbox user is never confronted with Serato **language that assumes they use it**: a Serato folder field, `Crates`, a Serato error or a Serato toast. A switched-off card is not that. Hiding it would break two things the design relies on: the card is the only way to turn Serato on later (a DJ who adds Serato next year, or keeps it in a non-default folder, needs the control), and the dialog is deliberately provider-agnostic and lists every registered provider (brief §4). Hiding by "not detected" would need a new rule and an "add a source" control, which is a new pattern for no booth benefit. It is symmetric: a Serato-only user sees a rekordbox card (`serato_1_open.png`) and that is a feature (discoverability).

**New wording** (replaces plan line 792): *A rekordbox-only user can turn rekordbox on and off, choose or clear the `Database` path, switch automatic updates on or off, save, and sync, and sees no Serato field, hint, prompt, error, toast, noun or placeholder. The name "Serato DJ" appears only as a switched-off provider card (`Off`), which is how Serato is turned on later.*

Optional, taste (O20): dim the off card's name to secondary grey so it recedes (L6).

## Open questions for the user

| # | Question | Default applied | Alternative |
|---|---|---|---|
| O17 | Clickable group header (select/clear one provider's rows)? | Not built | One click for "only rekordbox" or "only Serato" |
| O18 | Error emphasis | 12 pt bold in the existing Error red | A lighter red tint (new token) |
| O19 | Dialog heading size | Heading 15, card names 13 or 12 bold | Keep 13/13 |
| O20 | Off card styling | Unchanged | Dim the card name |

## Recommendations summary (build order)

1. T3c.10 (filter at scale), highest value for the DJ's data.
2. T3c.11 items H2, M1, M2 (and M5 check, L1, L3).
3. M3, L2, L5, O20 only after the user answers O19 and O20.
4. Guide updates (brief §11, plus the header colour and the `Select shown` pattern) after the user confirms; `docs/` was not edited.
