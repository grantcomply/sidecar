# Sidecar — DJ Track Selector

A desktop app that helps you pick the right next track while DJing. Sidecar reads your library from **rekordbox**, **Serato DJ**, or both. Select the track that's playing now and get scored suggestions based on harmonic compatibility, energy flow and BPM proximity.

Sidecar only ever **reads** your DJ software's files. It never changes your rekordbox database or your Serato crates.

## Installing (End Users)

Prebuilt installers are published on the [GitHub releases page](https://github.com/grantcomply/sidecar/releases/latest). Open that link and grab the asset for your platform from the **Assets** list:

- **Windows:** the `.exe` installer (`DJSidecar-Setup-<version>.exe`; versions up to 0.1.6 were called `SeratoSidecar-Setup-<version>.exe`)
- **macOS:** the `.zip` bundle (`DJSidecar-<version>-mac.zip`)

The filename version number will change over time. Always pull from `/releases/latest` and grab whichever `.exe` or `.zip` is listed — that way you never have to hand-edit a URL per release.

> Note: macOS builds are produced by CI on every release, but have not yet been validated end-to-end on a real Mac by a user. rekordbox support on macOS is also unverified. They *should* work; treat them as unverified until that changes.

### First Run — Windows (SmartScreen workaround)

On first launch Windows will show a blue **"Windows protected your PC"** dialog. Click **More info**, then **Run anyway**. You only need to do this once per install.

This happens because the binary is unsigned. A Windows OV/EV code-signing certificate runs $200+/year, which isn't justifiable for a hobby app shipped to friends. We're upfront about that rather than trying to obscure it.

### First Run — macOS (Gatekeeper workaround)

On first launch macOS will say **"DJSidecar cannot be opened because Apple cannot check it for malicious software"**. Right-click (or Ctrl-click) the app icon, choose **Open**, then click **Open** in the dialog that follows. You only need to do this once per install.

Same reason as Windows: the Apple Developer Program is $99/year and we're not paying for a hobby project.

### Auto-Updates

On startup the app checks GitHub for a newer release. If one exists, a toast appears in the app with a **Download** button; clicking it opens the new installer in your default browser. Run the installer like you did the first time — no need to uninstall the old version first. Your settings and library are preserved across upgrades.

User data (settings + library snapshots) lives at:
- **Windows:** `%APPDATA%\DJSidecar\`
- **macOS:** `~/Library/Application Support/DJSidecar/`

Versions up to 0.1.6 used a folder named `SeratoSidecar`. The first time a newer version starts, it copies your settings and library across from that folder and leaves the old folder untouched.

To disable the update check (e.g. for offline gigs), add `CHECK_FOR_UPDATES=false` to `settings.env` in that directory.

> **rekordbox users:** a rekordbox update can occasionally stop Sidecar from reading your rekordbox library until Sidecar itself is updated. If that happens, Sidecar keeps showing your library as it was at the last successful read, and Settings shows the error. Install the next Sidecar update when it's out.

## Running from Source (Developers)

### Prerequisites

- Python 3.10+ (releases are built with Python 3.11; the rekordbox packages are pinned for it)
- pip

### Install Dependencies

```bash
pip install -r requirements.txt
```

This includes `pyrekordbox`, `sqlcipher3-wheels` (native) and `SQLAlchemy` for rekordbox support. If they fail to install or load, the app still runs and Serato still works.

### Launch the App

```bash
python main.py
```

The app opens a dark-themed window and loads your library from its saved snapshots.

### Diagnostics

```bash
python main.py --self-check-rekordbox      # can this build load pyrekordbox + SQLCipher? (no DB access)
python main.py --check-rekordbox-library   # read your rekordbox library and write a counts-only report
```

## How It Works

### 1. Choose your music sources

Click the **gear** (top right) to open **Settings**. There is one card per music source, **rekordbox** and **Serato DJ**, each with an on/off switch:

- **rekordbox:** Sidecar finds rekordbox's database automatically (the `Database` field shows the path it found). Only choose a file if you moved it; it must be the file named `master.db`. **Update automatically** (on by default) keeps Sidecar in step with rekordbox while you work (see below).
- **Serato DJ:** point **Crates folder** at your `_Serato_/Subcrates` folder (pre-filled with the usual location).

Turn on one source or both. Edits are staged: **Save** applies them, **Cancel** (or Esc) drops them, and **Sync enabled sources** saves and then reads every enabled source. A source with a problem is skipped, and the others still sync.

When both sources are on, a track that is in both libraries (same file) appears once. Its details (key, BPM, comment, energy, play count) come from rekordbox, and Serato fills in anything rekordbox leaves empty. Its crates and playlists from both apps are all available in the filter.

### 2. Automatic updates from rekordbox

With **Update automatically** on, Sidecar checks rekordbox's database every 10 seconds (a cheap file-time check) and quietly re-reads it after you change something in rekordbox: at most about once a minute, less often when nothing is changing, and promptly when you switch back to the Sidecar window. Your current track, setlist, filters and preview stay as they are. Serato crates are re-read when you click **Sync enabled sources**.

Sidecar reads rekordbox from a private temporary copy of its database, so it never touches the files rekordbox is using, even while rekordbox is running.

### 3. Search for the Currently Playing Track

Start typing in the search box — it filters your entire library by title, artist, or filename as you type. The dropdown shows each match with its Camelot key, BPM and energy level. Click a result to select it.

### 4. Browse Suggestions

Once a track is selected, the left panel fills with up to 60 compatible tracks ranked by a weighted score:

| Factor | Weight | What It Measures |
|---|---|---|
| Key Compatibility | 45% | Camelot wheel harmony, in tiers: same key, adjacent number, A/B flip, diagonal, ±2, semitone, related |
| Energy Flow | 35% | How close the energy levels are (1-8 scale). Jumps greater than 3 are penalised |
| BPM Proximity | 20% | Closer BPM scores higher. Drops to zero at 20+ BPM difference |

Tracks with no harmonic relationship at all are left out.

Each suggestion shows a colour-coded score. Use the filter bar to narrow suggestions by **Crates** (Serato only) or **Playlists** (when rekordbox is on), genre, key offset (move up or down the wheel) and date added. The crates/playlists list is grouped by source and has a search box. Filter changes apply when you click **Apply**.

### 5. Chain Through Your Set

Click **Select** on any suggestion to make it the new current track. The suggestions refresh immediately, letting you plan a full set by chaining from track to track.

## Camelot Wheel Reference

The app uses the Camelot mixing system for harmonic compatibility. For any given key (e.g. `4A`), the closest transitions are:

- **Same key** (`4A` → `4A`) — perfect harmonic match
- **Adjacent number** (`4A` → `3A` or `5A`) — smooth key shift, same energy character
- **Mode flip** (`4A` → `4B`) — switches between minor and major, same root

Keys wrap around: `12A` → `1A` is a valid adjacent transition.

## Track Metadata

Key, BPM, title, artist, genre and play count come from rekordbox's database or from your files' tags (Serato). The **Comments** field can carry extra metadata in this format:

```
CamelotKey - EnergyLevel - Category - Descriptors
```

For example: `4A - 7 - Banger - Fat Bass Vocal`

**Energy Scale:** 1 (low) to 8 (peak). For rekordbox tracks, energy comes from the comment if it has one, otherwise from the file's `EnergyLevel` tag (MP3 files only), otherwise it is treated as unknown.

**Categories:** Groover, Driver, Filler, Banger, Chiller, Opener (shown, not scored)

## Project Structure

```
sidecar/
  main.py                      # Entry point — run this (also the --self-check / --check diagnostics)
  requirements.txt             # Python dependencies (rekordbox packages pinned)
  source/
    __version__.py             # Single source of truth for the version string
    app.py                     # Main window, event wiring, sync + live refresh
    config.py                  # User data dir, settings, scoring weights, refresh timing, colours
    models/
      track.py                 # Track data model
      library.py               # In-memory library, search, crate index
      path_identity.py         # File-path identity used to merge sources
    providers/                 # Everything specific to a DJ app
      base.py                  # LibraryProvider contract
      registry.py              # The list of providers (rekordbox, serato)
      serato/provider.py       # Reads Serato crates
      rekordbox/               # Reads a private copy of rekordbox's master.db
    services/
      library_sync.py          # Background sync across enabled sources
      library_store.py         # Per-source library snapshots (library/<source>.json)
      library_merge.py         # Merges sources into one library
      library_watcher.py       # Automatic rekordbox refresh
      settings_migration.py    # One-time settings upgrade
      camelot.py               # Camelot wheel compatibility logic
      crate_parser.py          # Serato .crate binary parser
      tag_reader.py            # ID3 metadata reader
      comment_format.py        # "4A - 7 - Banger - ..." comment parser
      suggestion_engine.py     # Track scoring algorithm
      diagnostics.py           # rekordbox self-check and library check
      updater.py               # Checks GitHub for new releases on startup
    ui/
      track_detail.py          # Now-playing dashboard with search
      suggestion_panel.py      # Scored suggestions list
      filter_bar.py            # Filter pills and overlays
      session_panel.py         # Setlist/history panel
      sync_panel.py            # Settings dialog (one card per music source)
      tooltip.py               # Hover tooltip utility
      utils.py                 # Shared UI helpers
  docs/                        # Architectural documentation
```

## Tuning the Scoring

Edit `config.py` (in the `source/` package) to adjust:

- **`SUGGESTION_WEIGHTS`** — Change how much each factor matters (must sum to 1.0)
- **`HARMONIC_TIER_SCORES`** — The score for each harmonic relationship
- **`BPM_MAX_DIFF`** — BPM difference at which the BPM score hits zero (default: 20)
- **`ENERGY_SEVERE_PENALTY_THRESHOLD`** — Energy gap above which a harsh penalty kicks in (default: 3)
- **`MAX_SUGGESTIONS`** — Number of suggestions shown (default: 60)
- **`REFRESH_*`** — rekordbox automatic-refresh timing

## Cross-Platform

Built with Python and CustomTkinter, so it runs on both Windows and Mac. Sidecar auto-detects the Serato Subcrates folder and the rekordbox database in their usual places. Use the Settings dialog to override them if needed. See `docs/cross-platform-guide.md` for details.
