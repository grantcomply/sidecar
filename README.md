# DJ Track Selector

A desktop app that helps you pick the right next track while DJing. Select your currently playing track and get scored suggestions based on harmonic compatibility, energy flow, BPM proximity, and style affinity.

## Quick Start

### Prerequisites

- Python 3.10+
- pip

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Launch the App

```bash
python main.py
```

The app opens a dark-themed window and auto-loads your track library from existing crate exports on startup.

## How It Works

### 1. Sync Your Crates

The top bar shows your Serato Subcrates folder path (auto-detected from your home directory). Click **Browse** to change it if needed, then click **Sync** to export all your Serato crates into CSV files the app can read.

You only need to sync when you've added or removed tracks in Serato. If you've already run `export_crates.py` before, the app picks up those existing CSVs automatically.

### 2. Search for the Currently Playing Track

Start typing in the search box — it filters your entire library by title, artist, or filename as you type. The dropdown shows each match with its Camelot key, BPM, energy level, and category. Click a result to select it.

### 3. Browse Suggestions

Once a track is selected, the right panel fills with up to 30 compatible tracks ranked by a weighted score:

| Factor | Weight | What It Measures |
|---|---|---|
| Key Compatibility | 40% | Camelot wheel harmony — identical key, adjacent number (±1), or A/B mode flip |
| Energy Flow | 30% | How close the energy levels are (1-8 scale). Jumps greater than 3 are penalized |
| BPM Proximity | 15% | Closer BPM scores higher. Drops to zero at 20+ BPM difference |
| Category Affinity | 15% | How well the track styles pair (e.g. Driver→Banger = 0.8, Driver→Chiller = 0.3) |

Tracks with incompatible keys are excluded entirely — you'll only see harmonically safe options.

Each suggestion shows a colour-coded score: green (75%+) is a great pick, yellow (55-74%) is solid, orange is more of a stretch.

### 4. Chain Through Your Set

Click **Select** on any suggestion to make it the new current track. The suggestions refresh immediately, letting you plan a full set by chaining from track to track.

## Camelot Wheel Reference

The app uses the Camelot mixing system for harmonic compatibility. For any given key (e.g. `4A`), compatible transitions are:

- **Same key** (`4A` → `4A`) — perfect harmonic match
- **Adjacent number** (`4A` → `3A` or `5A`) — smooth key shift, same energy character
- **Mode flip** (`4A` → `4B`) — switches between minor and major, same root

Keys wrap around: `12A` → `1A` is a valid adjacent transition.

## Track Metadata

Track information comes from your Serato crate exports. The **Comments** field in your MP3 tags encodes key metadata in this format:

```
CamelotKey - EnergyLevel - Category - Descriptors
```

For example: `4A - 7 - Banger - Fat Bass Vocal`

**Categories:** Groover, Driver, Filler, Banger, Chiller, Opener

**Energy Scale:** 1 (low) to 8 (peak)

## Project Structure

```
serato-sidecar/
  main.py                      # Entry point — run this
  requirements.txt             # Python dependencies
  source/
    app.py                     # Main window layout and wiring
    config.py                  # Default paths, scoring weights, affinity matrix
    models/
      track.py                 # Track data model
      library.py               # CSV loading, deduplication, search
    services/
      camelot.py               # Camelot wheel compatibility logic
      comments_parser.py       # Parses the Comments metadata field
      crate_sync.py            # Background Serato crate sync
      export_crates.py         # Serato .crate binary parser + CSV exporter
      suggestion_engine.py     # Track scoring algorithm
    ui/
      track_detail.py          # Now-playing dashboard with search
      suggestion_panel.py      # Scored suggestions list
      session_panel.py         # Setlist/history panel
      sync_panel.py            # Settings dialog (folder picker + sync)
      tooltip.py               # Hover tooltip utility
      utils.py                 # Shared UI helpers
  docs/                        # Architectural documentation
  crate-exports/               # CSV files generated from Serato crates
```

## Tuning the Scoring

Edit `config.py` (in the `source/` package) to adjust:

- **`SUGGESTION_WEIGHTS`** — Change how much each factor matters (must sum to 1.0)
- **`CATEGORY_AFFINITY`** — Adjust how well each category pairs with others (0.0 to 1.0)
- **`BPM_MAX_DIFF`** — BPM difference at which the BPM score hits zero (default: 20)
- **`ENERGY_SEVERE_PENALTY_THRESHOLD`** — Energy gap above which a harsh penalty kicks in (default: 3)
- **`MAX_SUGGESTIONS`** — Number of suggestions shown (default: 30)

## Cross-Platform

Built with Python and CustomTkinter, so it runs on both Windows and Mac. The app auto-detects your Serato Subcrates folder based on your home directory. Use the Settings dialog to override if needed.
