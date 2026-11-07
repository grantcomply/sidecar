# UI Design Brief: rekordbox Drag to Deck

> **Author:** UI designer agent. **Date:** 2026-11-06.
> **Companions:** `architect-blueprint.md` (ADR-016), `implementation-plan.md` (same folder). Both were revised in place to match this brief; see `## UI revisions applied` at the end of the plan.
> **Status:** Proposed. Phase 3 starts only after Phase 0 Gate A and Gate B pass (plan). Everything here is conditional on that.
> **Scope rule:** nothing outside this folder was changed. `docs/ui-design-guide.md` updates are listed in §9 and applied at ship time (plan T4.5).

---

## 0. Read this first: four things the user must know

1. **This is a drag, not a click.** The DJ cannot press a button in Sidecar and have a track appear on a deck (blueprint §1.3). The UI must never use the words "Load", "Loaded" or "Sent" for what the handle does. The honest verb is "Drag".
2. **Dragging does not select the track.** Sidecar's own "pick" (click a row) still adds the track to the setlist and recomputes suggestions. A DJ who drags a suggestion to a deck and later wants the setlist to follow must still click the row. That is an extra step in the core loop (O2 below). It is the right default, because Sidecar cannot tell whether the drop landed.
3. **There is no drag ghost, so the row has to say which track is in flight.** tkdnd on Windows shows only the OS copy cursor, not a picture of the track. The brief therefore keeps the source row visibly tinted for the whole drag (§3).
4. **The minimum window already clips the right side of the suggestion grid.** The grid is about 650 px wide (`source/ui/suggestion_panel.py:82-86` plus padding) and does not reflow. At the 1000x650 minimum with a 50/50 split the pane is about 470 px, so Energy, Genre, Play and `+` are already off-screen. A handle added at the right end would be invisible at the minimum window, so placement is the biggest decision in this brief (O1).

---

## 1. User goal

**Get the exact track I am looking at onto a rekordbox deck, with the fewest moves and no chance of loading a different track, while my eyes are on the set.**

## 2. Panels and components affected

```
┌ Row 0  top bar ──────────────────────────────────────────────┐
│  toast (refusal toast lands here)                       ⚙   │
├ Row 1  Now Playing dashboard ────────────────────────────────┤
│  artist / title                                              │
│  [KEY] [BPM] [ENERGY] [GENRE] [DRAG TO DECK]   <- NEW tile   │
├ Row 2  paned split ──────────────────┬───────────────────────┤
│  Suggestions                         │  Setlist              │
│  header: [Deck] % Artist Title ...   │  (no change in v1)    │
│  row:    [⠿] 87% ...  ▶  +           │                       │
│           ^ NEW handle (leftmost)    │                       │
└──────────────────────────────────────┴───────────────────────┘
```

| Component | Change | Side of window |
|---|---|---|
| `SuggestionPanel` row grid | New handle column and header cell `Deck` | Left pane of the split |
| `NowPlayingDashboard` badges row | One new badge-shaped tile after GENRE | Row 1 |
| `SettingsDialog`, rekordbox card | One new On/Off setting (no dialog code change) | Modal dialog |
| Top-bar toast | Used for one refusal message | Row 0 |
| New shared widget `source/ui/drag_handle.py` | One handle widget with five visual states, used by both panels so they cannot drift | n/a |
| Setlist, search dropdown | **No change in v1** (see O3) | Right pane / Row 1 |

## 3. The drag handle

### 3.1 Where it lives, and why

- **Suggestion rows: yes.** This is where the next track is chosen (blueprint D5 priority 1).
- **Now Playing: yes**, as a badge-shaped tile. It is the only place a track found by *search* can be dragged from, because dropdown rows select on press (`source/ui/track_detail.py:264-266`).
- **Setlist: no in v1.** Re-loading a played track is a plausible later use; not asked for.
- **Whole-row drag: not recommended.** Rows select on press (`suggestion_panel.py:587`, `:627`), and a press-to-select row destroys itself (blueprint §1.4). Changing that alters the core click, which is the most-used interaction in the app.

### 3.2 Suggestion-row handle: look and size

