# Architecture Overview — Serato Sidecar

> **Status:** Reviewed — architectural assessment complete
> **Last updated:** 2026-05-30 (ADR-011 — suggestion filter enhancements)

## System Purpose

Serato Sidecar is a desktop companion app for DJs using Serato DJ software. It reads the user's Serato crate library, analyzes track metadata, and suggests harmonically compatible next tracks based on a weighted scoring algorithm.

## High-Level Architecture

```
┌─────────────────────────────────────────────────┐
│                    main.py                       │
│              (Entry point, theme)                │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│                    app.py                        │
│         (Application orchestrator)               │
│  - UI layout construction                        │
│  - Event wiring between panels                   │
│  - State coordination                            │
│  - Sync orchestration                            │
└──┬───────────┬────────────────┬─────────────────┘
   │           │                │
   ▼           ▼                ▼
┌───────┐ ┌──────────┐  ┌────────────┐
│Models │ │ Services  │  │     UI     │
│       │ │           │  │            │
│Track  │ │Camelot    │  │Dashboard   │
│Library│ │Suggestions│  │Suggestions │
│       │ │CrateParser│  │Session     │
│       │ │CrateSync  │  │Settings    │
│       │ │Cache      │  │Tooltip     │
│       │ │Updater    │  │Utils       │
└───────┘ └──────────┘  └────────────┘
```

## Layer Responsibilities

### Models (`models/`)
Pure data structures and collections. No UI knowledge, no service dependencies.

| Component | Responsibility |
|-----------|---------------|
| `Track` | Immutable dataclass representing a single track with all metadata. Includes `date_added` (Unix timestamp float) used by the date-range suggestion filter — the file's **creation time** on this machine, read fresh each sync (no carry-forward); `0.0` = unknown. See ADR-013 (supersedes ADR-011 Decision B). |
| `TrackLibrary` | In-memory collection of tracks with search and crate membership |

### Services (`services/`)
Business logic and external integrations. No UI knowledge.

| Component | Responsibility |
|-----------|---------------|
| `harmonic_tier.py` | `HarmonicTier` enum — shared harmonic-relationship vocabulary; dependency-free leaf module (breaks the `config.py` ↔ `camelot.py` cycle). See ADR-010. |
| `camelot.py` | Camelot wheel harmonic compatibility — 7-tier harmonic model (`classify()` → `HarmonicTier`, `compatibility_score()` 0.0–1.0). See ADR-010. |
| `suggestion_engine.py` | Weighted multi-factor track scoring algorithm |
| `crate_parser.py` | Serato .crate binary file parser + ID3 metadata reader |
| `crate_sync.py` | Background thread wrapper for crate export |
| `cache.py` | JSON cache read/write for the in-memory track library |
| `updater.py` | Fetches release manifest from GitHub and returns `UpdateInfo` if a newer version exists. Called from a background daemon thread on app startup. |
| `audio_player.py` | *(Proposed)* Wraps `pygame.mixer.music` for audio preview playback with play/pause/stop/seek. Single instance owned by `app.py`. See ADR-009. |
| `waveform.py` | *(Proposed)* Generates visual amplitude data from audio files via raw byte sampling. In-memory LRU cache. See ADR-009. |

### UI (`ui/`)
Presentation layer. CustomTkinter widgets and panels.

| Component | Responsibility |
|-----------|---------------|
| `track_detail.py` | Now-playing dashboard with search and metadata badges |
| `suggestion_panel.py` | Scored suggestions grid with crate filtering |
| `session_panel.py` | Setlist history with track management |
| `sync_panel.py` | Settings dialog for Serato folder and sync |
| `tooltip.py` | Reusable hover tooltip widget |
| `utils.py` | Shared UI helper functions |
| `waveform_widget.py` | *(Proposed)* Canvas-based waveform display with seekable playhead for audio preview. See ADR-009. |

## Data Flow

```
Serato .crate files
    │
    ▼ (crate_parser.py + crate_sync.py)
track_cache.json (schema v2) in user data dir
    │
    ▼ (cache.py + TrackLibrary)
In-memory TrackLibrary
    │
    ├──▶ Search → Track selection → NowPlayingDashboard
    │
    └──▶ suggestion_engine.get_suggestions(key_offset, date_from, date_to, …)
              │
              ▼
         Scored suggestions → SuggestionPanel → User picks next track
                                                       │
                                                       ▼
                                                 SessionPanel (setlist)
```

**Cache schema:** `track_cache.json` is at schema **version 3** (see ADR-007, ADR-013). Each track dict carries a `date_added` timestamp that is the file's **creation time**, read **fresh on every sync** from `crate_parser.get_track_metadata` (via the cross-platform `source/services/file_times.file_creation_time` helper) — there is no carry-forward, so `crate_sync` no longer loads the prior cache to seed it. The `CACHE_VERSION` 2 → 3 bump forces a one-time self-healing re-sync that drops stale v2 mtime values and re-seeds every track from creation time.

