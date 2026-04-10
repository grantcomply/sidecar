# DJ Track Selector

A desktop app that helps you pick the right next track while DJing. Select your currently playing track and get scored suggestions based on harmonic compatibility, energy flow, BPM proximity, and style affinity.

## Installing (End Users)

Prebuilt installers are published on the [GitHub releases page](https://github.com/grantcomply/sidecar/releases/latest). Open that link and grab the asset for your platform from the **Assets** list:

- **Windows:** the `.exe` installer (e.g. `SeratoSidecar-Setup-0.1.1.exe`)
- **macOS:** the `.zip` bundle (e.g. `SeratoSidecar-0.1.1-mac.zip`)

The filename version number will change over time. Always pull from `/releases/latest` and grab whichever `.exe` or `.zip` is listed — that way you never have to hand-edit a URL per release.

> Note: macOS builds are produced by CI on every release, but have not yet been validated end-to-end on a real Mac by a user. They *should* work; treat them as unverified until that changes.

### First Run — Windows (SmartScreen workaround)

On first launch Windows will show a blue **"Windows protected your PC"** dialog. Click **More info**, then **Run anyway**. You only need to do this once per install.

This happens because the binary is unsigned. A Windows OV/EV code-signing certificate runs $200+/year, which isn't justifiable for a hobby app shipped to friends. We're upfront about that rather than trying to obscure it.

### First Run — macOS (Gatekeeper workaround)

On first launch macOS will say **"SeratoSidecar cannot be opened because Apple cannot check it for malicious software"**. Right-click (or Ctrl-click) the app icon, choose **Open**, then click **Open** in the dialog that follows. You only need to do this once per install.

Same reason as Windows: the Apple Developer Program is $99/year and we're not paying for a hobby project.

### Auto-Updates

On startup the app checks GitHub for a newer release. If one exists, a toast appears in the app with a **Download** button; clicking it opens the new installer in your default browser. Run the installer like you did the first time — no need to uninstall the old version first. Your settings and crate cache are preserved across upgrades.

User data (cache + settings) lives at:
- **Windows:** `%APPDATA%\SeratoSidecar\`
- **macOS:** `~/Library/Application Support/SeratoSidecar/`

To disable the update check (e.g. for offline gigs), add `CHECK_FOR_UPDATES=false` to `settings.env` in that directory.

## Running from Source (Developers)

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

You only need to sync when you've added or removed tracks in Serato. The app caches everything to `track_cache.json` in your user data directory and reloads from there on subsequent launches.

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
sidecar/
  main.py                      # Entry point — run this
  requirements.txt             # Python dependencies
  source/
    __version__.py             # Single source of truth for the version string
    app.py                     # Main window layout and wiring
    config.py                  # Default paths, scoring weights, affinity matrix
    models/
      track.py                 # Track data model
      library.py               # In-memory library, deduplication, search
    services/
      camelot.py               # Camelot wheel compatibility logic
      crate_parser.py          # Serato .crate binary parser + ID3 metadata reader
      crate_sync.py            # Background Serato crate sync
      cache.py                 # JSON cache read/write
      suggestion_engine.py     # Track scoring algorithm
      updater.py               # Checks GitHub for new releases on startup
    ui/
      track_detail.py          # Now-playing dashboard with search
      suggestion_panel.py      # Scored suggestions list
      session_panel.py         # Setlist/history panel
      sync_panel.py            # Settings dialog (folder picker + sync)
      tooltip.py               # Hover tooltip utility
      utils.py                 # Shared UI helpers
  docs/                        # Architectural documentation
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
