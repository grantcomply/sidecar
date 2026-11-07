# Testing Strategy — Sidecar

> Maintained by the Architect agent. Defines what to test, how to test, and coverage goals.

## Current State

**Broad unit suite in place.** `tests/` covers the services (Camelot, engine, filters, comment format, tag reader, file times, sync, store, merge, watcher, settings migration and view-model, sync outcome, copy, diagnostics, log safety), both providers and their contract, the models, config provider settings, and the key UI wiring (filter dropdowns, settings dialog, sync wiring, session rebind, quiet suggestion refresh, empty states, the copy button and clipboard). Run everything with `python -m pytest`; every phase of a feature ends green.

## Test Framework

- **Runner:** pytest
- **Structure:** `tests/` mirrors `source/` (`tests/services/`, `tests/providers/`, `tests/providers/rekordbox/`, `tests/models/`, `tests/ui/`)
- **Shared fixtures:** `tests/conftest.py` (e.g. an isolated user data dir, `make_track`), `tests/providers/rekordbox/conftest.py`, `tests/ui/conftest.py` (`tk_root`, below)

## Ground rules

1. **Synthetic data only.** Never copy titles, artists, file paths or comments from a real library, a spike report or a diagnostics report into code, fixtures or docs. Use invented names (`Artist A - Track 1.mp3`) under `tmp_path`.
2. **Never touch real DJ-software files.** Tests must not read the real `_Serato_` folder or the real rekordbox `master.db`. Use the fixtures below and `tmp_path`.
3. **No real key, ever.** Key-safety tests use the constant `SYNTHETIC_KEY` (`tests/providers/rekordbox/fakes.py`). Never paste a real or partial rekordbox key into a test, fixture, comment or doc.
4. **Isolated data dir.** Anything that touches `config.user_data_dir()` (snapshots, settings, diagnostics reports, the data-dir migration) must patch it to `tmp_path`.
5. **Pure logic first.** Decisions live in pure functions (`should_refresh`, `record_refresh_result`, `merge_records`, `sync_outcome`, `library_copy`, `build_provider_views`, `migrate_settings`, `resolve_track_path`). Test them directly with injected clocks and values; don't sleep.

## Fixture conventions

| Fixture | Use |
|---------|-----|
| `tests/fixtures/crate_bytes.py` | Builds Serato `.crate` binary content in memory (UTF-16BE track paths). Write the bytes into `tmp_path` to make a fake `Subcrates` folder. No binary fixture files are committed. |
| `tests/providers/rekordbox/fakes.py` | A fake `MasterDatabase` (content rows, playlist rows, playlist-song rows, `session.execute` for `PRAGMA quick_check`) plus `SYNTHETIC_KEY`. Injected through `RekordboxProvider(db_factory=…)` / `db_reader.read_library(..., db_factory=…)`, so tests never need pyrekordbox to open a real DB. |
| `RekordboxProvider(exists=…, energy_reader=…, energy_cache=…, tmp_root=…)` | Test seams for file existence, tag energy, the memo cache and the temp-copy root. |
| `LibraryWatcher(clock=…)` and `.tick()` | Deterministic watcher tests with no thread or sleep. |
| `SyncCoordinator(runner=…)` | Run syncs synchronously or hold them open to test coalescing. |
| `tk_root` (`tests/ui/conftest.py`) | A withdrawn live Tk root, shared by `tests/ui/`. **Skips cleanly** when Tk can't start (no display). Tk callback exceptions are collected on `root.callback_errors` instead of printed, so a test can assert `tk_root.callback_errors == []` after pumping timers. Teardown destroys the root and clears `CopyButton._flashing`, so the one-flash-at-a-time reference never leaks between tests. Modules that define their own `tk_root` (e.g. `test_suggestion_quiet.py`) keep theirs; new UI tests should use the shared one. |

## What must be tested (provider feature, ADR-015)

