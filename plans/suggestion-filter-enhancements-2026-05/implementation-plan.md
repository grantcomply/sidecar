# Implementation Plan — Suggestion Filter Enhancements

> Status: Proposed
> Date: 2026-05-30
> Author: Architect agent
> Companion: `architect-blueprint.md` (read it first — it carries the ADR reasoning)

Execute phases in order. Each engine change is gated behind a default argument, so
Phases 1–2 land with **zero behaviour change** until Phase 3 wires the UI. Run
`pytest` after every phase. All `file:line` citations are against the current tree.

---

## Phase 0 — UI Designer brief (blocks Phase 3 only)

**T0.1** — Hand `architect-blueprint.md` to the ui-designer. They produce
`plans/suggestion-filter-enhancements-2026-05/ui-design-brief.md` covering:
- the filter-UX review (sub-feature 2) — consolidated layout for four filters,
  reset/clear behaviour, the `None`-means-no-filter invariant from blueprint §3;
- the key-offset control spec (values from `KEY_OFFSET_RANGE`, default 0, copy);
- the date-added control spec (from / optional-to, preset-first per blueprint §4,
  honest first-sync caveat copy).

Engine work (Phases 1–2) proceeds in parallel; do not block on this.

---

## Phase 1 — Key transition offset (engine, no UI)

**T1.1 — Add `shift_key()` to `camelot.py`.**
- File: `source/services/camelot.py`. Add after `wheel_distance` (`:37-49`), before
  `classify` (`:52`).
- Signature: `def shift_key(key: str, steps: int) -> str | None:`
- Behaviour: parse via `parse_camelot` (`:24-34`); if `None`, return `None`. Shift the
  number with wrap: `new_num = ((num - 1 + steps) % 12) + 1`; keep the letter; return
  `f"{new_num}{letter}"`. Docstring must state it preserves letter and that direction
  lives here (engine), not in the symmetric score (cite ADR-010).
- Add `"shift_key"` to `__all__` (`:12-19`).

**T1.2 — Tests for `shift_key`.**
- File: `tests/services/test_camelot.py` (append).
- Cases: `shift_key("8A", 1) == "9A"`; `shift_key("1A", -1) == "12A"`;
  `shift_key("12B", 1) == "1B"`; `shift_key("8A", 0) == "8A"`;
  `shift_key("", 1) is None`; `shift_key("99X", 1) is None`.
- Add an explicit assertion/comment that `compatibility_score` symmetry is unaffected
  (guard against the R4 trap).

**T1.3 — Add `KEY_OFFSET_RANGE` to config.**
- File: `source/config.py`, near `MAX_SUGGESTIONS` (`:108`).
- `KEY_OFFSET_RANGE = (-2, 2)  # inclusive min/max for the transition offset filter`.

**T1.4 — Add `key_offset` to `get_suggestions`.**
- File: `source/services/suggestion_engine.py`.
- Signature (`:25-28`): add `key_offset: int = 0`.
- Import `shift_key` from camelot (`:6`).
- After computing `current.camelot_key` guard (`:52-53`), before scoring:
  - Resolve the harmonic target once, outside the loop (compute before `:35`):
    ```
    target_key = current.camelot_key
    if key_offset:
        shifted = shift_key(current.camelot_key, key_offset)
        if shifted:
            target_key = shifted
        # else: invalid/empty current key -> fall back to offset 0 (blueprint R5)
    ```
  - Inside the loop, when `key_offset` and `target_key != current.camelot_key`,
    exclude same-key candidates: after the `track.camelot_key` guard (`:52-53`), add
    `if key_offset and compatibility_score(current.camelot_key, track.camelot_key) >= 1.0: continue`
    (PERFECT == identical key — blueprint §2 "Excluding same-key").
  - Change the scoring call (`:54`) to score against the target:
    `key_score = compatibility_score(target_key, track.camelot_key)` and
    `harmonic_tier = classify(target_key, track.camelot_key)` (`:57`).
- Verify default `key_offset=0` reproduces today's exact behaviour (target == current,
  no exclusion).

**T1.5 — Tests for offset in `get_suggestions`.**
- File: `tests/services/test_suggestion_engine.py` (append).
- Cases: with `key_offset=1`, no PERFECT-same-key track appears; an exact `current+1`
  track scores as PERFECT against the shifted target; `key_offset=0` is identical to
  the existing baseline test; current track with empty key + offset falls back
  gracefully (no crash, behaves as offset 0).

