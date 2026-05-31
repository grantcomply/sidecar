# Architect Blueprint — Deferred Filter Apply

> **Status:** Proposed
> **Date:** 2026-05-30
> **Author:** Architect agent
> **Plan folder:** `plans/deferred-filter-apply-2026-05/`
> **Related ADRs:** ADR-011 (suggestion filters), ADR-002 (in-memory filtering); introduces the deferred-debt `SuggestionFilters` value object (`docs/architecture-overview.md` Architectural Debt #11).

---

## 1. Context

### The problem (user's words)
> "when i select filters as i select it's filtering and causing everything to reload and make it unresponsive. Once i change a filter an 'apply' or 'cancel' should appear at the bottom and only when i click 'apply' should the filter take effect."

### Why it happens today
Every filter control fires `on_change` on **every** interaction, and `on_change` is wired straight through to a full re-score:

- `FilterDropdown._on_check_changed` / `_select_all` / `_deselect_all` each call `self._fire()` → `_on_change` (`source/ui/filter_bar.py:360,367,371,387-389`).
- `KeyOffsetControl._step` calls `self._on_change` on every stepper tap (`source/ui/filter_bar.py:475-476`).
- `DateRangeControl._on_preset` / `_on_apply_manual` call `self._fire()` (`source/ui/filter_bar.py:608,633`).
- All four are wired to `FilterBar._changed` (`source/ui/filter_bar.py:716,720,723,726`), which calls `on_filter_change` (`source/ui/filter_bar.py:741-744`).
- That callback chain is `FilterBar.on_filter_change` → `SuggestionPanel._filter_changed` (`source/ui/suggestion_panel.py:123,199-201`) → `SuggestionPanel.on_filter_change` = `app._on_crate_filter_changed` (`source/app.py:97,301-302`) → `app._update_suggestions()` (`source/app.py:304-330`) → `get_suggestions(...)` (`source/services/suggestion_engine.py:26`).

So a single checkbox toggle in a 9-crate dropdown triggers a full `get_suggestions` pass over the entire library plus a complete teardown/rebuild of the suggestion grid (`SuggestionPanel.set_suggestions` destroys and recreates every row, `source/ui/suggestion_panel.py:203-317`). Toggling several checkboxes in sequence re-scores once per toggle — the unresponsiveness the user describes.

### Confirmed design (build to these — not re-litigated)
1. **Deferred apply, global scope.** All four filters (Crates, Genres, Transition/key-offset, Date) stage their changes. Changing any filter does NOT re-score. A single **Apply / Cancel** affordance appears whenever there are unapplied ("dirty") changes. Only **Apply** commits and triggers exactly ONE re-score.
2. **Cancel reverts to last-applied.** Cancel discards staged changes and restores every control to its last-applied values. It does NOT clear to defaults.

---

## 2. Decision (ADR-style)

### ADR-012: Deferred filter application with a `SuggestionFilters` snapshot

- **Status:** Proposed
- **Date:** 2026-05-30
- **Relates to:** ADR-011 (introduced the four filter inputs and named `SuggestionFilters` as the next step); ADR-002 (filtering stays in-memory).

#### Context
See §1. Filters apply live, one re-score per interaction. The user wants staged edits with an explicit Apply/Cancel. This is also the moment ADR-011 flagged for introducing the `SuggestionFilters` value object (`docs/architecture-overview.md` debt #11): a single snapshot of all four filter values that can be **captured on Apply**, **compared for dirty detection**, **restored on Cancel**, and **forwarded to `get_suggestions` in one object**.

#### Decision

**D1 — Introduce a frozen `SuggestionFilters` value object as the unit of staged-vs-applied state.**
A frozen dataclass holding the four filter values in their *engine-ready* form:

```python
# source/services/suggestion_filters.py  (new leaf module, no UI imports)
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass(frozen=True)
class SuggestionFilters:
    allowed_crates: frozenset[str] | None = None   # None = no crate filter
    allowed_genres: frozenset[str] | None = None   # None = no genre filter
    key_offset: int = 0
    date_from: float | None = None
    date_to: float | None = None
```

Rationale for adopting the value object **now** rather than keeping per-control staged state:
- The snapshot **is** the staged-vs-applied model. "Staged" and "applied" become two `SuggestionFilters` instances; dirty = `staged != applied`; Cancel = restore widgets from `applied`. Per-control staged duplicates this four times with no shared equality.
- Frozen + value-equality gives **dirty detection for free** (`==` on the dataclass). No bespoke per-control comparison.
- It collapses the five-keyword `get_suggestions` call (`source/app.py:320-329`) into one typed argument — paying down debt #11 exactly as ADR-011 scoped it.
- `frozenset` (not `set`) for the crate/genre fields so the dataclass is hashable and its equality is order-independent — two snapshots with the same crates compare equal regardless of selection order.

Why a new leaf module (`source/services/`): models the "current filter state" as domain data, not UI. It must be importable by both the engine and the panel with no UI dependency (mirrors the `harmonic_tier.py` leaf-module precedent from ADR-010).

**D2 — The widgets remain the single source of the *staged* state; the panel owns the *applied* snapshot.**
Do **not** add a second copy of staged state. The live widget values (existing `selected`, `selected_key_offset`, `selected_date_range`, etc.) **are** the staged state — they already hold "what the user is editing." The only new state is **one** `applied: SuggestionFilters` reference, owned by `SuggestionPanel`. Specifically:

- `SuggestionPanel` gains a method `current_staged_filters() -> SuggestionFilters` that reads the live control properties and assembles a snapshot (the `None`-means-no-filter normalisation currently in `app._update_suggestions` moves here — see D5).
- `SuggestionPanel` stores `self._applied_filters: SuggestionFilters` — the last-applied snapshot. Initialised to the default `SuggestionFilters()` at construction (= no filters), matching the initial unfiltered render.
- **Dirty** = `current_staged_filters() != self._applied_filters`.
- **Apply** = set `self._applied_filters = current_staged_filters()`, then trigger one re-score.
- **Cancel** = restore each control's widgets from `self._applied_filters`, then hide the Apply/Cancel affordance. No re-score (the displayed list already reflects `_applied_filters`).

This keeps exactly one authoritative copy of staged state (the widgets) and one of applied state (the snapshot), avoiding a third "working copy" that could desync.

**D3 — `on_change` is decoupled from re-score. It now means "recompute dirty state and update the Apply/Cancel affordance" — never "re-score."**
The control `on_change` callbacks and the `FilterBar._changed` → `on_filter_change` chain stay wired, but their **terminal effect changes**: the chain no longer reaches `app._update_suggestions()`. Instead the terminus is `SuggestionPanel._on_staged_change()`, which (a) recomputes dirty and shows/hides Apply/Cancel, and (b) updates the existing "Reset filters" visibility. The **only** path that calls `app._update_suggestions()` from a filter interaction is the new **Apply** action.

**D4 — Apply is the sole filter-driven re-score trigger; a track change re-scores using the last-applied filters.**
`app._update_suggestions()` is retained as the single re-score path but is **no longer wired to filter `on_change`**. It is called by: Apply (new), and the existing non-filter triggers that must keep working — track selection (`_on_track_selected`, `_on_suggestion_selected`, `source/app.py:283-293`), session clear/remove (`_on_session_cleared`, `_on_session_track_removed`, `source/app.py:295-299`). When the now-playing track changes, `_update_suggestions` reads the **applied** snapshot (not staged), so the persisted filters still apply. Staged-but-unapplied edits survive a track change untouched (they live in the widgets); the Apply/Cancel affordance stays visible if it was. This satisfies the edge case "a track change still re-scores using last-applied filters."

**D5 — `app._update_suggestions()` reads the applied snapshot and forwards it as one object.**
The `None`-normalisation block (`source/app.py:309-318`) moves into `SuggestionPanel.current_staged_filters()` (so the snapshot is always engine-ready). `_update_suggestions` becomes: read `self.suggestion_panel.applied_filters`, pass it to a `get_suggestions` overload that accepts a `SuggestionFilters`. The engine signature gains a single `filters: SuggestionFilters | None = None` parameter; when provided it supersedes the individual keyword args. (Keeping the keyword args with a default-`None` filters object preserves the existing engine tests and call sites — see Phase 1.)

**D6 — Reset (both per-control `reset()` and the bar-level "Reset filters" link) STAGES; it does not apply.**
For a consistent mental model — *all* filter mutations stage and require Apply — "Reset filters" restores every control to its **default** (all-selected / offset 0 / any-time), which is a staged change like any other. It marks dirty (if defaults differ from applied) and surfaces Apply/Cancel; it does **not** re-score. The existing `FilterBar._reset_all` (`source/ui/filter_bar.py:758-766`) currently calls `on_filter_change` (which used to re-score) — that now just flows into the dirty-recompute path, so Reset-then-Apply is required to take effect. This is the only consistent rule: if Reset applied immediately while every other control staged, the affordance contract would be ambiguous.

> **Note on the two "Reset"-shaped affordances:** "Reset filters" (revert to *defaults*, staged) and "Cancel" (revert to *last-applied*) are now distinct operations and must read as such. "Reset filters" stays as a right-anchored `CTkLabel` link in the `FilterBar` row (Row 1), unchanged in placement and label copy — it is a staged shortcut for setting all controls to defaults and does NOT merge into the Apply/Cancel bar. "Cancel" lives in the Apply/Cancel bar (Row 4, panel-owned), which is a separate grid row below the scroll frame. The three affordances — Reset filters link, Cancel button, Apply button — carry distinct labels and distinct mental models (defaults / last-applied / commit). See `ui-design-brief.md` §"Reset filters".

#### Consequences
- Pro: One re-score per Apply instead of one per interaction — fixes the unresponsiveness directly.
- Pro: `SuggestionFilters` lands, paying down debt #11; `get_suggestions` gains a single typed filter argument; dirty detection is free via dataclass equality.
- Pro: No third copy of state — widgets stay the staged source, panel owns one applied snapshot.
- Pro: Track/session changes keep working and correctly reuse the last-applied filters.
- Con: Loss of live preview — the user no longer sees results update as they toggle. This is the explicit, requested trade-off.
- Con: One more concept (staged vs applied) and a visible Apply/Cancel affordance the user must learn. UI-designer to make this obvious.
- Con: Two revert-style affordances (Reset-to-defaults vs Cancel-to-applied) risk confusion; mitigated by clear UI labelling (UI-designer).

---

## 3. Staged-vs-applied state model (the core)

| Concept | Where it lives | Notes |
|--------|----------------|-------|
| **Staged / working value** | The live control widgets (`FilterDropdown._vars`, `KeyOffsetControl._offset`, `DateRangeControl._range`/`_active_preset`/entries) | Already exists. Read via existing `selected*` / `is_cleared` / `selected_key_offset` / `selected_date_range` properties. No new staged copy. |
| **Staged snapshot (derived)** | `SuggestionPanel.current_staged_filters()` | Assembled on demand from the widgets; engine-ready (`None`-normalised). Used for dirty comparison and as the value committed on Apply. |
| **Applied / committed value** | `SuggestionPanel._applied_filters: SuggestionFilters` | The snapshot the engine last ran with. What Cancel reverts the widgets to. What `_update_suggestions` forwards. |
| **Dirty flag (derived)** | `current_staged_filters() != _applied_filters` | Drives Apply/Cancel visibility. Not stored — recomputed on each `on_change`. |

**Cancel restoration.** Cancel must push `_applied_filters` back into each control's widgets. This needs a new `apply_snapshot(filters)` (or per-control `restore(...)`) capability on each control, because the existing `reset()` methods restore to **defaults**, not to an arbitrary snapshot. Specifically each control needs:

- `FilterDropdown.restore(selected: frozenset[str] | None)` — set each checkbox var to `name in selected` (or all-true when `None` = no filter), refresh label. `None` here means "no crate filter" → all checkboxes true.
- `KeyOffsetControl.restore(offset: int)` — set `_offset`, `_refresh()`.
- `DateRangeControl.restore(date_from, date_to)` — reconstruct `_range`, `_active_preset`, and the pill/preset styling from an epoch tuple. **Open question O1** below: the snapshot stores epochs, but the control's display state (which preset was active, the manual entry strings) is richer than `(date_from, date_to)`. See O1.

All `restore(...)` calls must **not** fire `on_change` (mirroring how `reset()` is silent today), or Cancel would mark itself dirty.

---

## 4. Dirty detection

Dirty = the staged snapshot differs from the applied snapshot. Because `SuggestionFilters` is a frozen dataclass with `frozenset` collection fields, `==` is:
- order-independent for crates/genres (frozenset equality),
- exact for `key_offset` (int), `date_from`/`date_to` (float|None).

Edge cases this handles correctly:
- **No changes at all** → `current == applied` → not dirty → no Apply/Cancel. (Initial state: both are `SuggestionFilters()`.)
- **Toggle off then back on** → snapshot returns to equal → dirty clears → affordance hides. (Free, because equality is on values not on "did an event fire.")
- **Apply with nothing staged** → can't happen: Apply is only visible when dirty. If reached defensively, `applied = current` is a no-op assignment and the single re-score is harmless (same as today's behaviour). Recommend Apply also be a guarded no-op when `not dirty`.

> **Date normalisation caveat for equality:** the date control can represent "any time" as `(None, None)` and as a "This year"-style preset epoch tuple. For dirty detection only the **epoch tuple** matters (that's what the engine sees), so `current_staged_filters()` must read `selected_date_range` (epochs), and `_applied_filters.date_from/date_to` are epochs. Two date states that produce identical epoch windows are correctly equal. The *display* difference (preset vs manual) is irrelevant to the engine and to dirty — confirm with UI-designer that this is acceptable (it should be). See O1.

---

## 5. How Apply/Cancel interact with `reset()` and "Reset filters"

Per D6: **everything stages.** The decision table:

| Action | Staged effect | Applied effect | Re-score? | Affordance after |
|--------|---------------|----------------|-----------|------------------|
| Toggle any control | widget changes | none | no | Apply/Cancel shown if now-dirty |
| Per-control `reset()` (if exposed in UI) | control → default | none | no | Apply/Cancel shown if now-dirty |
| Bar "Reset filters" link | all controls → defaults | none | no | Apply/Cancel shown if defaults ≠ applied |
| **Apply** | unchanged | applied ← staged | **yes (one)** | hidden (now clean) |
| **Cancel** | controls ← applied | unchanged | no | hidden (now clean) |

"Reset filters" visibility (the existing right-anchored link, `source/ui/filter_bar.py:746-756`) keys off "any control deviates from default" and is independent of dirty. It can coexist with Apply/Cancel. **Recommendation confirmed:** "Reset filters" stays as a stage-only shortcut, right-anchored in the `FilterBar` row, visible when any staged value deviates from default (keyed off staged values, not applied). It does not couple to Apply/Cancel logic beyond the shared dirty-recompute. Visual relationship: Reset link in Row 1 (filter controls), Apply/Cancel bar in Row 4 (panel-owned, below the list). See `ui-design-brief.md` §"Reset filters".

---

## 6. The decoupling of `on_change` (precise wiring change)

**No control-level callback signatures change.** The controls keep firing `on_change` exactly as today. The change is purely in the **terminus**:

- **Today:** `control.on_change` → `FilterBar._changed` → `FilterBar.on_filter_change` → `SuggestionPanel._filter_changed` → `SuggestionPanel.on_filter_change` (= `app._on_crate_filter_changed`) → `app._update_suggestions()` (RE-SCORE).
- **After:** `control.on_change` → `FilterBar._changed` → `FilterBar.on_filter_change` → `SuggestionPanel._on_staged_change()` (DIRTY RECOMPUTE + Apply/Cancel visibility) → **stops here. No re-score.**

The single edit that breaks the live-apply link: `SuggestionPanel._filter_changed` (`source/ui/suggestion_panel.py:199-201`) must stop calling `self._on_filter_change` (the app re-score callback) and instead update dirty state. The app's `on_filter_change` constructor wiring (`source/app.py:97`) is **repurposed**: the panel should no longer treat it as "re-score now." Cleanest approach: the panel stops needing `app._on_crate_filter_changed` for filter edits entirely, and instead the panel calls back into the app **only on Apply** via a dedicated callback (e.g. reuse `on_filter_change` but only fire it from the Apply handler). See implementation plan for the exact rename/rewire.

---

## 7. Affected files

| File | Change |
|------|--------|
| `source/services/suggestion_filters.py` | **New.** Frozen `SuggestionFilters` dataclass (D1). |
| `source/services/suggestion_engine.py` | `get_suggestions(..., filters: SuggestionFilters \| None = None)` — when provided, unpack it; otherwise fall back to existing keyword args (D5). `:26-141`. |
| `source/ui/suggestion_panel.py` | Add `current_staged_filters()`, `applied_filters` property, `_applied_filters` state, `_on_staged_change()`, Apply/Cancel handlers (`_apply_filters`, `_cancel_filters`), `is_dirty`. Rewire `_filter_changed` (`:199-201`) to dirty-recompute. Move `None`-normalisation in from `app.py`. |
| `source/ui/filter_bar.py` | Add `restore(...)` to `FilterDropdown`, `KeyOffsetControl`, `DateRangeControl` (silent, for Cancel). Add the Apply/Cancel affordance widgets + a `set_dirty(bool)`/visibility hook, OR expose hooks so the panel owns the affordance (UI-designer to decide placement: in `FilterBar` vs in `SuggestionPanel`). Route `_changed`/`_reset_all` to dirty-recompute, not re-score. |
| `source/app.py` | `_update_suggestions()` (`:304-330`) reads `suggestion_panel.applied_filters`, forwards as one object; remove the inline `None`-normalisation. Repurpose `_on_crate_filter_changed`/`on_filter_change` wiring so it fires only on Apply (`:97,301-302`). |
| `docs/architecture-decisions.md` | Add ADR-012. |
| `docs/architecture-overview.md` | Mark debt #11 (`SuggestionFilters`) resolved; update the "Suggestion filters" data-flow note. |
| `tests/services/` | New `test_suggestion_filters.py` (equality/dirty, `None`-normalisation); extend `test_suggestion_engine.py` for the `filters=` path. |

---

## 8. Phases (high level — see implementation-plan.md for ordered tasks)

- **Phase 1 — State model + engine (no UI behaviour change yet).** Add `SuggestionFilters`; add `filters=` to `get_suggestions`; unit-test. Engine still works via existing keyword path; nothing observable changes.
- **Phase 2 — Panel staged/applied plumbing.** Add `current_staged_filters()`, `_applied_filters`, dirty detection, `restore(...)` on each control. Wire `_update_suggestions` to the applied snapshot. At end of Phase 2, behaviour can still be "apply live" if Apply/Cancel not yet shown — keep it gated.
- **Phase 3 — Decouple `on_change` from re-score + Apply/Cancel affordance.** Flip `_filter_changed` to dirty-recompute; add Apply/Cancel handlers; only Apply re-scores. This is the phase that delivers the user-visible behaviour change. Apply/Cancel bar: panel-owned `CTkFrame` in `SuggestionPanel` Row 4, hidden via `grid_remove()` by default, shown when dirty. Apply = accent blue (`#1f6aa5`) bold `CTkButton`; Cancel = neutral grey `CTkButton`; "Filters changed" `CTkLabel` left-anchored. Both buttons height 30, width 80. Full specification in `ui-design-brief.md`.
- **Phase 4 — Docs + tests.** ADR-012, overview update, panel-level tests for dirty/apply/cancel.

Phases 1–2 are safe to land without changing observable behaviour; Phase 3 flips the switch. This lets the engineer execute and verify the risky state-model work before touching UX.

---

## 9. Risks & open questions

**R1 — Cancel can't fully reconstruct the date control's display from an epoch tuple.** `_applied_filters` stores `(date_from, date_to)` epochs, but `DateRangeControl` display state also includes `_active_preset` and the manual entry strings (`source/ui/filter_bar.py:522-523,599-633`). Restoring epochs alone may leave the pill label / preset highlight inconsistent with the restored window. **Mitigation / O1:** either (a) `DateRangeControl.restore(from, to)` re-derives a best-effort display (match epochs back to a known preset, else show as a manual range), or (b) the control keeps its own richer "last-applied display state" snapshot internally that Cancel restores, while the panel-level `SuggestionFilters` keeps only epochs for the engine. **Recommendation: (b)** — let each control own restoring its own full display state on Cancel (a private `_committed_display` it snapshots on Apply), while `SuggestionFilters` stays a thin engine-facing epoch model. This keeps the value object clean and avoids reverse-engineering presets from epochs. Decide in Phase 2.

**R2 — Naming collision: the date overlay already has an internal "Apply" button.** `DateRangeControl._build_overlay` creates a `CTkButton(text="Apply", ...)` (`source/ui/filter_bar.py:572-576`) that applies the *manual date entry into the staged date value*. The new global Apply commits *all four filters and re-scores*. Two buttons labelled "Apply" with different scopes is a UX trap. **Resolved by UI-designer:** rename the overlay's button to **"Set dates"**. "Set dates" is scoped (confirms the manual entry into the staged value), while "Apply" is global (commits all four filters and re-scores). Width: increase from 60 to 70px to fit the two-word label at size 11. Wiring to `_on_apply_manual` is unchanged.

**R3 — `frozenset` vs `set` at the engine boundary.** `get_suggestions` currently does `allowed_crates.intersection(track.crates)` and `track.genre not in allowed_genres` (`source/services/suggestion_engine.py:81,85`). `frozenset` supports both, so no engine change is needed for the collection type. Confirm in Phase 1 test.

**R4 — The "Reset filters" link and Apply/Cancel can both be visible, plus per-control reset.** Three revert-ish affordances on screen at once (Reset-to-defaults link, Cancel-to-applied, and any per-control Clear). Functionally distinct but visually noisy. **Resolved by UI-designer:** three affordances, three distinct labels, two separate visual locations. "Reset filters" link = right end of FilterBar row (Row 1), always-visible when any staged value is non-default, label unchanged. "Cancel" + "Apply" = Apply/Cancel bar (Row 4, panel-owned), shown only when dirty. No merging. The per-control "Clear" button inside FilterDropdown overlays is a fourth affordance but is scoped to a single filter; it does not require visual separation from the others because it is only visible when the overlay is open. Full rationale in `ui-design-brief.md` §"Reset filters".

**R5 — Empty-state copy reads staged, not applied, state.** `SuggestionPanel.set_suggestions` derives its empty-state message from `self.crates_cleared` / `self.selected_date_range` (`source/ui/suggestion_panel.py:214-218`), which read **live widgets** (staged). After deferral the rendered list reflects **applied** filters, so the empty-state copy must read the **applied** snapshot, not the live controls — otherwise a staged-but-unapplied "Clear crates" would wrongly reword the (still-applied) result. **Mitigation:** `set_suggestions` should take its filter-context flags from `_applied_filters`. Fix in Phase 3.

**O1 (open) — date display restoration:** see R1. Recommend control-owned display snapshot. Decide in Phase 2.

**O2 (open, UI) — affordance ownership:** does the Apply/Cancel bar live in `FilterBar` (with the controls) or in `SuggestionPanel` (so it can sit "at the bottom of the suggestion panel" as the user said)? The user said "at the bottom." Architecturally either works; the panel owns the applied snapshot and the re-score trigger, so wiring is marginally simpler if the panel owns the affordance and `FilterBar` just emits a `dirty-changed` signal upward. **Panel-owned affordance confirmed.** The Apply/Cancel bar is a `CTkFrame` grid row in `SuggestionPanel` (Row 4, below the scroll frame Row 3). `FilterBar` emits dirty-changed signals upward; the panel owns the bar, the apply/cancel handlers, and the applied snapshot. `grid_remove()` / `grid()` on the bar frame avoids layout jumps when the bar appears. Full specification in `ui-design-brief.md` §"Apply/Cancel bar".
