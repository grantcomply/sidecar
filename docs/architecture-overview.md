# Architecture Overview — Serato Sidecar

> **Status:** Reviewed — architectural assessment complete
> **Last updated:** 2026-04-06 (Architect review #1)

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
│       │ │CrateSync  │  │Session     │
│       │ │Export     │  │Settings    │
│       │ │Comments   │  │Search      │
└───────┘ └──────────┘  └────────────┘
```

## Layer Responsibilities

### Models (`models/`)
Pure data structures and collections. No UI knowledge, no service dependencies.

| Component | Responsibility |
|-----------|---------------|
| `Track` | Immutable dataclass representing a single track with all metadata |
| `TrackLibrary` | In-memory collection of tracks with search and crate membership |

### Services (`services/`)
Business logic and external integrations. No UI knowledge.

| Component | Responsibility |
|-----------|---------------|
| `camelot.py` | Camelot wheel harmonic compatibility scoring |
| `suggestion_engine.py` | Weighted multi-factor track scoring algorithm |
| `export_crates.py` | Serato .crate binary file parser + CSV exporter |
| `crate_sync.py` | Background thread wrapper for crate export |
| `comments_parser.py` | ID3 Comments field structured parser |

### UI (`ui/`)
Presentation layer. CustomTkinter widgets and panels.

| Component | Responsibility |
|-----------|---------------|
| `track_detail.py` | Now-playing dashboard with search and metadata badges |
| `suggestion_panel.py` | Scored suggestions grid with crate filtering |
| `session_panel.py` | Setlist history with track management |
| `sync_panel.py` | Settings dialog for Serato folder and sync |
| `search_panel.py` | Autocomplete search dropdown |
| `tooltip.py` | Reusable hover tooltip widget |

## Data Flow

```
Serato .crate files
    │
    ▼ (export_crates.py)
CSV files in crate-exports/
    │
    ▼ (TrackLibrary.load_from_csv_dir)
In-memory TrackLibrary
    │
    ├──▶ Search → Track selection → NowPlayingDashboard
    │
    └──▶ suggestion_engine.get_suggestions()
              │
              ▼
         Scored suggestions → SuggestionPanel → User picks next track
                                                       │
                                                       ▼
                                                 SessionPanel (setlist)
```

## Current State & Known Issues

### Architectural Debt (prioritised)
1. **Broken import scheme** — All imports use `from source.xxx` but the project folder is `serato-sidecar/`, not `source/`. `main.py` manipulates `sys.path` to go two levels up, but no `source/` package exists at that level. This makes the app fragile and non-standard.
2. **Hardcoded Windows paths** — `config.py:8` has `FALLBACK_SUBCRATES_DIR = r"C:\Users\grant\Music\_Serato_\Subcrates"` and `export_crates.py:13` has `DEFAULT_MUSIC_ROOT = "C:\\"`. Both break on macOS/Linux.
3. **Dead code** — `ui/search_panel.py` (`SearchPanel` class) is never imported or used anywhere. Its functionality was absorbed into `ui/track_detail.py` (`NowPlayingDashboard`).
4. **Duplicated `_truncate` method** — Identical `_truncate(self, text, max_len)` appears in `track_detail.py:188`, `suggestion_panel.py:306`, `session_panel.py:120`, and `search_panel.py:87`.
5. **Duplicated Camelot regex** — `CAMELOT_RE` is defined independently in both `camelot.py:3` and `comments_parser.py:14`, with slightly different patterns.
6. **Bare `except Exception: pass`** — `app.py` lines 129, 144, 168 silently swallow errors when checking dialog state. `export_crates.py:74` silently returns empty metadata on any ID3 read failure.
7. **No logging** — All diagnostic output uses `print()` statements (`export_crates.py` lines 48, 150, 153-154, 166, 175, 177-179) or toast notifications.
8. **`os.path` everywhere** — Coding standards specify `pathlib.Path` but every file uses `os.path` for all path operations.
9. **No tests** — Zero automated test coverage.
10. **Mutable default in dataclass** — `Track.crates: list = field(default_factory=list)` is correctly handled with `field()`, but the list is mutated in-place by `library.py:41`, coupling library loading to track state.

### What's Working Well
1. **Clean layer separation** — Models, services, and UI are in distinct packages with clear responsibilities
2. **Configuration-driven scoring** — Weights and affinity matrix are externalized in `config.py`
3. **Background threading** — Crate sync runs on a daemon thread (`crate_sync.py`) with proper UI-thread callback via `self.after(0, ...)`
4. **Domain modeling** — `Track` dataclass, Camelot scoring, and the weighted suggestion engine are well-designed
5. **app.py is lean** — Despite being called a "God class" in the agent definition, `app.py` is only ~214 lines and its responsibilities (layout + event wiring) are reasonable for a project this size. It is NOT a God class -- it is a legitimate application controller.
6. **Callback-based UI coupling** — UI panels receive `on_select`, `on_clear`, `on_remove` callbacks rather than calling services directly. This is good separation.

## Target Architecture (incremental)

The current architecture is fundamentally sound for a hobby project. The recommendations below are ordered by impact-to-effort ratio and designed to be tackled one at a time:

1. **Fix the import/package structure** — Rename folder or add proper `__init__.py` so imports work without `sys.path` hacks
2. **Fix cross-platform paths** — Replace hardcoded Windows paths with `Path.home()` detection
3. **Delete dead code** — Remove `search_panel.py`
4. **Extract shared utilities** — Move `_truncate()` and shared constants to a utility module
5. **Add logging** — Replace `print()` with Python `logging` module
6. **Add Phase 1 tests** — Unit tests for `camelot.py`, `comments_parser.py`, `suggestion_engine.py`
7. **Migrate to pathlib** — Gradually replace `os.path` with `pathlib.Path`
