# Implementation Plan — Extended Camelot Matching

> Companion to `architect-blueprint.md` in this folder. Read the blueprint first — especially ADR-010 (§2) and Risks R1/R3 (§6).
> Status: Ready for engineer. Execute one phase at a time; do not start a phase until the previous one is reviewed.

## Conventions

- Every task cites `file:line` for where the change lands. Line numbers are from the current `main` branch at planning time — re-check before editing, as earlier edits in the same file shift later lines.
- Follow `docs/coding-standards.md`: type hints on public signatures, `from __future__ import annotations`, `X | None` unions, 100-char lines.
- `suggestion_panel.py` visual changes are specified — implement them in Phase 6 (after Phase 3 lands the backend field). Do not modify `suggestion_panel.py` before Phase 3 is complete.

---

## Phase 1 — Core `camelot.py` scoring rework + config

> **R1 warning:** This phase deletes `is_compatible()`. `suggestion_engine.py:4` still imports it until Phase 2. Land Phase 1 + Phase 2 together, or Phase 2 immediately after with no release in between. The app will not start between these two phases.
>
> **R3 warning (circular import):** `config.py` will import `HarmonicTier` from `camelot.py`. `camelot.py` must therefore **not** import `config.py` at module scope. This plan uses a function-level (lazy) import of `HARMONIC_TIER_SCORES` inside `compatibility_score()`. If you prefer, extract `HarmonicTier` into a new leaf module `source/services/harmonic_tier.py` instead (blueprint §6 R3 option b) — if you do, adjust the imports in tasks 1.1, 1.6, 2.1, 3.1 accordingly and tell the code-reviewer.

### Task 1.1 — Add the `HarmonicTier` enum to `camelot.py`
**File:** `source/services/camelot.py` — insert after the `CAMELOT_RE` definition at `camelot.py:3`, before `parse_camelot()`.

- Add `from __future__ import annotations` as the first line of the file and `from enum import Enum` to the imports (`camelot.py:1` currently only has `import re`).
- Define `class HarmonicTier(Enum)` with seven members. Give each member a value that is its human-readable display string (so the UI can use it directly per blueprint §5):
  - `PERFECT = "Perfect match"`
  - `ADJACENT = "Adjacent"`
  - `RELATIVE = "Relative"`
  - `DIAGONAL = "Diagonal"`
  - `ENERGY = "Energy ±2"`
  - `SEMITONE = "Semitone"`
  - `RELATED = "Related"`
  - `NONE = "No match"`
- Add a one-line docstring referencing ADR-010.

### Task 1.2 — Add the `wheel_distance()` helper to `camelot.py`
**File:** `source/services/camelot.py` — add after `parse_camelot()` (`camelot.py:6-16`), before the (about-to-be-rewritten) compatibility functions.

- Signature: `def wheel_distance(n1: int, n2: int) -> int:`
- Returns the unordered distance between two Camelot numbers on a 12-position wheel: `diff = abs(n1 - n2)`, then `min(diff, 12 - diff)`. Range is 0–6.
- Docstring must note: this is unordered (symmetric); a semitone shift maps to distance 5 (since +7 ≡ −5 mod 12); see the canonical mapping table in the blueprint §1.

### Task 1.3 — Add the `classify()` function to `camelot.py`
**File:** `source/services/camelot.py` — add after `wheel_distance()`.

