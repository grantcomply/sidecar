# Architecture Overview — Sidecar

> **Status:** Reviewed — architectural assessment complete
> **Last updated:** 2026-11-05 (ADR-015 — DJ library providers: rekordbox + Serato)

## System Purpose

Sidecar (formerly "Serato Sidecar") is a desktop companion app for DJs. It reads the user's DJ library from **Serato DJ** (crate files), **rekordbox** (its `master.db` database), or both, merges them into one in-memory library, and suggests harmonically compatible next tracks using a weighted scoring algorithm. It never writes to any DJ software's files.

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ main.py  logging + log_safety, CLI diagnostics, migrations   │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│ app.py  (application controller)                             │
│  layout · event wiring · SyncCoordinator · LibraryWatcher    │
│  reload (merge of stored snapshots) · toasts · settings      │
└──┬──────────────┬─────────────────────────┬──────────────────┘
   │              │                         │
   ▼              ▼                         ▼
┌────────┐ ┌──────────────────────────┐ ┌──────────────────────┐
│ Models │ │ Services                 │ │ UI                   │
│ Track  │ │ library_sync / _store /  │ │ Dashboard            │
│ Library│ │ _merge / _watcher        │ │ Suggestions + filters│
│ path_  │ │ settings_migration/model │ │ Session              │
│identity│ │ sync_outcome, copy       │ │ Settings dialog      │
│        │ │ suggestion engine, ...   │ │ Tooltip, utils       │
└────────┘ └───────────┬──────────────┘ └──────────────────────┘
                       │ (via registry only)
             ┌─────────▼──────────────────────────┐
             │ Providers  (source/providers/)      │
             │ base.py contract · registry.py      │
             │ serato/   rekordbox/                │
             └─────────┬──────────────────────────┘
                       │ uses leaf helpers only
             tag_reader · camelot · file_times · comment_format · log_safety · crate_parser