Run `pytest`. Phase 1 is complete and shippable without UI.

---

## Phase 2 — Date-added data plumbing (engine + cache, no UI)

**T2.1 — Add `date_added` to `Track`.**
- File: `source/models/track.py`.
- Add field after `play_count` (`:20`): `date_added: float = 0.0`.
- In `from_dict` (`:90-148`): read `date_added = float(data.get("date_added", 0.0) or 0.0)`
  inside a `try/except (ValueError, TypeError)` mirroring the `bpm` pattern (`:95-99`);
  pass into the constructor (`:130-148`).
- `from_csv_row` (legacy, `:25-87`): leave `date_added` at default `0.0` — CSV is the
  dead loader (ADR-007). No change needed beyond the new default field.

**T2.2 — Emit a seed `date_added` from the parser.**
- File: `source/services/crate_parser.py`, in `get_track_metadata` (`:75-147`).
- Add `from pathlib import Path` to imports (`:6-13`).
- Compute seed mtime near the top of the function:
  ```
  date_added = 0.0
  try:
      date_added = Path(path).stat().st_mtime
  except OSError:
      pass
  ```
- Add `"date_added": date_added` to BOTH the `empty` dict (`:83-97`) and the populated
  return dict (`:133-147`).

**T2.3 — Carry-forward existing `date_added` (keep parser pure — blueprint R2).**
- File: `source/services/crate_parser.py`, `parse_all_crates` (`:160-223`).
- Add a parameter: `previous_tracks: dict[str, dict] | None = None` (defaults `None`).
- After building each track's `meta` (`:210-212`), before inserting, if
  `previous_tracks` has this `absolute_path` with a non-zero `date_added`, overwrite the
  seeded value:
  ```
  if previous_tracks:
      prev = previous_tracks.get(absolute_path)
      if prev and prev.get("date_added"):
          meta["date_added"] = prev["date_added"]
  ```
- This keeps the parser pure (no cache import); the caller supplies prior state.

**T2.4 — Wire carry-forward through sync.**
- File: `source/services/crate_sync.py`, `_run()` (`:18-31`).
- Before `parse_all_crates` (`:20-23`), load the previous cache:
  ```
  from source.services.cache import load_cache, save_cache
  prev = load_cache()
  previous_tracks = (prev or {}).get("tracks", {})
  ```
  (Note: after T2.5 bumps `CACHE_VERSION`, `load_cache` returns `None` for an old v1
  cache, so first post-upgrade sync carries nothing forward and seeds from mtime —
  correct and intended.)
- Pass `previous_tracks=previous_tracks` into `parse_all_crates`.

**T2.5 — Bump cache version.**
- File: `source/services/cache.py:16` — `CACHE_VERSION = 2`.
- `date_added` flows into the written JSON automatically (`save_cache` writes the tracks
  dict verbatim, `:99`). No other cache code change. Old v1 caches are ignored by
  `load_cache` version check (`:70-76`), forcing one self-healing re-sync (ADR-007).

**T2.6 — Add date-range filter to `get_suggestions`.**
- File: `source/services/suggestion_engine.py`.
- Signature: add `date_from: float | None = None, date_to: float | None = None`.
- In the loop, after the genre filter (`:47-48`), add:
  ```
  if date_from is not None and track.date_added < date_from:
      continue
  if date_to is not None and track.date_added > date_to:
      continue
  ```
- Note (blueprint §4): a track with `date_added == 0.0` is excluded when `date_from` is
  set — this is the intended "can't prove it's in range" behaviour.

**T2.7 — Tests for date filter.**
- File: `tests/services/test_suggestion_engine.py` (append).
- Build a small library with known `date_added` values. Assert: `date_from` excludes
  older tracks; `date_to` excludes newer; both bound a window; `date_added == 0.0`
  track is excluded when `date_from` is set; both `None` reproduces baseline.

Run `pytest`. Phase 2 complete and shippable without UI.

---

## Phase 3 — UI wiring (against ui-design-brief.md)

> Do not start until `ui-design-brief.md` (T0.1) exists. It is now complete. The
> engineer implements controls per that brief; the wiring below is the architectural
> contract. Read `ui-design-brief.md` in full before touching any UI file.