### Provider contract (`tests/providers/test_contract.py`)
Parametrised over **every registered provider**, so a new provider is checked automatically:
- satisfies the `LibraryProvider` protocol; ids unique and lowercase; `env_key`s unique across providers;
- `default_settings()` keys ⊆ `setting_specs()` keys; `crate_noun` set; every FILE/DIRECTORY spec has a `browse_title`;
- **capability rules:** without `CHANGE_DETECTION`, `change_token()` returns `None`; without `DECK_LOAD`, `load_to_deck()` raises `DeckLoadNotSupported`;
- `detected_values()` returns only known setting keys.

`tests/providers/test_base_isolation.py` checks, in a fresh interpreter, that importing `providers/base.py` loads no provider, parser or mutagen.

### Golden equivalence (`tests/services/test_serato_equivalence.py`)
The Serato provider's output must equal the pre-refactor parse for the same `.crate` fixtures, including colliding labels and an empty folder. A converted legacy v3 cache must load the same library as a fresh sync. **Keep these green for any Serato change.**

### rekordbox (`tests/providers/rekordbox/`)
- `test_paths.py`: path resolution order (including `/contents_…`, UNC, missing files), `is_master_db`, the change token (with absent files and without `-shm`).
- `test_db_copy.py`: no `-shm` copied; retries when the token moves; "busy" after the attempts run out; cleanup on failure; stale-copy cleanup touches only `sidecar-rb-*`.
- `test_db_reader.py`: mapping from fake rows, soft-deleted rows, folders vs playlists, smart playlists skipped with a warning, `quick_check` failure → `CopyIntegrityError`, close/dispose always called. **Key-safety tests:** a factory or read error whose message contains `SYNTHETIC_KEY` never reaches the raised error's text, `__cause__`/`__context__`, or any captured log record.
- `test_mapping.py`, `test_energy_cache.py`, `test_rekordbox_provider.py`: field mapping (BPM ×100, key → Camelot, year 0 → `""`), energy order (comment → tag → 0), memo hits keyed by mtime and size, snapshot warnings, capabilities following `auto_refresh`.

### Key and log safety (`tests/services/test_log_safety.py`)
Minimum levels (pyrekordbox ERROR, sqlalchemy WARNING); child loggers are raised; a DEBUG record carrying the key is never recorded even with the root at DEBUG; stricter preset levels are not lowered; `_ensure_pyrekordbox` pins the loggers. **Any change to `log_safety.py` or the `db_reader` error boundary must keep these green.**

### Store, merge, sync, migration
- `test_library_store.py`: atomic writes, unchanged content → metadata-only write, schema/provider mismatch → `None`, legacy v3 conversion leaves the source file untouched, orphan temp cleanup.
- `test_library_merge.py`: same path in two snapshots → one track; `crates` union; `sources` order; rekordbox wins per non-empty field with Serato fallback; **`key`/`camelot_key` taken as a pair**; **native `play_count` wins even at 0**; separator, case (Windows) and NFC/NFD variants merge; crate filter admits a track through either provider's crate.
- `test_library_sync.py`: one provider failing doesn't stop the others and leaves its old snapshot intact; coordinator coalescing and silent/manual upgrade.
- `test_settings_migration.py`, `tests/test_config_providers.py`: existing vs fresh install, idempotence, backup once, nothing deleted, atomic combined save, CR/LF stripped.
- `tests/test_config_migration.py` (task T5.6): `SeratoSidecar` → `DJSidecar` copy-forward, with per-name data dirs under `tmp_path`. Cases: the copy happens; the legacy dir is left intact; the legacy cache is copied only without `library/`; no copy when the new dir already has settings; idempotent and once per process; the skip env var works; an `OSError` only warns. `tests/conftest.py` sets `SIDECAR_SKIP_DATA_DIR_MIGRATION` **before** `source.config` is imported, so no test can ever copy the real user's data. Keep it that way.

### Live refresh (`tests/services/test_library_watcher.py`)
Pure `should_refresh`: no token / same token; settle window; minimum interval; focus bypasses settle but honours the 30 s floor. `record_refresh_result`: backoff doubles every 3 unchanged refreshes up to the max; change or manual resets. Watcher: first tick uses the stored baseline; disabled providers are forgotten; a provider raising doesn't stop the others; `stop()` returns promptly.

