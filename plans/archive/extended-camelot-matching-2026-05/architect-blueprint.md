# Architect Blueprint — Extended Camelot Matching

> Status: Implemented
> Date: 2026-05-22
> Author: Architect agent
> Plan folder: `plans/extended-camelot-matching-2026-05/`

> **Revised post-implementation — 2026-05-22.** The feature has shipped and been
> code-reviewed. During implementation the original draft was found to be internally
> contradictory: §2 Decision point 4 specified a *symmetric* diagonal algorithm while
> §6 Risk R2 demanded an *asymmetric* diagonal. The asymmetric requirement was proven
> mathematically unsatisfiable (no rule consistent with the four named research
> examples can be asymmetric — see §2 Decision point 4 and §6 R2 below). The
> **symmetric diagonal** has been formally adopted as the design; it is the only
> internally-consistent and harmonically-correct option. §2 Decision point 4 and §6 R2
> have been corrected accordingly. The authoritative current statement is ADR-010 in
> `docs/architecture-decisions.md`; this blueprint is now historical and kept in sync.

---

## 1. Context

### The user request (verbatim)

> "Currently when recommending music we are only offered something that is within one or two Camelot keys ahead and there's a percentage to indicate a match, I would like to extend so that more Camelot keys are offered, there are Camelot keys that further away from a direct match please do some online research to determine the best Camelot keys that we can recommend then the percentages of these should go down. We really want a lot more tracks offered so that we can extend what we could potentially pick and help build our sets."

### Why the app currently only offers "one or two keys"

The suggestion engine applies a **hard harmonic filter** before scoring. Any track whose Camelot key is not one of three relationships to the current track is dropped from the candidate pool entirely:

- `source/services/suggestion_engine.py:50-51` — `if not is_compatible(...): continue`
- `source/services/camelot.py:19-33` — `is_compatible()` returns `True` only for: identical key, adjacent number same letter (±1), or same number A/B flip.

Everything else (energy boosts, semitone jumps, related keys) scores `0.0` in `compatibility_score()` (`source/services/camelot.py:36-59`) and is filtered out before the user ever sees it. So the headline problem is **not** the scoring percentages — it is the hard gate.

### Current scoring shape (to preserve)

- `compatibility_score(key1, key2)` returns a `0.0–1.0` float (`source/services/camelot.py:36-59`). It is **symmetric** in its arguments today.
- `suggestion_engine.get_suggestions()` blends `key_score`, `energy_score`, `bpm_score` with weights from `SUGGESTION_WEIGHTS` (`source/config.py:85-89`, key 0.45 / energy 0.35 / bpm 0.20).
- The displayed "percentage" is `total_score` (the weighted blend), rendered per row at `source/ui/suggestion_panel.py:283` and bucketed for colour by `_score_color()` at `source/ui/suggestion_panel.py:21-27`.
- The per-axis breakdown (Key/Energy/BPM) appears in the row tooltip at `source/ui/suggestion_panel.py:365-372`.
- `MAX_SUGGESTIONS = 30` (`source/config.py:93`) caps the final sorted list.

### Constraints from existing docs

- **ADR-003** (`docs/architecture-decisions.md:42-52`) explicitly records the current design as "weighted linear combination... **Hard filter on harmonic compatibility**". This feature changes that decision — ADR-010 below supersedes the hard-filter clause of ADR-003.
- **Coding standards** (`docs/coding-standards.md:58-62`): all tuneable values belong in `config.py`, not inline. New tier scores must live there.
- **Coding standards** (`docs/coding-standards.md:24-29`): type hints required on public signatures; prefer `X | None`; use `from __future__ import annotations`.
- **Testing strategy** (`docs/testing-strategy.md:31-49`): `camelot.py` and `suggestion_engine.py` are Phase 1 priority — pure functions, 90%+ target for `services/`. This feature must ship with tests.
- **Architectural debt** (`docs/architecture-overview.md:101-112`): item 9 "No tests" — this feature is a good opportunity to land the first `tests/` directory. Item 5 notes `CAMELOT_RE` is now centralised in `camelot.py` — keep it that way; do not scatter new regex.
- **Cross-platform**: this change is pure Python arithmetic and config — no path, encoding, or OS concerns. No `cross-platform-guide.md` impact.