**T3.0 — Date conversion helper.**
- File: `source/ui/utils.py` (or `source/services/dates.py` if the function exceeds
  ~30 lines).
- Implement `date_range_to_epoch(preset: str | None, from_str: str | None, to_str: str
  | None) -> tuple[float | None, float | None]`.
  - Preset values: `"any time"` → `(None, None)`; `"last month"` → last 30 days;
    `"last 3 months"` → last 90 days; `"last 6 months"` → last 180 days;
    `"this year"` → Jan 1 of current year to now.
  - `from_str` / `to_str`: parse YYYY-MM-DD; raise `ValueError` on malformed input
    (caller catches and shows inline error).
  - `to_str` omitted / `None` → second element of tuple is `None` (open-ended upper
    bound, no "now" timestamp — per brief §Open questions Q2).
- Unit-test cases: each preset; from-only; from+to; None preset + None dates = (None,
  None); bad date string raises ValueError; year-boundary wrap (Dec 31 → Jan 1).
- This task is a prerequisite for T3.2.

**T3.1 — Key-offset control (`KeyOffsetControl`) in `SuggestionPanel`.**
- File: `source/ui/suggestion_panel.py`, filter bar (replaces filter row `:207-217`).
- Implement `KeyOffsetControl` as a new class in `suggestion_panel.py` (or a separate
  `source/ui/filter_bar.py` if Phase 3 grows large — engineer's call on file
  organisation).
- Widget structure: outer `CTkFrame` (corner_radius=6) with three children in a row:
  `CTkButton("◀", width=24, height=28, fg_color="transparent")` | `CTkLabel` | 
  `CTkButton("▶", width=24, height=28, fg_color="transparent")`.
- Arrow characters: `◄` (◀) and `►` (▶).
- Centre label text per brief §Microcopy (key offset): "Transition: same key" at 0;
  "Transition: +N" / "Transition: −N" at non-zero.
- Pill `fg_color`: `("gray75", "gray35")` at offset 0; `"#1f6aa5"` when non-zero.
- ◀ button disables at `KEY_OFFSET_RANGE[0]`; ▶ button disables at `KEY_OFFSET_RANGE[1]`.
- On each button press: update internal `_offset` int, reconfigure label and colours,
  call `self._filter_changed()` (`:276`).
- Expose `selected_key_offset: int` property: returns current offset, default 0.
  Mirrors `selected_crates` pattern (`:260-262`).
- Attach a `Tooltip` (`:388`, `source/ui/tooltip.py`) with copy: "Shift harmonic
  matching up or down the Camelot wheel. At +1 same-key tracks are hidden and
  one-step-up tracks move to the top."

**T3.2 — Date-range control (`DateRangeControl`) in `SuggestionPanel`.**
- File: `source/ui/suggestion_panel.py` (or `source/ui/filter_bar.py`).
- Requires T3.0 (date conversion helper) to be complete first.
- Pill button: `CTkButton` or `CTkFrame`+`CTkLabel` styled as a pill, height=32.
  Default label: "Added: any time". Active label per brief §Microcopy (date range).
  Pill `fg_color`: grey when default, `"#1f6aa5"` when any filter is active.
- Clicking the pill opens the floating overlay panel (see T3.3 for overlay pattern).
  Overlay contents (top to bottom):
  1. Five preset `CTkButton` tiles in a single `CTkFrame` row, height=28:
     "Any time", "Last month", "Last 3 months", "Last 6 months", "This year".
     Active tile: `fg_color="#1f6aa5"`. Inactive tiles: `fg_color=("gray75","gray35")`.
     Selecting a tile calls `date_range_to_epoch(preset=...)`, stores the result, closes
     the overlay, updates the pill label, calls `self._filter_changed()`.
  2. Thin `CTkFrame` separator (height=1, `fg_color="gray40"`).
  3. Manual entry row: `CTkLabel("From")` + `CTkEntry` (width=110) + `CTkLabel("To
     (optional)")` + `CTkEntry` (width=110) + `CTkButton("Apply", width=60)`.
     On "Apply": call `date_range_to_epoch(from_str=..., to_str=...)` inside
     `try/except ValueError`. On success: store result, close overlay, update pill, fire
     `_filter_changed()`. On error: set `CTkEntry` `border_color="#dc3545"`,
     show `CTkLabel` below: "Enter a date as YYYY-MM-DD."
  4. `CTkLabel` caveat text (secondary-grey, font size 11): "Dates are approximate for
     tracks added before your first sync."