- Signature: `def classify(key1: str, key2: str) -> HarmonicTier:`
- Parses both keys with `parse_camelot()`. If either is `None`, return `HarmonicTier.NONE`.
- Directional semantics: `key1` is the current track, `key2` is the candidate ("what can I play after key1").
- Logic, in this order:
  1. Same number AND same letter → `PERFECT`.
  2. Same number AND different letter → `RELATIVE`.
  3. **Diagonal (directional, different letter, wheel distance 1):** if letters differ and `wheel_distance(n1, n2) == 1`, check direction. Valid diagonal when:
     - `key1` is `B` and `n2 == (n1 % 12) + 1` (B→A is +1; the `% 12` then `+1` makes 12→1), OR
     - `key1` is `A` and `n2 == ((n1 - 2) % 12) + 1` (A→B is −1; expresses `n1 - 1` with mod-12 wrap so 1→12).
     If the direction is valid → `DIAGONAL`. If letters differ, distance is 1, but direction is the dissonant reverse → `NONE` (do not fall through to anything else).
  4. **Same-letter number-distance tiers** — only when `l1 == l2`. Compute `d = wheel_distance(n1, n2)` and map:
     - `d == 1` → `ADJACENT`
     - `d == 2` → `ENERGY`
     - `d == 4` → `RELATED`
     - `d == 5` → `SEMITONE`
     - `d == 3` or `d == 6` → `NONE` (gaps in the wheel — see blueprint §1, intentional)
  5. Anything else (different letters with distance ≥ 2) → `NONE`.
- Add a comment next to the `d == 4` / `d == 5` lines noting the score is **non-monotonic** in distance (semitone at d=5 outscores related at d=4) — see blueprint §6 R5.
- Verify the mod-12 wrap arithmetic with the worked examples: `classify("12B","1A")` → `DIAGONAL`; `classify("1A","12B")` → `DIAGONAL`; `classify("12A","1A")` → `ADJACENT`; `classify("1A","8A")` → `SEMITONE` (d=5); `classify("8B","7A")` → `NONE` (dissonant reverse).

### Task 1.4 — Rewrite `compatibility_score()` in `camelot.py`
**File:** `source/services/camelot.py:36-59` — replace the existing body.

- Keep the signature `def compatibility_score(key1: str, key2: str) -> float:` and the `0.0–1.0` return contract (blueprint ADR-010 §Decision point 1).
- New body: `tier = classify(key1, key2)`, then look the tier up in `HARMONIC_TIER_SCORES` and return the float; `HarmonicTier.NONE` maps to `0.0`.
- Lazy import to break the cycle (blueprint R3 option a): `from source.config import HARMONIC_TIER_SCORES` **inside** the function body, not at module top. Add a brief comment explaining why the import is local.
- Rewrite the docstring: list all seven tier scores, and **explicitly state the function is asymmetric for the `DIAGONAL` tier** — `compatibility_score(k1, k2)` may differ from `compatibility_score(k2, k1)` because diagonal moves are directional (blueprint R2). State that `key1` is the current track, `key2` the candidate.

### Task 1.5 — Delete `is_compatible()` from `camelot.py`
**File:** `source/services/camelot.py:19-33` — delete the entire `is_compatible` function.

- Confirm with a grep for `is_compatible` across `source/` that the only remaining reference is the import in `suggestion_engine.py:4` (handled in Phase 2). The docstring example in `docs/testing-strategy.md:92` is handled in Phase 5.

### Task 1.6 — Add `HARMONIC_TIER_SCORES` to `config.py` and raise `MAX_SUGGESTIONS`
**File:** `source/config.py` — add near the existing tuning constants at `config.py:85-93`.

- Add import: `from source.services.camelot import HarmonicTier` (top of file, grouped with local imports per `docs/coding-standards.md:45-48`). This import is one-directional and safe **only because** `camelot.py` does not import `config.py` at module scope (task 1.4 used a lazy import) — do not break that.
- Add the mapping after `SUGGESTION_WEIGHTS` (`config.py:85-89`):
  ```python
  # Harmonic compatibility tier scores — see ADR-010.
  # Non-monotonic by design: SEMITONE (wheel distance 5) outranks RELATED (distance 4).
  HARMONIC_TIER_SCORES = {
      HarmonicTier.PERFECT:  1.0,
      HarmonicTier.ADJACENT: 0.8,
      HarmonicTier.RELATIVE: 0.7,
      HarmonicTier.DIAGONAL: 0.62,
      HarmonicTier.ENERGY:   0.57,
      HarmonicTier.SEMITONE: 0.47,
      HarmonicTier.RELATED:  0.37,
      HarmonicTier.NONE:     0.0,
  }
  ```