### Harmonic-mixing research (authoritative — supplied, web access unavailable to this agent)

Sources: Mixed In Key "Advanced Harmonic Mixing Techniques", DJ.Studio "Camelot Wheel" guide, plus corroborating DJ guides. All number moves wrap mod 12 (12 ↔ 1). Tiers, strongest to weakest:

| Tier | Name | Relationship | Example | Notes |
|------|------|--------------|---------|-------|
| 1 | Perfect match | Same key | 8A→8A | Already 1.0 |
| 2 | Adjacent | ±1 number, same letter | 8A→7A / 9A | Perfect fifth/fourth, one note different |
| 3 | Relative | A↔B swap, same number | 8A→8B | Relative major/minor, mood shift |
| 4 | Diagonal | ±1 number AND A/B swap, in the `{(B,+1),(A,−1)}` family | 8B→9A (B,+1); 8A→7B (A,−1) | Strong; a different pair such as `{8B,7A}` is dissonant and is **not** a diagonal (this is a different key, not a "reverse direction" — see §2 Decision point 4) |
| 5 | Energy ±2 | ±2 numbers, same letter | 8A→10A / 6A | Two-semitone shift; noticeable, use sparingly |
| 6 | Semitone ±7 | ±7 numbers, same letter | 2A→9A | One-semitone shift; riskier than ±2 |
| 7 | Related ±4 | ±4 numbers, same letter | 10B→2B | "+4 semitones" — loosest usable tier |

Key facts that shape the scoring model:

- The pure number-distance moves (adjacent, ±2, ±7, ±4) are naturally **symmetric** — the engine already has a separate `energy_score` axis (`suggestion_engine.py:57-63`) that captures whether a move raises or lowers energy. So harmonic boost-vs-drop direction does **not** need to live in the Camelot score.
- The **diagonal** move (tier 4) is **also symmetric**. The valid diagonal pairs form the `{(B,+1),(A,−1)}` family, which is closed under reversal (reversing a `(B,+1)` move gives an `(A,−1)` move), so harmonic compatibility for diagonals is order-independent like every other tier. The whole `compatibility_score` function is symmetric — see §2 Decision point 4. (The original draft of this blueprint wrongly treated the diagonal as directional; corrected post-implementation.)
- Mod-12 distance must use a clean wheel-distance helper. On a 12-position wheel the unordered distance between two numbers is `min(d, 12 - d)`, which ranges 0–6. A semitone shift is reachable as +7 one way or −5 the other — both map to the **same** unordered wheel distance of 5. So tier 6 ("±7") is, in unordered terms, **wheel distance 5**. The tier mapping must key off unordered wheel distance to avoid double-counting +7 and −5 as different things.

#### Unordered wheel-distance → tier mapping (the canonical table)

For two keys with the **same letter**, let `d = wheel_distance(n1, n2)` where `wheel_distance` returns `min(|n1−n2|, 12−|n1−n2|)` (range 0–6):

| `d` | Tier | Score |
|-----|------|-------|
| 0 | Perfect match | 1.0 |
| 1 | Adjacent | 0.8 (unchanged) |
| 2 | Energy ±2 | tier 5 score |
| 3 | — (no usable harmonic relationship) | 0.0 |
| 4 | Related ±4 | tier 7 score |
| 5 | Semitone ±7 | tier 6 score |
| 6 | — (tritone, dissonant) | 0.0 |

Note `d = 3` and `d = 6` deliberately score `0.0` — they are not in the research tiers. This is correct: a 12-key wheel has gaps. Tier 6 ("semitone, ±7") sits at `d = 5`, **further** around the wheel than tier 7 ("related, ±4") at `d = 4`, yet tier 6 scores *higher* than tier 7. The score is therefore **not** a monotonic function of wheel distance — it is a lookup keyed by harmonic relationship. This is intentional and is the central reason for a named tier table rather than a distance formula.

---

## 2. Decision

### ADR-010: Tiered Harmonic Compatibility Scoring (supersedes the hard-filter clause of ADR-003)

