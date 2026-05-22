# UI Design Brief — Extended Camelot Matching

> Status: Approved by ui-designer — ready for engineer
> Date: 2026-05-22
> Author: UI Designer agent
> Companion to: `architect-blueprint.md`, `implementation-plan.md`

---

## User goal

The DJ wants to see a much larger pool of harmonically usable tracks ranked by how safe
the move is, so they can build longer, more varied sets without leaving the suggestion
panel.

---

## Panels / components affected

| Component | Location in layout | Change type |
|---|---|---|
| `SuggestionPanel` — `_score_color()` | Row 2, left pane | Threshold re-tune (colour is data) |
| `SuggestionPanel` — per-row tooltip | Row 2, left pane | Add tier name as first tooltip line |
| `SuggestionPanel` — `set_suggestions` header | Row 2, left pane | Microcopy confirmation only — no layout change |
| `SuggestionPanel` — empty-state copy | Row 2, left pane | Microcopy confirmation only — no copy change |
| `SuggestionPanel` — `_COL` grid | Row 2, left pane | No new column — see Tier-label decision below |

No other panels are affected. Row 0 (top bar), Row 1 (Now Playing), and the session
panel (right pane) are untouched.

---

## Key design decisions

### Decision 1 — Score colour thresholds (the most critical UI change)

**Problem.** `_score_color()` at `suggestion_panel.py:21-27` currently has three buckets
tuned for a world where the minimum key score was 0.7. With the new seven-tier model
the key component of `total_score` now reaches as low as 0.37, and with the 0.45 key
weight the blended `total_score` for a Related-tier row will typically sit around
0.35–0.45. Under the current thresholds almost every new row lands in the orange
bucket, wiping out the colour signal entirely.

**Solution — expand to five buckets, each mapped to a named tier band.**

The existing green-yellow-orange palette stays (colour is data in this app; the DJ
reads it without thinking). A fourth colour — teal/blue-green — is inserted between
green and yellow to give the Relative/Diagonal tier its own distinct band. A fifth
colour — muted red-orange, distinct from the existing orange — marks the loosest
(Related) tier. This gives the DJ five visually distinct confidence bands across the
full score range.

Proposed thresholds and colours:

| Band | `total_score` range | Colour token | Hex | Harmonic tier(s) it typically catches |
|---|---|---|---|---|
| Strong match | ≥ 0.75 | Match-strong | `#28a745` (existing green) | Perfect, Adjacent |
| Good match | ≥ 0.60 | Match-good | `#20c997` (teal) | Relative, Diagonal |
| Usable | ≥ 0.48 | Match-usable | `#ffc107` (existing yellow) | Energy ±2 |
| Loose | ≥ 0.38 | Match-loose | `#fd7e14` (existing orange) | Semitone |
| Stretch | < 0.38 | Match-stretch | `#dc6060` (muted red) | Related |

**Why these thresholds, not the tier scores directly?** `total_score` is a weighted
blend (key 0.45, energy 0.35, bpm 0.20) so a track with a Related key score (0.37)
but a good energy and BPM match can blend up to ~0.50 and appear in the Usable band —
which is correct, it is usable. Threshold-on-`total_score` preserves the holistic
read. The tier-name tooltip (Decision 2) tells the DJ exactly which harmonic move it
is, regardless of where the blended score sits.

**Colour-blind note (design guide §7.2).** The five colours span green → teal → yellow
→ orange → muted-red. Green/teal is hard to distinguish under deuteranopia; the tier
name in the tooltip (Decision 2) provides the non-colour signal. This is a known debt
item (design guide §7.2) and acceptable here — the tier name in the tooltip closes the
gap without requiring a full colour-blind mode.

**Implementation target:** `source/ui/suggestion_panel.py:21-27` — replace the
three-branch `if/elif/else` with a five-branch version using the thresholds above.

---

### Decision 2 — Harmonic tier name: tooltip, not a column

**The question.** Should the harmonic-move name ("Perfect match", "Adjacent",
"Diagonal", "Energy ±2", "Semitone", "Related") appear as an inline column, a badge
in the score cell, or a tooltip line?

**Ruling: tooltip, first line.** A DJ glancing at the panel for half a second reads
the `%` badge colour (Decision 1 handles that) and picks a track. The tier name is
"why is this 47%?" context — it answers the question the DJ already has when they
*pause* on a row. The hover tooltip is exactly that: available on demand, never
consuming screen space. Adding an inline column would require either a new `_COL`
entry (pushing the grid past the minimum 1000px window width) or shrinking Artist/Title
columns (which are already truncated). Both harm the booth-use case more than a column
helps.