- Expose `selected_date_range: tuple[float | None, float | None]` property.
  Default: `(None, None)`.
- Handle empty-state copy override in `SuggestionPanel.set_suggestions`: if
  `scored_tracks` is empty AND `selected_date_range != (None, None)`, call
  `_show_empty("No tracks found in this date range. Try a wider window or reset the
  date filter.")` instead of the generic copy.

**T3.3 — Floating overlay utility (prerequisite for T3.2, also used in T3.4).**
- Implement a reusable floating panel pattern used by both `FilterDropdown` (revised)
  and `DateRangeControl`.
- Preferred approach: a `CTkFrame` shown via `place()` over the `SuggestionPanel` at a
  y-offset below the filter bar. Call `lift()` after placing. Close on `<Button-1>`
  outside the frame (bind to root window with `add="+"`, unbind on close) or when
  another pill is opened.
- Alternative: `CTkToplevel` set `transient` to the main window, no `grab_set()`. Adds
  teardown complexity; use only if `place()` z-order proves unworkable.
- Only one overlay is open at a time; opening a second pill closes the first.

**T3.4 — Redesign `FilterDropdown` as a pill with floating overlay (sub-feature 2 UX).**
- File: `source/ui/suggestion_panel.py`, `FilterDropdown` class (`:48-156`) and filter
  row (`:207-217`).
- Replace the existing `CTkButton` toggle + inline `CTkFrame` expand pattern with:
  - A `CTkButton` or `CTkFrame`+`CTkLabel` pill (height=32, corner_radius=16).
    Label text per brief §Microcopy (filter bar): "Crates" (all selected), "Crates: 3/9"
    (partial), "Crates: House" (one item, truncated at 10 chars via `truncate()`).
  - Pill `fg_color`: grey when `all_selected`; `"#1f6aa5"` otherwise.
  - Clicking opens the floating overlay (T3.3) containing:
    - Compact "Select all" `CTkButton` (secondary styling, sentence case, height=24).
      No "Deselect All" button (removed — see brief §Finding 2).
    - The scrollable `CTkCheckBox` checklist (`:94-110`) — preserve existing dimensions.
  - Remove `self.dropdown` (the old inline frame, `:69-72`) and `_toggle()` (`:113-119`).
  - `_update_label()` (`:136-144`) revised to produce brief §Microcopy pill label text.
- Preserve invariants: `selected` property (`:150-152`), `all_selected` (`:154-156`),
  `_fire()` → `_on_change` (`:146-148`). Engine `None`-means-no-filter contract
  unchanged.

**T3.5 — Filter bar container and "Reset filters" affordance.**
- File: `source/ui/suggestion_panel.py`, replace filter row (`:207-217`).
- The filter bar is a `CTkFrame` (transparent background, fixed height ~36px) containing
  all four pill controls in a horizontal row with 6px inter-pill gap.
  Layout (left to right): Crates pill | Genres pill | Transition (KeyOffsetControl) |
  Added (DateRangeControl) | [spacer, weight=1] | "Reset filters" label.
- "Reset filters" `CTkLabel`: right-anchored, `text_color="#999999"`, `cursor="hand2"`,
  shown only when any filter is non-default (`grid()` / `grid_remove()` based on state).
  Hover: reconfigure `text_color="#ffffff"`. Bind `<Button-1>` to a method that resets
  all four controls to defaults and calls one `_filter_changed()`.
- `SuggestionPanel.grid_rowconfigure(1, minsize=36)` to prevent the filter bar from
  shrinking below its usable height.

**T3.6 — Forward new filters from `app`.**
- File: `source/app.py`, `_update_suggestions` (`:304-324`).
- Read `self.suggestion_panel.selected_key_offset` and `selected_date_range`; forward
  `key_offset=...`, `date_from=...`, `date_to=...` into `get_suggestions` (`:317-323`).