- **Status:** Accepted
- **Date:** 2026-05-22
- **Revised:** 2026-05-22 (post-implementation) — Decision point 4 corrected to a symmetric diagonal tier.
- **Supersedes:** ADR-003's clause "Hard filter on harmonic compatibility (non-compatible tracks are excluded entirely)". The weighted-linear-combination decision in ADR-003 otherwise stands.

> The authoritative copy of ADR-010 is in `docs/architecture-decisions.md`. This in-plan
> copy is kept consistent with it; the doc version is the one to cite.

#### Context

ADR-003 chose a hard harmonic filter: any non-compatible track is excluded before scoring. In practice this surfaces only 3 of the 24 keys' relationships and produces a thin suggestion list. DJs want a wider pool of harmonically *usable* tracks ranked by how safe the harmonic move is, so they can build longer, more varied sets.

#### Decision

**1. Replace the 3-value `compatibility_score` with a 7-tier model.** `compatibility_score(key1, key2)` continues to return a `0.0–1.0` float so the existing `total_score` blend and the `%` display work unchanged. The new return values:

| Relationship | Score | Source |
|--------------|-------|--------|
| Perfect match (identical) | `1.0` | unchanged |
| Adjacent (±1 number, same letter) | `0.8` | unchanged |
| Relative (A/B swap, same number) | `0.7` | unchanged |
| Diagonal (`{(B,+1),(A,−1)}` family, symmetric) | `0.62` | new — research range 0.6–0.65, midpoint chosen |
| Energy ±2 (wheel distance 2, same letter) | `0.57` | new — research range 0.55–0.6, midpoint |
| Semitone (wheel distance 5, same letter) | `0.47` | new — research range 0.45–0.5, midpoint |
| Related (wheel distance 4, same letter) | `0.37` | new — research range 0.35–0.4, midpoint |
| No harmonic relationship | `0.0` | unchanged |

Midpoints of the researched ranges are chosen as the default values; they are tunable (see decision 3). The three legacy values (1.0 / 0.8 / 0.7) are preserved exactly so existing behaviour for those tiers does not regress.

**2. Remove the hard filter; filter on `compatibility_score(...) > 0` instead.** The engine offers a track if it has **any** harmonic relationship (score > 0). Truly unrelated keys still score `0.0` and stay filtered. `is_compatible()` is **deleted**, not redefined.

Rationale for deleting rather than redefining: `is_compatible()` is used in exactly one place — `suggestion_engine.py:50` (confirmed by grep; the only other hits are the import at `suggestion_engine.py:4` and a docstring example in `docs/testing-strategy.md:92`). A predicate named `is_compatible` that returns `True` for a tritone-related "related ±4" pair would be a misleading name. The engine already computes `compatibility_score()` one line later (`suggestion_engine.py:54`) — calling it twice (once as a boolean gate, once for the score) is wasteful. The clean change is: compute the score once, gate on `> 0`. One dead import and one stale docstring line are the only collateral, both trivially fixed.

**3. New tier scores live in `config.py` as a named, ordered structure.** Consistent with `SUGGESTION_WEIGHTS` and the thresholds already there (`config.py:85-93`) and with the coding standard "all tuneable values belong in `config.py`" (`docs/coding-standards.md:58-62`). The structure is a mapping from a `HarmonicTier` enum to a float. `camelot.py` imports it. The three legacy scores move into this structure too, so there is a single source of truth for all seven values.

Rationale for an enum over bare string keys: the tier is also a candidate UI label (see §5). An enum gives `camelot.py`, the engine, the tests, and the UI one shared vocabulary and prevents typo-keyed dict lookups. The enum lives in `camelot.py` (the module that owns harmonic logic); the score *values* live in `config.py` (the tuning surface). `config.py` imports the enum from `camelot.py` — `camelot.py` must not import from `config.py` to keep the dependency direction one-way (config is leaf-level tuning data; camelot is leaf-level domain logic — neither should depend on the other, so the enum-in-camelot / scores-in-config split needs care). See §6 Risk R3 for the resolution.