| Property | Direction | Precedent |
|---|---|---|
| Position | **Leftmost column** (recommended, O1) | n/a; list-reorder grip convention |
| Hit size | **32 wide x 28 tall**, filling the row's height (existing play/add buttons are 32 x 24, `suggestion_panel.py:594-612`, which is small for a drag that must start on the first try) | `_COL` widths, `:82-86` |
| Shape | Rounded tile, corner radius 6 | stat-badge radius 10 (`track_detail.py:112`) scaled down; row radius 4 (`suggestion_panel.py:561`) |
| Resting | Fill `#2a2a2a` (card fill token, darker than both row stripes so it reads as a separate control), glyph `⠿` in `#999999` (secondary text token) | card fill `track_detail.py:112` |
| Hover | Fill `#1f6aa5` (accent, as the play button hover at `suggestion_panel.py:596`), glyph white; cursor `fleur` so it feels different from the clickable rows (`hand2`, `:562`) | |
| Dragging | Fill `#1f6aa5` held, glyph white; **source row tinted with the existing hover grey** (`hover_bg`, `:554`) until drag end | |
| Ineligible | Same tile, glyph `—` in `#555555` (the placeholder token and glyph already used for empty badges, `track_detail.py:100` / guide §3), no hover change, default cursor | |
| Always visible | Yes. Not hover-reveal. A DJ in a dark booth must not hunt for a control | |

Glyph note for the engineer: `⠿` (U+283F) should render through Windows font fallback; verify at 100% and 150% scaling in the T3.7 manual check. If it shows as a box, use `≡` (U+2261). Do not use an emoji.

**Colour-blind fallback (guide §7.2):** state is carried by shape as well as fill. Eligible shows a grip, ineligible shows a dash, and ineligible has a tooltip stating why. Dragging is also signalled by the tinted source row and the OS cursor.

### 3.3 Header cell

When the feature is available, the header row gains a cell `Deck` (10 bold, like the others, `suggestion_panel.py:166-169`) above the handle column. It is a column label, not an instruction, so it matches `Artist`, `Title`. It shows whenever the feature is available, even if every visible row is ineligible, so the grid does not jump between renders.

### 3.4 Now Playing tile

A fifth badge in `badges_frame` (`track_detail.py:92-100`), built like `_make_badge` (`:111-127`): `#2a2a2a` card, label `DRAG TO DECK` (9 bold uppercase, `#666666`), value a large `⠿` (22 bold, `#999999`; white on hover/drag with the card filled `#1f6aa5`). It is about 80 x 70 px, which is a generous target. Ineligible: value `—` in `#555555`, same as an empty badge. No track loaded or empty message showing: the tile is hidden (`set_empty_message`, `:142-149`, must not leave it visible).

At 1000 px wide the five badges fit in one row (four are about 80-100 px each, `:111-125`).

### 3.5 How it is discovered (no onboarding modal)

In order of cost:
1. **Always-visible handle plus the `Deck` header.** The primary mechanism.
2. **Tooltip on the handle** after the standard 400 ms (`source/ui/tooltip.py:7`).
3. **Settings hint** on the rekordbox card, where the DJ turns it on or off.
4. **README / install guide** text (plan T4.2).

Not recommended: a first-run toast or coach-mark. It needs a persisted "seen" flag, a new state, and would appear mid-set after an upgrade. Listed as an option under O4.

### 3.6 Drag feedback (what the DJ sees, step by step)

| Moment | Feedback |
|---|---|
| Pointer over handle | Fill `#1f6aa5`, `fleur` cursor, tooltip after 400 ms |
| Press, small movement | Nothing. Below the OS drag threshold nothing starts, and the row does **not** select (the handle has no `<Button-1>` select binding) |
| Drag starts | Handle held blue; source row tinted; any visible tooltip is hidden first (the engineer adds a public hide on `Tooltip`; today only the private `_hide` exists, `tooltip.py:36`). Force one `update_idletasks()` before returning to tkdnd so the tint paints before the OS modal loop starts |
| In flight | OS copy cursor (arrow with a plus). No Sidecar ghost image is available. The tinted row is the only record of which track |
| Drop on a deck | Sidecar shows **nothing**. Confirmation is the deck loading in rekordbox. This is deliberate (blueprint D7): Sidecar cannot know |
| Drop on nothing / Esc | Handle and row return to resting. No message |
| Drag refused (file missing) | Red toast, no drag starts (§6) |

Honest limitation to state to the user: the DJ confirms the right track by reading rekordbox's deck after the drop, which is the same check they already make for any load.

## 4. Pattern precedent