- Change `MAX_SUGGESTIONS = 30` at `config.py:93` to `MAX_SUGGESTIONS = 60` (blueprint ADR-010 §Decision point 5; open question Q1).

**Phase 1 done when:** `camelot.py` has the enum, `wheel_distance`, `classify`, the rewritten `compatibility_score`, and no `is_compatible`; `config.py` has `HARMONIC_TIER_SCORES` and `MAX_SUGGESTIONS = 60`. The app will not run yet (Phase 2 fixes the import).

---

## Phase 2 — Suggestion-engine filter change

### Task 2.1 — Drop the `is_compatible` import
**File:** `source/services/suggestion_engine.py:4` — change
`from source.services.camelot import compatibility_score, is_compatible`
to
`from source.services.camelot import compatibility_score, classify`
(`classify` is needed in Phase 3; importing it now keeps the import line stable. If you do Phase 2 and Phase 3 as separate commits, add `classify` in Phase 3 instead.)

### Task 2.2 — Replace the hard filter with a score-based gate
**File:** `source/services/suggestion_engine.py:47-54` — replace this block:
```python
        # Hard filter: must be harmonically compatible
        if not current.camelot_key or not track.camelot_key:
            continue
        if not is_compatible(current.camelot_key, track.camelot_key):
            continue

        # Key score
        key_score = compatibility_score(current.camelot_key, track.camelot_key)
```
with:
```python
        # Harmonic filter: offer any track with a usable harmonic relationship.
        # compatibility_score > 0 means some tier matched; 0.0 means unrelated. See ADR-010.
        if not current.camelot_key or not track.camelot_key:
            continue
        key_score = compatibility_score(current.camelot_key, track.camelot_key)
        if key_score <= 0:
            continue
```
- This computes the score once (was effectively twice: once as a boolean gate, once for the value) — blueprint ADR-010 §Decision point 2.
- Argument order stays `(current.camelot_key, track.camelot_key)` — current first, candidate second — which is required for the diagonal directionality to be correct (blueprint ADR-010 §Decision point 4).

**Phase 2 done when:** the app runs again, `is_compatible` is gone from the codebase, and selecting a track produces a visibly larger suggestion list including diagonal/energy/semitone/related matches.

---

## Phase 3 — `ScoredTrack` data plumbing for the UI

> Pure backend hook. The `suggestion_panel.py` visual changes that consume this field are in Phase 6 (after ui-designer review). Do not implement Phase 6 tasks before Phase 3 is reviewed and merged.

### Task 3.1 — Add `harmonic_tier` to the `ScoredTrack` dataclass
**File:** `source/services/suggestion_engine.py:13-19` — add a field to the `ScoredTrack` dataclass:
```python
@dataclass
class ScoredTrack:
    track: Track
    total_score: float
    key_score: float
    energy_score: float
    bpm_score: float
    harmonic_tier: HarmonicTier
```
- Add `HarmonicTier` to the camelot import at `suggestion_engine.py:4` if not already present from Task 2.1: `from source.services.camelot import compatibility_score, classify, HarmonicTier`.
- Add `from __future__ import annotations` at the top of the file if not already present (`docs/coding-standards.md:27`).

### Task 3.2 — Populate `harmonic_tier` when constructing each `ScoredTrack`
**File:** `source/services/suggestion_engine.py:78-84` — the `results.append(ScoredTrack(...))` call.

- Before the append, compute the tier: `tier = classify(current.camelot_key, track.camelot_key)`. Place this next to the `key_score = compatibility_score(...)` line from Task 2.2 (same key arguments, same order).
- Optional micro-optimisation the engineer may take or leave: `compatibility_score` already calls `classify` internally; calling `classify` again here is a second cheap call. If preferred, refactor so the engine calls `classify` once and derives the score via the `HARMONIC_TIER_SCORES` lookup directly. Keep it simple unless the reviewer asks — two calls of a trivial pure function is fine.
- Add `harmonic_tier=tier` to the `ScoredTrack(...)` constructor call.