**4. The DIAGONAL tier is a symmetric relationship identified by a small explicit special-case inside `classify()`.** Harmonic *compatibility* — whether two tracks share enough notes to layer well — is a property of the unordered key *pair*, so it is order-independent. Energy direction (boost vs drop) is a separate concern, already captured by the engine's `energy_score` axis (`suggestion_engine.py:57-63`), and does not belong in the Camelot score. The diagonal tier is therefore symmetric, like every other tier.

A valid diagonal is any `±1-number-with-letter-swap` pair in the `{(B,+1),(A,−1)}` family — the move from the source key is either "B-letter, number step +1" or "A-letter, number step −1" (steps wrap mod 12). Applied to the four research examples:

- `8B→9A` — `(B,+1)` — DIAGONAL.
- `8A→7B` — `(A,−1)` — DIAGONAL.
- `8B→7A` — `(B,−1)` — not in the family — `NONE` (dissonant: this is the pair `{8B,7A}`, a genuinely different *key pair*, not a "reverse direction").
- `8A→9B` — `(A,+1)` — not in the family — `NONE` (dissonant).

The `{(B,+1),(A,−1)}` family is **closed under reversal** — reversing a `(B,+1)` move yields an `(A,−1)` move and vice versa (e.g. the reverse of `8B→9A` is `9A→8B`, which is `(A,−1)`, itself valid). The reverse of a dissonant pair is likewise dissonant. So the diagonal relation — and hence the **whole** `compatibility_score` function — is **symmetric**: `compatibility_score(k1, k2) == compatibility_score(k2, k1)` for every key pair.

`get_suggestions()` calls `compatibility_score(current.camelot_key, track.camelot_key)` (current first, candidate second). Because the function is symmetric, argument order does not affect the harmonic score; it is retained only for call-site readability.

History — why the original draft was wrong: the draft treated `9A→8B` as "the dissonant reverse" of `8B→9A` and demanded it score `0.0`. But `9A→8B` is an `(A,−1)` move, structurally identical to the named-valid example `8A→7B`; no rule consistent with the four research examples can mark it invalid. The draft conflated "the reverse direction" with "a different key": the research's "8B→7A is dissonant" statement is about the *pair* `{8B,7A}`, which is distinct from `{8B,9A}`. The symmetric diagonal correctly classifies all four research examples and is the only internally-consistent option.

**5. `MAX_SUGGESTIONS` raised to 60 (interim) and flagged as an open question.** Widening the filter from 3 relationships to ~7 will roughly double-to-triple the candidate pool. The current cap of 30 (`config.py:93`) would silently hide most of the newly-eligible tracks — defeating the feature. 60 is chosen as a reasonable interim default for a 200–500 track hobby library. The "right" number depends on library size and UI scroll comfort and is genuinely a user/UX call — see §6 Open Question Q1. The engineer should change the constant and nothing else; making it user-configurable is explicitly out of scope for this plan.

#### Consequences

- Pro: Suggestion pool widens substantially; DJs see harmonically-usable tracks they previously never saw.
- Pro: Scoring stays a transparent, tunable lookup; the `%` display and tooltip keep working with no UI-contract change.
- Pro: `compatibility_score` is fully symmetric for every tier — there is no per-tier asymmetry to remember or defend, which matches the harmonic reality and keeps the function simple to reason about.
- Pro: First real `tests/` directory lands, satisfying `docs/testing-strategy.md` Phase 1 priority for `camelot.py` and `suggestion_engine.py`.
- Pro: `compatibility_score` is computed once per candidate instead of effectively twice (gate + score).
- Con: Many more low-scoring rows (37%–62% blends) will appear. `_score_color()` thresholds (`suggestion_panel.py:21-27`) were tuned for a world where the lowest key score was 0.7 — they will now paint a lot of rows orange. This is a UI concern handed to the ui-designer (§5).
- Con: The score is non-monotonic in wheel distance (semitone at distance 5 outranks related at distance 4). Anyone reading the tier table must understand it is a harmonic lookup, not a distance curve.

---

## 3. Affected files