```

**Layering:** `ui → app → services (library_sync / store / merge / watcher, settings_*) → providers (via registry) → services leaf helpers`. `providers/base.py` and `models/path_identity.py` are stdlib-only leaves that any layer may import. One accepted exception: `services/diagnostics.py` imports `providers.rekordbox.paths` (ADR-015, "Accepted layering exception").

## Layer Responsibilities

### Models (`models/`)
Pure data structures and collections. No UI knowledge and no service dependencies.

| Component | Responsibility |
|-----------|---------------|
| `track.py` | `Track` dataclass. `crates` holds crate **ids** (ADR-015 D3). `sources` is the ordered tuple of provider ids that contain the file; it is set by the merge and never stored. `date_added` is the file's **creation time**, read fresh on every sync; `0.0` = unknown (ADR-013). |
| `library.py` | `TrackLibrary`: tracks keyed by `path_key`, `replace_all(tracks, crates)`, `track_by_path`, a crate index (`crate_label`, `crate_provider`, `crate_items` sorted case-insensitively by folder path), genres and search. |
| `path_identity.py` | `path_key(p)` = NFC(normcase(normpath(p))). The only file identity in the app (ADR-015 D6). Leaf module. |

### Providers (`providers/`) — new in ADR-015
The only place that knows about specific DJ software. Nothing outside this package imports a concrete provider, except `registry.py` (and the accepted diagnostics exception).

| Component | Responsibility |
|-----------|---------------|
| `base.py` | The contract: `LibraryProvider` protocol, `ProviderSnapshot`, `CrateInfo`, `TrackRecord`, `SettingSpec`/`SettingKind`, `ProviderCapability`, `ProviderIssue`, `ProviderError`, `DeckLoadNotSupported`. Stdlib only. |
| `registry.py` | `PROVIDERS` in precedence order (rekordbox, then serato), `get_provider`, `all_providers`, `first_deck_load_provider` (the deck-load gate; always `None` today). |
| `serato/provider.py` | `SeratoProvider`: reads `_Serato_/Subcrates` through `crate_parser` and `tag_reader`. Crate id `serato:<stem>`. No change detection, no deck load. |
| `rekordbox/provider.py` | `RekordboxProvider`: copies, reads and maps the database into a snapshot. Declares `CHANGE_DETECTION` while auto-update is on. |
| `rekordbox/paths.py` | Default DB location per OS, `resolve_db_path`, the stat-only change token (`master.db` + `-wal`), and track path resolution (`OrgFolderPath` first). Pure. |
| `rekordbox/db_copy.py` | Private temp copy of `master.db` (+ `-wal`, `-journal`, `masterPlaylists6.xml`; **never `-shm`**), torn-copy guard, stale-copy cleanup. Stdlib only. |
| `rekordbox/db_reader.py` | **The only module that imports `pyrekordbox`/SQLAlchemy** (lazily). Opens the copy, reads tracks and playlists, closes. Fixed-text errors (key safety). |
| `rekordbox/mapping.py` | Pure `RbTrack → TrackRecord`. |
| `rekordbox/energy_cache.py` | Thread-safe memo of file-tag energy keyed by `(path_key, mtime_ns, size)`. |

### Services (`services/`)
Business logic and orchestration. No UI imports.

| Component | Responsibility |
|-----------|---------------|
| `library_sync.py` | Background sync across the requested providers (sequential, one daemon thread) → `SyncReport`. `SyncCoordinator`: single-flight, coalesces requests that arrive during a run. Replaces `crate_sync.py`. |
| `library_store.py` | Per-provider snapshots `library/<provider>.json` (schema v4) + `<provider>.meta.json`; atomic writes; `content_hash` no-op detection; read-only v3 `track_cache.json` → `serato.json` converter. Replaces `cache.py`. |
| `library_merge.py` | Pure merge of snapshots in precedence order (rekordbox wins per non-empty field; `key`/`camelot_key` as a pair; native `play_count` wins even at 0). |
| `library_watcher.py` | Live refresh: polls change tokens (10 s poll, 5 s settle, ≥ 60 s interval, adaptive backoff to 300 s, focus refresh with a 30 s floor). Pure `should_refresh` / `record_refresh_result`. No Tk. |
| `settings_migration.py` | One-time startup migration to settings schema 2 (`PROVIDERS_ENABLED`), legacy cache conversion, orphan temp cleanup. Never raises; never deletes. |
| `settings_model.py` | View-model for the settings dialog: one `ProviderSettingsView` per provider. |
| `sync_outcome.py` | Pure rules for what the app does after a sync (reload, preserve state, stop audio, toasts and colours). |
| `library_copy.py` | Every user-visible string for sources, sync and settings, plus the crate/playlist noun rule. Pure, unit-tested. |
| `comment_format.py` | Pure parser for `"<Camelot> - <energy> - <category> - …"` comments. |
| `log_safety.py` | Holds the `pyrekordbox` logger tree at ERROR and `sqlalchemy` at WARNING (the DB key is logged at DEBUG). Leaf. |
| `diagnostics.py` | `--self-check-rekordbox` (CI, no DB access) and `--check-rekordbox-library` (counts-only report in `user_data_dir()/diagnostics/`). |
| `tag_reader.py` | ID3 metadata reader, `to_camelot`, `read_energy_level` (ID3 only). |
| `crate_parser.py` | Serato `.crate` binary parser (used by `SeratoProvider` only). |
| `harmonic_tier.py`, `camelot.py` | Harmonic tiers and the Camelot compatibility score (ADR-010). |
| `suggestion_engine.py`, `suggestion_filters.py` | Weighted scoring; the `SuggestionFilters` snapshot (ADR-012). `allowed_crates` holds crate ids. |
| `dates.py`, `file_times.py` | Date helpers; cross-platform file creation time (ADR-013). |
| `audio_player.py`, `waveform.py` | Preview playback and waveform data (ADR-009). |
| `updater.py` | Release-manifest check on a background thread (ADR-008). |

### UI (`ui/`)
Presentation layer: CustomTkinter widgets and panels. Panels receive callbacks and data; they don't call providers.

| Component | Responsibility |
|-----------|---------------|
| `track_detail.py` | Now Playing dashboard with search, badges and the empty-library placeholder. |
| `suggestion_panel.py` | Scored suggestions grid, deferred filters (ADR-012), quiet re-render on live refresh. |
| `filter_bar.py` | Filter pills and overlays. The crate/playlist filter is **grouped by provider** (headers only when two or more providers have crates), searchable (`Select shown` / `Clear shown`), 300 x 320. `preserve_selection` keeps choices across a refresh. |
| `session_panel.py` | Setlist; `rebind_tracks` after a refresh. |
| `sync_panel.py` | `SettingsDialog`: one card per provider (switch, generated settings rows, status chip, issues), staged edits with Save / Cancel / `Sync enabled sources`. Provider-agnostic. |
| `waveform_widget.py`, `tooltip.py`, `utils.py` | Waveform canvas, hover tooltip, shared helpers (`truncate`, `truncate_start`). |

## Data Flow

```
Serato _Serato_/Subcrates/*.crate        rekordbox master.db (+ -wal)
        │ SeratoProvider.scan                    │ copy → private temp dir (no -shm)
        │ (crate_parser + tag_reader)            │ RekordboxProvider.scan (db_reader, mapping,
        │                                        │   energy: comment → file tag → 0)
        ▼                                        ▼
     ProviderSnapshot ──── library_sync (one thread, sequential) ──── ProviderSnapshot
        │                                                                │
        ▼                                                                ▼
  user_data_dir()/library/serato.json            user_data_dir()/library/rekordbox.json
  (+ serato.meta.json)                           (+ rekordbox.meta.json)
        └────────────────────────┬───────────────────────────────────────┘
                                 ▼ app._reload_library: load enabled snapshots
                      library_merge.merge (precedence: rekordbox, serato)
                                 ▼
                        TrackLibrary.replace_all
                                 │
            ├──▶ Search → Track selection → NowPlayingDashboard
            └──▶ suggestion_engine.get_suggestions(filters=SuggestionFilters)
                       ▼
                 SuggestionPanel → SessionPanel (setlist)
```

**Startup:** `main.py` configures logging and calls `log_safety.silence_secret_loggers()` before any other project import. It handles `--self-check-rekordbox` / `--check-rekordbox-library` and exits. Otherwise it runs `settings_migration.run_startup_migrations()` (never raises) and starts the app, which loads the stored snapshots. Nothing is scanned at startup unless the watcher sees a changed token.

**Manual sync:** Settings → `Sync enabled sources` → `SyncCoordinator.request(silent=False)` → each provider's `scan` → `library_store.save_snapshot` → `sync_outcome` → reload from **all** stored snapshots (a failed provider keeps its last good one) → toasts.

**Live refresh (ADR-015 D11):** `LibraryWatcher` (daemon thread) → `provider.change_token` (stat only) → `should_refresh` → `app._request_refresh` on the Tk thread → silent single-provider sync. If `changed`, `_reload_library(preserve_state=True)` keeps the current track, setlist, filters and preview. Otherwise nothing reloads. Window focus requests an immediate check.

**rekordbox read (ADR-015 D8):** copy-then-read. SQLite opens only the private copy; the copy is checked with `PRAGMA quick_check` and deleted afterwards. The originals are opened only for reading by `shutil.copyfile`.

**Snapshot schema:** v4 per provider (ADR-015 D4). The pre-v4 single `track_cache.json` (v3) is converted once to `library/serato.json` and left untouched. `date_added` is still creation time, read fresh (ADR-013).

**Suggestion filters:** unchanged from ADR-012, except that `allowed_crates` holds crate **ids**. The filter shows labels grouped by provider. A merged track passes the crate filter if **any** of its crates (from any provider) is selected.

**Data directory:** `platformdirs` user data dir, renamed `SeratoSidecar` → `DJSidecar` with a one-time copy-forward (ADR-008 amendment). It contains `settings.env`, `settings.env.pre-schema2.bak`, `library/` and `diagnostics/`.

## Current State & Known Issues

### Architectural Debt (prioritised)
1. **Broken import scheme** — **Resolved** (ADR-004).
2. **Hardcoded Windows paths** — **Resolved** (ADR-005). Serato and rekordbox path detection now live in their providers (ADR-015).
3. **Dead code (`search_panel.py`)** — **Resolved**.
4. **Duplicated `_truncate` method** — Partly resolved: `ui/utils.py` has `truncate` and `truncate_start`. Check the remaining panels on next touch.
5. **Duplicated Camelot regex** — Centralised in `camelot.py`; `comment_format.py` uses it. Verify on next touch.
6. **Bare `except Exception: pass`** — Improved: `tag_reader` catches `(MutagenError, OSError)`. Sync, watcher and the provider adapters use documented boundary handlers that log (ADR-015 D5). Check `app.py` dialog-state handlers on next touch.
7. **No logging** — Largely resolved: services and providers use `logging`. `main.py` configures it.
8. **`os.path` everywhere** — Ongoing. New code uses `pathlib`, except where `os.path` semantics are the point (`path_key`, `resolve_track_path`).
9. **Tests** — Broad unit coverage now exists for services, providers, models and key UI wiring (see `docs/testing-strategy.md`).
10. **Mutable default in dataclass** — `Track.crates` list. `TrackLibrary` no longer mutates it during load (the merge builds fresh lists); re-check on next touch.
11. **No `SuggestionFilters` value object** — **Resolved** (ADR-012).
12. **Stale doc reference to `comments_parser.py`** — **Resolved.** The comment parser is `services/comment_format.py` (ADR-015); `CLAUDE.md` is updated separately.
13. **Layering smell `models` → `services` (path identity)** — **Resolved.** `path_key` lives in the leaf `models/path_identity.py`; `library_merge` re-exports it.
14. **Path-only track identity** (new, accepted) — Serato and rekordbox tracks merge only when their resolved paths match after `path_key`. Moved or duplicated files show as separate tracks. Fuzzy matching is out of scope (ADR-015 D6).
15. **ID3-only energy and tag reader** (new, R8) — `tag_reader.read_energy_level` reads ID3 only, so non-MP3 rekordbox tracks without comment energy get energy 0 (neutral). Possible follow-up: switch to `mutagen.File`.
16. **Deck-load gate** — **Resolved.** `DJTrackSelectorApp.deck_load_provider_for(track)` (`source/app.py:375`) filters `track.sources` to enabled providers and calls `registry.first_deck_load_provider`. Nothing calls it from the UI yet; Phase 6 will.
17. **No automated import-boundary test** (new) — "only `registry.py` imports concrete providers" and "only `db_reader.py` imports pyrekordbox" are enforced by review only. A small AST-scan test would lock them in.

### What's Working Well
1. **Provider boundary** — DJ-software knowledge is confined to `source/providers/`. The settings dialog is generated from `SettingSpec`s and never branches on provider ids.
2. **Read-only towards DJ apps** — Serato files are only read; rekordbox is read from a private copy.
3. **Pure decision functions** — merge, `should_refresh`, `sync_outcome`, `library_copy` and the settings view-model are pure and unit-tested.
4. **Configuration-driven scoring and refresh timing** — in `config.py`.
5. **Background threading** — sync and watcher threads hand results to the Tk thread via `after(0, ...)`.
6. **Callback-based UI coupling** — panels receive callbacks rather than calling services.

## Target Architecture (incremental)

1. ~~Fix the import/package structure~~ — Done
2. ~~Fix cross-platform paths~~ — Done
3. ~~Delete dead code~~ — Done
4. ~~Library provider boundary~~ — Done (ADR-015)
5. **Import-boundary test** for the provider rules (debt #17) — small, high value
6. **Verify macOS** rekordbox path, `OrgFolderPath` format and sqlcipher wheels (blueprint R13)
7. **Extract shared utilities** — finish the `_truncate` consolidation
8. **Migrate to pathlib** — gradually, in new or touched code
