# Implementation Plan — Deferred Filter Apply

> **For:** Engineer agent
> **Companion:** `architect-blueprint.md` (same folder) — read it first for the decision rationale (ADR-012).
> **Principle:** Phases 1–2 change NO observable behaviour (filters still apply live). Phase 3 flips the switch to deferred Apply. Land and verify the state-model/engine work before touching UX. Run `python -m pytest` after each phase.

Legend: each task cites `file:line`. `<!-- UI-designer to revise -->` marks look/placement/microcopy left to the UI designer — the engineer wires structure and behaviour only.

---

## Phase 1 — State model + engine (invisible)

Goal: introduce `SuggestionFilters` and let `get_suggestions` accept it. No UI touched. All existing tests stay green.

### T1.1 — New value object
**File:** `source/services/suggestion_filters.py` (new)
Create the frozen dataclass exactly as in blueprint §2 D1:
```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class SuggestionFilters:
    allowed_crates: frozenset[str] | None = None
    allowed_genres: frozenset[str] | None = None
    key_offset: int = 0
    date_from: float | None = None
    date_to: float | None = None
```
No UI imports. Leaf module (precedent: `source/services/harmonic_tier.py`). `frozenset` (not `set`) so the dataclass is hashable and equality is order-independent (blueprint §4).