The tooltip currently reads (from `suggestion_panel.py:365-372`):

```
Key: 80%   Energy: 75%   BPM: 90%
Crates: House, Tech House
```

The revised tooltip should read:

```
Energy ±2
Key: 57%   Energy: 75%   BPM: 90%
Crates: House, Tech House
```

The tier name is the first line, in sentence case, styled as a brief label (not a
heading). The key/energy/BPM line is unchanged. The crates line is unchanged. A blank
line between the tier name and the score line is acceptable if the tooltip widget
supports it cleanly.

**Implementation target:** `source/ui/suggestion_panel.py:365-372` — prepend
`scored.harmonic_tier.value` as the first line of `tip_lines`. `HarmonicTier.value` is
the human-readable display string defined in Task 1.1 of the implementation plan
(e.g., `"Energy ±2"`, `"Related"`, `"Perfect match"`). The engineer must import
`HarmonicTier` into `suggestion_panel.py` for type-checking if needed, but can access
`scored.harmonic_tier.value` without a direct import because the field is already a
`HarmonicTier` instance on `ScoredTrack`.

---

### Decision 3 — Header count copy

**Ruling: no change needed.** The current pattern `"Suggestions (N)"` at
`suggestion_panel.py:278` reads correctly at 60 rows. A large N is informative (it
tells the DJ the pool is wide), not alarming. The font and position are unchanged.

---

### Decision 4 — Empty-state copy

**Ruling: no change needed.** "No compatible tracks found" at `suggestion_panel.py:274`
remains accurate. Under the new model "compatible" encompasses any harmonic
relationship scoring above 0.0 — if a track appears at all it is compatible in the
new expanded sense; if none appear the copy is still correct.

---

### Decision 5 — Row ordering and visual grouping

**Ruling: no visual grouping or separators between tiers.** The list stays sorted
strictly by `total_score` descending (current behaviour at `suggestion_engine.py:86`).
Adding tier-group separators or alternating block backgrounds would require a new
layout pattern with no precedent in this codebase, add visual noise at the expense of
scannability, and break the alternating-row rhythm (`suggestion_panel.py:288`). The
colour coding of the `%` badge (Decision 1) already groups the list visually by tier
band — a DJ scanning downward sees the colours shift from green through teal-yellow-
orange-red as the rows get looser. No additional grouping is needed.

---

## Pattern precedent

| Design element | Precedent | File:line |
|---|---|---|
| Five-bucket score colour | Extended from existing three-bucket `_score_color()` | `suggestion_panel.py:21-27` |
| Tooltip with multi-line text | Existing `Tooltip` usage | `suggestion_panel.py:365-372` |
| Alternating row background | Existing row loop | `suggestion_panel.py:288` |
| Header with count | Existing `configure(text=...)` | `suggestion_panel.py:278` |
| Enum `.value` as display string | Pattern established by `HarmonicTier` enum in Task 1.1 of the implementation plan | `implementation-plan.md` Task 1.1 |

No new component patterns are introduced. All changes are extensions of existing
patterns within `suggestion_panel.py`.

---

## States to handle

- **Loading.** No change from current behaviour — the suggestion panel does not show a
  loading state during scoring (it is synchronous); the empty-state label covers the
  gap between track selection and results rendering. Design guide §6: no global loading
  indicator pattern is in use; consistent non-change.
- **Empty.** "No compatible tracks found" remains the copy at `suggestion_panel.py:274`.
  Under the new model this state is rarer (the candidate pool is wider) but the copy is
  still accurate and stays as-is. Design guide §6 empty convention: tells the DJ what
  happened, not what is missing.
- **Error.** No new error surface introduced. Key-scoring failures (invalid key strings)
  produce `0.0` and are filtered out silently, consistent with the existing approach at
  `suggestion_engine.py:48`. No toast is warranted for per-row filter events.
- **Success.** The normal populated state. Up to 60 rows, colour-coded by five-bucket
  score, with tier name in the tooltip. Header shows `"Suggestions (N)"` where N can
  now reach 60.

---

## Microcopy

All copy follows design guide §8 (sentence case for body text, UPPERCASE for badge
labels only).