- No change to existing crate/genre translation logic (`:309-315`).
- Example (additive — no structural change to `_update_suggestions`):
  ```
  key_offset = self.suggestion_panel.selected_key_offset
  date_from, date_to = self.suggestion_panel.selected_date_range
  scored = get_suggestions(
      self._current_track, self.library,
      exclude_paths=..., allowed_crates=..., allowed_genres=...,
      key_offset=key_offset, date_from=date_from, date_to=date_to,
  )
  ```

Run the app (`python main.py`); manually verify:
- Offset stepper shifts the suggestion pool and the same-key track disappears at ±1.
- Date preset narrows results; empty state shows the date-specific message when filtered.
- "Reset filters" restores all four controls and the suggestion list to defaults.
- No inline expand/collapse behaviour remains; all dropdowns are floating overlays.
- Filter pills turn blue when active, grey when default.

---

## Phase 4 — Documentation

**T4.1 — Commit ADR-011** into `docs/architecture-decisions.md` (draft in blueprint §5).

**T4.2 — Update ADR-007** (`docs/architecture-decisions.md:124-150`): add `date_added`
to the cache structure block and note `CACHE_VERSION` is now 2.

**T4.3 — Update `docs/architecture-overview.md`**: note `Track.date_added` and cache
schema v2 where the data flow / cache are described.

---

## Suggested commit boundaries

1. Phase 1 (offset engine + tests + config).
2. Phase 2 (date plumbing: track field, parser, cache bump, sync carry-forward, engine
   filter + tests).
3. Phase 3 (UI controls + redesign + app wiring) — after ui-designer brief.
4. Phase 4 (docs).

Each commit is independently reviewable; Phases 1 and 2 are safe to merge ahead of the
UI because every engine change is inert until a non-default argument is supplied.

---

## UI revisions applied

> Added by the UI Designer agent (2026-05-30) after producing `ui-design-brief.md`.

### What changed and why

**Blueprint §2 (key offset UI) — placeholder replaced.**
The architect's placeholder said "stepper or dropdown, ui-designer's call." The brief
chose a three-part inline stepper (`[◀  Transition: same key  ▶]`) over a dropdown or
segmented button. Rationale: one tap per step, no dropdown open/close overhead, and the
directional arrows make the "move up/down the wheel" mental model physically legible.
Blueprint §2 now contains the full visual spec and the wiring contract.

**Blueprint §3 (filter UX) — placeholder replaced.**
The architect's placeholder described the substrate but deferred all design calls. The
brief's audit identified six concrete findings (toggle-as-label, dangerous Deselect All,
inline-expand pushing the list down, no active-filter signal, no global reset, narrow-
pane collision). Each finding has a named fix. Blueprint §3 now records the design
decisions — floating overlay, pill-button pills with blue active state, removal of
Deselect All, "Reset filters" affordance — without prescribing implementation details
the engineer owns.

**Blueprint §4 (date-added UI) — placeholder replaced.**
The architect's placeholder proposed presets as "likely better" but left the decision
open. The brief confirmed: preset-first with secondary manual entry. The preset set is
specified ("Any time", "Last month", "Last 3 months", "Last 6 months", "This year"),
matching the user's stated example ("last two months") while covering adjacent cases.
The honest caveat copy is pinned verbatim. Blueprint §4 now contains the complete
control spec and the property contract.

**Phase 3 — tasks expanded from 4 to 7.**
The original plan had four tasks (T3.1–T3.4) that deferred all detail to the brief.
The brief revealed that the UX redesign requires a new overlay utility pattern (T3.3)
and a filter bar container + Reset affordance (T3.5) that were not scoped as separate
tasks. T3.0 (date conversion helper with unit tests) is a new prerequisite task that
was implicitly in T3.2 but needed to be explicit to allow parallel work. The task
ordering now reflects true dependencies: T3.0 before T3.2; T3.3 before T3.2 and T3.4.

**Open questions answered.**
Two architect open questions are resolved in the brief and no longer open:
- Same-key suppression at offset 0: confirmed as "never toggle independently" — the
  stepper itself is the only control, offset 0 = today's behaviour.
- `date_to` default when from-only: confirmed as `None` (open-ended), not "now".
Three genuine open questions remain and are listed in `ui-design-brief.md` §Open
questions (Q3: horizontal scroll vs clip; Q4: overlay implementation; Q5: date pill
tooltip).
