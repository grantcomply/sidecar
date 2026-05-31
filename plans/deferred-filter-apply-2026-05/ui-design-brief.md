# UI Design Brief — Deferred Filter Apply

> **Status:** Proposed
> **Date:** 2026-05-30
> **Author:** UI Designer agent
> **Plan folder:** `plans/deferred-filter-apply-2026-05/`
> **Companion:** `architect-blueprint.md` (state model), `implementation-plan.md` (task list)

---

## User goal

The DJ needs to make multiple filter adjustments without triggering a re-score on every
tap — staging all changes privately and firing exactly one re-score when they are ready,
without losing their place in the suggestion list mid-edit.

---

## Panels / components affected

| Component | Location in window layout | New or changed |
|-----------|--------------------------|----------------|
| `SuggestionPanel` — Apply/Cancel bar | Row 2, left pane, below the scroll frame | **New** |
| `FilterBar` — pill dirty indicator | Row 2, left pane, filter bar row | **Changed** (subtle staged state on pills) |
| `FilterBar` — "Reset filters" link | Row 2, left pane, right end of filter bar | **Changed** (label + placement) |
| `DateRangeControl` — overlay internal "Apply" button | Inside the date floating overlay | **Changed** (rename to avoid collision) |

---

## Pattern precedent

| Design element | Precedent | Notes |
|----------------|-----------|-------|
| Apply/Cancel bar as a bottom-anchored panel row | `source/ui/suggestion_panel.py:149–151` — the column-headers row uses `grid()` / `grid_remove()` for show/hide without layout jump. The Apply bar follows the same pattern: a fixed-height `CTkFrame` in its own grid row, hidden via `grid_remove()` when not dirty, shown via `grid()` when dirty. | No new pattern required. |
| Primary / secondary button pair | `source/ui/sync_panel.py` `SettingsDialog` — the modal's button row uses one accent-coloured action button and one neutral secondary. | Apply = accent blue; Cancel = neutral grey. |
| Pill colour-coding to convey state | `source/ui/filter_bar.py:384` `_update_label` — grey pill = no filter active, accent blue = filter narrowing. | Staged-but-unapplied uses a lighter tint of the accent (see §Staged affordance below). |
| Toast feedback on action completion | `source/app.py:137` `_show_toast` — transient top-bar message, colour-coded by outcome. | Apply completion uses this for user feedback. |
| "Reset filters" right-anchored label | `source/ui/filter_bar.py:729–739` — `CTkLabel` with `cursor="hand2"`, grey / white hover, `grid_remove()` when not needed. | Placement and style unchanged; label copy updated. |

---

## Apply/Cancel bar — detailed specification

### Placement

The bar is a `CTkFrame` that lives as a **grid row in `SuggestionPanel`**, anchored at
the bottom below the scroll frame. In the existing row numbering:

```
Row 0 — "Suggestions" header
Row 1 — FilterBar (minsize=36)
Row 2 — Column headers
Row 3 — CTkScrollableFrame (weight=1, expands to fill available height)
Row 4 — Apply/Cancel bar (NEW, fixed height, hidden by default)
```

`grid_rowconfigure(3, weight=1)` keeps the scroll frame as the expanding element.
Row 4 has no weight — it takes only its natural height (40px). This means the bar
**slides in below the list** rather than pushing the list up, avoiding the layout jump
the DJ would see mid-set.

When hidden, `grid_remove()` is used (not `grid_forget()`), so the row shrinks to zero
height rather than remaining as whitespace.

### Visual design

The bar is a `CTkFrame` with `fg_color=("gray20", "gray20")` and a 1px top border in
`#333333` (Sash token, design guide §3) to visually separate it from the scroll frame.
Internal padding: `padx=8, pady=6`.

Contents, left to right:

1. **"Filters changed" label** — `CTkLabel`, text `"Filters changed"`, size 12,
   `text_color="#999999"` (Secondary text token). This is the glanceable signal in a
   dark booth that something is staged.

2. **Spacer** — `grid_columnconfigure(1, weight=1)` pushes the buttons to the right.

3. **Cancel button** — `CTkButton`, text `"Cancel"`, height 30, width 80,
   `corner_radius=6`. Styling: `fg_color=("gray35", "gray35")`,
   `hover_color=("gray45", "gray45")`, `text_color="#ffffff"`. This is the secondary
   button; it must be clearly clickable but subordinate to Apply.