| New component | Closest existing pattern | Cite |
|---|---|---|
| Handle column / header cell | Play and `+` columns, `_COL` widths and header list | `source/ui/suggestion_panel.py:82-86`, `:154-169`, `:592-613` |
| Handle tile look | Stat-badge card fill and radius | `source/ui/track_detail.py:111-127` |
| Handle hover/blue | Play-button hover colour; filter pill accent | `suggestion_panel.py:594-600`; `source/ui/filter_bar.py` (guide §5 "Filter pill") |
| Ineligible `—` | Empty-badge placeholder | `track_detail.py:100`, guide §3 "Placeholder" |
| Now Playing tile | `_make_badge` | `track_detail.py:111-127` |
| Handle tooltip | `Tooltip` | `source/ui/tooltip.py:4-42`; row tooltip at `suggestion_panel.py:629-639` |
| Source-row tint | Row hover background | `suggestion_panel.py:554`, `:615-624` |
| Setting on rekordbox card | `auto_refresh` On/Off tiles | `source/providers/rekordbox/provider.py:98-108`; rendering `source/ui/sync_panel.py:232-271` |
| Refusal toast | `_show_toast` | `source/app.py:500-534` |
| Strings | `library_copy.py` constants | `source/services/library_copy.py:19-46` |

**New pattern, named explicitly:** a *drag handle* has no precedent in the app (no drag code exists, blueprint §1.4). It is built from existing parts (badge tile, play/add tile, accent hover), so no new colour or size is introduced. The one new **rule** is the hidden-versus-disabled split in §5.

## 5. States to handle

### 5.1 The four panel states (guide §6)

- **Loading.** No special handling. Handles exist only on rendered rows, and rows do not exist while the library is loading ("Reading your library…", guide §6). tkdnd loads in milliseconds at startup (blueprint D4), so there is no spinner. A sync or live refresh re-renders rows quietly and the `_dragging` guard (D6) holds the list steady during a drag.
- **Empty.** No handles, no new copy. The `Deck` header follows the feature gate, not row count (§3.3). Existing empty messages (`suggestion_panel.py:56-76`) are unchanged.
- **Error.** One error: a drag refused because the file is missing (§6, toast). A tkdnd or platform failure is not an on-screen error; the control is simply absent (hidden rule below) and the cause is logged.
- **Success.** Silent by design (§3.6). No toast, no "Loaded".

### 5.2 The availability matrix

The rule, and a proposed refinement of ADR-015 D12 (see §8):
- **Feature unavailable → hide the whole column and tile.** There is nothing the DJ can do in the row, and Serato-only users should never see rekordbox UI.
- **Feature available but this track is ineligible → show the tile disabled with a reason.** A silent gap in a row makes a DJ wonder whether the app is broken, and mid-set that costs seconds.

| Situation | Handle column + header | Row handle | Now Playing tile |
|---|---|---|---|
| `deck_drag` setting **off** | Hidden | n/a | Hidden |
| **Serato-only library** (rekordbox not enabled) | Hidden | n/a | Hidden |
| **Mixed library, track in rekordbox** (`sources[0]` is rekordbox, including tracks in both) | Shown | Active | Active |
| **Mixed library, Serato-only track** | Shown | **Disabled `—`**, tooltip `Not in your rekordbox library, so it can't be dragged to a deck` | Disabled `—`, same tooltip |
| **tkinterdnd2 missing or fails to load** | Hidden | n/a | Hidden. Warning logged. See O5 |
| **macOS** (until `DECK_DRAG_PLATFORMS` gains `"darwin"`, plan T4.4) | Hidden | n/a | Hidden. Settings row also hidden (see §7.3) |
| **File missing at drag start** | Shown | Active; drag refused with a red toast (§6) | Same |
| No track on Now Playing | n/a | n/a | Hidden |

## 6. Microcopy

All strings go in `source/services/library_copy.py` (guide §8), as constants with unit tests in the existing `tests/services/test_library_copy.py`. Sentence case; UPPERCASE only on the tiny badge label; "rekordbox" always lowercase.