### UI and app wiring (`tests/ui/`)
Smoke and behaviour tests that construct real CTk widgets (skipped without a display): settings dialog (staged edits, Save/Cancel, no provider branching), filter dropdown groups, search and `Select shown`/`Clear shown`, `preserve_selection`, app sync wiring, session rebind, quiet suggestion re-render, empty-library states. Keep UI decisions in pure modules (`library_copy`, `settings_model`, `sync_outcome`) so most of the behaviour is tested without Tk.

### Copy search text (ADR-016)
- `tests/services/test_paste_query.py`: every row of the blueprint D1 worked-examples table; shape (artist + title joined by one space, title only, artist only, all empty or whitespace → `None`, no hyphen added); whitespace and control characters collapse; case and accents kept; title stripping (balanced, nested and multiple brackets, `feat.`/`ft`/`featuring` tails in either order with brackets, unmatched opening bracket, stray closing bracket becomes a space, fallback when stripping leaves nothing, `Aftermath`/`Left Feather` untouched); artist stripping with collaborations (`&`, `,`, `x`, `vs.`) kept; separators trimmed at the ends but kept between words; the file-stem fallback (stripped, no artist prefix, only the last extension removed); deep nesting returns quickly.
- `tests/services/test_library_copy.py` (extended): toast truncation to exactly 75 characters with the 66/67 boundary; `COPY_FAILED` fits the toast; none of the copy strings uses an avoided word such as "Load"; both tooltips carry the exact, untruncated query as their second line; the four `BUTTON_*` glyphs are single, distinct BMP characters.
- `tests/ui/test_clipboard.py`: round trip through Tk's clipboard (this reads Tk's own copy, not the OS clipboard; the OS side is manual check M1); a second copy replaces the first; a `TclError` returns `False` and logs one WARNING that doesn't contain the text.
- `tests/ui/test_app_copy_track.py` (stub `self`, no window): success copies `paste_query` output and shows one green toast; stripped text reaches clipboard and toast; a stale row copies the library's current object; a track gone from the library copies the row's object; clipboard failure → red `COPY_FAILED`, returns `False`; `None` query → no clipboard call, no toast; no calls to the setlist, dashboard or suggestion panel.
- `tests/ui/test_suggestion_copy.py` (live root): a copy click calls `on_copy` without selecting or re-rendering, and doesn't stop a playing preview; a real pointer click on the button never reaches the row's select handler; no `on_copy` → failed state; the button is at grid column 0 and the score at column 1; the first header is `HEADER_COPY` at the copy width; a track with nothing to copy has a disabled button that still has its `COPY_NOTHING` tooltip; the ready tooltip previews the exact stripped query; glyphs and tooltips follow ready → copied/failed → ready; copied and failed hover with their own fill, ready hover paints the accent fill; a click hides the tooltip; rapid clicks restart the timer; only one button flashes at a time (including a failed flash); a re-render that destroys a flashing button leaves no stale timer or reference; destroy cancels a pending tooltip show. Tests compare against the `library_copy` constants, never literal glyphs, and shorten the 1.5 s timer by monkeypatching `COPY_FEEDBACK_MS`.
- `tests/ui/test_tooltip_hide.py`: public `Tooltip.hide()` cancels a pending show, destroys a shown tip, is harmless with nothing shown; scheduling twice keeps one pending show.

### Earlier priorities (still valid)
- `camelot.py` and `suggestion_engine.py`: tiers, symmetry (ADR-010 R2), key offset (ADR-011), filters (ADR-012).
- `comment_format.py`: `"4A - 7 - Banger - Fat Bass Vocal"`, partial (`"4A - 7"`, `"4A"`, `""`), malformed energy, unknown categories, free text.
- `crate_parser.py` with `crate_bytes.py` fixtures.

## Gaps to close

