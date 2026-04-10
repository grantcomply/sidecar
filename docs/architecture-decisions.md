# Architecture Decision Records (ADRs)

> Maintained by the Architect agent. Each ADR documents a significant architectural choice.

## ADR Format

```
### ADR-NNN: Title
- **Status:** Proposed | Accepted | Superseded | Deprecated
- **Date:** YYYY-MM-DD
- **Context:** Why this decision is needed
- **Decision:** What we decided
- **Consequences:** What changes as a result
```

---

### ADR-001: Use CustomTkinter for Desktop UI
- **Status:** Accepted (inherited)
- **Date:** 2026-04-02
- **Context:** Need a cross-platform desktop UI framework for Python. Options include Tkinter, CustomTkinter, PyQt, Kivy, and web-based (Electron/Tauri with Python backend).
- **Decision:** Use CustomTkinter — a modern wrapper around Tkinter with dark mode support, custom widgets, and no additional system dependencies.
- **Consequences:**
  - Pro: Ships with Python, no complex build toolchain
  - Pro: Modern appearance with dark theme out of the box
  - Pro: Simple learning curve for a first Python project
  - Con: Limited widget set compared to PyQt
  - Con: Less mature ecosystem for complex layouts

### ADR-002: CSV-Based Track Storage
- **Status:** Accepted (inherited)
- **Date:** 2026-04-02
- **Context:** Need to persist track metadata after syncing from Serato crates. Options: SQLite, JSON, CSV, or in-memory only.
- **Decision:** Export Serato crates to CSV files (one per crate), load into memory on startup.
- **Consequences:**
  - Pro: Human-readable, easy to debug and inspect
  - Pro: Simple implementation, no ORM or database dependencies
  - Con: No query capability — all filtering is in-memory
  - Con: No schema versioning or migration path
  - Con: Full reload on every sync (no incremental updates)

### ADR-003: Weighted Scoring Algorithm for Track Suggestions
- **Status:** Accepted (inherited)
- **Date:** 2026-04-02
- **Context:** Need to rank track compatibility. The scoring considers harmonic key compatibility, energy flow, BPM proximity, and category affinity.
- **Decision:** Use a weighted linear combination with configurable weights in config.py. Hard filter on harmonic compatibility (non-compatible tracks are excluded entirely).
- **Consequences:**
  - Pro: Transparent and tuneable scoring
  - Pro: Easy to explain to users (score breakdown in tooltips)
  - Con: Linear weighting may not capture complex DJ preferences
  - Future: Could evolve to user-trainable weights or ML-based scoring

---

### ADR-004: Fix Package/Import Structure
- **Status:** Proposed
- **Date:** 2026-04-06
- **Context:** The project folder is named `serato-sidecar` (invalid Python identifier due to the hyphen). All imports use `from source.xxx` which implies the package is called `source`. `main.py` adds the grandparent directory to `sys.path`, but no `source/` package exists at that path. This makes the app unable to run from a clean checkout and breaks IDE support.
- **Decision:** Rename the project's code folder to `source/` (a valid Python package name), or restructure so that all code lives under a `source/` subdirectory within `serato-sidecar/`. The recommended approach is:
  ```
  serato-sidecar/          # project root (git repo)
  ├── main.py              # entry point (no sys.path hacks)
  ├── source/              # Python package
  │   ├── __init__.py
  │   ├── app.py
  │   ├── config.py
  │   ├── models/
  │   ├── services/
  │   └── ui/
  ├── tests/
  ├── docs/
  └── requirements.txt
  ```
  Then `main.py` simply does `from source.app import DJTrackSelectorApp` with no path manipulation.
- **Consequences:**
  - Pro: Standard Python package structure, works with IDEs, linters, and test runners
  - Pro: Removes fragile `sys.path` manipulation from `main.py`
  - Con: Requires moving files into a `source/` subdirectory (one-time reorganization)

### ADR-005: Cross-Platform Path Detection
- **Status:** Proposed
- **Date:** 2026-04-06
- **Context:** `config.py:8` hardcodes `C:\Users\grant\Music\_Serato_\Subcrates` and `export_crates.py:13` hardcodes `DEFAULT_MUSIC_ROOT = "C:\\"`. These break on macOS and Linux.
- **Decision:** Replace hardcoded paths with platform-aware defaults using `pathlib.Path`:
  ```python
  from pathlib import Path
  FALLBACK_SUBCRATES_DIR = Path.home() / "Music" / "_Serato_" / "Subcrates"
  DEFAULT_MUSIC_ROOT = Path.home()  # or Path("/") on Unix
  ```
  The music root for resolving Serato .crate relative paths should detect the OS: on Windows it's typically `C:\`, on macOS/Linux it's `/`.