### T1.2 — Engine accepts a `filters` object
**File:** `source/services/suggestion_engine.py:26-32`
Add a leading-or-trailing keyword `filters: SuggestionFilters | None = None` to `get_suggestions`. When `filters is not None`, unpack it into the local `allowed_crates`, `allowed_genres`, `key_offset`, `date_from`, `date_to` BEFORE the existing logic (the keyword args become a fallback for callers/tests that don't pass `filters`). Import `SuggestionFilters` at top.
- Keep the defensive clamp (`:62`) and all existing filter logic (`:80-93`) unchanged — they operate on the unpacked locals.
- Confirm `frozenset` works at `:81` (`.intersection(...)`) and `:85` (`in`) — it does; no change (blueprint R3).
- Update the docstring (`:33-54`) to mention the `filters` parameter and that it supersedes the individual kwargs when given.

### T1.3 — Unit tests for the value object + engine path
**File:** `tests/services/test_suggestion_filters.py` (new)
- Equality: two `SuggestionFilters` with the same crates in different insertion order compare equal (frozenset).
- Default `SuggestionFilters()` has all-`None`/0 fields.
- Inequality across each field.

**File:** `tests/services/test_suggestion_engine.py` (extend)
- A test that `get_suggestions(..., filters=SuggestionFilters(allowed_crates=frozenset({"X"})))` returns the same result as passing `allowed_crates={"X"}` via the kwarg (proves the unpack is faithful).

**Gate:** `python -m pytest` green. No app/UI change yet.

---

## Phase 2 — Panel staged/applied plumbing + control `restore()`

Goal: the panel can assemble a staged snapshot, hold an applied snapshot, detect dirty, and restore controls from a snapshot. `_update_suggestions` now forwards the applied snapshot. **Behaviour still live-apply** — Apply/Cancel not yet shown, `_filter_changed` still re-scores. Nothing user-visible changes.

### T2.1 — `current_staged_filters()` on the panel
**File:** `source/ui/suggestion_panel.py` (after the filter property block, ~`:198`)
Add:
```python
def current_staged_filters(self) -> SuggestionFilters:
    ...
```
Move the `None`-normalisation currently in `app._update_suggestions` (`source/app.py:309-318`) here:
- `allowed_crates = None if self.all_crates_selected else frozenset(self.selected_crates)`
- `allowed_genres = None if self.all_genres_selected else frozenset(self.selected_genres)`
- `key_offset = self.selected_key_offset`
- `date_from, date_to = self.selected_date_range`
Return a `SuggestionFilters(...)`. Import `SuggestionFilters` at top.

> Note: a fully-cleared filter (`is_cleared`, none selected) yields `allowed_crates=frozenset()` (empty, not `None`) — the engine then matches nothing, preserving today's intentional empty-state (`source/ui/filter_bar.py:410-412`, `source/services/suggestion_engine.py:81`). Verify `all_crates_selected` is `False` when cleared so `None` is NOT chosen.

### T2.2 — Applied-snapshot state + accessors
**File:** `source/ui/suggestion_panel.py` `__init__` (~`:96-101`)
- Add `self._applied_filters: SuggestionFilters = SuggestionFilters()` (default = no filters, matches the initial unfiltered render).
- Add a read-only `applied_filters` property returning `self._applied_filters`.
- Add `is_dirty` property: `return self.current_staged_filters() != self._applied_filters`.

### T2.3 — `restore(...)` on each control (silent — no `on_change`)
**File:** `source/ui/filter_bar.py`
Add to each control a method that pushes snapshot values into the widgets WITHOUT firing `_on_change` (mirror the existing silent `reset()` methods):
- `FilterDropdown.restore(self, selected: frozenset[str] | None)` (near `reset()` `:391-395`): if `selected is None`, set all vars `True` (no filter); else set each var to `name in selected`. Call `_update_label()`. Do **not** `_fire()`.
- `KeyOffsetControl.restore(self, offset: int)` (near `reset()` `:484-487`): `self._offset = offset; self._refresh()`. No fire.
- `DateRangeControl.restore(...)` — see T2.4 (needs richer state).

### T2.4 — Date control: commit/restore its own display state (blueprint R1/O1, recommendation (b))
**File:** `source/ui/filter_bar.py` `DateRangeControl`
The epoch tuple alone can't reconstruct preset highlight + manual entry text. Have the control own a private display snapshot:
- Add `self._committed_display` holding `(_range, _active_preset, from_text, to_text)`.
- Add `commit_display(self)` — snapshot the current display state into `_committed_display`. Called by the panel on Apply (T3.4).
- Add `restore_display(self)` — restore `_range`, `_active_preset`, entry text, pill, preset styles from `_committed_display`. Silent (no `_fire`). Called by the panel on Cancel (T3.5).
- Initialise `_committed_display` to the default ("any time") state in `__init__`.

This keeps `SuggestionFilters` a thin engine-facing epoch model while Cancel still restores the exact visual state (blueprint §3, R1). Crate/genre/key controls restore fully from the snapshot (T2.3); only the date control needs this extra display memory.

### T2.5 — `_update_suggestions` forwards the applied snapshot
**File:** `source/app.py:304-330`
- Remove the inline `None`-normalisation block (`:309-318`).
- Replace the `get_suggestions(...)` call (`:320-329`) with:
  `scored = get_suggestions(self._current_track, self.library, exclude_paths=self.session_panel.played_paths, filters=self.suggestion_panel.applied_filters)`
- Import `SuggestionFilters` only if needed (not required here — the panel supplies it).

**Gate:** app still runs; filters still apply live (because `_filter_changed` still re-scores and Apply sets nothing yet). `_applied_filters` starts as default — confirm the initial render is unfiltered and a track selection re-scores with `applied_filters` (still default until Phase 3 sets it on Apply). **Important interim caveat:** between Phase 2 and Phase 3, because `_applied_filters` is never updated yet, live edits would NOT affect results (they update widgets but `_update_suggestions` reads the unchanging applied snapshot). To keep Phase 2 truly behaviour-neutral, in `_filter_changed` (still firing re-score this phase) also set `self._applied_filters = self.current_staged_filters()` *before* calling the app re-score. Remove that line in Phase 3 (T3.2). This keeps each phase independently runnable.

---

## Phase 3 — Decouple `on_change`; add Apply/Cancel (the visible change)

Goal: filter edits stage only; a dirty Apply/Cancel affordance appears; only Apply re-scores; Cancel reverts to applied. Apply/Cancel bar is panel-owned, anchored at the bottom of `SuggestionPanel` (Row 4), hidden by default. Pills gain a staged-tint state. Date overlay "Apply" button renamed "Set dates". Full specification: `ui-design-brief.md`.

### T3.1 — Panel `_on_staged_change()` (dirty recompute, no re-score)
**File:** `source/ui/suggestion_panel.py:199-201`
Rename/repurpose `_filter_changed` → `_on_staged_change`:
- Compute `dirty = self.is_dirty`.
- Show/hide the Apply/Cancel affordance based on `dirty` (T3.3).
- Do **NOT** call the app re-score callback here.
Update the `FilterBar(... on_filter_change=self._on_staged_change)` wiring (`:123`).

### T3.2 — Remove the interim applied-sync from `_filter_changed`
**File:** `source/app.py`
Delete the interim line added in T2.5 that set `_applied_filters` on every edit. From now on `_applied_filters` is set ONLY by Apply (T3.4). Confirm `app._on_crate_filter_changed` (`:301-302`) is no longer reached by filter edits.

### T3.3 — Apply/Cancel affordance widgets (panel-owned — blueprint O2)
**File:** `source/ui/suggestion_panel.py`
Add an Apply/Cancel affordance the panel can show/hide. A `CTkFrame` in `SuggestionPanel` grid Row 4 (below the scroll frame, which remains Row 3 with `weight=1`). Row 4 has no weight — it takes only its natural height (40px). Hidden by default via `grid_remove()`; shown via `grid()` when dirty.

Bar contents (left to right):
- `CTkLabel` text `"Filters changed"`, size 12, `text_color="#999999"`. Column 0.
- Spacer: `grid_columnconfigure(1, weight=1)`.
- Cancel `CTkButton`: text `"Cancel"`, height 30, width 80, `corner_radius=6`, `fg_color=("gray35","gray35")`, `hover_color=("gray45","gray45")`, `text_color="#ffffff"`. Column 2.
- Apply `CTkButton`: text `"Apply"`, height 30, width 80, `corner_radius=6`, `fg_color="#1f6aa5"`, `hover_color="#2980c0"`, `text_color="#ffffff"`, `font=CTkFont(size=12, weight="bold")`. Column 3.

Bar frame: `fg_color=("gray20","gray20")`, 1px top border `#333333`, `padx=8, pady=6`.

Both handlers must call `FloatingOverlay.close_open()` first to dismiss any open overlay before applying or reverting.

`_show_apply_bar()` / `_hide_apply_bar()` toggle `grid()` / `grid_remove()` on the bar frame.

### T3.4 — Apply handler (the sole filter re-score trigger)
**File:** `source/ui/suggestion_panel.py`
```python
def _apply_filters(self):
    if not self.is_dirty:        # guarded no-op (blueprint §4)
        self._hide_apply_bar(); return
    self._applied_filters = self.current_staged_filters()
    self.filter_bar.date_range.commit_display()   # T2.4
    self._hide_apply_bar()
    if self._on_filter_change:   # the app re-score callback, now fired ONLY here
        self._on_filter_change()
```
`self._on_filter_change` is the existing constructor callback (= `app._on_crate_filter_changed` → `_update_suggestions`, `source/app.py:97,301-302`). It now fires exclusively from Apply.

### T3.5 — Cancel handler (revert widgets to applied; no re-score)
**File:** `source/ui/suggestion_panel.py`
```python
def _cancel_filters(self):
    f = self._applied_filters
    self.filter_bar.crate_filter.restore(f.allowed_crates)
    self.filter_bar.genre_filter.restore(f.allowed_genres)
    self.filter_bar.key_offset.restore(f.key_offset)
    self.filter_bar.date_range.restore_display()   # T2.4
    self.filter_bar._update_reset_visibility()     # keep "Reset filters" link correct
    self._hide_apply_bar()
    # no re-score: the rendered list already reflects _applied_filters
```
> `restore(None)` for crate/genre means "no filter" → all-selected (T2.3). Confirm this matches the applied state when no filter was active.

### T3.6 — Reset stages (does not apply) — blueprint D6
**File:** `source/ui/filter_bar.py:741-766`
- `FilterBar._changed` (`:741-744`): route to the panel's dirty recompute (already happens via `on_filter_change` → `_on_staged_change`). Confirm it no longer reaches a re-score.
- `FilterBar._reset_all` (`:758-766`): after resetting all controls, it currently calls `on_filter_change` — that now flows into `_on_staged_change` (dirty recompute), so Reset surfaces Apply/Cancel and requires Apply to take effect. No code change beyond confirming the terminus; remove any assumption that `_reset_all` re-scores.

### T3.7 — Empty-state copy reads APPLIED state (blueprint R5)
**File:** `source/ui/suggestion_panel.py:203-218`
`set_suggestions` currently derives empty-state flags from live widgets (`self.crates_cleared`, `self.selected_date_range`). Change these to read `self._applied_filters`:
- crates_active_empty: `self._applied_filters.allowed_crates == frozenset()` (cleared = empty set, not `None`).
- genres_active_empty: `self._applied_filters.allowed_genres == frozenset()`.
- date_filter_active: `(self._applied_filters.date_from, self._applied_filters.date_to) != (None, None)`.
This ensures the empty-state message describes the filters actually in effect, not staged-but-unapplied edits.

### T3.8 — Rename the date overlay's internal "Apply" button (blueprint R2)
**File:** `source/ui/filter_bar.py:572-576`
Rename to `text="Set dates"`, `width=70` (up from 60 to fit two words at size 11). Wiring (`_on_apply_manual`) is unchanged — it still only stages the manual date entry into the staged date value. "Set dates" is scoped; "Apply" is global. No other changes to this button.

### T3.9 — Staged-tint pill colour (visual staged-vs-applied affordance)
**Files:** `source/ui/filter_bar.py` (`FilterDropdown._update_label`, `KeyOffsetControl._refresh`, `DateRangeControl._update_pill`)

Add a third pill colour state for "staged, non-default, differs from applied." The panel calls a `mark_staged(is_staged: bool)` method on each control after every `_on_staged_change()` call. Each control stores the flag and uses it in its colour logic:

- `is_staged=True` AND non-default value → `fg_color="#3a88c8"` (staged tint, lighter than applied accent).
- `is_staged=False` AND non-default value → `fg_color="#1f6aa5"` (ACCENT_BLUE, applied accent, full intensity).
- Default value (regardless of `is_staged`) → `fg_color=NEUTRAL_PILL` (grey).

The panel derives `is_staged` per-control in `_on_staged_change()` by comparing the relevant field of `current_staged_filters()` against `_applied_filters`:
- Crates: `staged.allowed_crates != applied.allowed_crates`
- Genres: `staged.allowed_genres != applied.allowed_genres`
- Key offset: `staged.key_offset != applied.key_offset`
- Date: `(staged.date_from, staged.date_to) != (applied.date_from, applied.date_to)`

On Apply (T3.4), call `mark_staged(False)` on all controls after updating `_applied_filters` — the applied state is now committed, no control is staged. On Cancel (T3.5), the `restore(...)` calls bring widget values in line with applied; then call `mark_staged(False)` on all controls.

**Gate (manual):** toggling several crate checkboxes does NOT re-score; Apply/Cancel appears on first change; Apply re-scores exactly once; Cancel restores every control to last-applied and hides the bar; a track selection re-scores using last-applied filters while any staged-but-unapplied edits remain visible in the controls; "Reset filters" stages and needs Apply; changed pills show lighter blue tint while staged, full accent blue after Apply.

---

## Phase 4 — Docs + tests

### T4.1 — ADR-012
**File:** `docs/architecture-decisions.md` (append after ADR-011)
Add ADR-012 from blueprint §2 (status Accepted once merged).

### T4.2 — Overview updates
**File:** `docs/architecture-overview.md`
- Architectural Debt #11: mark `SuggestionFilters` **Resolved** (now a value object in `source/services/suggestion_filters.py`, assembled by the panel and forwarded to the engine).
- "Suggestion filters" data-flow note (`:102`): note that `get_suggestions` now accepts a single `SuggestionFilters` and that filters are applied on an explicit Apply (deferred), not live. Reference ADR-012.

### T4.3 — Panel/behaviour tests (where testable without a display)
**File:** `tests/services/test_suggestion_filters.py` (extend) — already covers equality/dirty.
Note: `SuggestionPanel` is CTk-bound and hard to unit-test headless; keep the *logic* testable by ensuring `current_staged_filters()` normalisation and dirty comparison live in pure/near-pure form. If feasible, extract the `None`-normalisation into a small pure helper (`build_filters(all_crates_selected, selected_crates, ...) -> SuggestionFilters`) in `suggestion_filters.py` and unit-test that directly; the panel method then just calls it with widget reads. **Recommend this extraction** — it makes dirty detection and normalisation testable without a Tk display.

**Gate:** `python -m pytest` green.

---

## Execution order summary
1. T1.1 → T1.2 → T1.3 (engine; invisible; tests green)
2. T2.1 → T2.2 → T2.3 → T2.4 → T2.5 (panel plumbing; still live-apply via interim sync)
3. T3.1 → T3.2 → T3.3 → T3.4 → T3.5 → T3.6 → T3.7 → T3.8 → T3.9 (flip to deferred Apply + full visual treatment)
4. T4.1 → T4.2 → T4.3 (docs + tests)

Do not start Phase 3 until Phase 2 runs cleanly: the state model and engine wiring must be proven before the UX changes.

---

## UI revisions applied

> Added by the UI Designer agent on 2026-05-30. Summarises every `<!-- UI-designer to revise -->` placeholder that was replaced and any task additions or changes made on UI grounds.

### Placeholders replaced

**Blueprint §2 D6 / §5 "Reset filters" placement** — replaced the open call-out with a confirmed decision: "Reset filters" stays as a right-anchored `CTkLabel` link in the FilterBar row (Row 1) with its existing label copy unchanged. It does not merge into the Apply/Cancel bar. Rationale: three affordances with distinct labels ("Reset filters" = defaults, "Cancel" = last-applied, "Apply" = commit) are clearer than any merged control, and spatial separation (Row 1 vs Row 4) reinforces the distinction.

**Blueprint §8 Phase 3 affordance** — replaced the open call-out with a precise specification: panel-owned `CTkFrame` in `SuggestionPanel` Row 4, `grid_remove()` when clean, `grid()` when dirty. Apply = accent blue bold button; Cancel = neutral grey button; "Filters changed" label left-anchored. Tokens and sizes specified.

**Blueprint R2 date overlay button** — resolved naming collision: internal "Apply" button renamed to "Set dates" (`width=70`). "Set dates" = scoped commit of manual entry to staged value; global "Apply" = commit all four filters and re-score. Wiring unchanged.

**Blueprint R4 three affordances** — resolved visual relationship: Reset link (Row 1, always in filter area), Apply/Cancel bar (Row 4, below list). No merging, no coupling beyond the shared dirty-recompute path. Per-control "Clear" inside FilterDropdown overlays is a fourth affordance, scoped to overlay-open state, no conflict.

**Blueprint O2 affordance ownership** — confirmed panel-owned placement. `FilterBar` emits dirty-changed signals upward; panel owns the bar and handlers.

**Implementation plan Phase 3 header** — replaced open call-out with concise spec summary pointing to `ui-design-brief.md`.

**Implementation plan T3.3** — replaced open call-out with full widget specification: grid layout, button tokens (height 30, width 80, colour values), `FloatingOverlay.close_open()` requirement in both handlers.

**Implementation plan T3.8** — replaced open call-out for final label with confirmed copy: "Set dates", `width=70`.

### Tasks added

**T3.9 — Staged-tint pill colour** — new task in Phase 3. Introduces a `mark_staged(bool)` method on each control; panel calls it on every `_on_staged_change()`, Apply, and Cancel. Staged + non-default pill colour: `#3a88c8` (lighter tint). Applied + non-default: `#1f6aa5` (full accent). Default: grey. This gives the DJ a per-pill cue for which filters have pending edits, complementing the Apply/Cancel bar as the primary pending-changes signal.

### Scope clarification added

**R5 / T3.7 coordination** — the empty-state copy must read `_applied_filters` fields, not live widget properties. Confirmed in T3.7 (already in plan); flagged in the design brief §States (State 5) so the engineer has explicit direction from both sides.

**FloatingOverlay.close_open() in Apply and Cancel handlers** — added as a requirement in T3.3 and the design brief §Risks R5. An open overlay must be dismissed before Apply or Cancel executes to avoid a stale floating panel over a freshly re-scored list.
