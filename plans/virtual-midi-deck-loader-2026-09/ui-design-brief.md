# UI Design Brief: Virtual MIDI Deck Loader

> **For:** Engineer agent + user sign-off
> **Companion:** `architect-blueprint.md`, `implementation-plan.md` (same folder)
> **Reads:** `docs/ui-design-guide.md`, `source/ui/track_detail.py`, `source/ui/sync_panel.py`,
> `source/ui/tooltip.py`, `source/app.py`
> **Status:** Settles every `<!-- UI-designer to revise -->` placeholder except the ones that are
> genuinely the user's call (O1, and the new questions this brief raises). Does **not** decide O1.

---

## User goal

A DJ wants to get the track they just picked in Sidecar onto a physical deck in Serato without
digging through Serato's own library mid-set — ideally in one or two glanceable clicks, without
risking the wrong track landing on the deck they're about to play.

**Important correction to the request's mental model, carried over from the architect's §1.3:**
MIDI cannot tell Serato *which* track to load — only Serato's own highlighted-in-library track
gets loaded. Under the architect's recommended Option B, Sidecar's job is to make it fast and
low-friction to get the right track highlighted in Serato, then fire the load. The UI must never
imply the click loads "the Sidecar track" directly.

---

## Panels / components affected

| Component | Status | Window location |
|---|---|---|
| `NowPlayingDashboard` (`source/ui/track_detail.py`) | Extended | Row 1 (dashboard) |
| `MidiConfigDialog` (new, `source/ui/midi_config_dialog.py`) | New | Free-floating `CTkToplevel`, non-modal |
| Top bar (`source/app.py` `_build_ui`) | Extended | Row 0 |
| Warning toast (`app._show_toast`) | Extended (new colour) | Row 0 |
| `SuggestionPanel` (`source/ui/suggestion_panel.py`) | **Not changed** (confirms architect O2) | Row 2, left pane |
| `SettingsDialog` (`source/ui/sync_panel.py`) | **Not changed** (see O4 decision below) | — |

---

## Central design decision: split "Copy" from "Load" (revises T4.3)

The blueprint's Option B bundles clipboard-copy and MIDI-fire into a single click
(`implementation-plan.md` T4.3, flagged `<!-- UI-designer to revise -->` for ordering). **That
ordering doesn't work in the booth:** the moment the button is clicked, Sidecar fires the MIDI
load *immediately* — before the DJ has had a chance to alt-tab to Serato, paste, and confirm the
right track is highlighted. A single combined click would load whatever Serato had highlighted
*before* the click, not the intended track. That's worse than doing nothing, because it looks
like it worked.

**Decision: two separate controls, used in sequence.**

1. **Copy Track Name** — copies `"Artist Title"` to the clipboard. Always available (no MIDI
   dependency at all — pure Tk `clipboard_append`).
2. **Load Left Deck** / **Load Right Deck** — fires the MIDI trigger only. Disabled/hidden per
   MIDI connection state (below).

