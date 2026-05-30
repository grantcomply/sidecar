# Architect Blueprint — Suggestion Filter Enhancements

> Status: Proposed
> Date: 2026-05-30
> Author: Architect agent
> Plan folder: `plans/suggestion-filter-enhancements-2026-05/`

> UI-shaped sections are marked `<!-- UI-designer to revise -->`. The architect scopes
> the state/wiring substrate only; the ui-designer owns look, layout, copy, and the
> filter-UX redesign. Do not finalise visual decisions from this document.

---

## 1. Context

### The user request (verbatim)

> "Currently the track suggestion system works really really well, I often find myself
> getting stuck in the same key though because like for like key matching is so much
> easier to do, I would like the option to transition by plus or minus a as one of the
> filters so that we can say transition plus one and then it won't offer me anything in
> the same key helping me work my way up through the keys. With this the filters are a
> little bit finicky to use can we also do a UR review on how the filters work lastly in
> interface. Additionally I would also like to only get suggested tracks that are added
> within a time range, sometimes I like to look back at tracks I found in the last two
> months and only filter on those so another filter range would be date added between
> where I can maybe have a from date only or a from and A to date was something like
> that."

### Three distinct sub-features

1. **Key transition offset filter** — shift harmonic matching by ±N Camelot steps so the
   DJ is steered off like-for-like (same-key) matches and progressively up (or down) the
   wheel.
2. **Filter UX review** — the existing filters are "finicky". This is a UI review handed
   to the ui-designer. The architect scopes the current filter state/wiring so the
   redesign has a clean substrate.
3. **Date-added range filter** — filter suggestions to tracks whose "date added to
   library" falls in a `from` (and optional `to`) range. **The data does not exist
   today** — see §4, the dominant open question in this blueprint.

### How suggestions are produced today (the substrate)

- `source/services/suggestion_engine.py:25-91` — `get_suggestions(current, library,
  exclude_paths, allowed_crates, allowed_genres)` iterates every track, applies filters
  (self/exclude `:37-40`, crate `:43-44`, genre `:47-48`, harmonic-gate `:52-56`), blends
  `key_score` + `energy_score` + `bpm_score` (`:75-79`), sorts and truncates to
  `MAX_SUGGESTIONS` (`:90-91`).