**Phase 3 done when:** every `ScoredTrack` carries a populated `harmonic_tier`; no UI change; existing behaviour otherwise identical to end-of-Phase-2.

---

## Phase 4 — Tests

> Satisfies `docs/testing-strategy.md` Phase 1 (services priority, 90%+ target). This is the first `tests/` directory in the project — see blueprint §3.

### Task 4.1 — Create the `tests/` skeleton
**Files (new):** `tests/__init__.py` (may be empty or omitted if using pytest rootdir config), `tests/services/__init__.py`, `tests/conftest.py`.

- `tests/conftest.py`: add pytest fixtures for a sample `Track` and a small `TrackLibrary`, per `docs/testing-strategy.md:14-16` and the structure at `docs/testing-strategy.md:73-86`. A fixture factory `make_track(camelot_key=..., bpm=..., energy=...)` keeps the engine tests concise. Use the `Track` dataclass directly (`source/models/track.py:5-23`) — construct with keyword args, not `from_csv_row`.

### Task 4.2 — Write `tests/services/test_camelot.py`
**File (new):** `tests/services/test_camelot.py`. Cover, with names per `docs/coding-standards.md:85` (`test_<function>_<scenario>_<expected>`):

- `parse_camelot`: valid `"8A"`/`"12B"`; invalid `""`, `"13A"`, `"0A"`, `"8C"`, `"8"`, `None`; whitespace `" 8A "`.
- `wheel_distance`: `(8, 8)→0`, `(8, 9)→1`, `(12, 1)→1` (wrap), `(8, 10)→2`, `(8, 12)→4`, `(1, 8)→5`, `(8, 2)→6`; symmetry `wheel_distance(a,b) == wheel_distance(b,a)`.
- `classify` — one test per tier:
  - `PERFECT`: `"8A","8A"`.
  - `ADJACENT`: `"8A","9A"`, `"8A","7A"`, and wrap `"12A","1A"`, `"1A","12A"`.
  - `RELATIVE`: `"8A","8B"`, `"8B","8A"`.
  - `DIAGONAL` valid: `"8B","9A"`, `"8A","7B"`, and wraps `"12B","1A"`, `"1A","12B"`.
  - `DIAGONAL` dissonant reverse → `NONE`: `"8B","7A"`, `"8A","9B"`, `"9A","8B"`, `"7B","8A"`.
  - `ENERGY` (distance 2): `"8A","10A"`, `"8A","6A"`.
  - `SEMITONE` (distance 5): `"1A","8A"`, `"8A","3A"`.
  - `RELATED` (distance 4): `"10B","2B"`, `"8A","12A"`.
  - `NONE` for wheel gaps: distance 3 `"8A","11A"`; distance 6 (tritone) `"8A","2A"`; different-letter distance ≥2 `"8A","10B"`.
  - `NONE` for invalid input: `"","8A"`, `"8A","13A"`.
- `compatibility_score` — assert exact values match `HARMONIC_TIER_SCORES`: `1.0`, `0.8`, `0.7`, `0.62`, `0.57`, `0.47`, `0.37`, `0.0`.
- **Diagonal asymmetry (blueprint R2) — explicit dedicated test:** assert `compatibility_score("8B","9A") > 0` AND `compatibility_score("9A","8B") == 0.0`. Name it so the intent is obvious, e.g. `test_compatibility_score_diagonal_is_directional`.
- **Symmetry of the non-diagonal tiers:** assert `compatibility_score(a,b) == compatibility_score(b,a)` for an ADJACENT, ENERGY, SEMITONE, RELATED, RELATIVE and PERFECT pair (these must stay symmetric — only DIAGONAL breaks it).

### Task 4.3 — Write `tests/services/test_suggestion_engine.py`
**File (new):** `tests/services/test_suggestion_engine.py`. Cover:

- `get_suggestions` includes a track whose key scores `> 0` (e.g. a SEMITONE match that the *old* hard filter would have dropped) — this is the core regression-prevention test for the feature.
- `get_suggestions` excludes a track whose key scores `0.0` (truly unrelated, e.g. distance-3 or tritone).
- `get_suggestions` still excludes self (`suggestion_engine.py:34`), `exclude_paths` members (`:36`), and tracks failing the crate/genre filters (`:40-45`).
- Tracks with empty/unparseable `camelot_key` are excluded (`suggestion_engine.py:48`).
- Result list is capped at `MAX_SUGGESTIONS` and sorted descending by `total_score` (`suggestion_engine.py:86-87`).
- Each returned `ScoredTrack` has a `harmonic_tier` that is a `HarmonicTier` member and is consistent with its `key_score` (e.g. a `key_score` of `0.47` ⇒ `harmonic_tier is HarmonicTier.SEMITONE`).
- Empty library returns `[]`.

### Task 4.4 — Verify the suite runs
Run `python -m pytest tests/services/ -v` (per `docs/testing-strategy.md:97-99`). Optionally `python -m pytest --cov=source/services/camelot.py --cov=source/services/suggestion_engine.py --cov-report=term-missing` and confirm `camelot.py` is at or near 100% (it is small and pure) and `suggestion_engine.py` meets the 90% services target (`docs/testing-strategy.md:110-114`).

**Phase 4 done when:** the suite passes and `camelot.py` / `suggestion_engine.py` meet the coverage target.

---

## Phase 5 — Documentation

> May be folded into the Phase 4 commit. Listed separately so it is not skipped.

### Task 5.1 — Append ADR-010 to `docs/architecture-decisions.md`
**File:** `docs/architecture-decisions.md` — append after ADR-009 (file currently ends at `architecture-decisions.md:216`).

- Copy ADR-010 verbatim from `architect-blueprint.md` §2. Set **Status: Accepted** once the user signs off (leave **Proposed** until then).
- Also update ADR-003 (`architecture-decisions.md:42-52`): add a line under its Status noting the hard-filter clause is superseded by ADR-010.

### Task 5.2 — Update `docs/architecture-overview.md`
**File:** `docs/architecture-overview.md`.

- Update the `camelot.py` row in the services table (`architecture-overview.md:55`) to mention the 7-tier harmonic model.
- In the "Architectural Debt" list, update item 9 "No tests" (`architecture-overview.md:110`) to note `camelot.py` and `suggestion_engine.py` now have unit-test coverage and a `tests/` directory exists.

### Task 5.3 — Update `docs/testing-strategy.md`
**File:** `docs/testing-strategy.md`.

- Fix the stale docstring example at `testing-strategy.md:92` — `is_compatible` no longer exists; replace with a `classify`- or `compatibility_score`-based example name.
- Update the "Current State" line (`testing-strategy.md:7`) and Phase 1 items 1 and 3 (`testing-strategy.md:33-49`) to note `camelot.py` and `suggestion_engine.py` tests are delivered.

**Phase 5 done when:** all four docs reflect ADR-010 and the new test coverage.

---

---

## Phase 6 — Suggestion panel visual updates

> Depends on Phase 3. Do not start until `ScoredTrack.harmonic_tier` is landed and
> reviewed. These are the only changes to `source/ui/suggestion_panel.py` in this
> feature. Full rationale in `ui-design-brief.md` Decisions 1 and 2.

### Task 6.1 — Expand `_score_color()` from three buckets to five
**File:** `source/ui/suggestion_panel.py:21-27`

Replace the existing three-branch function body with five branches, in descending
threshold order:

| Return value | Threshold | Hex |
|---|---|---|
| `"#28a745"` | `score >= 0.75` | Green — strong match (Perfect / Adjacent) |
| `"#20c997"` | `score >= 0.60` | Teal — good match (Relative / Diagonal) |
| `"#ffc107"` | `score >= 0.48` | Yellow — usable (Energy ±2) |
| `"#fd7e14"` | `score >= 0.38` | Orange — loose (Semitone) |
| `"#dc6060"` | else | Muted red — stretch (Related) |