The DJ's flow: click **Copy Track Name** → alt-tab to Serato → paste into its search → confirm
the right track is highlighted → alt-tab back (or use Serato's own shortcut) → click **Load Left
Deck**. Still two clicks in Sidecar plus a manual step in Serato, same as before, but it no longer
race-conditions itself.

This is a genuine change to the blueprint's click model, not a cosmetic copy edit — flagging for
explicit user sign-off in Open Questions below, since Option B's appeal partly rested on being
"one click."

---

## Pattern precedent

- **Stat badge / track_frame layout** — `source/ui/track_detail.py:67-99` (`track_frame`, rows
  0-3: artist, title, badges, info line). The new deck-action row is **row 4** of the same frame,
  following the same `grid_columnconfigure(0, weight=1)` / `sticky="w"` convention.
- **Transient button text-swap** — `source/ui/sync_panel.py:75-80` (`set_syncing`: button text
  flips to `"Syncing..."` and disables during the operation). The **same mechanic** covers the
  Load buttons' "Sending…" and "Sent ✓" feedback states (see States, below) — no new component
  needed.
- **Toast notification** — `source/app.py:137-171` (`_show_toast`), colour-coded, optional inline
  action button, auto-dismiss. Reused as-is for the MIDI warning toast; only the colour is new
  (see Design-guide conflicts).
- **Modal dialog** — `source/ui/sync_panel.py:7-83` (`SettingsDialog`) is cited by the blueprint
  as the model for `MidiConfigDialog`, but `SettingsDialog` calls `grab_set()`
  (`sync_panel.py:16`), and `MidiConfigDialog` **must not** be modal (the DJ has to click into
  Serato while it's open). This is construction/centring precedent only, not a modal precedent —
  see Design-guide conflicts, this needs a new pattern row.
- **Hover tooltip** — `source/ui/tooltip.py`. Used for the honesty caveat on the Load buttons and
  for disabled-state explanations, exactly as it's used elsewhere.
- **Top-bar icon button** — `source/app.py:70-78` (`settings_btn`: 32×32, transparent, grey icon,
  hover-highlight). The MIDI entry-point button matches this shape.

No existing precedent for: a non-modal control surface, or a "live/firing" repeating state with
an auto-stop cap. Both are named as new patterns below rather than forced into old ones.

---

## Now Playing dashboard: deck-action row

Sits as **row 4** of `track_frame`, below the existing info line (`track_detail.py:95-99`).
ASCII layout (fits comfortably at the 1000px minimum window width; `track_frame` currently uses
~600-700px of it):

```
[ Copy Track Name ]     [ ◀ Load Left Deck ]   [ Load Right Deck ▶ ]
```

- Left-aligned, matching every other row in `track_frame`.
- **Copy Track Name**: small secondary button (grey, like `browse_btn` styling in
  `sync_panel.py:35-39`), ~150px wide, height 30. Always enabled once a track is selected; not
  gated on MIDI at all.
- **Load Left/Right Deck**: accent-coloured buttons (theme default blue), ~170px wide, height 30,
  with a small gap (24px) after the Copy button to visually separate "prep" from "fire." Arrows
  (`◀`/`▶`) point toward the deck side they represent — a fast laterality cue that resolves
  before the label text does, which matters at booth-glance speed.
- Whole row is **hidden** (not just disabled) via `grid_remove()` when `MIDI_ENABLED` is `false`
  (the default) — see States below for why.

---

## States

Following design-guide §6 (loading / empty / error / success), applied to the **MIDI feature as
a whole**, not just one widget:

- **Loading (connecting).** At startup with `MIDI_ENABLED=true`, or after "Connect" in the
  dialog: Load buttons disabled, dialog status line reads `"Connecting…"`. Mirrors
  `SettingsDialog.set_syncing()`'s text-swap-and-disable, not a spinner (`sync_panel.py:75-80`).
- **Empty (no port found / MIDI off).**
  - `MIDI_ENABLED=false` (default): deck-action row is **hidden entirely** in the dashboard — a
    DJ who hasn't opted in shouldn't see buttons that don't work. Discovery happens through the
    MIDI entry point in the top bar (always visible), not through a disabled row in the
    dashboard. This follows the guide's placeholder convention of *"tell the user what to do,"*
    not *"what's missing"* (§8) — but here the right move is to not show the control at all
    rather than show a disabled one with an empty-state label, because it's opt-in, not a normal
    empty state like "no track selected."
  - `MIDI_ENABLED=true`, no port found (`NO_PORT`): deck-action row **shown but Load buttons
    disabled**, tooltip explains why (copy below). Dialog's port dropdown shows a disabled
    placeholder row `"No ports found"` and the setup-help text is visible without scrolling.
- **Error.** Send failure / lost connection (`ERROR`): Load buttons disable, dialog status line
  and (if the warning-toast policy applies) a toast state that names the failure plainly, per
  §8's *"Errors name what failed and stay short"* — see Microcopy.
- **Success (connected).** Load buttons enabled, accent colour. Dialog status line shows a green
  dot **plus text** (`"● Connected — loopMIDI Port 1"`), so colour is never the only signal
  (addresses guide debt #2 proactively for this one new surface, without expanding scope). No
  toast on successful connect — the dialog (if open) and the now-enabled buttons are the
  glanceable confirmation; a toast here would be noise, not signal.
- **Just sent (new, feature-specific micro-state).** After a Load click: button text swaps to
  `"Sending…"` (disabled, ~150 ms) then `"Sent ✓"` (~600 ms) then reverts to its normal label.
  This both gives the DJ confidence the click registered *and* acts as the double-click guard the
  blueprint's R2 asks for (`architect-blueprint.md:241`) — no separate timer needed, the disabled
  window *is* the debounce. Same mechanic for **Copy Track Name** → `"Copied ✓"`.

---

## MIDI Config dialog (`MidiConfigDialog`)

**Not modal** — confirmed against `SettingsDialog`'s `grab_set()` (`sync_panel.py:16`), which
this dialog must *not* call, because the DJ needs to click into Serato's own window while this
one stays open. `transient(master)` only (keeps it above the main window, doesn't steal focus
exclusivity). This is a genuinely new dialog *shape* for this codebase — see Design-guide
conflicts.

Region layout (construction/centring pattern from `sync_panel.py:57-64`; everything else new):

```
┌ MIDI Config — Serato Sidecar v0.1.6 ──────────────── [x] ┐
│ Port     [ Auto (recommended)          ▾]  [Refresh] [Connect] │
│ Status   ● Connected — loopMIDI Port 1                         │
│                                                                 │
│ Setup: (platform-specific help text + link, see copy below)    │
│ ──────────────────────────────────────────────────────────── │
│ Test & mapping                                                 │
│  [ Emit Test Signal — Deck 1 ]   [ ] Repeat every 2s            │
│  [ Emit Test Signal — Deck 2 ]   [ ] Repeat every 2s            │
│  ⚠ Once mapped, every signal really loads a track in Serato.   │
│    Stop repeating before you play.                              │
│                                                                 │
│ Mapping steps in Serato: (numbered list, see copy below)        │
└─────────────────────────────────────────────────────────────┘
```

- **Port dropdown**: `CTkOptionMenu`. Loopback-eligible ports listed first (unsuffixed);
  non-loopback ports (e.g. `Microsoft GS Wavetable Synth`, any hardware controller) appended with
  a suffix and visually muted (grey text), never hidden — a DJ debugging a bad setup still needs
  to see what's available, but nothing suggests picking them is safe.
- **Repeat toggle**: `CTkSwitch` (not a checkbox — matches CTk's toolkit-provided affordances and
  gives a clearer "on = actively firing" read than a checkbox). Label next to the active switch
  changes to a live countdown: `"Repeating — 9 left (stops in ~18s)"`, and the switch itself
  should read as visually "hot" while firing (e.g. a filled/accent track, not just position) —
  this is the "clear firing state" the architect's D10 asks for. When the auto-stop cap or the
  other deck's toggle stops it, the switch visually returns to off; don't rely on the DJ noticing
  a label change alone.
- **Mapping steps list**: keep **generic, non-Serato-menu-specific wording** until Phase 0's
  findings are recorded (`implementation-plan.md` "Phase 0 findings," currently empty). Don't
  invent exact menu names — placeholder copy below is deliberately vague on Serato's menu path
  and should be tightened once T0.1 reports back.

---

## Top bar entry point (settles O4)

**Recommendation: a single entry point, in the top bar, always visible** (not inside
`SettingsDialog`).

- A small icon-only button, same shape as the existing gear (`app.py:70-78`: 32×32, transparent,
  grey, `hover_color=("gray75","gray35")`), placed **to the left of** the gear at column 1 (gear
  moves to column 2, per the blueprint's T3.4 note).
- Label: short text glyph `"MIDI"` at 11pt rather than a Unicode icon — CTk's default font glyph
  coverage for music/plug symbols is inconsistent across Windows/macOS, and a DJ scanning the top
  bar under stage lighting reads three legible letters faster than guessing an ambiguous icon.
- **Always visible**, even when `MIDI_ENABLED=false` — this is the feature's only discovery path
  (the dashboard row is hidden when disabled, by design above), so it must not also be hidden.
- Not duplicated inside `SettingsDialog`. One entry point is easier to keep in sync with dialog
  singleton state (`app.py:227-237` pattern) and avoids two code paths opening the same
  `CTkToplevel`. If the user wants a second path for discoverability, it's cheap to add later —
  flagged as an open question below rather than built speculatively.
- **Status affordance** on the button itself is intentionally left open — see Open Questions
  (two options, differing in how much "colour is data" territory this claims).

---

## Microcopy

**Case:** button labels in this codebase already use Title Case (`"Sync Crates"`, `"Browse"`),
not the sentence-case rule that governs body text/messages (§8) — followed here for consistency,
not as a deviation from the guide (the guide's rule was written for body text and toasts; button
labels were already Title Case before this feature).

### Dashboard

| Element | Copy |
|---|---|
| Copy button (default) | `Copy Track Name` |
| Copy button (feedback) | `Copied ✓` |
| Copy tooltip | `Copies "Artist – Title" so you can paste it into Serato's search.` |
| Load Left (default) | `◀ Load Left Deck` |
| Load Right (default) | `Load Right Deck ▶` |
| Load button (sending) | `Sending…` |
| Load button (sent) | `Sent ✓` |
| Load tooltip (always, any state) | `Sends the load command to Serato. Serato loads whichever track is highlighted in its own library — paste the copied name into Serato's search first.` |
| Load tooltip (disabled, no port) | `MIDI not connected. Open MIDI Config to set up a port.` |
| Load tooltip (disabled, connecting) | `Connecting to MIDI…` |

### MIDI Config dialog

| Element | Copy |
|---|---|
| Title | `MIDI Config — Serato Sidecar v{version}` |
| Port label | `Port` |
| Port dropdown default | `Auto (recommended)` |
| Port dropdown, non-loopback entries | `{port name} (not a loopback port)` |
| Port dropdown, empty | `No ports found` (disabled row) |
| Refresh button | `Refresh` |
| Connect button | `Connect` |
| Status — connected | `● Connected — {port name}` |
| Status — connecting | `Connecting…` |
| Status — no port | `⚠ No port found` |
| Status — error | `✕ Lost connection to {port name}` |
| Status — unavailable | `✕ MIDI driver not available on this system` |
| Setup help, Windows | `Serato needs a virtual MIDI port to receive signals from Sidecar. Install loopMIDI (free), create a port, then select it above.` + a `Download loopMIDI` link button (opens browser, same pattern as the update toast's action button, `app.py:215-223`) |
| Setup help, macOS | `Open Audio MIDI Setup → IAC Driver → check "Device is online" — or leave this on Auto to use Sidecar's own virtual port.` |
| Section header | `Test & mapping` |
| Test button, Deck 1 | `Emit Test Signal — Deck 1` |
| Test button, Deck 2 | `Emit Test Signal — Deck 2` |
| Repeat switch label | `Repeat every 2s` |
| Repeat active label | `Repeating — {n} left (stops in ~{n*2}s)` |
| Repeat safety line (always visible near the switches, not just while firing) | `Once mapped, every signal really loads a track in Serato. Stop repeating before you play.` |
| Mapping steps header | `Map these signals in Serato` |
| Mapping steps (placeholder — confirm exact Serato menu path from Phase 0 findings before shipping) | `1. In Serato, turn on MIDI Assign mode. 2. Click the deck's Load control in Serato. 3. Click "Emit Test Signal" for the matching deck here. 4. Turn off MIDI Assign mode to save the mapping.` |
| §1.3 limitation, one line, always visible in the dialog | `Serato loads whichever track is currently highlighted in its own library — not the track selected in Sidecar.` |

### Warning toast (D7)

Matches the existing toast voice — *"states the outcome plainly"* (§8) — and only fires once per
state transition into a warning state, not on every retry:

| Platform / condition | Toast text | Action button |
|---|---|---|
| Windows, no port | `MIDI enabled but no port found. Start loopMIDI, then reconnect.` | `MIDI Setup` |
| macOS, no port | `MIDI enabled but no port found. Enable the IAC Driver, then reconnect.` | `MIDI Setup` |
| Driver unavailable | `MIDI driver not available on this system.` | `MIDI Setup` |

Duration: **10000ms** (architect's suggestion) — in line with the existing scale where more
context-switch-y toasts run longer (update toast: 15000ms, `app.py:220`; plain sync toasts:
4000ms default). Action button label styled identically to the existing `"Download"` /
`"MIDI setup"`-style toast action buttons (`app.py:159-169`).

---

## Design-guide conflicts / proposed additions (not applied — brief only)

1. **New colour token needed.** §3's status-colour table has Success / Error / Info but no
   **Warning**. The MIDI "no port found" toast needs one. Proposed addition: `Warning` /
   `#ffc107` / *"Non-blocking caution — needs attention but doesn't block the app (e.g. MIDI port
   not found)."* Also reuse for the dialog's `⚠` status line.
2. **New dialog pattern.** §5's only documented dialog pattern is `SettingsDialog`, which is
   explicitly modal (`grab_set()`). `MidiConfigDialog` is the first **non-modal** `CTkToplevel` in
   the app. Propose a new §5 row: *"Non-modal control dialog — `CTkToplevel`, `transient()` only,
   no `grab_set()`. Used when the user must interact with another application while the dialog is
   open."* Don't let engineers copy `grab_set()` from `SettingsDialog` by habit.
3. **New micro-pattern: transient button text-swap with auto-revert.** Currently only exists as
   the specific case `SettingsDialog.set_syncing()` (permanent until sync finishes). This feature
   introduces a *timed*, auto-reverting version (`"Sending…"` → `"Sent ✓"` → back). Worth
   promoting to a named §5 pattern since it's the debounce mechanism as well as the feedback
   mechanism — likely reusable (e.g. "Add to session" style actions elsewhere).
4. **A "firing/live" repeat state has no precedent anywhere in the app.** Nothing currently loops
   an action on a Tk `after()` timer with a visible countdown and a hard cap. Worth a §5 entry
   once built, for any future "auto-repeat" control.

---

## Open questions (for the user — not settled by this brief)

1. **O1 (architect's, unresolved).** UX view for the record: Option B is the only one that
   attempts real value, but only if the Copy/Load split above is accepted — a single combined
   click cannot work correctly given the timing (see "Central design decision"). If the user
   would rather have the simpler, more honest Option A (global load-trigger-only buttons, not
   tied to a Sidecar track at all), the whole dashboard row goes away and two small buttons move
   into the top bar instead, always enabled once connected, with tooltip *"Loads whichever track
   is selected in Serato onto this deck."* That's a materially simpler build. The user should
   pick knowing this brief already assumes Option B either way for §Phase 3/4 sizing.
2. **Copy/Load split (new, raised by this brief).** Confirms whether the two-click,
   two-button sequence above is acceptable, or whether the user would rather accept the
   race-condition risk of a single combined button for speed. Recommend the split; flagging
   because it changes the click-count promise implicit in the original request.
3. **Accidental-load guard.** Plain, fast click on Load (relying on Serato's own "Protect
   playing deck" setting, once Phase 0 confirms it exists) vs. some in-app friction (e.g.
   press-and-hold, or a confirm-on-first-use-only toast). Recommend the plain click — matches
   "low click-count," "never blocking" — but this is a live-safety tradeoff the user should
   confirm, not one to default silently.
4. **Top-bar MIDI button status affordance.** Plain icon-style button (matches the gear, no
   status leak into the top bar) vs. a small connection-state indicator on the button itself
   (colour/dot, requiring a non-colour fallback per debt #2). Recommend starting plain — simpler,
   avoids clutter — and revisit if users report not noticing disconnects.
5. **Second entry point for MIDI Config inside `SettingsDialog`.** Recommend against it for now
   (single source of truth); confirm if discoverability turns out to be a problem.
6. **Mapping-steps copy.** Genuinely blocked on Phase 0's findings (exact Serato menu names) —
   not a taste call, just needs the spike's output before shipping.

---

## Risks

- **Accessibility / colour-blind fallback (§7.2).** Addressed for the dialog's status line (dot +
  text, not colour alone). The Load buttons' enabled/disabled states rely on CTk's built-in
  disabled styling (dimmed, not colour-only) plus the tooltip text — acceptable, but note the
  "just sent" flash uses a checkmark glyph, not colour, for the same reason.
- **Minimum window (1000×650).** The three-button dashboard row (`Copy Track Name` + two Load
  buttons, ~150+170+170px plus gaps ≈ 520px) fits well inside `track_frame`'s available width at
  minimum size, since the dashboard already spans the full window width at row 1. No wrapping
  logic needed, but this should be visually confirmed once built rather than assumed.
- **Extreme pane widths.** Not applicable — the dashboard sits above the paned split (row 1), not
  inside either pane.
- **Toast collision.** If a MIDI warning toast fires around the same time as a sync toast or the
  update-available toast, only one shows (existing `_show_toast` cancels/replaces the prior
  toast, `app.py:152-155`). Acceptable — matches existing single-toast-at-a-time behaviour, not a
  new problem this feature introduces, but worth the engineer's awareness since MIDI's startup
  connect and the update check both fire near app launch.
- **Repeat-mode visual clarity under time pressure.** The "firing" state must be unmistakable at
  a glance, since a forgotten repeat really loads tracks in Serato. The switch-track-colour +
  countdown-label combination is the recommended minimum; if the user finds it too subtle in
  practice, a flashing/pulsing accent could be considered, but CTk has no built-in animation
  primitive — would need a manual `after()`-driven colour toggle, which is more complexity than
  this brief recommends starting with.