4. **Apply button** — `CTkButton`, text `"Apply"`, height 30, width 80,
   `corner_radius=6`. Styling: `fg_color="#1f6aa5"` (ACCENT_BLUE token),
   `hover_color="#2980c0"`, `text_color="#ffffff"`, `font=CTkFont(size=12,
   weight="bold")`. Apply is the primary action — accent colour, bold text.

Both buttons: height 30px and width 80px give a click target that is usable in a dark
booth without being visually heavy. Do not make them shorter or narrower.

The right-to-left reading order (Cancel then Apply) is intentional: the DJ scanning
right sees Apply first, which is the expected next action. Cancel is there for a quick
bail-out but should not be the accidental first target.

### Appearance / disappearance

Dirty → `grid()` called on the bar frame. Not dirty (after Apply or Cancel) →
`grid_remove()`. Because the bar occupies Row 4 with no weight, the scroll frame in
Row 3 simply expands to fill the freed space; there is no midair list-jump. The
transition is instantaneous — no animation is needed or possible in CustomTkinter.

**There is one timing concern:** when the bar appears on the first dirty change, Row 3
shrinks by 40px. This is unavoidable but acceptable because the DJ has just interacted
with a filter (a deliberate action), so a small layout shift at that moment is not
surprising. The shift only happens once per editing session (first dirty), not on every
tick.

---

## Staged-but-unapplied affordance on filter pills

### Decision: use a lighter tint, not an outline or dot

The existing pill visual language is binary: grey (no filter) / accent blue (filter
active, `#1f6aa5`). A third state — staged-but-not-yet-applied — must be
distinguishable without looking identical to the applied state.

**Staged state colour:** `#3a88c8` — a lighter, less saturated step above `#1f6aa5`.
This reads as "blue, but softer" — not as vivid as the applied accent, clearly
different from the grey default. At arm's length in a dark booth it reads as "this
filter is doing something, but maybe not fully committed yet."

**Applied state colour:** unchanged `#1f6aa5` (full accent blue).

**Rule:**
- Pill is grey (`NEUTRAL_PILL`) when the staged value is the default (no filter).
- Pill is staged-tint (`#3a88c8`) when the staged value is non-default AND differs from
  the applied value.
- Pill is accent blue (`#1f6aa5`) when the staged value matches the applied value and
  is non-default (i.e., a filter is active and has been applied).

In practice, at initial state all pills are grey (both staged and applied are default).
After Apply, active-filter pills become full accent blue. Between editing and Apply,
only pills whose value has changed since the last Apply use the staged tint.

This is a **subtle signal** — the DJ does not need to track which pills are staged
individually. The Apply/Cancel bar already provides the primary "something is pending"
signal. The pill tint is supplementary: it answers "which controls did I touch?" without
cluttering the bar.

### Implementation note for the engineer

`FilterDropdown._update_label()` currently drives the pill colour from `selected vs
total`. After this change, `_update_label()` must also accept (or read) an
`is_applied` flag so it can choose between the staged tint and the full accent. The
panel controls this flag on each `_on_staged_change()` call, pushing it to each pill.
Add a `set_applied_state(applied: frozenset | None)` method on each control that the
panel calls on Apply (to mark the new applied baseline) and on initial render. Between
edits and Apply, the pill reads its own staged value and compares against the last
pushed applied baseline to pick its colour.

Alternatively (simpler): the panel, on each `_on_staged_change()`, pushes a
`mark_staged(bool)` flag to each control — True if that control's current staged value
differs from the applied snapshot. The control colours its pill staged-tint when
`mark_staged=True` and non-default, full-accent when `mark_staged=False` and
non-default. The panel derives this per-control by comparing the assembled
`current_staged_filters()` fields against `_applied_filters` field-by-field.

The simpler push approach is recommended — it avoids each control needing to store its
own applied baseline copy.

---

## Naming collision resolution (R2) — date overlay internal button

The date overlay currently has a `CTkButton(text="Apply", ...)` at
`source/ui/filter_bar.py:572–576`. This button applies the manual From/To entry into
the staged date value (it does not commit to the engine). With a new global "Apply" bar,
two "Apply" buttons with different scopes is a UX trap.

**New label: "Set dates"**

Rationale:
- "Set" is a common affordance word for "confirm this local entry." It is shorter than
  "Use range" and more specific than "Done."
- "Set dates" describes exactly what it does: confirm the manual date entry and stage
  it as the date filter value.
- It is clearly not the global commit action — "Set dates" is scoped, "Apply" is
  global.
