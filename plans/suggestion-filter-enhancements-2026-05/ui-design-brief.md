# UI Design Brief — Suggestion Filter Enhancements

> Status: Final
> Date: 2026-05-30
> Author: UI Designer agent
> Companion: `architect-blueprint.md` (architecture reasoning), `implementation-plan.md` (task list)
> Plan folder: `plans/suggestion-filter-enhancements-2026-05/`

---

## User goal

The DJ wants to steer their set deliberately up or down the Camelot wheel and narrow
suggestions to recently-found tracks — without needing to fiddle or think about the
controls mid-mix.

---

## Panels / components affected

| Component | Location in window | New or existing |
|-----------|-------------------|-----------------|
| `SuggestionPanel` filter bar (row 1 of panel) | Row 2, left pane of `PanedWindow` | Existing — redesigned |
| `FilterDropdown` widget (`suggestion_panel.py:48`) | Inside filter bar | Existing — revised |
| New: `KeyOffsetControl` | Inside filter bar | New inline widget |
| New: `DateRangeControl` | Inside filter bar | New inline widget |
| `FilterBar` container frame | Inside `SuggestionPanel`, replaces current 2-column filter row | New framing — same grid slot (row 1 of panel) |

No changes to the top bar, dashboard, or session panel.

---

## Filter UX audit — what makes the current filters "finicky"

Read `source/ui/suggestion_panel.py:48–156` and `207–217` before reasoning about fixes.

### Finding 1 — The toggle button doubles as both affordance and state label (High)

`suggestion_panel.py:59–67`: the single `CTkButton` carries the full "Filter Crates: 3
of 9 selected" text. A button whose label changes meaning is hard to scan glance-by-glance
— the DJ reads it as a state display, not as a tap target.

**Fix:** Separate the state indicator from the tap target. Each pill shows its current
selection state as compact text (e.g. "Crates: 3/9") with a small chevron. The chevron
is visually distinct from the label, making the tap target obvious.

### Finding 2 — "Deselect All" is a large red button that yields zero results (High)

`suggestion_panel.py:87–92`: the red "Deselect All" button inside the dropdown is the
same visual weight as "Select All". Deselecting everything means zero suggestions — the
list goes empty and looks broken. This is "None Selected" reading as a bug
(blueprint §3, confirmed observation).

**Fix:** Remove the "Deselect All" button entirely from the multi-select dropdowns.
Replace with a compact "Clear" text link or small secondary-styled button that is visually
subordinate to "Select All". Better still: see Finding 5 — a single "Reset all filters"
clears everything at once and is the safer affordance for live use.

### Finding 3 — The dropdown expands inline and pushes down the suggestion list (Medium)

`suggestion_panel.py:69–72`: the dropdown grows inside the panel, pushing the grid header
and results list downward. In a small pane this can collapse the visible suggestions to
near nothing. The DJ clicks a filter to narrow results, then can't see enough results to
decide — counter-productive.

**Fix:** Make dropdowns overlay rather than push. Implement as a `CTkToplevel` floating
panel (or a `CTkFrame` drawn with a raised z-order via `lift()`) positioned directly
below the filter pill. The suggestion list does not move. The overlay auto-closes on any
click outside or when a new filter pill is opened.

**Constraint flag:** `CTkToplevel` for a floating panel is possible but adds teardown
complexity (must destroy on panel clear/update). An alternative is a `tk.Frame`
`place()`d over the scroll frame at a fixed y-offset — simpler lifecycle, no separate
window. The engineer should choose based on teardown ease; either is visually identical.
This is an **open question for the engineer** during T3.3.

### Finding 4 — No visual indication that a filter is active when the dropdown is closed (High)

When "Crates: 3 of 9 selected" the suggestion list is already narrowed — but if the DJ
closes the dropdown and looks at the filter bar quickly, the button text is the only
signal. In a dark booth, reading "3 of 9" while looking for a track is too much
cognitive load.