| File | Change | Reference |
|------|--------|-----------|
| `source/services/camelot.py` | Add `HarmonicTier` enum, `wheel_distance()` helper, `classify()` (key pair → tier). Rewrite `compatibility_score()` to use the tier table. Delete `is_compatible()`. | `camelot.py:19-33` (delete), `camelot.py:36-59` (rewrite) |
| `source/config.py` | Add `HARMONIC_TIER_SCORES` mapping (`HarmonicTier` → float). Raise `MAX_SUGGESTIONS` to 60. | `config.py:85-93` |
| `source/services/suggestion_engine.py` | Drop `is_compatible` import. Replace hard-filter block with `key_score = compatibility_score(...)` + `if key_score <= 0: continue`. Add `harmonic_tier` field to `ScoredTrack`. | `suggestion_engine.py:4`, `:48-54`, `:13-19`, `:78-84` |
| `source/ui/suggestion_panel.py` | Backend hook only: `ScoredTrack` now carries a tier label the UI may render. Visual changes (colour thresholds, tier label, tooltip) deferred to ui-designer. | `suggestion_panel.py:21-27`, `:283`, `:365-372` — marked for ui-designer |
| `tests/services/test_camelot.py` | New file — full tier coverage, mod-12 wrapping, diagonal classification (valid `{(B,+1),(A,−1)}` pairs and dissonant non-family pairs), `compatibility_score` symmetry, invalid input. | new |
| `tests/services/test_suggestion_engine.py` | New file — filter behaviour (score > 0 included, 0 excluded), `harmonic_tier` plumbing. | new |
| `tests/conftest.py` | New file — shared `Track` / `TrackLibrary` fixtures. | new |
| `docs/architecture-decisions.md` | Append ADR-010 (after ADR-009 at `architecture-decisions.md:216`). | doc update |
| `docs/architecture-overview.md` | Update `camelot.py` row in the services table (`architecture-overview.md:55`); note tests now exist (debt item 9, `:110`). | doc update |
| `docs/testing-strategy.md` | Fix stale `is_compatible` docstring example (`testing-strategy.md:92`); note `camelot.py` / `suggestion_engine.py` Phase 1 tests delivered. | doc update |

No model, cache, crate-parser, cross-platform, or packaging files are touched.

---

## 4. Phases

The work is sequenced so each phase is independently reviewable and the app stays runnable between phases (except that Phase 1 alone leaves a dangling `is_compatible` import — Phase 1 and Phase 2 should land together or Phase 2 immediately after).

### Phase 1 — Core `camelot.py` rework + config
Add the `HarmonicTier` enum, `wheel_distance()` helper, and `classify()` function. Rewrite `compatibility_score()` to use the tier table. Delete `is_compatible()`. Add `HARMONIC_TIER_SCORES` to `config.py` and raise `MAX_SUGGESTIONS`. After this phase `camelot.py` is self-consistent but `suggestion_engine.py` still imports the now-deleted `is_compatible` — Phase 2 must follow before the app runs.

### Phase 2 — Suggestion-engine filter change
Drop the `is_compatible` import. Compute `key_score` once and gate on `key_score <= 0`. App is runnable again with the widened pool.

### Phase 3 — `ScoredTrack` data plumbing for the UI
Add a `harmonic_tier: HarmonicTier` field to `ScoredTrack` and populate it from `classify()`. This is a pure backend hook — it gives the ui-designer something to render without forcing a UI decision now. No `suggestion_panel.py` visual change in this phase.

### Phase 4 — Tests
Create `tests/`, `conftest.py`, `test_camelot.py`, `test_suggestion_engine.py`. Cover every tier, mod-12 wrapping, diagonal classification (valid `{(B,+1),(A,−1)}` pairs and dissonant non-family pairs), `compatibility_score` symmetry across all tiers, invalid input, and the engine filter boundary.