- Length fits comfortably on a `width=70` button at size 11.

The button width can be reduced from 60 to 70px to accommodate the two-word label
without wrapping.

The error path (`_show_error`) does not change. The wiring to `_on_apply_manual`
does not change — this is a copy change only.

---

## "Reset filters" — label, placement, and staging behaviour

### Staging behaviour (confirmed from architect blueprint D6)

"Reset filters" now stages to defaults, exactly like any other filter change. It does
not apply. If staged defaults == applied state, it does not mark dirty (the Apply/Cancel
bar stays hidden). If they differ, the bar appears.

### Label

The existing label is `"Reset filters"` (`source/ui/filter_bar.py:729`). This remains
appropriate. It communicates "restore to the clean slate" — a distinct intent from
"Cancel" (which reverts to last-applied, not to defaults). The fact that it now requires
Apply to take effect is communicated by the Apply/Cancel bar appearing — the label
itself does not need to change. Adding "(staged)" or "Reset to defaults" would be
over-explaining for a booth context.

One adjustment: the "Reset filters" link visibility logic already keys off "any control
deviates from default" (`filter_bar.py:746–756`). After deferred apply, this remains
keyed off the **staged** values (the live controls), not the applied values. This is
correct — "Reset filters" is a shortcut for "set all staged values back to defaults"
and should appear whenever any staged value is non-default, regardless of whether it has
been applied.

### Placement relative to the Apply/Cancel bar

"Reset filters" stays in the `FilterBar` row (Row 1), right-anchored, as today. The
Apply/Cancel bar is in Row 4. They are visually separate — the reset link is part of
the filter controls row; the Apply/Cancel bar is a dedicated action affordance below the
list. There is no visual ambiguity about which is which.

**Reading the three affordances together:**

```
[Crates] [Genres] [Transition: same key] [Added: any time]   Reset filters
-------------------------------------------------------------------
[ Suggestions list scrolls here                              ]
-------------------------------------------------------------------
Filters changed                          [Cancel]  [Apply]
```

- "Reset filters" = "quickly stage all filters back to defaults, then decide whether to
  Apply or Cancel"
- "Cancel" = "discard everything I staged since the last Apply, go back to what the
  list was showing"
- "Apply" = "commit what I've staged and re-score"

These are three distinct mental models with three distinct labels. The DJ learns them
once; they do not conflict mid-set.

---

## States to handle

### 1. No changes staged (clean state — Apply/Cancel bar hidden)

Bar is hidden via `grid_remove()`. This is the default state at launch and after every
Apply or Cancel. All pills show their applied-state colours (grey if no filter, accent
blue if an active filter is applied). "Reset filters" link hidden (no active filters
differ from default). Per design guide §6: this is the success/idle state — no special
indicator needed.

### 2. Changes staged (dirty — Apply/Cancel bar shown)

Bar appears (`grid()`). Changed pills show staged-tint colour (`#3a88c8`) if their
staged value is non-default and differs from applied. "Reset filters" link visible if
any staged value is non-default. Per design guide §6: no loading state applies here —
the bar is instantaneous.

### 3. Apply clicked (bar hides, list reloads)

Bar hides immediately. The suggestion list tears down and rebuilds (existing
`set_suggestions` path). During the rebuild, the scroll frame briefly shows no rows
before the new rows are populated — this is the existing behaviour on any track
selection and is acceptable (it is fast enough not to need a spinner). No toast is
shown for a filter apply — the list updating is self-evidencing feedback. If the result
is zero tracks, the empty-state message appears (see State 5). Per design guide §6: the
"loading" phase is implicit in the list rebuild; no separate loading indicator is needed
for this sub-second operation.

### 4. Cancel clicked (controls snap back, bar hides)

Each control's widgets restore to their `_applied_filters` values. The pill colours
restore to applied-state colours. Bar hides. No re-score. No toast. The list is
unchanged — it continues to reflect the last-applied state. Per design guide §6: Cancel
is a revert, not an error; no feedback message is needed.

### 5. Empty state after Apply

If Apply produces zero results, `set_suggestions([])` is called and the empty-state
message appears. Crucially, the empty-state copy must reflect the **applied** filters
(not staged). This is blueprint R5, addressed by T3.7: `set_suggestions` reads
`_applied_filters` to derive its message flags.