| Where | Text | Notes |
|---|---|---|
| Header cell | `Deck` | 10 bold, like other headers |
| Handle tooltip (active) | `Drag onto a rekordbox deck to load this track` | Imperative; the word "load" describes the DJ's drop result, not a Sidecar action |
| Handle tooltip (ineligible) | `Not in your rekordbox library, so it can't be dragged to a deck` | |
| Now Playing label | `DRAG TO DECK` | Uppercase per badge rule (guide §8) |
| Refusal toast, red | `Can't drag this track: its file is missing or moved` | 51 chars, under the 75 limit, no path, no title. Duration 6000 ms (longer than default 4000 because the DJ's eyes are on the handle or rekordbox, not the top bar). Colour: `ERROR_COLOR` (O6) |
| Setting label | `Drag tracks to decks` | Noun-phrase label in the same register as `Update automatically` |
| Setting hint | `Adds a grip to each track. Drag it onto a rekordbox deck to load that track.` | 77 chars, one grey line like the `auto_refresh` hint |
| Setting tiles | `On` / `Off` | Rendered by the existing CHOICE renderer |
| README sentence | `Drag the grip next to a track onto a rekordbox deck. Keep rekordbox and Sidecar visible side by side or on two screens, and don't run rekordbox as administrator.` | Plan T4.2 also adds the playing-deck-lock tip once S1c names the preference |

Words to avoid anywhere in this feature: "Load" as a Sidecar action, "Loaded", "Sent", "Success", "Deck 1/2" (Sidecar does not know which deck).

### Fallback-phase copy

| | Text |
|---|---|
| **F1 button** (a 48 px text button, not a grip, because it is a *click*) | `Show` |
| F1 header cell | `File` |
| F1 tooltip, Windows | `Show this file in Explorer. Drag it from there onto a rekordbox deck.` |
| F1 tooltip, macOS | `Show this file in Finder. Drag it from there onto a rekordbox deck.` |
| F1 failure toast, red | `Couldn't open the folder` |
| F1 setting hint | `Adds a Show button to each track. It opens the file's folder so you can drag it onto a rekordbox deck.` |
| **F2 button** | `Copy` |
| F2 header cell | `Name` |
| F2 tooltip | `Copy artist and title, then paste into rekordbox's search` |
| F2 toast, green | `Copied "{artist} - {title}"` (artist and title truncated to 25 characters each with `utils.truncate`) |
| F2 setting hint | `Adds a Copy button to each track. rekordbox finds the track from the pasted name; check it before you load.` |

F1 and F2 must never say "Load". F2 is not exact (the DJ confirms by eye), so its tooltip says "paste" and its hint says "check it".

## 7. Settings toggle (rekordbox card)

### 7.1 Is it needed? (O5, the architect's question)

**Recommended: keep it.** It costs one `SettingSpec` and zero dialog code (the card renders On/Off tiles from the spec, `sync_panel.py:232-271`, as it does for `auto_refresh`). It is the only way for a DJ who never drags to take back the 32 px the column adds, which matters at the minimum window (§0.4). Default **On** so the feature is discoverable.

### 7.2 Behaviour

Edits are staged and applied on Save (guide §5 "Settings dialog"). After Save the app recomputes the gate and the signature change re-renders the rows (plan T3.4/T3.6), so no restart is needed. A change is visible the moment the dialog closes.

### 7.3 macOS and honesty (open point for the architect)

The CHOICE spec is static, so on macOS the card would show a toggle that does nothing. A toggle that does nothing is a lie. Preferred: the rekordbox provider omits the `deck_drag` spec on platforms outside the allowlist, so the dialog (which never branches on provider id) shows nothing. This needs the provider to know the platform allowlist (today only `config.DECK_DRAG_PLATFORMS` holds it, plan T2.2). Fallback if the architect objects: keep the toggle and append `Windows only for now.` to the hint. Raised as O7.

## 8. Conflicts with the design guide and ADRs

1. **ADR-015 D12 "hidden while the gate returns None" (blueprint D8)** is applied here at the *feature* level (column and tile absent). At the *row* level (feature available, one track ineligible) this brief proposes **disabled with reason**, which D8's "If any condition fails, the control is hidden" does not allow. This is a refinement, not a reversal, and needs the architect and user to agree (O2). If rejected, the fallback is a blank spacer (the engineer's original T3.3), with the cost that a Serato-only row has an unexplained gap.
2. **Guide §6 Success** says outcomes are confirmed. Here there is none, deliberately (blueprint D7). Not a conflict, but a stated exception.
3. **Guide §3** forbids off-token colours. None are introduced: `#2a2a2a`, `#999999`, `#555555`, `#1f6aa5`, `#ffffff`.
4. **Guide §8** toast limit of 75 characters and no paths: met.
5. **ADR-015 D8 / coding standard #5** (read-only towards DJ apps): the UI does not conflict. The wording avoids implying Sidecar writes anything.
6. No conflict with ADR-014 (this brief also refuses to put the word "Load" on a button, for the same reason that plan was rejected).

