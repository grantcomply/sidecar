# Implementation Plan — `date_added` from File Creation Time

> Companion to `architect-blueprint.md`. Ordered, phased, one task at a time.
> Each task cites `file:line`. No UI work — the date filter UI is unchanged.
> Cache moves to `CACHE_VERSION = 3`, forcing one self-healing re-sync on upgrade (ADR-007).

---

## Phase 1 — Creation-time helper (pure, isolated)

### Task 1.1 — Add `source/services/file_times.py`

Create a new dependency-free leaf module (only `os`, `sys`, `pathlib`; no project imports — same
pattern as `harmonic_tier.py`). Define:

```python
def file_creation_time(path: str | Path) -> float | None:
    """Return the file's creation time as a Unix timestamp, or None if it can't be read.

    Fallback chain (first hit wins):
      1. os.stat(path); OSError -> None
      2. st_birthtime, if present and > 0   (macOS all versions; Windows on Python 3.12+)
      3. st_ctime, if sys.platform == "win32"  (Windows on 3.11: st_ctime IS creation time)
      4. st_mtime                            (Linux/other dev machines — best available)
    """
```

Implementation notes:
- Guard `st_birthtime` with `getattr(st, "st_birthtime", None)` (attribute is absent on Windows
  3.11) **and** `> 0` (some filesystems report 0 = "unknown birth"; fall through if so).
- Catch `OSError` from `os.stat` only; return `None`. Do **not** substitute sync-time here — the
  caller owns that policy (keeps the helper a pure stat-reader).
- Type hint `float | None`; full docstring per `docs/coding-standards.md`.

### Task 1.2 — Add `tests/services/test_file_times.py`

Unit tests mocking `os.stat` and `sys.platform`. Mirror source structure
(`docs/coding-standards.md`: `tests/services/test_file_times.py`). Cases:

- macOS-style stat (has `st_birthtime > 0`) → returns `st_birthtime`, regardless of platform string.
- `st_birthtime == 0` present → falls through (does **not** return 0).
- Windows + no `st_birthtime` (3.11 sim) → returns `st_ctime`.
- Windows + `st_birthtime > 0` (3.12 sim) → returns `st_birthtime` (prefers it over ctime).
- Linux (`sys.platform == "linux"`, no usable `st_birthtime`) → returns `st_mtime`.
- `os.stat` raises `OSError` → returns `None`.

---

## Phase 2 — Swap the seed source in the parser

### Task 2.1 — Import the helper

`source/services/crate_parser.py:14` — add `from source.services.file_times import file_creation_time`
to the local-imports group (after the existing `from source.services.camelot import parse_camelot`).

### Task 2.2 — Replace the mtime seed in `get_track_metadata`

`source/services/crate_parser.py:85-93`. Replace the mtime block and its comment:

- Old: `date_added = Path(path).stat().st_mtime` inside `try/except OSError`, with the
  mtime-rationale comment at `:85-88`.
- New: `ct = file_creation_time(path)`; `date_added = ct if ct is not None else 0.0`.
  (Keeps the existing "`0.0` = unknown" contract that `suggestion_engine.py:88-93` relies on; the
  helper already swallows `OSError`, so no local try/except is needed.)
- New comment: `date_added` is the file's **creation time** (cross-platform via `file_times`); read
  fresh each sync (no carry-forward). Reference ADR-013 and `cross-platform-guide.md`.

The two emission sites (`crate_parser.py:108` empty dict, `:159` populated dict) keep using the
local `date_added` variable — no change needed there beyond the variable now holding creation time.

> After Phase 2 the seed source is correct. Carry-forward (Phase 3) is still present but now merely
> re-freezes a creation-time value; harmless interim state, app fully runnable.

---

## Phase 3 — Drop the carry-forward (read fresh each sync)

### Task 3.1 — Remove the carry-forward block in `parse_all_crates`

`source/services/crate_parser.py:231-238`. Delete the `if previous_tracks:` carry-forward block (the
`prev = previous_tracks.get(absolute_path)` / `if prev and prev.get("date_added"):` logic). The
freshly-seeded creation-time value from `get_track_metadata` is now used as-is.

### Task 3.2 — Remove the `previous_tracks` parameter

`source/services/crate_parser.py:178` (signature) and `:186-189` (docstring Args entry). Remove the
`previous_tracks: dict[str, dict] | None = None` parameter and its docstring paragraph. Keep the
`progress_callback` parameter.

### Task 3.3 — Stop threading `previous_tracks` from `crate_sync`

`source/services/crate_sync.py`:
- `:24-25` — remove the `prev = load_cache()` / `previous_tracks = (prev or {}).get("tracks", {})`
  lines (the load existed only to feed carry-forward; not needed for this feature).
- `:26-30` — remove the `previous_tracks=previous_tracks` argument from the `parse_all_crates(...)`
  call.
- `:4` — remove `load_cache` from the `from source.services.cache import load_cache, save_cache`
  import; keep `save_cache`.
- Remove the now-stale carry-forward comment at `:20-23`.

> After Phase 3, `date_added` reflects creation time read fresh on every sync.

---