Empty-state messages (confirmed copy, unchanged from existing):
- Crates fully cleared and applied: `"No crates selected — pick at least one crate to see suggestions."`
- Genres fully cleared and applied: `"No genres selected — pick at least one genre to see suggestions."`
- Date filter applied, no results: `"No tracks found in this date range. Try a wider window or reset the date filter."`
- No specific filter cause: `"No compatible tracks found"`

### 6. Error state

No new error states are introduced by deferred Apply. If `get_suggestions` throws, the
existing red toast path handles it. The Apply/Cancel bar does not need its own error
state.

---

## Microcopy — verbatim

All text uses sentence case per design guide §8. UPPERCASE only for badge labels.

| Location | Text |
|----------|------|
| Apply/Cancel bar — left label | `"Filters changed"` |
| Apply button | `"Apply"` |
| Cancel button | `"Cancel"` |
| Date overlay — manual date confirm button (renamed from "Apply") | `"Set dates"` |
| "Reset filters" link | `"Reset filters"` (unchanged) |
| Tooltip on Apply button (optional, if Tooltip is added) | `"Apply staged filters and refresh suggestions"` |
| Tooltip on Cancel button (optional) | `"Discard changes and revert to the last applied filters"` |

Note: button tooltips are optional — at 30px height the buttons are readable at a
glance. Only add tooltips if the engineer judges they add clarity without clutter.

---

## Open questions

**OQ-1 — Staged-tint colour sign-off.** The staged-pill tint `#3a88c8` is a design
proposal. The user should confirm or adjust. The only constraint: it must be visibly
lighter than `#1f6aa5` (applied) and not close to `#999999` (grey default). If the user
prefers no staged-tint on pills (Apply/Cancel bar is sufficient signal), the pills can
stay grey when staged-non-default, and flip to accent blue only on Apply. Simpler, but
the DJ loses the per-pill "which one did I touch?" cue.

**OQ-2 — "Filters changed" label visibility.** The brief specifies a `"Filters
changed"` label on the left of the Apply/Cancel bar. An alternative is to omit the
label and let the two buttons alone communicate that something is pending — the booth
context favours shorter copy. The user should confirm which they prefer.

**OQ-3 — Apply feedback.** Currently no toast is specified for a successful Apply. An
alternative is a brief info-coloured toast (*"Filters applied"*) using the existing
`_show_toast` path (`app.py:137`). This would reassure the DJ that the click registered.
The user should decide whether silent re-score (list updates are self-evidencing) or a
brief toast is preferred.

---

## Risks

**R1 — Layout shift on first dirty change.** The scroll frame (Row 3) shrinks by 40px
when the Apply bar appears for the first time in an editing session. At minimum window
(1000x650), with Row 0 (32px) + Row 1 (36px) + Row 2 (26px headers) + Row 3
(scroll) + Row 4 (40px bar), Row 3 is approximately 516px at minimum size — well above
usable. The shift is not catastrophic but is noticeable. This is the accepted
trade-off of panel-owned placement.

**R2 — Narrow pane width.** At very narrow pane widths (DJ drags the sash far left),
the Apply/Cancel bar must not clip its buttons. At 80px per button + 80px spacer + 14px
label + 16px padding, the bar needs approximately 290px minimum. Below that, the
"Filters changed" label should be hidden first (it is informational, not actionable).
The engineer should use `grid_remove()` on the label when the pane is very narrow, or
simply let it wrap — `CTkLabel` will ellipsis if given a `width` constraint. The buttons
must not be removed.

**R3 — Colour-blind fallback for staged-tint pill.** The staged tint `#3a88c8` vs
applied `#1f6aa5` is a hue/brightness difference. For protanopia/deuteranopia this
distinction may be insufficient. Mitigation: the Apply/Cancel bar itself is the primary
"pending changes" signal and requires no colour discrimination. The pill tint is
supplementary; its loss for colour-blind users is acceptable. Per design guide §7.2
(known debt), a full colour-blind safe mode is a separate future decision.

**R4 — `DateRangeControl` "Set dates" button width.** The renamed button may wrap at
the default `width=60`. Increase to `width=70` to accommodate the two-word label at
size 11. Verify in implementation.

**R5 — Apply/Cancel bar and floating overlay coexistence.** If a filter overlay is open
when Apply or Cancel is clicked, the overlay should close. The Cancel handler already
calls `self.filter_bar._update_reset_visibility()` (T3.5); ensure it also calls
`FloatingOverlay.close_open()` to dismiss any open overlay. Same for the Apply handler.
This prevents a stale overlay floating over a freshly re-scored list.