- The harmonic gate is "offer any track with `compatibility_score(current, candidate) >
  0`" (`:54-56`), i.e. any of the 7 tiers from ADR-010. Same-key (PERFECT, score 1.0) is
  always offered and, being the highest key tier, dominates the top of the list — this is
  exactly the "stuck in the same key" problem the user reports.
- `source/services/camelot.py:52-107` — `classify(key1, key2) -> HarmonicTier`;
  `:110-135` — `compatibility_score()`. Both are **symmetric** (ADR-010 Decision 4).
- `source/config.py:87-104` — `SUGGESTION_WEIGHTS`, `HARMONIC_TIER_SCORES`, limits.

### Current filter state/wiring (substrate for the UX review)

- `source/ui/suggestion_panel.py:48-156` — `FilterDropdown`: a checkbox dropdown with
  Select-All / Deselect-All. Two instances: `crate_filter` (`:213`), `genre_filter`
  (`:216`). State lives in `tk.BooleanVar` per item (`:103`); selection exposed via
  `.selected` (`:150-152`) and `.all_selected` (`:154-156`).
- Change propagation: `FilterDropdown._fire()` → `_on_change` (`:146-148`) →
  `SuggestionPanel._filter_changed()` (`:276-278`) → `on_filter_change` →
  `app._on_crate_filter_changed()` (`source/app.py:301-302`) → `_update_suggestions()`.
- `app._update_suggestions()` (`source/app.py:304-324`) translates "all selected" into
  `None` (meaning no filter) and otherwise passes the selected set into `get_suggestions`.
- The panel exposes `set_crates()`/`set_genres()` (`:254-258`), populated from
  `library.crate_names`/`genre_names` on load and sync (`source/app.py:127-128`,
  `:265-266`).

### Constraints from existing docs (call-outs and conflicts)

- **ADR-010** (`docs/architecture-decisions.md:220-291`): the harmonic score is
  **symmetric** — `compatibility_score(a,b) == compatibility_score(b,a)`. Sub-feature 1
  introduces *direction* (+1 vs −1), which is a new concern that **must not** be pushed
  into `compatibility_score`/`classify`. Doing so would break the symmetry tests in
  `tests/services/test_camelot.py` and re-open the R2 trap. **Direction is an engine-level
  concern, layered on top of the symmetric Camelot primitives.** This is the key
  architectural boundary to respect.
- **ADR-003** (`:42-52`): weighted-linear-combination scoring stands. Sub-feature 1's
  preferred form (a target-key re-anchor) keeps that intact.
- **ADR-007** (`:106-170`): the cache is a single versioned `track_cache.json`. The
  date-added field (§4) requires a **cache schema change** — bump `CACHE_VERSION` and
  document the new field in the ADR-007 structure. This is the cross-cutting decision
  ADR-011 below.
- **ADR-002** (`:30-40`): "No query capability — all filtering is in-memory." Both new
  filters are in-memory passes inside `get_suggestions` — consistent, no storage-engine
  change.
- **Coding standards** (`docs/coding-standards.md:32-36`): `pathlib.Path`, never hardcode
  separators, `encoding="utf-8"`. The date-added source uses `Path.stat()` (§4).
- **Coding standards** (`:58-62`): all tuneable values in `config.py` — new limits
  (offset range, default tiers preferred per offset) belong there.
- **Coding standards** (`:38-42`): no bare `except`; catch specific exceptions. The
  `Path.stat()` calls in §4 must catch `OSError` specifically.
- **Testing strategy**: `suggestion_engine.py` and `camelot.py` are Phase-1 priority.
  Every new pure-function helper here ships with tests.
- **Architectural debt** (`docs/architecture-overview.md:102-112`): item 10 — `Track`
  dataclass is mutated in-place by library load. Sub-feature 3 adds a field to `Track`;
  follow the existing pattern (default-valued field, populated in `from_dict`).
- **Cross-platform** (`docs/cross-platform-guide.md`): file-timestamp semantics differ by
  OS — `st_birthtime` (creation) is not reliably available on Linux. This directly shapes
  the §4 data-source decision. No path-handling concerns beyond using `Path.stat()`.

---

## 2. Sub-feature 1 — Key transition offset filter

### The decision (ADR-011-A — filter-vs-rescore, target-key re-anchor)

**Decision: implement the offset as a TARGET-KEY RE-ANCHOR, not a hard post-filter and
not a re-weighting.** When the offset is `+N`, the engine scores every candidate against a
*shifted target key* (current key's number advanced by N around the wheel), and PERFECT
same-key matches are excluded. When offset is `0` (default), behaviour is exactly today's.

Three options were considered:

| Option | What it does | Verdict |
|--------|--------------|---------|
| **A. Hard filter** | Keep scoring against the current key; after scoring, drop any candidate whose key is not exactly `current ± N`. | Rejected. Too rigid — collapses the pool to one or two keys, throws away the tiered harmonic model ADR-010 just built, and ignores energy/BPM. The user said the system "works really really well"; a hard filter guts it. |
| **B. Re-weight / penalise same-key** | Keep current key as anchor; multiply same-key scores by a penalty so they sink. | Rejected. Doesn't actually move the DJ *up* the wheel — it just demotes same-key while still anchoring everything around the current key. Diffuse and hard to reason about; the "+1" intent (work toward the next key) is lost. |
| **C. Target-key re-anchor (CHOSEN)** | Compute a shifted target key = `shift(current.camelot_key, +N)`. Score harmonic compatibility against the *target*, not the current. Exclude PERFECT (the unshifted same key). | Chosen. Matches the mental model exactly: "+1 → treat one-key-up as the new home, offer me everything harmonically compatible *with that*." Preserves the full tiered model and the energy/BPM blend — a +1 still surfaces a rich, ranked pool, just centred one step up the wheel. |

**Why re-anchor and not just "offer key == current+1":** harmonic mixing toward a target is
itself tiered. If the DJ wants to move to 9A, tracks adjacent/relative/diagonal to 9A are
all valid stepping stones, not just exact-9A tracks. Re-anchoring lets the existing
`compatibility_score` do its job against the new centre, so the suggestion list stays rich
and ranked exactly as it is today — only the harmonic centre of gravity moves.

### How the shift respects ADR-010 symmetry

The shift is **directional**, but it is applied to the *target key string* before the
symmetric `compatibility_score` is called — it does **not** make the score function
directional. New leaf helper in `camelot.py`:

```
def shift_key(key: str, steps: int) -> str | None:
    """Return the Camelot key 'steps' positions around the wheel (same letter).
    +1 from 8A -> 9A; -1 from 1A -> 12A (wraps mod 12). None for invalid keys."""
