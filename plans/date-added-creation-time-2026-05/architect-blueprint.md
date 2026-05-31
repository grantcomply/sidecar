# Architect Blueprint — `date_added` from File Creation Time

> **Feature:** Source the date-added filter from the file's **creation timestamp** instead of the mtime-seeded "first-seen-in-cache" value.
> **Scope:** Pure backend. No UI changes (the date filter UI is unchanged).
> **Author:** Architect agent · **Date:** 2026-05-31
> **Status:** Proposed — pending implementation

---

## 1. Context

The date-added filter shipped in ADR-011 (Decision B). It added `Track.date_added: float`
(`source/models/track.py:21`) and seeded it from the file's **modification time**
(`Path(path).stat().st_mtime`, `source/services/crate_parser.py:91`), emitted into both the
empty and populated metadata dicts (`crate_parser.py:108`, `:159`). That seed is the
**first-seen-in-cache** value: established once per track, then **frozen** — carried forward
unchanged on every later sync by `parse_all_crates` (`crate_parser.py:187`, `:231-238`) using the
injected `previous_tracks` dict, which `crate_sync._run()` populates from the prior cache
(`crate_sync.py:24-30`). The cache is at `CACHE_VERSION = 2` (`cache.py:16`).

ADR-011 chose mtime-seeded first-seen **deliberately and explicitly rejected** creation time:

> "Rejected sources: … `st_ctime` (inode-change-time on Linux, creation on Windows —
> inconsistent); `st_birthtime` (not reliably available on Linux). `mtime` is the only
> universally-present, cross-platform timestamp." — ADR-011, Decision B (`docs/architecture-decisions.md:337`)

**The user now wants the opposite:** *"can we now add a change where the date added is based on
the created date time of the file on my computer so the filter uses that."*

This blueprint **consciously reverses** ADR-011's date_added source decision. The reversal is
documented as **ADR-013**, which supersedes/amends ADR-011 Decision B. The reversal is acceptable
now for a reason that did not weigh in ADR-011's framing: **Serato Sidecar ships installers only
for Windows and macOS** (`docs/cross-platform-guide.md:7-11`, ADR-008). On both of those platforms a
true file creation time **is** obtainable. Linux was the only platform where creation time is
unreliable, and Linux is not a shipping target — it is a dev-machine-only "Future" tier.

---

## 2. The Python-version constraint (verified)

The interpreter is **Python 3.11.9**. This is the load-bearing technical fact for the helper design:

| Platform | Shipping? | Creation-time source on **Python 3.11** | Notes |
|----------|-----------|------------------------------------------|-------|
| macOS | Yes | `os.stat().st_birthtime` | True creation time; available on macOS since early Python 3. |
| Windows | Yes | `os.stat().st_ctime` | On **Windows**, `st_ctime` **is** the creation time (not inode-change time). `st_birthtime` is **not** exposed on Windows until **Python 3.12** — so on 3.11 we must use `st_ctime`. |
| Windows (future, 3.12+) | Yes | `st_birthtime` (preferred) → `st_ctime` | When the bundled interpreter moves to 3.12, `st_birthtime` appears on Windows and is preferred; `st_ctime` remains a correct fallback. |
| Linux / other | No (dev only) | none reliable → fall back to `st_mtime` | `st_ctime` on Linux is inode-change time (wrong meaning); `st_birthtime` is filesystem-dependent and not exposed by CPython. mtime keeps dev machines functional without claiming false accuracy. |

This is why a naïve `st_birthtime`-only or `st_ctime`-only approach is wrong: the correct value
depends on both platform and interpreter version. The helper encodes the full fallback chain so the
call sites stay trivial. See `docs/cross-platform-guide.md` (a new "File creation time" section is
added as part of this work).

---

## 3. Decision (ADR-013, summarised — full ADR text lands in `docs/architecture-decisions.md`)

### D1 — Reverse the source: `date_added` is the file's creation time