The function signature (`score: float) -> str:`) and docstring concept are unchanged;
update the docstring to list all five bands and note they key off `total_score` (the
blended value), not the raw key score.

These thresholds are intentionally keyed off the blended `total_score`, not the tier
score directly. A Related-key track with strong energy and BPM scores can blend into
the Usable band — which is correct DJ semantics. Do not replace the threshold logic
with a tier-to-colour lookup; the blended score is the right input.

**Colour-blind note:** the green-to-teal transition (bands 1–2) can be hard to
distinguish under deuteranopia. The tier name in the tooltip (Task 6.2) provides the
non-colour fallback. No further action needed in this task.

**Minimum-window note:** `_score_color()` is a pure function; no layout impact.

### Task 6.2 — Add tier name as first line of the per-row tooltip
**File:** `source/ui/suggestion_panel.py:365-372`

The current tooltip construction is:
```python
tip_lines = [
    f"Key: {int(scored.key_score * 100)}%   "
    f"Energy: {int(scored.energy_score * 100)}%   "
    f"BPM: {int(scored.bpm_score * 100)}%",
]
if track.crates:
    tip_lines.append(f"\nCrates: {', '.join(track.crates)}")
Tooltip(row, "\n".join(tip_lines))
```

Revise to prepend the tier name as the first element:
- Read `scored.harmonic_tier.value` — this is the human-readable display string
  (e.g. `"Energy ±2"`, `"Related"`, `"Perfect match"`) defined in Task 1.1.
- The revised `tip_lines` must start with `scored.harmonic_tier.value`, followed by
  the existing Key/Energy/BPM line, followed by the Crates line if present.
- Separate the tier name from the score line with `\n` (single newline). Check
  `source/ui/tooltip.py` for the `wraplength` setting — if a blank line (`\n\n`)
  renders poorly, single `\n` is sufficient.

No import of `HarmonicTier` is required in `suggestion_panel.py` — the field is
already a `HarmonicTier` instance on `ScoredTrack`, and `.value` is a standard enum
attribute. If a type annotation is needed for `TYPE_CHECKING`, add `HarmonicTier` to
the existing `if TYPE_CHECKING` block at `suggestion_panel.py:15`.

**Phase 6 done when:** the `%` badge in the suggestion grid uses five colour bands, and
hovering any row shows the tier name as the first tooltip line.

---

## Cross-cutting checklist for the code-reviewer

- [ ] No module-scope import of `config` inside `camelot.py` (cycle — blueprint R3).
- [ ] `compatibility_score` still returns a `0.0–1.0` float; legacy tiers still score exactly 1.0 / 0.8 / 0.7.
- [ ] `compatibility_score` docstring states the DIAGONAL asymmetry; a test asserts it (R2).
- [ ] `is_compatible` fully removed — no references anywhere in `source/`.
- [ ] Argument order `(current, candidate)` preserved at `suggestion_engine.py` call sites — diagonal direction depends on it.
- [ ] `MAX_SUGGESTIONS` is 60 (open question Q1 — confirm the user is happy before release).
- [ ] All new tier scores live in `config.py`, not inline in `camelot.py` (`docs/coding-standards.md:58-62`).
- [ ] Phase 6: `_score_color()` has exactly five branches; thresholds are 0.75 / 0.60 / 0.48 / 0.38 / else (ui-design-brief Decision 1).
- [ ] Phase 6: tooltip first line is `scored.harmonic_tier.value`; existing Key/Energy/BPM and Crates lines are unchanged (ui-design-brief Decision 2).
- [ ] Phase 6: no new column added to `_COL` dict (`suggestion_panel.py:147-151`) — tier name is tooltip-only.
- [ ] Phase 6 not merged before Phase 3 — `ScoredTrack.harmonic_tier` must exist before the panel reads it.