**Suggestion filters:** `get_suggestions` now accepts a single `filters: SuggestionFilters` snapshot (`source/services/suggestion_filters.py`, a frozen dataclass) carrying all four filter values — `allowed_crates`, `allowed_genres`, `key_offset` (Camelot wheel re-anchor, default 0), and `date_from` / `date_to` (date-added window). The individual keyword args remain as a fallback for existing call sites/tests. All filtering is in-memory (ADR-002). Filters are **deferred**: changing a control stages it (the live widgets are the staged source of truth); an Apply/Cancel bar in the suggestion panel appears while staged ≠ applied; only Apply commits and re-scores. `app._update_suggestions()` forwards `suggestion_panel.applied_filters` — so a track/session change re-scores with the last-applied filters while staged-but-unapplied edits remain in the controls. The filter controls live in `source/ui/filter_bar.py` (`FilterBar`, `FilterDropdown`, `KeyOffsetControl`, `DateRangeControl`, `FloatingOverlay`); the panel owns the applied snapshot and the Apply/Cancel affordance. See ADR-011 and ADR-012.

## Current State & Known Issues

### Architectural Debt (prioritised)
1. **Broken import scheme** — ~~All imports use `from source.xxx` but the project folder is `serato-sidecar/`, not `source/`.~~ **Resolved** during Phase 1 of the deployment work. Code now lives under a proper `source/` package with no `sys.path` manipulation. See `docs/architecture-decisions.md` (ADR-004).
2. **Hardcoded Windows paths** — ~~`config.py:8` has `FALLBACK_SUBCRATES_DIR = r"C:\Users\grant\Music\_Serato_\Subcrates"` and `export_crates.py:13` has `DEFAULT_MUSIC_ROOT = "C:\\"`.~~ **Resolved** during Phase 1. `config.py` uses `Path.home()` and `crate_parser.py` detects `sys.platform`. See ADR-005.
3. **Dead code** — ~~`ui/search_panel.py` (`SearchPanel` class) is never imported or used.~~ **Resolved** — `search_panel.py` has been deleted.
4. **Duplicated `_truncate` method** — Identical `_truncate(self, text, max_len)` appears in `track_detail.py`, `suggestion_panel.py`, and `session_panel.py`. Candidate for extraction into `ui/utils.py`.
5. **Duplicated Camelot regex** — `CAMELOT_RE` patterns historically lived in multiple services. Now centralised in `camelot.py` — verify on next touch of the parser code.
6. **Bare `except Exception: pass`** — `app.py` silently swallows errors when checking dialog state. `crate_parser.py` silently returns empty metadata on any ID3 read failure.
7. **No logging** — Diagnostic output still uses `print()` statements or toast notifications.
8. **`os.path` everywhere** — Coding standards specify `pathlib.Path` but every file uses `os.path` for all path operations.
9. **No tests** — ~~Zero automated test coverage.~~ **Partially resolved** — a `tests/` directory now exists with unit coverage for `camelot.py` and `suggestion_engine.py` (services Phase 1 priority, both at ~100% line coverage). See ADR-010 and `docs/testing-strategy.md`. The rest of the codebase remains untested.
10. **Mutable default in dataclass** — `Track.crates: list = field(default_factory=list)` is correctly handled with `field()`, but the list is mutated in-place by `library.py:41`, coupling library loading to track state.
11. **No `SuggestionFilters` value object** — ~~`get_suggestions` carries four filter inputs as separate keyword args, and filter state is scattered across the `filter_bar.py` widgets.~~ **Resolved** (ADR-012). A frozen `SuggestionFilters` dataclass now lives in `source/services/suggestion_filters.py`; the panel assembles a staged snapshot via `current_staged_filters()` (using the pure `build_filters()` helper) and forwards the applied snapshot to `get_suggestions(..., filters=...)`. This collapsed the keyword list into one typed argument and gave the UI a single "current filter state" for dirty detection (deferred apply), restore-on-Cancel, and the staged-vs-applied affordance.
12. **Stale doc reference to `comments_parser.py`** — `CLAUDE.md` lists `services/comments_parser.py` in the project structure, but that module no longer exists in the tree (functionality folded elsewhere). Out of scope to fix here; noted for a future `CLAUDE.md` cleanup.

### What's Working Well
1. **Clean layer separation** — Models, services, and UI are in distinct packages with clear responsibilities
2. **Configuration-driven scoring** — Weights and affinity matrix are externalized in `config.py`
3. **Background threading** — Crate sync runs on a daemon thread (`crate_sync.py`) with proper UI-thread callback via `self.after(0, ...)`
4. **Domain modeling** — `Track` dataclass, Camelot scoring, and the weighted suggestion engine are well-designed
5. **app.py is lean** — Despite being called a "God class" in the agent definition, `app.py` is only ~214 lines and its responsibilities (layout + event wiring) are reasonable for a project this size. It is NOT a God class -- it is a legitimate application controller.
6. **Callback-based UI coupling** — UI panels receive `on_select`, `on_clear`, `on_remove` callbacks rather than calling services directly. This is good separation.

## Target Architecture (incremental)

The current architecture is fundamentally sound for a hobby project. The recommendations below are ordered by impact-to-effort ratio and designed to be tackled one at a time:

1. ~~**Fix the import/package structure**~~ — Done (Phase 1 of deployment work)
2. ~~**Fix cross-platform paths**~~ — Done (Phase 1 of deployment work)
3. ~~**Delete dead code**~~ — Done (`search_panel.py` removed)
4. **Extract shared utilities** — Move `_truncate()` and shared constants into `ui/utils.py`
5. **Add logging** — Replace `print()` with Python `logging` module
6. **Add Phase 1 tests** — Unit tests for `camelot.py`, `crate_parser.py`, `suggestion_engine.py`
7. **Migrate to pathlib** — Gradually replace `os.path` with `pathlib.Path`