## 9. Design-guide updates to apply at ship (plan T4.5)

Not done now (scope rule). At ship: §5 add a "Drag handle" row and a "Badge-shaped action tile" note; §5 Settings dialog row notes the new rekordbox setting; §6 note the silent-success exception for drag; §8 add the "never say Load for a drag" rule and the new strings; §9 record the answers to O1-O7.

## 10. Open questions (the user owns these)

- **O1 Handle position in the suggestion row.** (A) **Leftmost**, recommended. Pro: always visible at the 1000x650 minimum and at a narrow sash; matches the list-grip convention. Con: pushes every data column 32 px to the right, so at the minimum window BPM is the next casualty after Energy (already clipped). (B) **Rightmost, after `+`**. Pro: no data moves. Con: hidden at the minimum window and any pane narrower than about 690 px, which defeats discovery; the DJ must drag the sash to find it. Taste call, but B needs a decision on how a clipped handle is found.
- **O2 Ineligible rows.** Disabled `—` with a reason (recommended) or a blank gap (architect's original)?
- **O3 Searched tracks.** Selecting a search result adds it to the setlist and makes it Now Playing. A DJ who only wants to *load* a searched track must therefore "play" it in Sidecar's eyes first. Options: accept that (v1), or add a handle to the search dropdown rows later, which has the same press-to-select problem (`track_detail.py:264-266`) and needs its own design.
- **O4 Announce the new column to existing users?** Default On puts a new column in their layout after the upgrade. Options: say nothing (recommended, no new state), one-time toast (needs a persisted flag), or ship default Off (less discoverable).
- **O5 tkdnd fails on a supported platform.** The toggle still says On but no grips appear. Options: log and README troubleshooting only (recommended), or an amber issue line on the rekordbox card (needs the provider or app to expose that state to the dialog).
- **O6 Refusal toast colour.** Red (`#dc3545`, recommended: the DJ's action did not happen and must be noticed under time pressure; guide §3 lists "a real failure") or amber (`#ffc107`, nothing in Sidecar is broken)?
- **O7 macOS toggle.** Hide the spec off-platform (recommended) or keep it with `Windows only for now.`?
- **O8 (architect O2, restated).** Should a drag also select the track and add it to the setlist? Recommended **no**, because Sidecar cannot tell whether the drop landed, so a wrong or aborted drag would write a false setlist entry. The cost is one extra click when the DJ goes live with the track. If the user wants it, the safe version is a separate explicit step, not an automatic one.

## 11. Risks

- **Minimum window and pane widths.** Covered in §0.4 and O1. Very wide pane: nothing changes (columns are fixed width and left-aligned). Very narrow pane: the leftmost handle stays visible and data clips on the right as it does today. The Now Playing tile wraps nowhere; at 1000 px the five badges fit.
- **No ghost image, no confirmation.** The tinted row and the rekordbox deck itself are the only checks (§3.6). The worst failure, the wrong track, is prevented by the payload being the row's own path (blueprint §7), not by the UI.
- **Wrong deck / playing deck.** Sidecar cannot see rekordbox's decks. Mitigation is documentation only (rekordbox's playing-deck lock, name from spike S1c).
- **Tooltip window left on screen** during the OS modal drag, because `<Leave>` may not fire. Hide it explicitly on drag start (§3.6).
- **Visual repaint during the modal drag loop.** Tk timers pause (blueprint D6, S2e). Paint the tint before returning to tkdnd, and verify in S2e.
- **Tint stuck.** If `<<DragEndCmd>>` does not fire on a cancelled drag, the row stays tinted and the `_dragging` guard blocks re-render. Test Esc-cancel and drop-on-nothing in T3.7; add a safety reset on the next `<Motion>`/`<ButtonRelease>` over the panel if it can occur.
- **Colour-blind:** state is carried by glyph shape (grip vs dash), tooltip text and the tinted row, not by fill alone. The dragging state is colour-only on the handle itself, backed by the OS cursor.
- **CTk scaling at 150%.** Glyph rendering and the 28 px height need the T3.7 check.
- **Mouse-only.** No keyboard path, consistent with known debt (guide §7.6, not re-flagged).
- **User expectation.** A DJ who reads "Drag to deck" as "click to load" will look for a button. The tile label and tooltip say "drag" in the first words, and the README leads with it.