---

## UI revisions applied

**Date:** 2026-05-22 | **Author:** UI Designer agent

The following changes were made to the architect's documents:

### 1. `architect-blueprint.md` §5 — replaced placeholder with finalised visual spec

The `<!-- UI-designer to revise -->` block in §5 was replaced with concrete direction:
five-bucket score colours (replacing the three-bucket system), tooltip-first-line tier
name (rather than an inline column or badge), and explicit "no change" rulings for the
header count, empty-state copy, and row ordering. All five open UI questions from the
architect's draft were resolved and documented.

**Why:** The architect correctly identified the four visual questions but deferred all
decisions. The replacement text records the decisions so the engineer has unambiguous
direction and the code-reviewer has acceptance criteria.

### 2. `implementation-plan.md` — added Phase 6 (suggestion panel visual updates)

Phase 6 adds two tasks:
- **Task 6.1** (`suggestion_panel.py:21-27`) — `_score_color()` five-bucket expansion
  with exact hex values and threshold values.
- **Task 6.2** (`suggestion_panel.py:365-372`) — tooltip tier-name prepend, including
  the note that no `HarmonicTier` import is required in `suggestion_panel.py`.

**Why:** The original plan's note "No `suggestion_panel.py` visual change in this plan"
was correct as an interim placeholder, but without a Phase 6 the backend feature would
ship with no visual signal of the new tier system — R4 from the architect's blueprint
("makes most rows orange") would be a live UX regression. Phase 6 closes R4.

### 3. `implementation-plan.md` — updated conventions note and Phase 3 header

The conventions note that said "Do not touch `suggestion_panel.py` visuals" was updated
to "implement them in Phase 6 (after Phase 3 lands the backend field)" so the engineer
has a clear ordering constraint. The Phase 3 header note was updated to reference
Phase 6 explicitly.

### 4. `implementation-plan.md` — updated code-reviewer checklist

Added four Phase 6 checklist items covering the five-bucket threshold values, the
tooltip structure, the absence of a new `_COL` entry, and the Phase 3 → Phase 6
ordering dependency.

---

## Post-implementation corrections

**Date:** 2026-05-22 | **Author:** Architect agent

The diagonal-tier resolution after code review:

- **Task 1.3's algorithm was correct.** The `classify()` diagonal logic specified in
  Task 1.3 (valid diagonal = the `{(B,+1),(A,−1)}` letter-swap family, with mod-12
  wrap) correctly classifies all four research examples — `8B→9A` and `8A→7B` as
  `DIAGONAL`, `8B→7A` and `8A→9B` as `NONE`. It was implemented as written and is
  correct as shipped. No change.
- **Task 4.2's diagonal-asymmetry assertions were wrong.** Task 4.2 called for a test
  asserting `compatibility_score("8B","9A") > 0` AND `compatibility_score("9A","8B")
  == 0.0`. That assertion is unsatisfiable: the `{(B,+1),(A,−1)}` family is closed
  under reversal, so the diagonal relation — and the whole `compatibility_score`
  function — is **symmetric**. `compatibility_score("9A","8B")` equals
  `compatibility_score("8B","9A")`; both score the `DIAGONAL` tier. The engineer
  correctly made the tests assert the actual symmetric behaviour (including the
  cross-tier symmetry test), which the code-reviewer approved.
- **The symmetric diagonal is the accepted design.** Risk R2's asymmetric-diagonal
  requirement was withdrawn as mathematically unsatisfiable and harmonically wrong
  (compatibility is a property of an unordered key pair; energy direction is the
  separate `energy_score` axis). The authoritative statement is the revised **ADR-010**
  in `docs/architecture-decisions.md` (and the synced copy in
  `architect-blueprint.md` §2 Decision point 4 / §6 R2). This implementation plan is
  historical; Tasks 1.3 and 4.2 are not re-edited — read them alongside this note.