- **Import-boundary test** (recommended): an AST scan of `source/` asserting that (a) only `providers/registry.py` imports `providers.serato`/`providers.rekordbox` modules (allow-list: `services/diagnostics.py` → `providers.rekordbox.paths`), and (b) only `providers/rekordbox/db_reader.py` imports `pyrekordbox` or `sqlalchemy`.
- **Deck-load gate:** covered by `tests/ui/test_app_deck_load_gate.py` (`None` with the real providers; a fake `DECK_LOAD` provider is returned only when enabled and present in `sources`).
- **Manual-only checks** (record results in the plan): frozen build `--self-check-rekordbox` and `--check-rekordbox-library` on Windows; upgrade from v0.1.6 (settings and library preserved, no duplicate shortcuts); editing in rekordbox while Sidecar is open (refresh appears quietly); the 1000x650 window minimum and 150% scaling.

### Manual checklist: copy search text (ADR-016)
Tk's own clipboard is all the automated tests can see. Pasting into another app, timing, scaling and macOS need these manual checks. Full wording and pass criteria: `plans/copy-track-search-text-2026-11/implementation-plan.md` T3.6.

**Status:** M1-M10 and M13-M16 were accepted by the user on Windows; per-check results not recorded. M11 and M12 are **unverified**. Gate G (glyph render at CustomTkinter scaling 100% and 150%) passed on 2026-11-06. A synthetic render at 1000x650 shows the Copy and Key columns visible, with BPM's cells under the scrollbar (M8).

| # | Check | Status |
|---|---|---|
| M1 | Copy a suggestion, paste into rekordbox's search; the track is in the results | Accepted (Windows); not itemised |
| M2 | Same, pasting within half a second (the no-`update()` decision) | Accepted (Windows); not itemised |
| M3 | Same as M1 in Serato DJ | Accepted (Windows); not itemised |
| M4 | Copy, close Sidecar, paste into Notepad | Accepted (Windows); not itemised |
| M5 | Copy while a preview plays: preview continues, row not selected, setlist unchanged | Accepted (Windows); not itemised |
| M6 | Copy, then move the pointer back over the row: no selection, no rebuild flicker | Accepted (Windows); not itemised |
| M7 | Copy two tracks quickly: second toast replaces the first, clipboard holds the second, only the second row flashes | Accepted (Windows); not itemised |
| M8 | 1000x650 at several sash positions: Copy column always visible | Accepted (Windows); synthetic render: Copy and Key visible, BPM under the scrollbar |
| M9 | Accented, CJK and emoji characters: record what pastes | Accepted (Windows); not itemised |
| M10 | A title with `(Extended Mix)` and `feat. X`: toast and paste show the stripped query | Accepted (Windows); not itemised |
| M11 | Real Windows 150% display scaling: glyphs fit 36 x 28, header fits, rows don't grow | **Unverified** |
| M12 | macOS: M1 and M4 with rekordbox or Serato for Mac | **Unverified** |
| M13 | Five clicks in a second: stays copied, reverts about 1.5 s after the last, no blue flicker | Accepted (Windows); not itemised |
| M14 | Hover for the tooltip, then click: tooltip disappears and stays hidden until re-entry | Accepted (Windows); not itemised |
| M15 | Hover two rows' buttons: each tooltip previews its own row's text | Accepted (Windows); not itemised |
| M16 | Force a failed copy: red failed state and red toast; the next good copy recovers | Accepted (Windows); not itemised |

Re-run M1-M3 after any change to `paste_query`, `ui/clipboard.py` or the Tk version, and record results per check next time.

## Test Naming Convention

```python
def test_<function>_<scenario>_<expected_result>():
    """Example: test_classify_adjacent_number_same_letter_returns_adjacent"""
```

## Running Tests

```bash
# All tests
python -m pytest

# Specific module
python -m pytest tests/services/test_camelot.py

# With coverage
python -m pytest --cov=source --cov-report=term-missing
```

## Coverage Goals

| Area | Target |
|------|--------|
| `services/` (pure logic) | 90%+ |
| `providers/` | 90%+ (`db_reader` via fakes) |
| `models/` | 80%+ |
| Overall | 70%+ |