```

`shift_key` only moves the *number* (energy boost/drop along the same letter), wrapping
12↔1 — the natural reading of "transition +1". `compatibility_score(shifted_target,
candidate)` is then called with the symmetric function untouched. **No change to
`classify` or `compatibility_score`.** The symmetry tests stay green. This is the load
bearing boundary: direction lives in the engine via a pre-shift, never inside the Camelot
score.

### Excluding same-key

With offset `!= 0`, exclude candidates where `compatibility_score(current.camelot_key,
candidate.camelot_key) == 1.0` (PERFECT / identical key). This is the literal "won't offer
me anything in the same key" requirement. Implemented as one guard in the engine loop;
when offset is `0` the guard is skipped and nothing changes.

### Engine signature change

`get_suggestions(..., key_offset: int = 0)`. When `key_offset == 0`, the function behaves
byte-for-byte as today (default-arg keeps all existing callers and tests valid). When
non-zero:
1. `target = shift_key(current.camelot_key, key_offset)` (skip the whole offset path if
   `target is None`, i.e. current track has no/invalid key — fall back to offset 0).
2. Score harmonic against `target` instead of `current.camelot_key`.
3. Exclude PERFECT-vs-current candidates (same-key suppression).

`ScoredTrack.harmonic_tier` is then the tier relative to the *target* — the tooltip
already shows the tier name (`suggestion_panel.py:380-382`), which stays meaningful.

### Config

Add to `config.py`: `KEY_OFFSET_RANGE = (-2, 2)` (or similar) so the UI knows the legal
selectable values and the engine can clamp. Default `0`. Range is tunable per coding
standard "all tuneable values in config.py".

**UI surface — `KeyOffsetControl` inline stepper (see `ui-design-brief.md` §Sub-feature 1)**

The offset control is a three-part inline stepper pill: `[◀  Transition: same key  ▶]`.

- Implemented as a single `CTkFrame` (corner_radius=6) containing two `CTkButton`
  widgets (◀ and ▶, width=24, height=28, transparent background) flanking a `CTkLabel`
  showing the current offset in human-readable form.
- Label copy: "Transition: same key" at offset 0; "Transition: +1" / "Transition: −1"
  at non-zero offsets.
- The pill's `fg_color` is `("gray75", "gray35")` at offset 0 (neutral) and
  `"#1f6aa5"` (accent blue) at any non-zero offset — matching the filter-active signal
  used across the redesigned filter bar.
- The ◀ and ▶ buttons disable (`state="disabled"`) at `KEY_OFFSET_RANGE` min/max ends.
- On each button press, call `self._filter_changed()` (the same path as all other
  filters: `suggestion_panel.py:276–278` → `app.py:301–302` → `_update_suggestions()`).
- Panel exposes `selected_key_offset: int` property, default 0, clamped to
  `KEY_OFFSET_RANGE`. Mirrors `selected_crates` property pattern (`suggestion_panel.py:260–262`).
- Tooltip on the pill (400ms delay, `tooltip.py:7`): "Shift harmonic matching up or
  down the Camelot wheel. At +1 same-key tracks are hidden and one-step-up tracks move
  to the top."
- Placement: in the redesigned filter bar (row 1 of `SuggestionPanel`), after the
  Genres pill and before the Date pill. See brief §Redesigned filter bar — layout.
- Same-key suppression at offset 0 is never toggled independently — offset 0 means
  today's behaviour, any non-zero offset suppresses same-key. No separate checkbox.

---

## 3. Sub-feature 2 — Filter UX review

This sub-feature is **owned by the ui-designer**. The architect's contribution is to
describe the substrate precisely so the redesign rests on clean wiring.

### What exists today (architecture facts the redesign must honour)

- Two `FilterDropdown` instances (crates, genres) in a 2-column filter row
  (`suggestion_panel.py:207-217`). Each is a button that expands an inline panel with
  Select-All / Deselect-All and a scrollable checklist (`:48-156`).
- "All selected" is the neutral state and is translated to "no filter" (`None`) in
  `app._update_suggestions()` (`:309-315`). Important invariant: **the engine treats
  `None` (no filter) and "every item selected" identically** — the UI redesign must
  preserve a clear "no filter / everything" affordance, or the engine contract changes.
- Every selection change fires a full `_update_suggestions()` recompute
  (`suggestion_panel.py:146-148` → `app.py:301-302`). For a 200–500 track library this is
  cheap; the redesign can keep live-update semantics without performance concern.
- Selection state is per-widget (`tk.BooleanVar`), not centralised. There is **no filter
  state object** — state is scattered across the two dropdowns plus (after this work) the
  offset control and date control. See the architectural note below.

### Architectural note / opportunity (non-blocking recommendation)

Adding two more filters (offset, date) to a panel whose filter state is already scattered
across widgets pushes toward a small **filter-state value object**. Recommended but
**optional** for this feature: a frozen dataclass `SuggestionFilters(allowed_crates,
allowed_genres, key_offset, date_from, date_to)` that the panel assembles and hands to
`app`, which forwards it to `get_suggestions`. This:
- collapses the growing `get_suggestions` keyword list into one typed argument,
- gives the UX redesign a single "current filter state" to render/reset,
- is trivially testable.

This is a *medium* refactor touching the engine signature and `app._update_suggestions`.
**Recommendation: defer to a follow-up unless the ui-designer's redesign naturally wants
it.** For this feature, additive keyword args on `get_suggestions` are acceptable and
lower-risk. Flag it in ADR-011 consequences as the documented next step.

**Filter UX redesign — see `ui-design-brief.md` for full audit and spec.**

Summary of decisions (architect wiring implications only):

1. **FilterDropdown becomes a pill button with floating overlay.** The inline
   expand/collapse (which pushed the suggestion list down) is replaced by a floating
   overlay panel positioned below the pill. The overlay does not affect grid layout of
   `SuggestionPanel`. The engineer implements this as either a `CTkToplevel` (transient,
   no `grab_set()`) or a `place()`d `CTkFrame` with `lift()` — both are acceptable;
   choose based on lifecycle simplicity (see brief §Finding 3).

2. **"Deselect All" button is removed.** The all-unchecked state (which yields zero
   suggestions and reads as broken) is no longer reachable via normal interaction. The
   engine `None`-means-no-filter contract is unchanged: `all_selected → None`. If a user
   manually deselects the last item, the result is an empty suggestion list with a blue
   pill — the "Reset filters" button at the bar level restores defaults immediately.

3. **"Select All" becomes a compact secondary-style control** inside the dropdown (not
   a large green button). Sentence case label: "Select all."

4. **Filter bar is a single horizontal row** of four pills + a "Reset filters"
   affordance. All four controls (Crates, Genres, Transition, Added) sit in this row.
   "Reset filters" is right-anchored, shown only when any filter deviates from default,
   implemented as a `CTkLabel` with `cursor="hand2"` and hover colour change (no button
   chrome). Its `command` resets all four filter controls to defaults and calls one
   `_filter_changed()`.

5. **Active filter pills render with accent blue** (`fg_color="#1f6aa5"`) background;
   neutral/default pills use `("gray75", "gray35")`. This gives glance-level signal that
   a filter is narrowing results.

6. **Empty state for crate/genre dropdowns before sync:** "No crates loaded — sync
   your library first." (sentence case; inside the floating dropdown panel only.)

The engine `None`-means-no-filter contract (`app.py:309–315`) is preserved without
change.

---

## 4. Sub-feature 3 — Date-added range filter

### LOUD FLAG: the "date added to library" data does not exist today

I checked every layer of the pipeline:

- **`Track` dataclass** (`source/models/track.py:5-23`): has a `date` field (`:17`), but
  it is populated from the ID3 **`TDRC`** tag (`crate_parser.py:142`) — that is the
  *recording / release date of the music*, NOT when the track was added to the DJ's
  library. Using it for "date added" would be wrong (a 1995 track added yesterday would
  filter out of a "last two months" view).
- **`crate_parser.get_track_metadata`** (`crate_parser.py:75-147`): reads ID3 tags only.
  Serato/ID3 expose **no reliable "date added to library" frame**. (Serato stores library
  add-dates in its own binary `database V2` file, which this app does not parse — it only
  reads `.crate` files and ID3 tags. Parsing `database V2` is out of scope and fragile.)
- **`cache.py`** (`source/services/cache.py:80-108`): stores a single global `synced_at`
  timestamp and per-crate `crate_mtimes` — **nothing per track**.

**Conclusion: there is no existing per-track timestamp to filter on. We must derive one.**

### The decision (ADR-011-B — date-added data source)

Options for a per-track "date added" proxy:

| Source | API | Pros | Cons |
|--------|-----|------|------|
| ID3 `TDRC` (existing `date` field) | already parsed | free | **Wrong meaning** — release date, not add date. Rejected. |
| Serato `database V2` add-date | new binary parser | true add-date | Out of scope, fragile, undocumented binary format, large effort. Rejected for now. |
| File **mtime** (`Path.stat().st_mtime`) | `stat` | cross-platform, always present | Changes if the file is re-tagged/edited; approximates "last touched" not "added". |
| File **ctime** (`st_ctime`) | `stat` | present everywhere | Means inode-change-time on Linux, creation on Windows — inconsistent. Rejected. |
| File **birthtime** (`st_birthtime`) | `stat` | true creation time | **Not available on Linux**; on Windows exposed as `st_ctime`. Inconsistent. |
| **First-seen-in-cache timestamp** | recorded by us at sync | exactly "date we first saw this track in your library" — closest to user intent | Requires cache schema change + carry-forward logic across syncs; tracks already in the library at first sync all share the first-sync date. |

**Decision: record a `date_added` per track that is the FIRST-SEEN-IN-CACHE timestamp,
with file `mtime` used as the seed value on first sight.** Concretely, at sync time, for
each track:
- If the track already exists in the *previous* cache with a `date_added`, **carry it
  forward unchanged** (it keeps its original first-seen value).
- If it's new (not in previous cache), set `date_added` to the file's **`mtime`**
  (`Path(path).stat().st_mtime`), falling back to the sync time if `stat` fails (`OSError`).

**Rationale:** First-seen-in-cache is the truest available proxy for "tracks I found in
the last two months" — it is the date the track entered *this app's* view of the library.
Seeding new tracks from `mtime` (rather than sync-time) gives a more accurate add-date for
tracks the DJ added between two syncs (a track added 6 weeks ago but first synced today
gets ~6-weeks-ago, not today). After first sight the value is frozen, so re-tagging a file
later does not move it. This is robust, cross-platform (mtime is universal), needs no new
binary parsing, and degrades gracefully.

**Honest caveat to surface in UI copy (ui-designer):** on the *very first* sync of an
existing library, every pre-existing track gets an mtime-derived date — which for many
DJs' files may cluster oddly (e.g. all show the file's last-edit date). The filter becomes
progressively more accurate as the user syncs over time and new tracks get real first-seen
dates. This limitation must be stated plainly to the user, not hidden.

### Data model and cache changes (ADR-011-B mechanics)

1. **`Track` dataclass** (`models/track.py`): add `date_added: float = 0.0` (Unix
   timestamp, float, matching `crate_mtimes`/`synced_at` conventions). Populate in
   `from_dict` (`:90-148`) from `data.get("date_added", 0.0)`. `from_csv_row` (the legacy
   path, `:25-87`) can leave it `0.0` — CSV is the dead legacy loader (ADR-007).
2. **`crate_parser.get_track_metadata`**: add `"date_added"` to the returned dict. The
   *seed* value (mtime) is computed here per file via `Path(path).stat().st_mtime` inside
   a `try/except OSError`.
3. **Carry-forward logic** lives in `parse_all_crates` (`crate_parser.py:160-223`) or a
   thin wrapper: it needs the *previous* cache's tracks to preserve existing `date_added`.
   Load the old cache (`cache.load_cache()`), and for each parsed track, if the path
   existed before with a non-zero `date_added`, overwrite the freshly-seeded value with
   the old one. **This couples the parser to the cache read** — acceptable, or inject the
   previous-tracks dict as a parameter to keep the parser pure (preferred; see
   implementation plan).
4. **Cache schema**: `date_added` is now a key in each track dict written by
   `cache.save_cache` (`cache.py:80-108`) — it flows through automatically since
   `save_cache` writes the tracks dict verbatim. **Bump `CACHE_VERSION` from 1 to 2**
   (`cache.py:16`) because the schema gained a field. Per ADR-007, a version mismatch makes
   `load_cache` return `None` (`cache.py:70-76`), forcing a one-time re-sync — acceptable
   and self-healing. Document the new field in ADR-007's structure block.

### Engine filter

`get_suggestions(..., date_from: float | None = None, date_to: float | None = None)`. In
the loop, after the existing genre filter, add:
```
if date_from is not None and track.date_added < date_from:  continue
if date_to   is not None and track.date_added > date_to:    continue
```
A track with `date_added == 0.0` (unknown — e.g. legacy/failed stat) is **excluded** when
a `date_from` is set (it can't be proven to be in range). Document this; the ui-designer
may want a visible note when the filter is active. Both `None` = no date filter, preserving
today's behaviour.

**UI surface — `DateRangeControl` preset-first pill (see `ui-design-brief.md` §Sub-feature 3)**

The date filter is a pill button labelled "Added: any time" (default, grey) or
"Added: last 3 months" / "Added: from 2026-01-01" etc. (active, blue). Clicking the
pill opens a floating overlay panel containing:

1. **Preset tiles (primary affordance):** five `CTkButton` tiles in a horizontal row:
   "Any time", "Last month", "Last 3 months", "Last 6 months", "This year". Selecting
   any preset immediately applies the filter and closes the panel. Active preset tile
   shows blue background; "Any time" is the default (grey).

2. **Manual entry (secondary affordance, below a thin rule):** two `CTkEntry` fields
   ("From", "To (optional)") in YYYY-MM-DD format, plus an "Apply" button. Invalid
   input shows a red border (`border_color="#dc3545"`) and inline text: "Enter a date
   as YYYY-MM-DD." The engine is never called with a bad value.

3. **Honest caveat (below manual entry, secondary-grey text):**
   "Dates are approximate for tracks added before your first sync."
   This line appears once, inside the date panel only — not in toasts or tooltips.

**Wiring:**
- Panel exposes `selected_date_range: tuple[float | None, float | None]` property.
  Default: `(None, None)`. When a preset or manual range is active, returns the
  corresponding epoch floats. When `to` is not set, returns `(from_epoch, None)` —
  `None` to means open-ended (no upper bound), confirmed per brief §Open questions Q2.
- `app._update_suggestions()` reads this property and forwards `date_from`, `date_to`
  to `get_suggestions` (same pattern as `allowed_crates` / `allowed_genres`).

**Date conversion helper:**
`date_range_to_epoch(preset, from_str, to_str) -> tuple[float | None, float | None]`
lives in `source/ui/utils.py` (or `source/services/dates.py` if it grows beyond ~30
lines). Must be unit-tested.

**Empty state when date filter zeroes results:**
"No tracks found in this date range. Try a wider window or reset the date filter."
This overrides the generic "No compatible tracks found" copy only when the date filter
is active and `scored_tracks` is empty. The engineer checks this condition in
`SuggestionPanel.set_suggestions`.

**Tracks with `date_added == 0.0`** are silently excluded by the engine when
`date_from` is set (blueprint §4 invariant). No additional UI handling needed — the
count in "Suggestions (N)" reflects the narrowed pool.

---

## 5. ADR-011 (to be written into `docs/architecture-decisions.md`)

This feature warrants one new ADR with two decision points. Draft below for the architect
to commit on acceptance.

> ### ADR-011: Suggestion Filter Enhancements (key-offset re-anchor; first-seen date-added)
> - **Status:** Proposed
> - **Date:** 2026-05-30
> - **Context:** Users get "stuck in the same key" because PERFECT same-key matches
>   dominate the suggestion list, and want to filter suggestions by when a track was added
>   to their library. Neither a direction concept nor a per-track add-date exists today.
> - **Decision A (key offset = target-key re-anchor):** Add a `key_offset` engine
>   parameter. Non-zero offset shifts the harmonic *target* via a new symmetric-safe
>   `camelot.shift_key(key, steps)` helper and excludes PERFECT-vs-current candidates.
>   Direction is an engine concern applied as a pre-shift; `compatibility_score` /
>   `classify` stay symmetric and untouched (preserves ADR-010 and its tests).
> - **Decision B (date-added = first-seen-in-cache, mtime-seeded):** Add `Track.date_added`
>   (Unix float). At sync, carry forward an existing track's `date_added`; seed a newly
>   seen track from file `mtime` (fallback: sync time on `OSError`). Bump `CACHE_VERSION`
>   1→2 (forces one self-healing re-sync). ID3 `TDRC` is rejected (release date ≠ add
>   date); Serato `database V2` parsing is out of scope; ctime/birthtime rejected for
>   cross-platform inconsistency.
> - **Consequences:** Pro — rich ranked suggestions re-centred up/down the wheel without
>   gutting the tiered model; cross-platform date proxy with no new dependencies; cache
>   versioning absorbs the schema change cleanly. Con — first-sync add-dates are
>   mtime-approximate and improve over time (must be stated to users); a future
>   `SuggestionFilters` value object is the documented next step as filter count grows;
>   one forced re-sync on upgrade.
> - **Supersedes/relates:** Extends ADR-002 (still in-memory filtering), ADR-007 (cache
>   schema v2), respects ADR-010 (symmetry preserved).

---

## 6. Affected files

| File | Change | Sub-feature |
|------|--------|-------------|
| `source/services/camelot.py` | Add `shift_key()` leaf helper (+ `__all__`, tests) | 1 |
| `source/services/suggestion_engine.py` | Add `key_offset`, `date_from`, `date_to` params; target re-anchor + same-key exclusion; date guards | 1, 3 |
| `source/config.py` | Add `KEY_OFFSET_RANGE` (and any default) | 1 |
| `source/models/track.py` | Add `date_added: float` field; populate in `from_dict` | 3 |
| `source/services/crate_parser.py` | Emit `date_added` (mtime seed); carry-forward logic | 3 |
| `source/services/cache.py` | Bump `CACHE_VERSION` 1→2 | 3 |
| `source/services/crate_sync.py` | Pass previous-cache tracks into parse for carry-forward | 3 |
| `source/ui/suggestion_panel.py` | New offset control + date control; `selected_key_offset`, `selected_date_range` props; place in filter row | 1, 2, 3 — **UI-designer brief first** |
| `source/app.py` | `_update_suggestions()` forwards offset + date range to engine | 1, 3 |
| `tests/services/test_camelot.py` | `shift_key` tests (wrap, invalid, ±) | 1 |
| `tests/services/test_suggestion_engine.py` | offset re-anchor, same-key exclusion, date range filter | 1, 3 |
| `docs/architecture-decisions.md` | Add ADR-011; note ADR-007 schema v2 | all |
| `docs/architecture-overview.md` | Note `date_added` on Track; cache v2 | 3 |
| `plans/.../ui-design-brief.md` | Produced by ui-designer | 1, 2, 3 |

---

## 7. Phases (high level — see implementation-plan.md for ordered tasks)

- **Phase 0 — ui-designer brief.** Filter UX review (sub-feature 2) + offset and date
  control specs. Blocks all UI work; engine work can start in parallel.
- **Phase 1 — Key offset (engine first).** `shift_key` + tests; engine `key_offset` +
  tests; config range. No UI yet (testable via tests).
- **Phase 2 — Date-added data plumbing.** `Track.date_added`; parser mtime seed +
  carry-forward; cache v2 bump; engine date guards + tests. No UI yet.
- **Phase 3 — UI wiring.** Implement offset + date controls per ui-designer brief; wire
  `app._update_suggestions`. Apply the filter-UX redesign.
- **Phase 4 — Docs.** Commit ADR-011; update ADR-007 structure block and overview.

Sequencing rationale: each engine change is independently testable behind a default-arg
(zero behaviour change until the UI sends a non-default value), so Phases 1–2 can land and
be reviewed before any pixel moves. The date-data plumbing (Phase 2) is the riskiest
(schema + carry-forward) and is isolated from the UI.

---

## 8. Risks & open questions

- **R1 — First-sync date accuracy (data quality).** On a user's first sync, all
  pre-existing tracks get mtime-derived dates that may not reflect true add order. *Status:
  accepted with mitigation* — improves over time as new tracks get real first-seen dates;
  ui-designer writes honest caveat copy. **Open question for the user:** is mtime-seeded
  first-seen good enough, or do they want a future Serato `database V2` parser for true
  add-dates? (Recommend shipping first-seen now, revisit only if they ask.)
- **R2 — Carry-forward coupling.** Implementing carry-forward couples the parser to the
  previous cache. *Mitigation:* inject the previous-tracks dict as a parameter
  (parser stays pure; `crate_sync` does the cache read). See implementation plan.
- **R3 — Cache version bump forces a re-sync.** Every existing user re-syncs once on
  upgrade. *Status: accepted* — self-healing per ADR-007; sync is fast and user-initiated
  already.
- **R4 — Direction leaking into the symmetric Camelot core (the ADR-010 trap).** A future
  contributor might "simplify" the offset by making `classify`/`compatibility_score`
  directional. *Mitigation:* ADR-011 Decision A states the boundary explicitly; symmetry
  tests in `test_camelot.py` fail if violated; `shift_key` keeps direction in the engine.
- **R5 — Offset on a track with no/invalid key.** If `current.camelot_key` is empty,
  `shift_key` returns `None`. *Mitigation:* engine falls back to offset 0 (today's
  behaviour) rather than emptying the list. Stated in §2.
- **R6 — Filter-state sprawl.** Four filters with per-widget state. *Status: flagged,
  deferred* — `SuggestionFilters` value object recommended as the documented next step
  (§3), not required for this feature.
- **Open question — UI for offset semantics.** Should the same-key suppression at offset 0
  ever be optional (offer "+1 but still allow same key")? Current decision: offset 0 =
  today's behaviour (same key allowed); any non-zero offset = same key suppressed. The
  ui-designer should confirm this matches user expectation when writing the control copy.
- **Open question — date filter `to` default.** When the user sets only a `from` date,
  `to` is `None` (open-ended to now). Confirm with ui-designer this is the right default
  vs. defaulting `to` to "now".