- **Consequences:**
  - Pro: Works on Windows and macOS without user configuration
  - Pro: Removes personal username from source code
  - Con: Music root heuristic may need refinement for non-standard Serato installs

### ADR-006: Remove Dead Code (SearchPanel)
- **Status:** Proposed
- **Date:** 2026-04-06
- **Context:** `ui/search_panel.py` defines a `SearchPanel` class that is never imported or used. The search functionality was integrated into `NowPlayingDashboard` in `ui/track_detail.py`. Dead code increases maintenance burden and confuses developers.
- **Decision:** Delete `ui/search_panel.py`.
- **Consequences:**
  - Pro: Reduces confusion about which search component is active
  - Pro: Less code to maintain
  - Con: None

### ADR-007: Replace CSV Cache with Single JSON Cache File
- **Status:** Proposed
- **Date:** 2026-04-06
- **Supersedes:** ADR-002 (CSV-Based Track Storage)
- **Context:** The current architecture uses CSV files (one per crate) as an intermediate cache between Serato .crate parsing and in-memory track data. The question was raised whether to eliminate this cache entirely and parse .crate files + ID3 tags directly on every launch.

  **Analysis of "skip cache entirely" approach:**
  - Reading ID3 tags via Mutagen takes roughly 10-50ms per file. For a typical hobby DJ library of 200-500 tracks, that means 2-25 seconds of startup time on every launch.
  - This creates a poor user experience — the app appears frozen or slow to load on every start, even when the library has not changed.
  - The cache layer is architecturally justified: it trades a one-time sync cost for near-instant startup.

  **Problems with the current CSV cache:**
  - One file per crate creates file management complexity (stale file cleanup in `export_crates.py:175-179`).
  - CSV format is string-only — BPM, energy, and play count must be re-parsed from strings in `Track.from_csv_row()`.
  - No schema version — if CSV columns change, old cache files silently produce bad data.
  - The `crate_to_csv_name()` mapping and per-file I/O are unnecessary indirection.
  - Tracks appearing in multiple crates are stored redundantly across CSV files and must be deduplicated on load (`library.py:42-45`).

- **Decision:** Replace the per-crate CSV files with a single `track_cache.json` file in the project root. The JSON file stores all tracks with their crate memberships in one place.

  **Cache file structure:**
  ```json
  {
    "version": 1,
    "synced_at": "2026-04-06T14:30:00",
    "crate_mtimes": {
      "My Crate.crate": 1712412600.0
    },
    "tracks": {
      "/path/to/track.mp3": {
        "file_name": "track.mp3",
        "title": "Song Title",
        "artist": "Artist",
        "bpm": 124.0,
        "key": "Am",
        "camelot_key": "8A",
        "genre": "House",
        "energy_level": 5,
        "play_count": 3,
        "comments": "8A - Energy 5 - Groover",
        "crates": ["My Crate", "House Bangers"]
      }
    }
  }
  ```

  **What changes:**
  1. `export_crates.py` → Refactor into `crate_parser.py`. Keep `parse_crate_file()` and `get_track_metadata()`. Remove all CSV writing. Add a function that returns parsed track dicts (not CSV rows).
  2. New `cache.py` service — Handles reading/writing `track_cache.json`. Provides `load_cache() -> dict` and `save_cache(tracks, crate_mtimes)`.
  3. `TrackLibrary` — Add `load_from_cache(cache_path)` method alongside or replacing `load_from_csv_dir()`. Add `from_dict()` class method on `Track` (replaces `from_csv_row()`).
  4. `crate_sync.py` — Sync now writes JSON cache instead of CSV files.
  5. `app.py` startup — Load from `track_cache.json` instead of scanning `crate-exports/` directory.
  6. Delete `crate-exports/` directory and remove `DEFAULT_EXPORT_DIR` from `config.py`.

  **Future enhancement (not in scope now):** Smart cache invalidation. Store `.crate` file modification times in the cache. On startup, compare mtimes — if no crates changed, skip re-parsing entirely. If crates changed, re-parse only the changed ones. This would make "Sync Crates" automatic and invisible to the user.

- **Consequences:**
  - Pro: Single file instead of N files — no stale file cleanup needed
  - Pro: Typed values in JSON (numbers stay numbers, no re-parsing from strings)
  - Pro: Schema version field enables future migration
  - Pro: Track deduplication handled at write time, not read time
  - Pro: Startup remains near-instant (reading one JSON file)
  - Pro: Simpler code — removes `crate_to_csv_name()`, CSV column mapping, per-file I/O loop
  - Con: JSON is slightly less human-readable than CSV for quick inspection (but still inspectable)
  - Con: One-time migration effort to replace CSV plumbing
