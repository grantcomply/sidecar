# Sidecar — DJ Track Selector

## Project Overview
Desktop application that helps DJs pick the next track during a set. Reads the DJ's library through pluggable **library providers** — rekordbox (its library database, read from a private copy) and Serato DJ (crate files + ID3 tags) — either or both enabled in Settings. Scores track compatibility based on harmonic keys (Camelot wheel), energy flow, BPM proximity, and category affinity. The exe is `DJSidecar.exe` and the data dir is `DJSidecar` (copied forward from the legacy `SeratoSidecar` dir).

## Tech Stack
- **Language:** Python 3.10+
- **UI:** CustomTkinter (dark theme, blue accents)
- **Audio metadata:** Mutagen (ID3 tag reading)
- **rekordbox:** pyrekordbox + sqlcipher3-wheels (only `providers/rekordbox/db_reader.py` imports them; never log the DB key, never open rekordbox's own files)
- **Data storage:** Per-provider JSON snapshots (`library/<provider>.json`) merged into an in-memory TrackLibrary
- **Config:** `.env` file for user settings, `config.py` for app constants

## Project Structure
```
sidecar/
├── main.py                  # Entry point (+ --self-check-rekordbox / --check-rekordbox-library)
├── app.py                   # Main window, event wiring, layout
├── config.py                # Settings, weights, affinity matrix, colors
├── models/
│   ├── track.py             # Track dataclass + from_dict parsing
│   ├── path_identity.py     # path_key(): file-path identity (stdlib-only leaf)
│   └── library.py           # TrackLibrary collection, search, crate index (id → label)
├── providers/
│   ├── base.py              # LibraryProvider protocol + snapshot types (stdlib-only, no project imports)
│   ├── registry.py          # Provider registry (get_provider, all_providers)
│   ├── serato/provider.py   # SeratoProvider
│   └── rekordbox/           # RekordboxProvider (reads a private copy of master.db via pyrekordbox)
│       ├── provider.py      # RekordboxProvider
│       ├── paths.py         # DB location, change token, track path resolution
│       ├── db_copy.py       # Copy master.db (+ -wal) to a temp dir; never touches the original
│       ├── db_reader.py     # Only module that imports pyrekordbox; key never logged
│       ├── mapping.py       # rekordbox rows → TrackRecord
│       └── energy_cache.py  # File-tag energy fallback cache
├── services/
│   ├── camelot.py           # Harmonic key compatibility scoring
│   ├── crate_parser.py      # Serato .crate binary parser
│   ├── tag_reader.py        # ID3 metadata reader + key → Camelot conversion
│   ├── library_sync.py      # Background sync across enabled providers + single-flight SyncCoordinator
│   ├── library_watcher.py   # Live refresh: polls provider change tokens (adaptive backoff, refresh on focus)
│   ├── sync_outcome.py      # Pure rules for what the app does after a sync (reload, toasts, dialog state)
│   ├── library_copy.py      # Every user-visible string for sources, sync and settings
│   ├── settings_model.py    # Settings dialog view-model (one view per provider)
│   ├── library_store.py     # Per-provider snapshots (library/<provider>.json); converts legacy track_cache.json
│   ├── library_merge.py     # Path identity + merging provider snapshots into one library
│   ├── settings_migration.py # One-time startup settings migration (schema 2, PROVIDERS_ENABLED)
│   ├── log_safety.py        # Pins pyrekordbox/sqlalchemy loggers above DEBUG (key safety)
│   ├── comment_format.py    # "<key> - <energy> - <category> - ..." comment parser
│   ├── diagnostics.py       # --self-check-rekordbox / --check-rekordbox-library reports
│   ├── suggestion_engine.py # Track scoring algorithm
│   ├── suggestion_filters.py, harmonic_tier.py, dates.py, file_times.py  # Filter + scoring helpers
│   └── audio_player.py, waveform.py, updater.py  # Preview playback, waveform, auto-update
├── ui/
│   ├── track_detail.py      # Now Playing dashboard with badges
│   ├── suggestion_panel.py  # Scored suggestions grid + crate filter
│   ├── session_panel.py     # Setlist/history panel
│   ├── sync_panel.py        # Settings dialog: one card per music source (switch, settings, status) + sync
│   ├── search_panel.py      # Autocomplete search dropdown
│   └── tooltip.py           # Hover tooltip utility
└── docs/                    # Architectural documentation (maintained by architect agent)
```

## Key Domain Concepts
- **Camelot Wheel:** 24-key system (1A-12A, 1B-12B) for harmonic mixing compatibility
- **Energy Levels:** 1-8 scale tracking track intensity
- **Categories:** Banger, Driver, Groover, Filler, Chiller, Opener
- **Track Comments Format:** `"4A - 7 - Banger - Fat Bass Vocal"` (key - energy - category - descriptors)
- **Crate:** a Serato crate or a rekordbox playlist. Crate ids are provider-namespaced (`serato:…`, `rekordbox:…`); the UI says "Crates" when only Serato is enabled, otherwise "Playlists"
- **Merge:** tracks are identified by file path; when both providers have a file, rekordbox's non-empty values win (rekordbox's own analysis is the source of truth)

## Agent Workflow
This project uses four specialized agents that collaborate:
1. **Architect** (`.claude/agents/architect.md`) — Designs architecture, maintains docs/, defines standards
2. **UI Designer** (`.claude/agents/ui-designer.md`) — Designs the CustomTkinter desktop UI, maintains `docs/ui-design-guide.md`, produces design briefs and audits
3. **Engineer** (`.claude/agents/engineer.md`) — Implements code changes following architect and UI designer guidance
4. **Code Reviewer** (`.claude/agents/code-reviewer.md`) — Reviews engineer's code for quality and standards compliance

**Workflow:** Architect + UI Designer design → Engineer implements → Code Reviewer reviews → Engineer fixes

**Planning a feature:** Run `/feature-request <description>` to produce an architect blueprint, implementation plan, and UI design brief in `plans/<slug>-<YYYY-MM>/`.

## Development Commands
```bash
pip install -r requirements.txt
python main.py
```

## Cross-Platform Notes
- Serato crate paths differ: Windows uses `C:\Users\...\Music\_Serato_\Subcrates`, macOS uses `~/Music/_Serato_/Subcrates`
- rekordbox DB: Windows `%APPDATA%\Pioneer\rekordbox\master.db`, macOS `~/Library/Pioneer/rekordbox/master.db`; track paths come from `OrgFolderPath` (`/` separators, converted to native)
- Path identity normalises NFC + `os.path.normcase` (`models/path_identity.py`)
- See `docs/cross-platform-guide.md` for the sqlcipher wheel matrix and the rekordbox upgrade runbook in `docs/deployment-guide.md`