`date_added` is now seeded from a cross-platform **creation-time** read, replacing the `st_mtime`
read at `crate_parser.py:91`. ADR-011 Decision B's mtime choice is superseded. The reversal is
acceptable because the residual risk (Linux's unreliable creation time) lands only on a
non-shipping platform.

### D2 — A small, pure, testable creation-time helper with an explicit fallback chain

Add `file_creation_time(path) -> float | None` as a **leaf helper** in a new dependency-free module
`source/services/file_times.py`. Rationale for a dedicated module over inlining in `crate_parser.py`:

- It is pure and platform-branching — exactly the kind of logic that wants isolated unit tests
  (`tests/services/test_file_times.py`), mockable via `os.stat` / `sys.platform` without dragging in
  ID3 parsing.
- It has no project dependencies (only `os` / `sys` / `pathlib`), so it cannot create an import
  cycle and can be imported by `crate_parser.py` freely. This mirrors the `harmonic_tier.py`
  leaf-module pattern from ADR-010.

**Exact fallback chain** (in order; first hit wins):

1. `st = os.stat(path)`; if `OSError` → return `None`.
2. If `hasattr(st, "st_birthtime")` and `st.st_birthtime > 0` → return `st.st_birthtime`.
   (Covers macOS on all versions, and Windows on 3.12+.)
3. Else if `sys.platform == "win32"` → return `st.st_ctime`.
   (Windows on 3.11: `st_ctime` is the creation time.)
4. Else → return `st.st_mtime`.
   (Linux/other dev machines — best available, mtime; not a shipping target.)

Contract notes:
- Returns `float | None`. `None` means "could not stat the file" — distinct from `0.0`.
- It does **not** itself substitute sync-time on failure; that policy belongs to the caller
  (`get_track_metadata`), keeping the helper a pure stat-reader. This preserves the existing
  semantics where `date_added == 0.0` means "unknown" and is excluded when `date_from` is set
  (`suggestion_engine.py:88-93`, unchanged).
- The `st_birthtime > 0` guard matters: some filesystems report `st_birthtime == 0` ("unknown
  birth"); treating that as a miss lets the chain fall through to a usable value.

### D3 — Drop the carry-forward; read creation time fresh each sync

ADR-011 froze `date_added` as a first-seen-in-cache value because "first seen" is **observation
state** — it only has meaning relative to when the cache first saw the track, so it must be pinned.

Creation time is **not** observation state. It is an **intrinsic property of the file** read
directly from the filesystem on every sync. Freezing an intrinsic, re-readable value adds
complexity for no benefit and actively causes drift: a frozen value can disagree with the file's
real creation time forever after.

Therefore **the carry-forward is dropped.** `date_added` reflects the file's creation time read
**fresh on every sync**. Concretely:

- Remove the carry-forward block in `parse_all_crates` (`crate_parser.py:231-238`).
- Remove the `previous_tracks` parameter from `parse_all_crates` (`crate_parser.py:178`, `:186-189`)
  and stop threading it from `crate_sync._run()` (`crate_sync.py:24-25`, `:29`). `crate_sync` no
  longer needs to `load_cache()` purely to feed carry-forward (it still may load for future smart
  invalidation, but that is out of scope — remove the now-dead load for this feature).

**The real-world trade-off (documented, accepted):** copying or re-downloading a track resets its
filesystem creation time, so `date_added` will jump to the copy date on the next sync. The user's
phrasing — *"based on the created date time of the file on my computer"* — describes exactly this:
the date of the file as it exists on their machine, read fresh. A DJ who re-downloads a track is, in
practice, re-acquiring it, so surfacing it as "recently added" is defensible and matches the user's
mental model. The alternative (carry-forward / pinned) would keep showing the original date and
**ignore** the user's machine state, which is the opposite of what they asked for.

> Trade-off summary: **fresh read** = tracks the file as it is on disk now (what the user asked for),
> but a re-copied file looks "newly added." **Carry-forward** = stable once seen, but diverges from
> the actual file and contradicts the request. We choose **fresh read**.

### D4 — Cache migration: bump `CACHE_VERSION` 2 → 3

Existing v2 caches hold mtime-based `date_added` values that are now semantically wrong (mtime, not
creation time) and — with carry-forward dropped — would otherwise never be re-seeded for unchanged
tracks. Per ADR-007's versioning mechanism, bump `CACHE_VERSION` from `2` to `3` (`cache.py:16`).
A version mismatch makes `load_cache` return `None` (`cache.py:70-76`), which the app treats as
"no cache" and triggers one **self-healing re-sync** on upgrade. After that sync every track carries
a fresh creation-time `date_added`.

This bump is correct under **both** halves of D3: it discards the stale frozen mtime values that
carry-forward used to preserve, and it guarantees the first post-upgrade sync re-seeds everything
from creation time. No bespoke migration code is needed — this is the documented ADR-007 pattern.

### D5 — Field name unchanged; semantic note added

`date_added` is referenced widely (`Track` dataclass `:21`, `from_dict` `:109-153`, cache dicts,
the engine filter `suggestion_engine.py:88-93`, the filter bar/date control, ADR-011/overview docs).
Renaming it (e.g. to `creation_time`) would ripple across the model, cache, engine, and UI for **no
functional gain**. The field name **stays `date_added`**.

However the field's **meaning shifts**: from "first time this app saw the track (mtime-seeded,
frozen)" to "the file's creation time on this machine (read fresh)." This semantic shift is recorded
in:
- the `Track.date_added` field comment / docstring (`source/models/track.py:21`),
- the `get_track_metadata` seed comment (replacing `crate_parser.py:85-88`),
- ADR-013 and the updated ADR-011 cross-reference,
- the architecture-overview `date_added` row (`docs/architecture-overview.md:47`, `:100`).

The honest-caveat UI copy from ADR-011 ("Dates are approximate for tracks added before your first
sync") is **no longer accurate** under creation-time sourcing and should be revisited — but that is
**UI Designer territory**, flagged as an open question below, not implemented here.

---

## 4. Affected files

| File | Change | Citation |
|------|--------|----------|
| `source/services/file_times.py` | **New** leaf module: `file_creation_time(path) -> float \| None` with the D2 fallback chain. | new |
| `source/services/crate_parser.py` | Replace mtime seed with `file_creation_time(...)`; update seed comment; drop carry-forward block and `previous_tracks` param. | `:14`(import), `:85-93`, `:108`, `:159`, `:174-189`, `:231-238` |
| `source/services/crate_sync.py` | Stop loading prior cache for carry-forward; drop `previous_tracks` arg from the `parse_all_crates` call. | `:4`, `:18-30` |
| `source/services/cache.py` | Bump `CACHE_VERSION` 2 → 3. | `:16` |
| `source/models/track.py` | Update `date_added` field comment to the new semantic (no logic change; `from_dict` already reads it). | `:21` |
| `docs/architecture-decisions.md` | Add **ADR-013**; mark ADR-011 Decision B as superseded-in-part; update ADR-007 schema-history block (add v3). | — |
| `docs/architecture-overview.md` | Update the `date_added` row and the cache-schema paragraph. | `:47`, `:100` |
| `docs/cross-platform-guide.md` | Add a "File creation time" section documenting the helper and the 3.11-vs-3.12 Windows `st_birthtime` constraint. | — |
| `tests/services/test_file_times.py` | **New** unit tests for the fallback chain (mock `os.stat` / `sys.platform`). | new |

**Not changed:** the date filter UI (`filter_bar.py`'s `DateRangeControl`), `suggestion_engine.py`
(the `date_from`/`date_to` window logic and the `0.0`-excluded rule are unchanged), the
`SuggestionFilters` value object (ADR-012), `Track.from_dict` parsing (it already coerces
`date_added`, `track.py:109-153`).

---

## 5. Phases (one-at-a-time execution)

1. **Phase 1 — Helper.** Add `source/services/file_times.py` + `tests/services/test_file_times.py`.
   Pure, no integration. Lands and is verifiable in isolation.
2. **Phase 2 — Seed swap.** Wire `file_creation_time` into `get_track_metadata`
   (`crate_parser.py:85-93`, `:108`, `:159`). Behaviour now reads creation time; carry-forward still
   present (harmless — it would still freeze, but the seed source is correct).
3. **Phase 3 — Drop carry-forward.** Remove the carry-forward block and `previous_tracks` plumbing
   from `crate_parser.parse_all_crates` and `crate_sync._run()`. `date_added` now reads fresh.
4. **Phase 4 — Cache bump.** `CACHE_VERSION` 2 → 3 (`cache.py:16`). Forces the self-healing re-sync.
5. **Phase 5 — Docs.** ADR-013 commit, ADR-011/ADR-007 amendments, overview + cross-platform-guide
   updates, `Track.date_added` comment.

Phases 2–4 each individually leave the app runnable; the cleanest single shippable unit is 2+3+4
together (so users don't get an interim state where the bump hasn't happened). Phase 1 and Phase 5
bracket them.

---

## 6. Risks & open questions

- **R1 — Windows `st_ctime` semantic on 3.11.** Correctly handled: on Windows `st_ctime` *is*
  creation time, and the helper only falls through to it after the `st_birthtime` check (which is
  absent on Windows 3.11). When the bundled interpreter moves to 3.12+, `st_birthtime` transparently
  takes precedence — no code change needed. Locked by a unit test that asserts the Windows-3.11
  branch returns `st_ctime`.
- **R2 — Re-copied/re-downloaded files look "newly added."** Accepted, by D3. This is the direct
  consequence of fresh-read and matches the user's request. Documented in ADR-013 consequences.
- **R3 — Forced re-sync on upgrade.** One self-healing re-sync per existing user on the v2→v3 bump
  (ADR-007 R3 pattern). Accepted; sync is fast and user-initiated.
- **R4 — Linux dev machines get mtime, not creation time.** Accepted: Linux is not a shipping
  target. The helper degrades to mtime so dev runs stay functional without crashing or claiming
  false accuracy. Documented in `cross-platform-guide.md`.
- **R5 — Stale UI caveat copy.** ADR-011's "approximate for tracks added before your first sync"
  copy in the date panel is no longer accurate under creation-time sourcing. **Open question for the
  UI Designer** — out of scope for this backend change; flagged, not touched here.
- **Open question — future Serato `database V2` add-date.** Still the truest "when I added it to my
  library" source, still out of scope (undocumented binary format). Revisit only on request.