**Fix:** Filter pills that are in a non-default state (anything other than "all selected
/ no filter active") render with the CTk blue accent (`#1f6aa5` or the system accent)
as their background. Neutral/default pills are the standard `gray35` background. This
gives colour-at-a-glance: any blue pill = this filter is narrowing your results.

### Finding 5 — No single "reset" affordance across all filters (Medium)

The DJ accidentally narrows to a subset they didn't want and must open each dropdown
individually to restore defaults.

**Fix:** Add a single "Reset filters" text label or compact icon-button at the right
end of the filter bar, visible only when at least one filter is non-default. Pressing it
restores all four filters to their neutral state (all crates, all genres, offset 0, no
date filter) and fires a single `_filter_changed()` call. This also resolves the
"Deselect All" trap — there is no way to leave all items unchecked because "Reset" is
one action away.

### Finding 6 — Two filters side by side at minimum pane width collide (Medium)

`suggestion_panel.py:210–217`: two `FilterDropdown` widgets share a 2-column row with
`weight=1` each. At narrow pane widths (user drags sash left) both collapse and their
text clips. Now there will be four filters — the collision is worse.

**Fix:** The filter bar adopts a single horizontal scrollable row of pills using a
`CTkScrollableFrame` with `orientation="horizontal"`. At any pane width the pills stay
full size; the bar scrolls horizontally if needed. Alternatively: pills wrap to a second
row when space is tight (requires `grid` layout with responsive `columnconfigure` — less
predictable in Tkinter). **Horizontal scroll is recommended** — the row height stays
fixed, which is critical for the suggestion list below it.

**Open question:** the user must decide whether a fixed one-row scrollable bar or a
wrapping two-row bar is acceptable. The brief recommends one row.

---

## Redesigned filter bar — layout

```
┌─────────────────────────────────────────────────────────────────┐
│ SUGGESTIONS (12)                                                │
├─────────────────────────────────────────────────────────────────┤
│ [Crates ▾]  [Genres ▾]  [Transition: 0 ◀ ▶]  [Added ▾]  Reset │ ← filter bar (fixed height ~36px)
├─────────────────────────────────────────────────────────────────┤
│  %   Artist          Title             Key  BPM  E  Genre      │ ← column header
│ ─────────────────────────────────────────────────────────────── │
│  ...suggestions...                                             │
└─────────────────────────────────────────────────────────────────┘
```

- All four controls sit in a single horizontal row inside a `CTkScrollableFrame`
  (`orientation="horizontal"` — this is the Tkinter/CTk `xscrollcommand` pattern, not a
  CTkScrollableFrame option; the engineer should implement as a `CTkFrame` inside a
  `tk.Canvas` with an `xscrollbar` hidden, or simply as a non-scrolling frame and accept
  clipping below ~500px pane width — see Risks).
- The "Reset" affordance lives at the right edge of the bar, outside the scrollable
  region, and is only visible when any filter deviates from its default.
- Pill height: **32px** — large enough for a reliable click target in a booth.
- Inter-pill gap: **6px** horizontal.

**Note on `CTkScrollableFrame` direction:** `CTkScrollableFrame` in the current CTk
version scrolls vertically only. A horizontal-scrolling filter bar requires either a
`tk.Canvas` + `tk.Frame` inside it (the standard Tkinter horizontal scroll pattern), or
accepting that the bar clips at narrow widths. **Decision for the engineer:** implement
horizontal canvas scroll, or accept fixed-width pills that clip. Flag this in the
implementation plan. For now the brief assumes pills clip below ~600px pane width and
that the minimum usable pane width for the filter bar is around that mark — acceptable
because the user controls the sash.

---

## Sub-feature 1 — Key transition offset control

### Design

The offset control is an **inline stepper** — three adjacent elements in a single
`CTkFrame` pill: a "◀" decrement button, a centre label showing the current offset
value in formatted text, and a "▶" increment button.

```
[ ◀  Transition: +1  ▶ ]
```

- The centre label text follows the microcopy in §Microcopy below.
- Buttons are `CTkButton`, `width=24`, `height=28`, `fg_color="transparent"`,
  `hover_color` = the standard hover token. They are large enough to click accurately
  under pressure. Arrow characters: `◀` (U+25C4) and `▶` (U+25BA).
- The outer pill frame has `corner_radius=6`, `fg_color=("gray75", "gray35")` when at
  default (offset 0) and `fg_color="#1f6aa5"` (accent blue) when non-zero — consistent
  with Finding 4.
- Range: `KEY_OFFSET_RANGE` from `config.py` (currently `(-2, 2)`). Buttons disable
  (`state="disabled"`) at the min/max ends — the DJ can't go past the range limit.
  Visual: disabled buttons are greyed; the pill state label reflects the clamped value.
- Clicking "▶" at offset `+2` does nothing (button is disabled).

**Why not a `CTkOptionMenu` or `CTkSlider`?** An option menu requires a click to open
plus a second click to select — two interactions for what is a conceptually simple
increment. A slider is imprecise under pressure. The stepper is one tap per step and
reads as a directional control, matching the "transition +1, transition +2" mental model
exactly.

### Pattern precedent

No existing stepper widget in the codebase. Closest analogue: the `FilterDropdown`
toggle button (`suggestion_panel.py:59–67`) for the outer pill frame styling. The
inner `◀ / ▶` buttons follow the `CTkButton` transparent style used for the play button
(`suggestion_panel.py:343–351`). The pill colour-as-state-signal is a new pattern for
the filter bar but consistent with the domain-colour-as-data principle (§3 of design
guide).

### States

- **Default (offset 0):** pill label "Transition: same key", grey pill background.
  "◀" decrement is enabled; "▶" increment is enabled.
- **Non-zero offset:** pill label "Transition: +1" / "−1" etc., blue accent pill.
  Button at the range limit is disabled.
- **No valid key on current track (R5):** engine falls back to offset 0 behaviour. The
  control itself remains interactive — the DJ can still set it; it just has no effect
  until a keyed track is selected. No special UI state needed; the control does not know
  about the current track's key validity.

---

## Sub-feature 2 — Filter UX redesign (FilterDropdown revision)

### Revised FilterDropdown pill appearance

Each existing `FilterDropdown` becomes a **pill button** — a `CTkButton` styled as a
rounded pill (`corner_radius=16`) showing the filter state as compact text.

| State | Label text | Pill background |
|-------|-----------|----------------|
| All selected (no filter) | "Crates" | `gray35` |
| Partial | "Crates: 3/9" | Accent blue `#1f6aa5` |
| One item | "Crates: House" (truncated at 10 chars) | Accent blue |

Clicking the pill opens the floating dropdown panel (see Finding 3 fix). The dropdown
contains:
- A "Select all" compact text button (sentence case, secondary styling — NOT a large
  green button).
- The scrollable checklist as today (`suggestion_panel.py:94–110`), same checkbox
  dimensions.
- No "Deselect All" button (removed per Finding 2).

The floating panel closes when the DJ clicks anywhere outside it or presses Escape. It
also closes when a different pill is opened (only one dropdown open at a time).

### Engine invariant preserved

When all items are checked, `selected` returns the full set, `all_selected` returns
`True`, and `app._update_suggestions()` translates that to `None` (no filter). This
contract is unchanged (`app.py:309–315`). The "Deselect All" button removal means the
panel can never reach all-unchecked state through normal use; if a user somehow
deselects the last checkbox manually, the engine receives an empty set — the suggestion
list goes empty and the pill goes blue. The "Reset filters" button at the bar level
immediately restores everything, so the user is never stuck.

---

## Sub-feature 3 — Date-added range filter

### Input mechanism decision

CustomTkinter has no native date picker. The options for a booth context are:

| Approach | Booth suitability | Complexity |
|----------|------------------|-----------|
| Free-text entry (e.g. "2026-03-01") | Poor — typing a date mid-mix is slow and error-prone | Low |
| Relative presets only (e.g. "Last month") | Excellent for the common case; misses precise ranges | Low |
| Preset + optional manual from/to entry | Good — preset handles 90% of use; manual entry available when needed | Medium |
| Calendar picker (custom widget) | Good ergonomics if built well; high custom build cost for no existing pattern | High |

**Recommendation: preset-first with optional manual entry.** This is the most
appropriate balance for a DJ booth. Design:

A single `DateRangeControl` pill. Clicking it opens a floating panel containing:

1. **Preset row** — a set of `CTkButton` tiles in a horizontal row. Presets:
   - "Any time" (default / reset)
   - "Last month"
   - "Last 3 months"
   - "Last 6 months"
   - "This year"

   Selecting a preset immediately closes the panel and applies the filter. The active
   preset tile shows with blue accent background; "Any time" = grey (no filter).

2. **Manual entry section** (below presets, optional) — two `CTkEntry` fields labelled
   "From" and "To (optional)", each accepting `YYYY-MM-DD` format. A small "Apply"
   button next to the "To" field commits the manual range. This section is for DJs who
   want a specific window (e.g. "tracks added between a festival trip and now").

The pill label reflects the active selection:
- "Added: any time" — grey pill, no filter active.
- "Added: last 3 months" — blue pill, preset active.
- "Added: from 2026-01-01" — blue pill, custom from-only active.
- "Added: 2026-01-01 – 2026-03-01" — blue pill, custom range active.

### Date conversion helper

A helper `date_range_to_epoch(preset: str | None, from_str: str | None, to_str: str |
None) -> tuple[float | None, float | None]` converts preset names and ISO date strings
to Unix epoch floats. The engineer places this in `source/ui/utils.py` (or
`source/services/dates.py` per blueprint §4 if the function grows). It must be unit-
tested. When `to_str` is `None` and `preset` yields an open-ended range, `date_to` is
`None` (open to now) — see the open question below for confirmation.

### Honest caveat for first-sync accuracy

The caveat must appear exactly once — inside the floating panel, as a single line of
secondary-grey text below the preset tiles:

> "Dates are approximate for tracks added before your first sync."

This is the complete copy. It is:
- Short enough to read in a glance.
- Honest without being alarming (the filter still works; it gets more accurate over
  time).
- Positioned below the interactive controls so it does not block the primary action.
- Never shown as a toast or modal — it does not interrupt the workflow.

Do not add this text to the main panel or to any tooltip; inside the date panel only.

### States

- **Default (no filter):** pill shows "Added: any time", grey background. Panel shows
  "Any time" preset tile highlighted.
- **Active:** pill shows summary of active range, blue background.
- **Tracks with `date_added == 0.0`** (unknown — blueprint §4): these tracks are
  silently excluded by the engine when a `date_from` is set. No special UI state is
  needed; the count in "Suggestions (N)" header naturally reflects the narrowed pool.
  If the number drops unexpectedly low and the DJ wonders why, the tooltip on the date
  pill (see §Risks) can explain.
- **Invalid manual date entry:** if the user enters a malformed date string and clicks
  Apply, the field border turns red (CTk `border_color="#dc3545"`) and a one-line error
  appears below: "Enter a date as YYYY-MM-DD". The filter is not applied until valid
  input is confirmed. The engine is never called with a bad value.

---

## States to handle (all four, per design guide §6)

| Panel / control | Loading | Empty | Error | Success |
|-----------------|---------|-------|-------|---------|
| Filter bar | No loading state needed — filter controls are populated at sync time; before sync, the crate and genre dropdowns show no items, which is the existing empty state. | Crate/genre pills show "Crates" / "Genres" with no items; opening them shows a "No crates loaded — sync your library first" line inside the dropdown. | Not applicable — filters themselves cannot error; errors are at the sync level (toast, §6). | Controls populate normally on `set_crates()` / `set_genres()` call. |
| Offset control | No loading state — it renders at default (0) immediately. | Not applicable. | Not applicable (engine falls back on invalid key, control is always interactive). | Renders with current offset value; pill blue if non-zero. |
| Date range control | No loading state. | Default "Any time" preset, grey pill. | Invalid manual entry: red field border + inline message (see above). | Active filter: blue pill with range summary. |

---

## Microcopy

All body text uses sentence case. Badge/header labels use UPPERCASE per §8.

### Key offset control

| Offset value | Pill centre label |
|---|---|
| 0 (default) | `Transition: same key` |
| +1 | `Transition: +1` |
| +2 | `Transition: +2` |
| −1 | `Transition: −1` |
| −2 | `Transition: −2` |

Tooltip on the offset pill (400ms delay, per `tooltip.py:7`):
> "Shift harmonic matching up or down the Camelot wheel. At +1 same-key tracks are
> hidden and one-step-up tracks move to the top."

### Date range control

| State | Pill label |
|---|---|
| Default / no filter | `Added: any time` |
| Last month preset | `Added: last month` |
| Last 3 months preset | `Added: last 3 months` |
| Last 6 months preset | `Added: last 6 months` |
| This year preset | `Added: this year` |
| Custom from only | `Added: from YYYY-MM-DD` |
| Custom from + to | `Added: YYYY-MM-DD – YYYY-MM-DD` |

Preset tile labels (title case, matching convention of short action labels): "Any time",
"Last month", "Last 3 months", "Last 6 months", "This year".

Manual entry field labels (sentence case): "From", "To (optional)".

Manual entry apply button: "Apply".

Manual entry error text: "Enter a date as YYYY-MM-DD."

Honest caveat line (inside date panel, secondary-grey text):
"Dates are approximate for tracks added before your first sync."

Empty crate/genre dropdown copy: "No crates loaded — sync your library first."

### Filter bar — Reset affordance

"Reset filters" — shown only when any filter is non-default. Sentence case. Styled as a
plain `CTkLabel` with a `hand2` cursor and a hover underline effect (configure
`text_color` from `#999999` to `#ffffff` on hover). No button chrome — it reads as a
link, not a button, so it is visually subordinate to the pills.

### Suggestion panel header (unchanged from today's pattern)

"Suggestions (N)" — already correct. No change.

Empty state when date filter zeroes out results:
"No tracks found in this date range. Try a wider window or reset the date filter."

This replaces the generic "No compatible tracks found" only when the date filter is the
active reason for zero results. (The engineer detects this by checking if the date filter
is active when `scored_tracks` is empty — a simple boolean check in
`SuggestionPanel.set_suggestions`.)

---

## Open questions

1. **Same-key suppression at offset 0 (blueprint §8):** should offset 0 ever allow
   "show same key" to be toggled independently? Current decision: offset 0 = today's
   behaviour (same key always shown). This brief confirms that is the right UX — the DJ
   uses the stepper to escape same-key, not a separate checkbox. No change needed.

2. **`date_to` default when only `from` is set (blueprint §8):** when the DJ sets a
   "from" date only (or picks a preset like "Last 3 months"), `date_to` should be `None`
   (no upper bound, open-ended to the present). This brief confirms that default — do
   not set `date_to` to "now" as a timestamp, because tracks added in the future (an
   impossible edge case) should not be hidden. `None` = "no upper limit."

3. **Horizontal scroll vs clip for the filter bar at narrow pane widths:** at pane
   widths below approximately 600px the four pills plus Reset will not fit in one row.
   Options: (a) pills clip silently — the DJ rarely runs such a narrow suggestions pane;
   (b) horizontal canvas scroll — more code, always accessible. **User decision required.**
   The brief recommends option (a) with a minimum useful pane width note in the codebase.

4. **Floating dropdown implementation (Finding 3):** `CTkToplevel` vs `place()`d
   `CTkFrame`. Both achieve the overlay effect. The engineer decides based on lifecycle
   complexity; either is acceptable from a design standpoint.

5. **Date filter tooltip on the pill:** should the date pill show a tooltip explaining
   the first-sync caveat? The brief places the caveat inside the date panel only. Adding
   a tooltip as well would duplicate the copy. **Recommendation: no tooltip on the date
   pill — panel-level copy is sufficient.** Confirm if the user disagrees.

---

## Risks

### R1 — Colour-blind accessibility (design guide §7.2)
The blue-pill-as-active-filter signal uses hue only. A colour-blind DJ has the pill
label text (which changes to show a non-default value like "Crates: 3/9") as the
fallback — this is adequate. The offset and date pills also change their text content
when non-default. The known colour-blind debt (§7) is not introduced further here;
the text fallback is sufficient for filter state. Flag if the user wants a shape/icon
fallback in a future pass.

### R2 — Minimum window size (1000×650)
At minimum window size with 50/50 sash split, the suggestion pane is ~497px wide. Four
pills at estimated 130px each = ~520px plus gaps — the pills will clip at minimum
window. The filter bar must not clip the "Reset" affordance; it should be right-anchored
outside the pill scroll area so it is always visible. At the absolute minimum the DJ
will lose sight of one pill at most; "Reset" remains clickable.

### R3 — Extreme pane widths
At maximum suggestions pane width (sash dragged far right), the filter bar has more
space than needed — pills simply have whitespace between them, which is fine. At very
narrow pane widths (< 300px), the filter bar is essentially unusable, but the
suggestion list is also too narrow to be useful — the DJ would not operate at this
width. Document the ~500px useful minimum.

### R4 — Date filter excluding `date_added == 0.0` tracks silently
Tracks with no date (unknown) disappear from the list when the date filter is active.
The suggestion count will drop, which the DJ will notice in the header. The empty-state
copy ("No tracks found in this date range. Try a wider window or reset the date
filter.") handles the extreme case. For intermediate cases (some tracks present, some
silently excluded), no additional UI is needed — the DJ is getting a narrowed pool,
which is the intent.

### R5 — `FilterDropdown` floating overlay z-order
A `place()`d overlay frame inside the `SuggestionPanel` may be occluded by child
frames at certain Tkinter rendering orders. The engineer must call `lift()` after
placing. If `CTkToplevel` is chosen instead, ensure it is set `transient` to the main
window and does not grab focus (no `grab_set()`).

### R6 — Manual date entry on touchscreen / live keyboard access
The manual date entry field is a free-text `CTkEntry`. Typing `2026-03-01` mid-mix is
not ideal. The preset tiles handle the DJ's stated use case ("last two months"). The
manual entry section is a secondary affordance — it appears in the panel but should be
visually less prominent than the presets (smaller, lower, separated by a thin rule). If
the user never uses manual entry in practice, that is fine — the presets cover the job.

---

## Pattern precedent summary

| Element | Precedent | File:line |
|---------|-----------|-----------|
| Pill button outer frame | `FilterDropdown` toggle button styling | `suggestion_panel.py:59–67` |
| Transparent-background icon buttons (◀ ▶) | Play/pause button in suggestion row | `suggestion_panel.py:343–351` |
| Floating tooltip overlay | `Tooltip` widget | `source/ui/tooltip.py:1–45` |
| Hover colour change on label/link | Row hover in suggestion grid | `suggestion_panel.py:364–373` |
| Scrollable checklist | Existing `FilterDropdown.checklist` | `suggestion_panel.py:94–110` |
| Error colour for invalid input | Error toast token | `app.py:137`, token `#dc3545` |
| Accent blue for active state | CTk default accent | `suggestion_panel.py:83` (green used there — use blue `#1f6aa5` instead for filter active state, a new application of the accent) |
| Floating panel below trigger | No direct precedent — new pattern. Closest: `search_dropdown` which uses `grid_remove()` inline. Floating overlay is new and should be documented in `docs/ui-design-guide.md` §5 once implemented. |
| Stepper widget (◀ value ▶) | No precedent — new pattern in this codebase. | — |
| Preset-tile row (multiple CTkButtons inline) | No precedent — new pattern. | — |

The floating overlay, stepper, and preset-tile patterns are new to this codebase. Each
should be added to `docs/ui-design-guide.md` §5 once Phase 3 ships.