## Phase 4 — Cache migration (force one self-healing re-sync)

### Task 4.1 — Bump `CACHE_VERSION`

`source/services/cache.py:16` — change `CACHE_VERSION = 2` to `CACHE_VERSION = 3`. No other code
change: `load_cache` already returns `None` on version mismatch (`cache.py:70-76`), which the app
treats as "no cache" and re-syncs. This discards stale v2 mtime-based `date_added` values and
re-seeds every track from creation time on the first post-upgrade sync (ADR-007 mechanism).

---

## Phase 5 — Documentation

### Task 5.1 — Model field comment

`source/models/track.py:21` — update the `date_added: float = 0.0` comment to state the new
semantic: "file creation time (Unix timestamp), read fresh each sync; `0.0` = unknown. See ADR-013."
No logic change (`from_dict` at `:109-153` already coerces the value).

### Task 5.2 — Add ADR-013

`docs/architecture-decisions.md` — append **ADR-013: `date_added` sourced from file creation time
(supersedes ADR-011 Decision B)**. Use the standard ADR template. Capture:
- Status: Accepted; Date: 2026-05-31; Supersedes: ADR-011 Decision B (date_added source).
- Context: user's explicit request to reverse; why acceptable now (Win+macOS-only installers per
  ADR-008 / `cross-platform-guide.md`; creation time obtainable on both).
- Decision D1–D5 from the blueprint: source reversal, the `file_times` helper + fallback chain
  (incl. the Python 3.11 `st_birthtime`-absent-on-Windows constraint), carry-forward dropped /
  read-fresh, `CACHE_VERSION` 2→3, field name retained with semantic shift noted.
- Consequences incl. R2 (re-copied files look newly added — accepted) and the stale UI-caveat
  open question routed to the UI Designer.

### Task 5.3 — Amend ADR-011 and ADR-007

`docs/architecture-decisions.md`:
- ADR-011 — add a "Superseded in part by ADR-013" note on the **Status** line, and a one-line marker
  at the head of Decision B (`:328`) pointing to ADR-013 for the date_added source. Leave the
  Decision A (key offset) text intact.
- ADR-007 — extend the "Schema version history" block (`:153-157`) with a **v3** entry: "(ADR-013,
  2026-05-31) — `date_added` re-sourced from file **creation time**, read fresh each sync (no
  carry-forward). `CACHE_VERSION` is now `3`; the bump forces one self-healing re-sync that drops
  stale v2 mtime values." Update the JSON example's `date_added` comment if one is present.

### Task 5.4 — Update architecture overview

`docs/architecture-overview.md`:
- `:47` — `Track` row: change "first-seen-in-cache time … seeded from file `mtime` … carried
  forward" to "the file's **creation time** (Unix timestamp), read fresh each sync. See ADR-013."
- `:100` — cache-schema paragraph: drop the "injects previous cache tracks … carried forward"
  sentence; state that `date_added` is read fresh from creation time each sync and the
  `CACHE_VERSION` 2→3 bump forces a one-time self-healing re-sync. Note schema is now v3.

### Task 5.5 — Add cross-platform-guide section

`docs/cross-platform-guide.md` — add a new "## File creation time" section documenting:
- the per-platform source table (macOS `st_birthtime`; Windows `st_ctime` on 3.11, `st_birthtime`
  on 3.12+; Linux mtime fallback / dev-only),
- the Python 3.11-vs-3.12 `st_birthtime`-on-Windows constraint as the reason the helper exists,
- a pointer to `source/services/file_times.file_creation_time`.

---

## Execution order summary

| # | Task | File(s) | Citation |
|---|------|---------|----------|
| 1.1 | New helper module | `source/services/file_times.py` | new |
| 1.2 | Helper unit tests | `tests/services/test_file_times.py` | new |
| 2.1 | Import helper | `crate_parser.py` | `:14` |
| 2.2 | Swap mtime → creation-time seed | `crate_parser.py` | `:85-93`, `:108`, `:159` |
| 3.1 | Remove carry-forward block | `crate_parser.py` | `:231-238` |
| 3.2 | Remove `previous_tracks` param | `crate_parser.py` | `:178`, `:186-189` |
| 3.3 | Drop carry-forward plumbing | `crate_sync.py` | `:4`, `:18-30` |
| 4.1 | Bump `CACHE_VERSION` 2→3 | `cache.py` | `:16` |
| 5.1 | Field semantic comment | `models/track.py` | `:21` |
| 5.2 | Add ADR-013 | `docs/architecture-decisions.md` | append |
| 5.3 | Amend ADR-011 + ADR-007 | `docs/architecture-decisions.md` | `:304`, `:328`, `:153-157` |
| 5.4 | Update overview | `docs/architecture-overview.md` | `:47`, `:100` |
| 5.5 | Cross-platform-guide section | `docs/cross-platform-guide.md` | append |

**Verification:** after Phase 4, delete (or version-mismatch) the local `track_cache.json`, run a
sync, and confirm `date_added` for a known file matches its OS-reported creation time (Windows: file
Properties → Created; macOS: `stat -f %B`). Run `pytest tests/services/test_file_times.py`.