### Phase 5 — Documentation
Append ADR-010, update the overview and testing-strategy docs. (The engineer may fold this into Phase 4's commit; it is listed separately so it is not forgotten.)

UI visual work (colour thresholds, whether to show the tier name, tooltip wording, header count, ordering) is **not** a phase here — it is handed to the ui-designer after this blueprint, per §5.

---

## 5. UI surface

> Revised by ui-designer — 2026-05-22. Full rationale in `ui-design-brief.md`.

### Backend hooks the implementation provides

- `ScoredTrack` gains a `harmonic_tier: HarmonicTier` field (Phase 3). The UI reads
  `scored.harmonic_tier.value` (the enum's human-readable display string) in the tooltip.
- `HarmonicTier` enum members carry their display string as the `.value`:
  `"Perfect match"`, `"Adjacent"`, `"Relative"`, `"Diagonal"`, `"Energy ±2"`,
  `"Semitone"`, `"Related"`, `"No match"`.
- The per-row `%` value (`suggestion_panel.py:283`) is unchanged in meaning —
  `total_score × 100`, weighted blend. The colour of that badge changes (see below).
- The Key/Energy/BPM tooltip breakdown (`suggestion_panel.py:365-372`) gains one
  prepended line: the tier name.

### Visual changes (decided — implement these)

#### 1. `_score_color()` — five buckets replacing three (`suggestion_panel.py:21-27`)

The existing three thresholds were tuned when the minimum key score was 0.7. With
tier scores now reaching 0.37, the three-bucket system would paint most new rows
orange, destroying the colour signal. Replace with five buckets:

| Band | `total_score` threshold | Colour | Hex |
|---|---|---|---|
| Strong match | ≥ 0.75 | Green (unchanged) | `#28a745` |
| Good match | ≥ 0.60 | Teal (new) | `#20c997` |
| Usable | ≥ 0.48 | Yellow (unchanged) | `#ffc107` |
| Loose | ≥ 0.38 | Orange (unchanged) | `#fd7e14` |
| Stretch | < 0.38 | Muted red (new) | `#dc6060` |

Thresholds key off `total_score` (the blended value), not off the raw key score, so
that a Related-key track with a strong energy and BPM match can score into the Usable
band — which is correct DJ semantics.

**Implementation target:** `source/ui/suggestion_panel.py:21-27`.

#### 2. Tooltip — add tier name as first line (`suggestion_panel.py:365-372`)

Revised tooltip format:

```
Energy ±2
Key: 57%   Energy: 75%   BPM: 90%
Crates: House, Tech House
```

The tier name (`scored.harmonic_tier.value`) is prepended as the first element of
`tip_lines`. The existing Key/Energy/BPM line and Crates line are unchanged.

**Implementation target:** `source/ui/suggestion_panel.py:365-372` — insert
`tip_lines = [scored.harmonic_tier.value, ...]` before the existing key/energy/bpm
string, separated by `\n`.

#### 3. Header count — no change

`"Suggestions (N)"` at `suggestion_panel.py:278` reads correctly at 60 rows. No
layout or copy change needed.

#### 4. Empty-state copy — no change

`"No compatible tracks found"` at `suggestion_panel.py:274` remains accurate.

#### 5. Row ordering and grouping — no change

List stays sorted by `total_score` descending (`suggestion_engine.py:86`). The
five-colour `%` badge provides the visual tier grouping without needing separators
or block-level backgrounds. No new layout pattern needed.

### Resolved UI questions from the architect's draft

1. **`_score_color()` thresholds** — resolved. Five-bucket scale, thresholds above.
   Not keyed off the tier directly (the blended `total_score` is the right signal because
   energy and BPM contribute; a Related-key track with good energy can be genuinely usable).
2. **Whether to surface the tier name, and where** — resolved. Tooltip first line.
   An inline column would push the grid past the 1000px minimum window width. A badge
   in the score cell would be too busy. The tooltip is available on demand without consuming
   screen space — correct for a half-second glance tool.
3. **"Suggestions (N)" at large N** — resolved. Reads fine; no change.
4. **Row ordering / grouping** — resolved. No grouping; colour coding is sufficient.
5. **Empty-state copy** — resolved. No change needed.

### Open questions for the user (not yet decided)

- **Five colours vs three re-tuned colours.** The design above recommends five buckets
  (adding teal for Relative/Diagonal and muted-red for Related). Three colours with
  re-tuned thresholds would be simpler but lose granularity at the lower end. User call.
- **`MAX_SUGGESTIONS = 60`.** Architect open question Q1 — try it and revisit after
  the DJ has used the wider pool live.
- **Related tier by default.** Architect open question Q2 — included by default; can be
  disabled by setting `RELATED: 0.0` in `HARMONIC_TIER_SCORES` with no UI change.

---

## 6. Risks & open questions

### Risks

- **R1 — Dangling import between Phase 1 and Phase 2.** Phase 1 deletes `is_compatible()` while `suggestion_engine.py:4` still imports it. Mitigation: land Phase 1 and Phase 2 in the same PR, or Phase 2 immediately after with no release in between. The implementation plan flags this.
- **R2 (repurposed — 2026-05-22) — a future contributor wrongly assumes the diagonal must be directional.** The original R2 demanded an *asymmetric* diagonal (`compatibility_score(9A,8B) == 0`); that requirement was proven mathematically unsatisfiable and is withdrawn — see §2 Decision point 4 "History" and the Resolution note in ADR-010. The real residual risk is the inverse: "diagonal" reads intuitively as a one-way move, and the original draft of this blueprint made exactly that mistake, so a future contributor might "fix" the symmetric diagonal into an asymmetric one and reintroduce a harmonically-wrong rule. Mitigation: the symmetric behaviour is stated in §2 Decision point 4, in the `compatibility_score` / `classify` docstrings in `source/services/camelot.py`, and is locked in by a dedicated symmetry test in `tests/services/test_camelot.py` asserting `compatibility_score("9A","8B") == compatibility_score("8B","9A")`.
- **R3 — Circular import between `config.py` and `camelot.py`.** The `HarmonicTier` enum lives in `camelot.py`; `HARMONIC_TIER_SCORES` lives in `config.py` and is keyed by that enum, so `config.py` must `import` from `camelot.py`. `camelot.py` then needs the score values from `config.py` — if `camelot.py` imports `config.py` at module load, that is a cycle. Resolution: `camelot.py` must **not** import `config.py` at module scope. Two acceptable options, engineer to pick one and the code-reviewer to confirm: (a) `camelot.py` imports `HARMONIC_TIER_SCORES` lazily *inside* `compatibility_score()`; or (b) define the enum in a tiny new leaf module (e.g. `source/services/harmonic_tier.py`) that both `config.py` and `camelot.py` import, breaking the cycle cleanly. Option (b) is architecturally cleaner (a leaf module with no dependencies) but adds a file; option (a) is fewer files but uses a function-level import, which the coding standards tolerate for cycle-breaking. The implementation plan assumes option (a) for minimal disruption but the engineer may choose (b).
- **R4 — `_score_color()` makes most rows orange.** Not a correctness bug but a UX regression if shipped without the ui-designer's threshold re-tune. Mitigation: §5 hands this explicitly to the ui-designer; do not ship the backend change to users without the UI follow-up.
- **R5 — Non-monotonic score vs wheel distance confuses maintainers.** Semitone (distance 5) outscores related (distance 4). Mitigation: the canonical mapping table in §1 and a comment in `camelot.py` next to the tier lookup.
- **R6 — `harmonic_tier` on `ScoredTrack` with no consumer yet.** Phase 3 adds a field nothing reads until the ui-designer's follow-up. Low risk — it is a small, well-named dataclass field and is exercised by Phase 4 tests; acceptable as a deliberate forward hook.

### Open questions

- **Q1 (for the user) — What should `MAX_SUGGESTIONS` be?** The plan raises it from 30 to 60 as an interim default. The right value depends on the user's library size and how long a suggestion list they want to scroll. Options: keep 60; raise higher (90/120); make it user-configurable in the Settings dialog (out of scope for this plan, would be a follow-up). Recommend shipping 60 and revisiting after the user has tried the widened pool.
- **Q2 (for the user / ui-designer) — Should the very weakest tier (Related, ±4, ~0.37) be offered at all by default?** It is the loosest "sometimes it works" tier. Offering it maximises the pool (the stated goal) but adds the lowest-confidence rows. Recommend offering it (it still scores > 0 and the user explicitly asked for "a lot more tracks"), but the ui-designer may choose to visually de-emphasise or group it.
- **Q3 (for the ui-designer) — Colour and tier-label treatment.** Deferred entirely; see §5.
- **Q4 — Should tracks with a missing/unparseable Camelot key ever be suggested?** Current behaviour drops them (`suggestion_engine.py:48-49`). This plan keeps that behaviour unchanged — a track with no key cannot be harmonically scored. Flagged only so it is a conscious non-change.