### Score column header
`%` — unchanged. (It is an abbreviation, not a badge label, and fits the narrow column.)

### Tooltip (revised)
Line 1 (tier name): the `.value` string from `HarmonicTier` — `"Perfect match"`,
`"Adjacent"`, `"Relative"`, `"Diagonal"`, `"Energy ±2"`, `"Semitone"`, `"Related"`.
These are already defined in implementation-plan Task 1.1 and must match exactly.
Line 2 (score breakdown): `"Key: {N}%   Energy: {N}%   BPM: {N}%"` — unchanged.
Line 3 (crates, when present): `"Crates: {name}, {name}"` — unchanged.

### Empty state
`"No compatible tracks found"` — unchanged.

### Header
`"Suggestions ({N})"` — unchanged.

### Tier names (canonical, from `HarmonicTier` enum values)
These must be exactly consistent between the enum definition and any future UI that
uses them:

| Enum member | Display string |
|---|---|
| `PERFECT` | `"Perfect match"` |
| `ADJACENT` | `"Adjacent"` |
| `RELATIVE` | `"Relative"` |
| `DIAGONAL` | `"Diagonal"` |
| `ENERGY` | `"Energy ±2"` |
| `SEMITONE` | `"Semitone"` |
| `RELATED` | `"Related"` |
| `NONE` | `"No match"` (should not appear in the rendered list — only tracks scoring > 0 are shown) |

---

## Open questions

1. **Does the user want the five-colour range, or prefer to keep three colours
   (green/yellow/orange) with re-tuned thresholds?** Five colours give the DJ more
   gradient information; three colours are simpler and the teal may feel unfamiliar.
   This is a taste call. The design above recommends five — surface this to the user
   before the engineer implements.

2. **`MAX_SUGGESTIONS = 60` — is 60 the right ceiling?** The architect flagged this as
   open question Q1. With a 200–500 track library, 60 is a reasonable first cut. The
   DJ should try it and report whether the list feels too long to scroll in a live set.
   This is explicitly a post-ship tuning decision.

3. **Should the "Related" tier (score ~0.37) be suppressed by default?** The architect
   flagged this as Q2. The design above includes it (the user explicitly asked for more
   tracks). The muted-red colour band (Decision 1) visually de-emphasises it. If the
   DJ finds the bottom of the list unusable in practice, the tier can be removed by
   setting `RELATED: 0.0` in `HARMONIC_TIER_SCORES` — no UI change required.

4. **Tooltip line separator.** Should the tier name and the score line be separated by
   a blank line (`\n\n`) or a newline (`\n`)? This depends on how the existing
   `Tooltip` widget (`source/ui/tooltip.py`) renders multi-line strings. The engineer
   should check `tooltip.py` for the wraplength and line-spacing behaviour and pick
   whichever reads more clearly. No design call needed — implementation judgment.

---

## Risks

- **Colour-blind legibility (design guide §7.2).** The five-band colour system uses
  green and teal as adjacent bands. Under deuteranopia these are indistinguishable.
  Mitigation: the tier name in the tooltip provides the non-colour label ("Adjacent"
  vs "Relative" vs "Diagonal") for any DJ who hovers. A full colour-blind mode (shapes,
  labels alongside hue) remains a design guide §9 open question and is not addressed
  here.
- **Minimum window width (1000px).** No new column is added. The existing `_COL` grid
  width budget is unchanged. The five-colour change and tooltip change have zero layout
  impact. Risk: none.
- **Extreme narrow left pane.** The suggestion panel can be dragged very narrow.
  Artist and title columns truncate via `truncate()` (`utils.py:1`). The score, key,
  bpm, and energy columns have fixed widths. The tier-name tooltip is off-panel and
  not affected by pane width. Risk: unchanged from current behaviour.
- **Very large N in the header.** If the user's library grows large and the pool exceeds
  60, `MAX_SUGGESTIONS` caps it and the header shows `"Suggestions (60)"`. This is
  correct — it describes the rendered list, not the full pool. No risk.
- **`HarmonicTier.NONE` appearing in tooltip.** If a `ScoredTrack` with
  `harmonic_tier = HarmonicTier.NONE` were ever rendered (e.g., a bug in Phase 2
  where the score-gate is bypassed), the tooltip would show `"No match"` — odd but
  not harmful. The Phase 4 tests should assert this cannot happen.
