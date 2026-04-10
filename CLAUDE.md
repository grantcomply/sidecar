# Serato Sidecar — DJ Track Selector

## Project Overview
Desktop application that helps DJs pick the next track during a set. Reads Serato DJ crate files, parses track metadata (ID3 tags), and scores track compatibility based on harmonic keys (Camelot wheel), energy flow, BPM proximity, and category affinity.

## Tech Stack
- **Language:** Python 3.10+
- **UI:** CustomTkinter (dark theme, blue accents)
- **Audio metadata:** Mutagen (ID3 tag reading)
- **Data storage:** JSON cache file (track_cache.json) + in-memory TrackLibrary
- **Config:** `.env` file for user settings, `config.py` for app constants

## Project Structure
```
serato-sidecar/
├── main.py                  # Entry point
├── app.py                   # Main window, event wiring, layout
├── config.py                # Settings, weights, affinity matrix, colors
├── models/
│   ├── track.py             # Track dataclass + from_dict/from_csv_row parsing
│   └── library.py           # TrackLibrary collection, search, crate tracking
├── services/
│   ├── cache.py             # JSON cache read/write (track_cache.json)
│   ├── camelot.py           # Harmonic key compatibility scoring
│   ├── comments_parser.py   # ID3 Comments field parser
│   ├── crate_parser.py      # Serato .crate binary parser + ID3 metadata reader
│   ├── crate_sync.py        # Background thread sync wrapper
│   └── suggestion_engine.py # Track scoring algorithm
├── ui/
│   ├── track_detail.py      # Now Playing dashboard with badges
│   ├── suggestion_panel.py  # Scored suggestions grid + crate filter
│   ├── session_panel.py     # Setlist/history panel
│   ├── sync_panel.py        # Settings dialog (folder picker + sync)
│   ├── search_panel.py      # Autocomplete search dropdown
│   └── tooltip.py           # Hover tooltip utility
└── docs/                    # Architectural documentation (maintained by architect agent)
```

## Key Domain Concepts
- **Camelot Wheel:** 24-key system (1A-12A, 1B-12B) for harmonic mixing compatibility
- **Energy Levels:** 1-8 scale tracking track intensity
- **Categories:** Banger, Driver, Groover, Filler, Chiller, Opener
- **Track Comments Format:** `"4A - 7 - Banger - Fat Bass Vocal"` (key - energy - category - descriptors)

## Agent Workflow
This project uses three specialized agents that collaborate:
1. **Architect** (`architect.md`) — Designs architecture, maintains docs/, defines standards
2. **Engineer** (`engineer.md`) — Implements code changes following architect's designs
3. **Code Reviewer** (`code-reviewer.md`) — Reviews engineer's code for quality and standards compliance

**Workflow:** Architect designs → Engineer implements → Code Reviewer reviews → Engineer fixes

## Development Commands
```bash
pip install -r requirements.txt
python main.py
```

## Cross-Platform Notes
- Serato crate paths differ: Windows uses `C:\Users\...\Music\_Serato_\Subcrates`, macOS uses `~/Music/_Serato_/Subcrates`
- File paths in CSVs use OS-native separators
- The app currently has Windows-specific fallback paths in config.py
