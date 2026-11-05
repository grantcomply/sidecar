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
- **Status:** Accepted (inherited) — the hard-filter clause is superseded by ADR-010 (the weighted-linear-combination decision otherwise stands).
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
- **Status:** Accepted (implemented). Superseded in part by ADR-015: Serato path detection now lives in `SeratoProvider` (`SeratoProvider.default_settings()`, `source/providers/serato/provider.py:66-68`), and `config.FALLBACK_SUBCRATES_DIR` no longer exists. rekordbox database detection lives in `source/providers/rekordbox/paths.py:24-32`.
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
- **Status:** Accepted (implemented); **superseded in part by ADR-015** (structure → per-provider snapshots, schema v4). The single `track_cache.json` and `cache.py` are gone. Each provider now has its own snapshot at `user_data_dir()/library/<provider_id>.json` (`source/services/library_store.py`). The **version-mismatch rule below still applies, per snapshot file**. A legacy v3 `track_cache.json` is converted once, read-only, to `library/serato.json` and left in place (`library_store.convert_legacy_cache_if_needed`, `source/services/library_store.py:378-411`).
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
    "version": 2,
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
        "date_added": 1712412600.0,
        "crates": ["My Crate", "House Bangers"]
      }
    }
  }
  ```

  **Schema version history:**
  - **v1** — original structure (no `date_added`).
  - **v2** (ADR-011, 2026-05-30) — adds `date_added` (Unix timestamp float): the first-seen-in-cache time for the track, seeded from file `mtime` on first sight and carried forward unchanged across subsequent syncs. `CACHE_VERSION` is now `2` (`source/services/cache.py:16`). Because a version mismatch makes `load_cache` return `None` (see below), the bump forces a **one-time, self-healing re-sync** on upgrade — old v1 caches are ignored, every track is freshly mtime-seeded, and no bespoke migration code is needed. See ADR-011 Decision B. *(Superseded by v3 — `date_added` is no longer mtime-seeded or carried forward.)*
  - **v3** (ADR-013, 2026-05-31) — `date_added` is re-sourced from the file's **creation time** (via `source/services/file_times.file_creation_time`), read **fresh on every sync** (no carry-forward). `CACHE_VERSION` is now `3`; the bump forces one self-healing re-sync that drops the stale v2 mtime-seeded values and re-seeds every track from creation time. See ADR-013.

  **Version-mismatch behaviour:** `load_cache` compares the file's `version` against `CACHE_VERSION` and returns `None` on any mismatch (`source/services/cache.py:70-76`), which the app treats as "no cache" and triggers a re-sync. This is the migration mechanism — schema changes are absorbed by bumping the version rather than transforming old files in place.

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

### ADR-008: Distribution and Update Strategy
- **Status:** Accepted
- **Date:** 2026-04-10
- **Context:** Ship a Python desktop app to friends on Windows and macOS with a way to deliver updates. Needs to be zero-cost (hobby project), survive upgrades without losing user data, and demand minimal ongoing maintenance. Five sub-decisions were required.

- **Decision:**

  **1. GitHub Releases on a dedicated public repo as the distribution mechanism.** The project ships from `grantcomply/sidecar` (a standalone public repo split out from the earlier monorepo). Considered alternatives: self-hosting on a personal domain, S3 + CloudFront, third-party installer hosts. Public GitHub Releases wins on anonymous downloads (no auth tokens baked into the updater), a free CDN for release assets, and unlimited free GitHub Actions minutes including macOS runners — private repos cap macOS at ~200 minutes/month.

  **2. PyInstaller one-folder + Inno Setup on Windows, zipped `.app` on macOS.** Considered one-file PyInstaller (simpler distribution) but rejected it: one-file extracts into a temp directory on every launch, adding 1–3s of startup latency and triggering Windows Defender false positives more often. One-folder is faster, less suspicious, and easier to wrap in a real installer. Inno Setup is free, open source, and runs on `windows-latest` with no licensing concerns. On macOS, `ditto -c -k --keepParent` is used instead of plain `zip` because it preserves bundle attributes.

  **3. Roll-your-own updater with a `latest.json` manifest.** Considered `tufup` and `PyUpdater` but rejected both for this stage: the client is ~80 LOC and uses only `urllib`, `json`, and `packaging.version.Version`. A full TUF-based framework adds dependency weight and release-process complexity that a hobby-scale project shipping to a handful of friends can't justify. If the user base grows, `tufup` is the documented upgrade path — it's actively maintained and the swap is well-defined. `PyUpdater` is stagnant since 2022 and not a future path. The manifest is hosted at a floating `latest` tag so the URL stays stable across versions: `https://github.com/grantcomply/sidecar/releases/download/latest/latest.json`.

  **4. Unsigned binaries on both platforms.** Code signing costs money ($99/year Apple Developer Program, $200+/year Windows OV/EV certificate). For a hobby app shipping to friends, neither is justifiable. Users hit SmartScreen on Windows and Gatekeeper on macOS once per install; both workarounds are a few clicks and documented in the README. The alternative — paying for a cert — would be the single largest ongoing cost of the project and buys only a small UX polish.

  **5. `platformdirs` for user data locations.** Considered hand-rolled `os.environ["APPDATA"]` / `~/Library/Application Support` lookups. `platformdirs` is small, pure-Python, well-maintained, and correctly handles edge cases (XDG fallback on Linux, roaming vs local on Windows). Settings and library snapshots live in `%APPDATA%\DJSidecar\` on Windows and `~/Library/Application Support/DJSidecar/` on macOS so they survive upgrades — PyInstaller bundles extract into read-only temp dirs, so storing user data next to the exe is not an option.

  > **Amended 2026-11-05 (ADR-015 D10, rebrand to "Sidecar").** The data dir was `SeratoSidecar` up to v0.1.6 and is renamed to `DJSidecar`, with a **copy-forward migration** (task T5.6): on first launch, if `DJSidecar` has no `settings.env` and the legacy `SeratoSidecar` dir has one, Sidecar **copies** (never moves) `settings.env`, `settings.env.pre-schema2.bak` and the `library/` tree (plus `track_cache.json` if there is no `library/`). `diagnostics/` is not copied. The legacy dir is left intact, so a downgrade still works. `settings.env` is copied **last**, through a temp file, so its presence marks a finished copy and an interrupted copy is retried on the next start. An `OSError` is logged as a warning and never stops startup. The migration runs once per process inside `config.user_data_dir()`, before `ENV_FILE` is computed (`source/config.py:41-106`). Setting the env var `SIDECAR_SKIP_DATA_DIR_MIGRATION` disables it; the test suite sets it in `tests/conftest.py` so tests can never copy real user data. Display name: **"Sidecar"**. Exe: `DJSidecar.exe`; installer `DJSidecar-Setup-<ver>.exe`; Mac bundle `DJSidecar.app`. **Never change:** the Inno Setup `AppId` (`build/installer.iss:32`, so the installer upgrades in place), the updater manifest URL (`source/services/updater.py`), the macOS `bundle_identifier` (`serato-sidecar.spec`), or the logo asset (`source/ui/SeratoSidecarLogo.png`, deferred by the user). The installer removes the stale `SeratoSidecar.exe` and old shortcuts via `[InstallDelete]`.

- **Consequences:**
  - Pro: Zero ongoing hosting cost, zero signing cost, free CI minutes on macOS.
  - Pro: Friends can install the app with one download and one click-through of a security prompt.
  - Pro: User data is preserved across upgrades automatically. One exception so far: the one-time `SeratoSidecar` → `DJSidecar` copy-forward (amendment above). Data-format changes inside the dir are migrated by `services/settings_migration.py` (settings schema 2) and `services/library_store.py` (v3 cache → v4 snapshots).
  - Con (added by ADR-015): The build now ships a **mandatory native dependency**: `pyrekordbox==0.5.0`, `sqlcipher3-wheels==0.5.7` (SQLCipher, native) and `SQLAlchemy==2.1.8` (plus `psutil`, native, which pyrekordbox needs), all pinned in `requirements.txt`. CI installs them with `--only-binary=sqlcipher3-wheels,psutil` and runs the frozen `--self-check-rekordbox` on both platforms (`.github/workflows/release.yml`). The spec must collect `pyrekordbox`, `sqlcipher3` and the SQLAlchemy SQLite dialect. The import is lazy (ADR-009 pattern), so a broken native module disables rekordbox only. rekordbox upgrades can require a pyrekordbox bump and a re-release (runbook in `docs/deployment-guide.md`).
  - Pro: The updater is small enough to audit in one sitting and has no framework lock-in.
  - Con: Unsigned binaries produce a scary one-time dialog on both platforms — requires a clear README explanation to avoid users bouncing.
  - Con: The roll-your-own updater offers no silent in-place upgrade (user has to click Download and run the installer). Acceptable trade-off for this scale.
  - Con: macOS builds are produced by CI but currently unverified on a real Mac — first real-world Mac user will be the de facto QA.

### ADR-009: Audio Preview with pygame and Raw Byte Waveforms
- **Status:** Proposed
- **Date:** 2026-04-12
- **Context:** DJs want to audition suggested tracks before committing to play them. This requires audio playback with seek capability and a visual waveform for navigation. The solution must be cross-platform (Windows + macOS), bundle with PyInstaller, and not require users to install external software (like VLC or ffmpeg).
- **Decision:**
  1. **Playback engine: `pygame.mixer`** — Use only the mixer subsystem (no display init). Supports MP3, WAV, OGG, FLAC via SDL2. Mature PyInstaller hooks. Provides play, pause, stop, and seek. Chosen over `python-vlc` (requires VLC installed), `miniaudio` (less PyInstaller community knowledge), and `pyaudio` (raw PCM only).
  2. **Waveform generation: raw byte sampling** — Sample raw file bytes at regular intervals to approximate amplitude. No audio decoding required, no new dependencies. Produces visually adequate waveforms for preview purposes. Higher-fidelity decoded waveforms (via numpy + pygame.sndarray) are a documented future upgrade path.
  3. **Waveform caching: in-memory LRU (50 entries)** — No disk persistence. Regeneration takes ~50-100ms per file. Cache clears on library re-sync.
  4. **Architecture: three new files** — `services/audio_player.py` (playback control), `services/waveform.py` (amplitude data), `ui/waveform_widget.py` (canvas rendering). `AudioPlayer` is instantiated once in `app.py` and passed to `SuggestionPanel` via constructor.
  5. **UI pattern: expandable waveform below the suggestion row** — Play button added as a new column in the suggestion grid. Waveform appears in an expandable section below the playing row. Clicking the row still selects the track (play button click does not trigger selection).
- **Consequences:**
  - Pro: Single new dependency (`pygame`) with proven cross-platform and PyInstaller support.
  - Pro: Waveform generation requires zero additional dependencies beyond pygame.
  - Pro: Clean separation — playback service has no UI knowledge, waveform widget has no playback knowledge.
  - Pro: Preview and selection are separate actions, matching DJ workflow expectations.
  - Con: pygame adds ~3-5MB to the bundle size.
  - Con: Raw byte waveforms are approximate — visually useful but not sample-accurate. Acceptable for preview; upgrade path documented.
  - Con: pygame.mixer has limited format support compared to ffmpeg-based solutions (no AAC/M4A). If users have AAC files this will need revisiting.
  - See: `docs/audio-preview-design.md` for full design.

---

### ADR-010: Tiered Harmonic Compatibility Scoring (supersedes the hard-filter clause of ADR-003)

- **Status:** Accepted
- **Date:** 2026-05-22
- **Revised:** 2026-05-22 (post-implementation) — Decision point 4 corrected to a **symmetric** diagonal tier; Risk R2 repurposed. The original draft's asymmetric-diagonal intent was found to be mathematically unsatisfiable during implementation; see the Resolution note below.
- **Supersedes:** ADR-003's clause "Hard filter on harmonic compatibility (non-compatible tracks are excluded entirely)". The weighted-linear-combination decision in ADR-003 otherwise stands.

#### Context

ADR-003 chose a hard harmonic filter: any non-compatible track is excluded before scoring. In practice this surfaces only 3 of the 24 keys' relationships and produces a thin suggestion list. DJs want a wider pool of harmonically *usable* tracks ranked by how safe the harmonic move is, so they can build longer, more varied sets.

#### Decision

**1. Replace the 3-value `compatibility_score` with a 7-tier model.** `compatibility_score(key1, key2)` continues to return a `0.0–1.0` float so the existing `total_score` blend and the `%` display work unchanged. The new return values:

| Relationship | Score | Source |
|--------------|-------|--------|
| Perfect match (identical) | `1.0` | unchanged |
| Adjacent (±1 number, same letter) | `0.8` | unchanged |
| Relative (A/B swap, same number) | `0.7` | unchanged |
| Diagonal (valid direction) | `0.62` | new — research range 0.6–0.65, midpoint chosen |
| Energy ±2 (wheel distance 2, same letter) | `0.57` | new — research range 0.55–0.6, midpoint |
| Semitone (wheel distance 5, same letter) | `0.47` | new — research range 0.45–0.5, midpoint |
| Related (wheel distance 4, same letter) | `0.37` | new — research range 0.35–0.4, midpoint |
| No harmonic relationship | `0.0` | unchanged |

Midpoints of the researched ranges are chosen as the default values; they are tunable (see decision 3). The three legacy values (1.0 / 0.8 / 0.7) are preserved exactly so existing behaviour for those tiers does not regress.

**2. Remove the hard filter; filter on `compatibility_score(...) > 0` instead.** The engine offers a track if it has **any** harmonic relationship (score > 0). Truly unrelated keys still score `0.0` and stay filtered. `is_compatible()` is **deleted**, not redefined.

Rationale for deleting rather than redefining: `is_compatible()` is used in exactly one place — `suggestion_engine.py`. A predicate named `is_compatible` that returns `True` for a tritone-related "related ±4" pair would be a misleading name. The engine already computes `compatibility_score()` one line later — calling it twice (once as a boolean gate, once for the score) is wasteful. The clean change is: compute the score once, gate on `> 0`.

**3. New tier scores live in `config.py` as a named, ordered structure.** Consistent with `SUGGESTION_WEIGHTS` and the thresholds already there and with the coding standard "all tuneable values belong in `config.py`". The structure is a mapping from a `HarmonicTier` enum to a float. `camelot.py` imports it. The three legacy scores move into this structure too, so there is a single source of truth for all seven values.

Rationale for an enum over bare string keys: the tier is also a UI label. An enum gives `camelot.py`, the engine, the tests, and the UI one shared vocabulary and prevents typo-keyed dict lookups. To break the `config.py` ↔ `camelot.py` import cycle (config keys its scores by the enum; camelot needs the scores), the `HarmonicTier` enum is defined in a small dependency-free leaf module `source/services/harmonic_tier.py` that both `config.py` and `camelot.py` import; `camelot.py` re-exports it for backward-compatible imports.

**4. The DIAGONAL tier is a symmetric relationship, identified by a small explicit special-case inside `classify()`.** Harmonic *compatibility* — whether two tracks share enough notes to layer well — is inherently order-independent: it is a property of the unordered key *pair*, not of a play direction. Energy direction (boost vs drop) is a separate concern, already captured by the engine's independent `energy_score` axis (`suggestion_engine.py:57-63`); it does not belong in the Camelot score. The DIAGONAL tier is therefore symmetric, exactly like the other tiers.

A valid diagonal is any `±1-number-with-letter-swap` pair drawn from the `{(B,+1), (A,−1)}` family — that is, the move from the source key is either "B-letter, number step +1" or "A-letter, number step −1" (all number steps wrap mod 12, 12 ↔ 1). The four research examples are classified as follows:

- `8B→9A` — `(B,+1)` — **DIAGONAL**.
- `8A→7B` — `(A,−1)` — **DIAGONAL**.
- `8B→7A` — `(B,−1)` — not in the family — `NONE` (dissonant).
- `8A→9B` — `(A,+1)` — not in the family — `NONE` (dissonant).

The `{(B,+1), (A,−1)}` family is **closed under reversal**: reversing a `(B,+1)` move yields an `(A,−1)` move and vice versa (e.g. the reverse of `8B→9A` is `9A→8B`, which is `(A,−1)` — itself a valid diagonal). The reverse of a dissonant pair is likewise dissonant (`8B→7A` and `7A→8B` are both outside the family). Consequently the diagonal relation — and therefore the **whole** `compatibility_score` function — is **symmetric**: `compatibility_score(k1, k2) == compatibility_score(k2, k1)` for every key pair. This matches the harmonic reality and is verified by the symmetry tests in `tests/services/test_camelot.py`.

`get_suggestions()` calls `compatibility_score(current.camelot_key, track.camelot_key)` (current first, candidate second). Argument order is harmless to the harmonic score because the function is symmetric; it is retained only for readability and to keep the call site's intent ("score the move from current to candidate") explicit.

**5. `MAX_SUGGESTIONS` raised to 60.** Widening the filter from 3 relationships to ~7 roughly doubles-to-triples the candidate pool. The previous cap of 30 would silently hide most newly-eligible tracks. 60 is an interim default for a 200–500 track hobby library, revisited after live use.

#### Resolution note (2026-05-22, post-implementation)

The original draft of this ADR was internally contradictory. Decision point 4 specified a *symmetric* diagonal algorithm (the `{(B,+1), (A,−1)}` family above), while Risk R2 simultaneously demanded the diagonal be *asymmetric* — that `compatibility_score("9A","8B")` return `0.0` as "the dissonant reverse" of the valid `8B→9A`.

During implementation the engineer and the code-reviewer independently proved this asymmetric requirement unsatisfiable. A distance-1 letter-swap move is fully characterised by `(source-letter, signed-step)`. The four named research examples pin the valid set to exactly `{(B,+1), (A,−1)}`. The reverse of `8B→9A` is `9A→8B`, which is an `(A,−1)` move — the *same structural case* as the named-valid example `8A→7B`. No rule consistent with the four research examples can mark `9A→8B` invalid; the diagonal relation is necessarily symmetric. R2 conflated "the reverse direction" with "a different key": the research statement "8B→7A is dissonant" concerns the pair `{8B, 7A}`, a genuinely different pair from `{8B, 9A}` — not a reverse-direction effect. Energy boost-vs-drop direction is handled by the separate `energy_score` axis, not by the harmonic score.

Decision point 4 has been corrected above to formally adopt the symmetric diagonal — the only internally-consistent and harmonically-correct option. The shipped code (`classify()` / `compatibility_score()` in `source/services/camelot.py`) and its tests are correct and unchanged; this ADR was revised to match and endorse them. Risk R2 has been repurposed (see Consequences / risks below).

#### Consequences

- Pro: Suggestion pool widens substantially; DJs see harmonically-usable tracks they previously never saw.
- Pro: Scoring stays a transparent, tunable lookup; the `%` display and tooltip keep working with no UI-contract change.
- Pro: `compatibility_score` is fully symmetric — `compatibility_score(a, b) == compatibility_score(b, a)` for every key pair. There is no surprising per-tier asymmetry to remember, document defensively, or accidentally "fix". This matches the harmonic reality (compatibility is a property of an unordered pair) and keeps the function trivially reasoned-about.
- Pro: First real `tests/` directory lands, satisfying `docs/testing-strategy.md` Phase 1 priority for `camelot.py` and `suggestion_engine.py`.
- Pro: `compatibility_score` is computed once per candidate instead of effectively twice (gate + score).
- Con: Many more low-scoring rows (37%–62% blends) will appear. `_score_color()` was re-tuned to five buckets (see `ui-design-brief.md`) so the colour signal survives the wider score range.
- Con: The score is non-monotonic in wheel distance (semitone at distance 5 outranks related at distance 4). The named tier table, not a distance curve, is the source of truth.

#### Residual risk

- **R2 (repurposed) — a future contributor wrongly assumes the diagonal must be directional.** "Diagonal" can intuitively read as a one-way move, and the original draft of this ADR made exactly that mistake. A contributor might "fix" the symmetric diagonal into an asymmetric one, reintroducing an unsatisfiable, harmonically-wrong rule. Mitigation: the symmetric behaviour is stated in Decision point 4 above, in the `compatibility_score` / `classify` docstrings in `source/services/camelot.py`, and is locked in by a dedicated symmetry test in `tests/services/test_camelot.py` that asserts `compatibility_score("9A","8B") == compatibility_score("8B","9A")`. Any directional "fix" breaks that test.

---

### ADR-011: Suggestion Filter Enhancements (key-offset re-anchor; first-seen date-added)

- **Status:** Accepted — Decision B (date_added source) **superseded in part by ADR-013** (2026-05-31).
- **Date:** 2026-05-30
- **Relates to:** Extends ADR-002 (filtering stays in-memory) and ADR-007 (cache schema bumped to v2); respects ADR-010 (Camelot symmetry preserved).

#### Context

Two user-driven enhancements to the suggestion system, plus a UX review of the filter bar:

1. **"Stuck in the same key."** PERFECT same-key matches (score `1.0`, the top harmonic tier from ADR-010) always dominate the suggestion list, so like-for-like mixing is the path of least resistance and DJs never climb the wheel. Users want a "transition ±N" control that steers them off same-key matches and progressively up (or down) the Camelot wheel.
2. **"Date added" filtering.** DJs want to review tracks they discovered recently (e.g. "the last two months"). No per-track "date added to library" timestamp existed anywhere in the pipeline — `Track.date` is the ID3 `TDRC` release date (wrong meaning), and the cache only stored a single global `synced_at` plus per-crate `crate_mtimes`.
3. **Filter UX review** (owned by the UI Designer; see `plans/suggestion-filter-enhancements-2026-05/ui-design-brief.md`). Architecturally this only required keeping the existing `None`-means-no-filter engine contract intact while the filter controls were redesigned into a floating-overlay pill bar (`source/ui/filter_bar.py`).

The architectural risk shared by (1) and (2) is that each is a *cross-cutting* change: (1) introduces *direction*, which must not leak into the symmetric Camelot core (the ADR-010 R2 trap); (2) requires a cache **schema** change, which must route through ADR-007's versioning.

#### Decision A — Key offset as a target-key re-anchor

`get_suggestions(..., key_offset: int = 0)`. A non-zero offset does **not** hard-filter or re-weight; it **re-anchors the harmonic target**. The engine computes `target = shift_key(current.camelot_key, key_offset)` (a new leaf helper in `source/services/camelot.py`) and scores every candidate against that shifted target instead of the current key, while excluding PERFECT (identical-key) candidates measured against the *current* key. At `key_offset == 0` (the default) the target is the current key and nothing is excluded — byte-for-byte today's behaviour.

Rejected alternatives: a **hard filter** (`current ± N` only) collapses the pool to one or two keys and discards the ADR-010 tiered model; a **same-key penalty / re-weight** demotes like-for-like but still anchors everything around the current key and fails to move the DJ *toward* the next key. The re-anchor preserves the full tiered model and the energy/BPM blend — the suggestion list stays rich and ranked, only its harmonic centre of gravity moves.

**The load-bearing boundary (ADR-010 R4):** direction is applied as a *pre-shift to the target key string*, before the symmetric `compatibility_score` / `classify` are called. `shift_key` only advances the *number* around the wheel (wrapping 12↔1) and keeps the letter; it returns `None` for invalid/empty keys, in which case the engine falls back to offset-0 behaviour (blueprint R5). `compatibility_score` and `classify` are **never** made directional — the symmetry tests in `tests/services/test_camelot.py` stay green.

`KEY_OFFSET_RANGE` lives in `source/config.py` (default `(-2, 2)`). The engine **defensively clamps** `key_offset` to this range (`suggestion_engine.py:62`) so a future caller passing a raw out-of-range value cannot silently re-anchor to an unintended key. *(This clamp was added during implementation; it was not in the original blueprint draft but is a strict safety improvement consistent with the decision.)*

#### Decision B — Date-added as a first-seen-in-cache timestamp, mtime-seeded

> **Superseded in part by ADR-013 (2026-05-31):** the `date_added` *source* described below (mtime-seeded first-seen-in-cache, carried forward) has been reversed — `date_added` is now the file's **creation time**, read fresh each sync. The field name, the engine filter, and the `0.0 = unknown` contract are unchanged. See ADR-013.

Add `Track.date_added: float = 0.0` (Unix timestamp, matching the `synced_at` / `crate_mtimes` conventions). Its value is the **first-seen-in-cache** time, established once and then frozen:

- **New track** (not in the previous cache): seed `date_added` from the file's **`mtime`** (`Path(path).stat().st_mtime`), falling back to sync time on `OSError`. The seed is computed in `crate_parser.get_track_metadata`.
- **Existing track** (present in the previous cache with a non-zero `date_added`): **carry the value forward unchanged**. Carry-forward is done by `parse_all_crates`, which receives the previous cache's tracks as an injected parameter — the parser stays pure and does not import the cache (blueprint R2). `crate_sync` reads the previous cache and supplies it.

First-seen-in-cache is the truest available proxy for "tracks I found recently": it is the date the track entered *this app's* view of the library. Seeding from `mtime` (rather than sync time) gives a more accurate add-date for tracks added between syncs. Once set the value never moves, so re-tagging a file later does not disturb it.

Rejected sources: ID3 `TDRC`/`Track.date` (release date, not add date); Serato `database V2` add-date (out of scope — undocumented binary format, fragile, large effort); `st_ctime` (inode-change-time on Linux, creation on Windows — inconsistent); `st_birthtime` (not reliably available on Linux). `mtime` is the only universally-present, cross-platform timestamp.

**Engine filter:** `get_suggestions(..., date_from: float | None = None, date_to: float | None = None)`. Both `None` = no date filter. A track with `date_added == 0.0` (unknown) is **excluded** when `date_from` is set — it cannot be proven to be in range (`suggestion_engine.py:88-93`).

**Cache schema:** `date_added` flows into each track dict written by `save_cache` automatically. `CACHE_VERSION` is bumped **1 → 2** (`source/services/cache.py:16`). Per ADR-007 a version mismatch makes `load_cache` return `None`, forcing one self-healing re-sync on upgrade (after which old caches carry nothing forward and every track is freshly mtime-seeded — correct and intended). See ADR-007's updated structure block.

#### Consequences

- Pro: A non-zero offset surfaces a rich, ranked suggestion pool re-centred up/down the wheel without gutting the ADR-010 tiered model; energy/BPM blending is untouched.
- Pro: Direction is confined to the engine; the Camelot core stays symmetric and its tests stay green. The defensive clamp removes a footgun for future callers.
- Pro: A cross-platform "date added" proxy with no new dependencies and no new binary parsing; the value is stable once set.
- Pro: The schema change rides ADR-007's versioning cleanly — one forced, self-healing re-sync, no bespoke migration code.
- Con: **First-sync add-dates are mtime-approximate** and cluster oddly for pre-existing libraries; accuracy improves over time as new tracks get real first-seen dates. This must be stated plainly to users (the UI Designer pinned honest caveat copy in the date panel: "Dates are approximate for tracks added before your first sync."). *(Superseded by ADR-013: with creation-time sourcing this approximation no longer applies and the caveat copy was replaced — see ADR-013 R5.)*
- Con: One forced re-sync for every existing user on upgrade to cache v2 (ADR-007 R3 — accepted; sync is fast and user-initiated).
- Con: The engine signature now carries four filter keyword args (`allowed_crates`, `allowed_genres`, `key_offset`, `date_from`/`date_to`). A future `SuggestionFilters` value object (a frozen dataclass the panel assembles and forwards) is the **documented next step** as filter count grows — deferred for this feature in favour of lower-risk additive args. Tracked as architectural debt in `docs/architecture-overview.md`.

#### Residual risk

- **R4 (from ADR-010) — direction leaking into the symmetric core.** A future contributor might "simplify" the offset by making `classify` / `compatibility_score` directional. Mitigation: the boundary is stated in Decision A and the `camelot.py` docstrings; `shift_key` keeps direction in the engine; the symmetry tests fail on any directional change.
- **R1 — first-sync date accuracy.** Accepted with mitigation (improves over time; honest UI caveat). Open question deferred to the user: whether a future Serato `database V2` parser for true add-dates is worth building. Recommendation: ship first-seen now, revisit only on request.

---

### ADR-012: Deferred filter application with a `SuggestionFilters` snapshot
- **Status:** Accepted
- **Date:** 2026-05-30
- **Relates to:** ADR-011 (introduced the four filter inputs and named `SuggestionFilters` as the next step); ADR-002 (filtering stays in-memory). Resolves architectural debt #11.

- **Context:** Filters applied live — every control `on_change` was wired straight through to a full `get_suggestions` re-score plus a teardown/rebuild of the suggestion grid. A single checkbox toggle in a multi-crate dropdown re-scored the whole library; toggling several in sequence re-scored once per toggle, which the user reported as unresponsiveness. The user asked for staged edits with an explicit Apply/Cancel at the bottom of the suggestion panel, applying only on Apply. This is also the moment ADR-011 flagged for introducing the `SuggestionFilters` value object (debt #11).

- **Decision:**
  - **D1 — A frozen `SuggestionFilters` value object** (`source/services/suggestion_filters.py`, a leaf module with no UI imports) holds all four filter values in engine-ready form: `allowed_crates`/`allowed_genres` as `frozenset[str] | None` (`None` = no filter), `key_offset: int`, `date_from`/`date_to: float | None`. `frozenset` makes the dataclass hashable and its equality order-independent — dirty detection is free via `==`.
  - **D2 — The widgets remain the single source of *staged* state; the panel owns one *applied* snapshot** (`SuggestionPanel._applied_filters`). `current_staged_filters()` assembles an engine-ready snapshot from the live controls (the `None`-normalisation moved here from `app._update_suggestions`, extracted to a pure `build_filters()` helper). Dirty = `current_staged_filters() != _applied_filters`.
  - **D3 — `on_change` is decoupled from re-score.** The control `on_change` → `FilterBar._changed` → `on_filter_change` chain now terminates at `SuggestionPanel._on_staged_change()`, which recomputes dirty, shows/hides the Apply/Cancel bar, and pushes per-control staged-tint flags. It never re-scores.
  - **D4 — Apply is the sole filter-driven re-score.** `_apply_filters()` sets `_applied_filters = current_staged_filters()`, commits the date control's display snapshot, clears staged tints, hides the bar, and fires the one re-score callback. A track/session change still re-scores via `_update_suggestions`, reading the **applied** snapshot — persisted filters survive a track change while staged-but-unapplied edits remain in the widgets.
  - **D5 — `get_suggestions` gains `filters: SuggestionFilters | None = None`.** When provided it supersedes the individual keyword args (which remain as a fallback for existing call sites/tests). `_update_suggestions` forwards `suggestion_panel.applied_filters` as one object.
  - **D6 — Reset stages, it does not apply.** Both per-control `reset()` and the "Reset filters" link restore controls to defaults as a staged change; they surface Apply/Cancel and require Apply to take effect. Cancel, by contrast, restores the controls to the **last-applied** snapshot (via silent `restore(...)` methods on each control; the date control owns a private display snapshot so Cancel reconstructs preset highlight + manual entry text, not just epochs).

- **Consequences:**
  - Pro: One re-score per Apply instead of one per interaction — fixes the unresponsiveness directly.
  - Pro: `SuggestionFilters` lands (debt #11 resolved); `get_suggestions` gains a single typed filter argument; dirty detection is free.
  - Pro: No third copy of state — widgets stay the staged source, the panel owns one applied snapshot; track/session changes correctly reuse the last-applied filters.
  - Con: Loss of live preview — the explicit, requested trade-off.
  - Con: One more concept (staged vs applied) and two revert-style affordances (Reset-to-defaults vs Cancel-to-applied), mitigated by distinct labels, a staged-tint pill cue (`#3a88c8` vs applied `#1f6aa5`), and the "Filters changed" Apply/Cancel bar. The date overlay's internal "Apply" button was renamed "Set dates" to avoid a naming collision with the global Apply.

---

### ADR-013: `date_added` sourced from file creation time (supersedes ADR-011 Decision B)

- **Status:** Accepted
- **Date:** 2026-05-31
- **Supersedes:** ADR-011 Decision B (the `date_added` *source*: mtime-seeded first-seen-in-cache, carried forward).
- **Relates to:** ADR-007 (cache schema bumped to v3); ADR-008 / `docs/cross-platform-guide.md` (Windows + macOS are the only shipping targets); ADR-010 (leaf-module pattern, mirrored by `file_times.py`).

#### Context

ADR-011 Decision B added `Track.date_added: float` and seeded it from the file's **modification time** (`Path(path).stat().st_mtime`), establishing a frozen *first-seen-in-cache* value carried forward on every later sync. ADR-011 **explicitly rejected** creation time at the time, because `st_ctime` means inode-change-time on Linux and `st_birthtime` is not reliably available there — `mtime` was "the only universally-present, cross-platform timestamp."

The user now wants the opposite: *"the date added [should be] based on the created date time of the file on my computer so the filter uses that."* This ADR consciously reverses ADR-011's date_added source. The reversal is acceptable now for a reason that did not weigh in ADR-011's framing: **Serato Sidecar ships installers only for Windows and macOS** (ADR-008, `cross-platform-guide.md`), and on **both** of those platforms a true file creation time is obtainable. Linux — the only platform where creation time is unreliable — is a dev-machine-only "Future" tier, not a shipping target.

The load-bearing technical fact: the bundled interpreter is **Python 3.11.9**, which does **not** expose `st_birthtime` on Windows (that arrives in Python 3.12). On Windows 3.11, `st_ctime` *is* the creation time, so the helper must use it there.

#### Decision

- **D1 — Reverse the source: `date_added` is the file's creation time.** It is seeded from a cross-platform creation-time read, replacing the `st_mtime` read in `crate_parser.get_track_metadata`. The residual risk (Linux's unreliable creation time) lands only on a non-shipping platform.
- **D2 — A small, pure, testable creation-time helper.** New leaf module `source/services/file_times.py` exposes `file_creation_time(path) -> float | None` with an explicit fallback chain (first hit wins): (1) `os.stat`; `OSError` → `None`; (2) `st_birthtime` if present and `> 0` (macOS all versions; Windows 3.12+); (3) `st_ctime` if `sys.platform == "win32"` (Windows 3.11: ctime is creation time); (4) `st_mtime` (Linux/other, dev-only). The helper has no project deps (mirrors `harmonic_tier.py`, ADR-010) and is unit-tested via mocked `os.stat` / `sys.platform`. It returns `None` on stat failure rather than substituting a fallback timestamp — the **caller** maps `None` → `0.0` ("unknown"), preserving the engine's `0.0`-excluded date-filter contract (`suggestion_engine.py:88-93`). The `> 0` guard handles filesystems reporting `st_birthtime == 0` ("unknown birth").
- **D3 — Drop the carry-forward; read creation time fresh each sync.** ADR-011 froze `date_added` because *first-seen* is observation state (meaningful only relative to when the cache first saw the track). Creation time is **not** observation state — it is an intrinsic, re-readable property of the file. Freezing it adds complexity and causes drift, so the carry-forward is removed: the `previous_tracks` plumbing is dropped from `parse_all_crates` and `crate_sync._run()`, and `date_added` is read fresh on every sync.
- **D4 — Cache migration: bump `CACHE_VERSION` 2 → 3.** Existing v2 caches hold mtime-based values that are now semantically wrong and (with carry-forward gone) would never be re-seeded for unchanged tracks. Per ADR-007's versioning mechanism, the bump makes `load_cache` return `None` on the version mismatch, triggering one self-healing re-sync that re-seeds every track from creation time. No bespoke migration code.
- **D5 — Field name unchanged; semantic note added.** `date_added` is referenced across the model, cache, engine and UI; renaming it would ripple for no functional gain. The name stays; its **meaning** shifts from "first time this app saw the track (mtime-seeded, frozen)" to "the file's creation time on this machine (read fresh)." The shift is recorded in the `Track.date_added` comment, the `get_track_metadata` seed comment, this ADR, the ADR-011 cross-reference, and the architecture overview.

#### Consequences

- Pro: `date_added` now reflects exactly what the user asked for — the file's creation date on their machine — read directly from the filesystem.
- Pro: The platform-branching logic is isolated in one pure, unit-tested leaf module; call sites stay trivial and the Windows-3.11 `st_ctime` branch is locked by a test so the future 3.12 move can't silently regress it.
- Pro: Dropping the carry-forward removes state and the cache-load it required; the schema change rides ADR-007's versioning cleanly (one forced, self-healing re-sync, no bespoke migration).
- Con (**R2, accepted**): Copying or re-downloading a track resets its filesystem creation time, so `date_added` jumps to the copy date on the next sync — a re-acquired track surfaces as "recently added." This matches the user's mental model ("the file on my computer"); the carry-forward alternative would ignore machine state, contradicting the request.
- Con (**R3, accepted**): One forced re-sync per existing user on the v2 → v3 bump (ADR-007 R3 pattern; sync is fast and user-initiated).
- Con (**R4, accepted**): Linux dev machines get `mtime`, not creation time. Linux is not a shipping target; the helper degrades gracefully without claiming false accuracy. Documented in `cross-platform-guide.md`.

#### Residual risk

- **R1 — Windows `st_ctime` semantic on 3.11.** Correctly handled: the helper only falls through to `st_ctime` after the `st_birthtime` check (absent on Windows 3.11). When the bundled interpreter moves to 3.12+, `st_birthtime` transparently takes precedence — no code change needed. Locked by `tests/services/test_file_times.py::test_windows_python_311_returns_ctime`.
- **R5 — Stale UI caveat copy (resolved here).** ADR-011's date-panel caveat ("Dates are approximate for tracks added before your first sync") is no longer accurate. Replaced with "Date added is the file's creation date on this computer." (`source/ui/filter_bar.py`).
- **Open question — future Serato `database V2` add-date.** Still the truest "when I added it to my library" source, still out of scope (undocumented binary format). Revisit only on request.
- **Note (ADR-015 D9):** ADR-013 holds for every library provider. rekordbox tracks read `date_added` from the creation time of the **resolved** local file, not from rekordbox's `StockDate` (the import date).

---

### ADR-014: Virtual MIDI deck loader (Serato)
- **Status:** Rejected (recorded 2026-11-05)
- **Date:** 2026-09-19
- **Context / finding:** A virtual MIDI note mapped to "Load to Deck" loads whatever track is *selected in the DJ app's own browser*. The note cannot identify a track, so it cannot load the track chosen in Sidecar. See `plans/virtual-midi-deck-loader-2026-09/architect-blueprint.md` §1.3. The draft ADR in that plan was never written here; this entry records the outcome.
- **Consequence:** Any future deck-loading implementation (the ADR-015 `DECK_LOAD` capability) must show how it targets a **specific** track before it is accepted. `SeratoProvider` never declares `DECK_LOAD`, and its `load_to_deck` raises `DeckLoadNotSupported` (`source/providers/serato/provider.py:142-149`).

---

### ADR-015: DJ library providers and per-provider library snapshots

- **Status:** Accepted
- **Date:** 2026-11-05 (implemented in commit `4578d5c`)
- **Supersedes in part:** ADR-007 (single `track_cache.json` → one snapshot per provider, schema v4); ADR-005 (Serato default-path detection moves from `config.py` into `SeratoProvider`).
- **Relates to:** ADR-008 (data-dir rename and copy-forward; `AppId` unchanged; mandatory native dependency), ADR-009 (lazy import and degradation, reused for `pyrekordbox`), ADR-012 (`SuggestionFilters.allowed_crates` stays `frozenset[str]`, but now holds crate **ids**), ADR-013 (`date_added` stays file creation time for every provider), ADR-014 (sets the bar for `DECK_LOAD`).
- **Design record:** `plans/dj-library-providers-2026-11/architect-blueprint.md` (the full D1–D12 text, risks R1–R20) and `implementation-plan.md`. This ADR summarises the decisions **as built**. Where the blueprint and the code differ, the code is described here.

#### Context
Sidecar was built as a Serato companion. Serato-specific parsing, paths and naming ran through config, services, the model loader, app orchestration and the settings dialog. The user moved to rekordbox and wants to enable either source or both, with rekordbox read live from its database. The crate filter used display names as identities, so same-named crates from two sources would have collided. The cache was one file with no notion of where its data came from. The user also wanted deck loading to be part of the provider contract, even though no provider can do it yet.

#### Decision

**D1: A `LibraryProvider` protocol is the only place DJ-software knowledge lives.** Package `source/providers/`:
- `base.py`: the contract. A stdlib-only leaf, guarded by `tests/providers/test_base_isolation.py`.
- `registry.py`: `PROVIDERS` (insertion order = display order, fresh-install detection order and merge precedence: **rekordbox, then serato**, `registry.py:19-22`), `get_provider`, `all_providers` and `first_deck_load_provider`.
- `serato/` and `rekordbox/`.

Providers are **stateless** with respect to the contract: settings are passed into every call. Pure memo caches that change only speed, never results, are allowed (the rekordbox energy cache). **Nothing outside `source/providers/` imports a concrete provider except `registry.py`.** Providers may use the leaf helpers in `source/services/` (`tag_reader`, `camelot`, `file_times`, `comment_format`, `log_safety`, `crate_parser`). They never use UI, `config` accessors or the library store.

**The contract** (`source/providers/base.py:125-175`):

| Member | Meaning |
|---|---|
| `id` | Persisted. **Never rename** (`"serato"`, `"rekordbox"`) |
| `display_name` | Vendor styling: `"Serato DJ"`, `"rekordbox"` (lowercase, even at the start of a sentence) |
| `crate_noun` | `"crate"` (Serato) or `"playlist"` (rekordbox). The UI pluralises with "s". Rule for the shown word: Serato only → "Crates"; any rekordbox → "Playlists" (`library_copy.crate_noun_for`, `source/services/library_copy.py:85-96`) |
| `setting_specs()` | `SettingSpec` list (`key`, `env_key`, `label`, `kind`, `choices`, `visible_when`, `file_patterns`, `placeholder`, `hint`, `browse_title`, `required`, `secret`). The settings dialog renders from these and never branches on a provider id |
| `default_settings()` | Platform-aware defaults (stat calls only) |
| `detect()` | True if this DJ app's library appears to exist. Used for first-run defaults only |
| `detected_values(settings)` | Values in effect for settings left **empty**: display only, never persisted, stat calls only, UI-thread safe. Serato returns `{}`; rekordbox returns `{"db_path": …}` only when the field is empty and an existing `master.db` is found (`rekordbox/provider.py:117-124`). Lets the dialog show the auto-detected database as a placeholder without provider branching. Added in Phase 3c |
| `capabilities(settings)` | A `frozenset[ProviderCapability]`. It depends on settings (rekordbox drops `CHANGE_DETECTION` when auto-update is off) |
| `validate(settings)` | Cheap and UI-thread safe; never imports optional dependencies (uses `importlib.util.find_spec`) |
| `scan(settings, progress)` | Blocking; background thread only. Returns a `ProviderSnapshot`; raises `ProviderError` |
| `change_token(settings)` | Stat-only, any thread. `None` unless `CHANGE_DETECTION` is declared |
| `load_to_deck(settings, track_path, deck)` | 1-based deck; may block, so call it off the Tk thread. Raises `DeckLoadNotSupported` unless `DECK_LOAD` is declared |

**Capability flags** (`base.py:61-66`):

| Capability | Serato | rekordbox | Rule |
|---|---|---|---|
| `PLAYLIST_FOLDERS` | yes | yes | Crates have a hierarchy (`CrateInfo.path`) |
| `SMART_PLAYLISTS` | no | no | rekordbox smart playlists are read defensively if pyrekordbox can evaluate them, but the capability is not declared (unverified; the user has none) |
| `NATIVE_PLAY_COUNT` | yes | yes | The provider's play count is authoritative. **Merge consequence:** the highest-precedence record's `play_count` wins **even when it is 0** (D6) |
| `CHANGE_DETECTION` | no (a scan re-reads every tag; too heavy to run automatically) | yes while `REKORDBOX_AUTO_REFRESH=on` | `change_token()` must return `None` without it (contract-tested) |
| `DECK_LOAD` | no (ADR-014) | no (Phase 6 follow-up) | `load_to_deck()` must raise `DeckLoadNotSupported` without it (contract-tested) |

**Message convention:** `ProviderIssue.message` and `ProviderError` text are short phrases with an initial capital, no trailing period, no provider name and no file path (`base.py:11-13`). They must fit the 75-character partial-failure toast.

**D2: A provider produces a `ProviderSnapshot`.** Tracks are keyed by the provider-native absolute path, as `TrackRecord` dicts (the existing cache track schema plus `crates: list[crate_id]`), plus a crate index `dict[crate_id, CrateInfo]` that includes empty crates. Providers never build `Track` objects and never touch `TrackLibrary`.

**D3: Crates have globally unique ids, separate from their labels.** `crate_id = f"{provider_id}:{native_id}"`: the Serato `.crate` filename stem (`serato:House%%Bangers`) or the rekordbox `djmdPlaylist.ID` (`rekordbox:41`). `CrateInfo` carries `label`, `path` (folder hierarchy, leaf last), `provider_id` and `is_smart`. `Track.crates` and `SuggestionFilters.allowed_crates` hold **ids**; the UI shows labels only. Same-named crates from two providers are distinct entries, grouped by provider in the filter. Stable ids let a live refresh keep the filter selection.

**D4: One snapshot per provider (schema v4).** `user_data_dir()/library/<provider_id>.json` holds `schema`, `provider`, `synced_at`, `fingerprint`, `change_token`, `content_hash`, `crates` and `tracks`. **As built, there is also a small `<provider_id>.meta.json`** (`synced_at`, `change_token`, `content_hash`, `fingerprint`, counts; `library_store.py:180-193`). When a sync's content hash is unchanged, only the metadata file is rewritten, so the live-refresh baseline advances without rewriting a multi-megabyte file every minute. `load_snapshot` takes the token from the metadata only when its hash matches the snapshot. All writes are atomic (temp file + `replace_with_retry`), and orphan `*.tmp` files older than 60 s are cleaned at startup. Why one file per provider:
- syncing one provider never rescans another;
- a failed sync keeps that provider's last good snapshot (the safety net for a rekordbox upgrade that breaks decryption);
- disabling a provider just skips its file, so re-enabling it is instant;
- the merge stays a pure in-memory function.

A schema or provider mismatch makes that one file load as "no snapshot" (the ADR-007 rule, per file).

**D5: Sync is orchestrated by `services/library_sync.py`, which replaces `crate_sync.py`.** One daemon thread scans the requested providers **sequentially** and saves each snapshot. It returns a `SyncReport` with one `ProviderSyncResult` per provider: counts, warnings, error, `changed` and `change_token`. Error policy: providers raise `ProviderError` for configuration-level failures; per-track problems become snapshot warnings; the orchestrator catches `ProviderError` and `OSError` per provider, plus **one** documented last-resort `except Exception` at the thread boundary (`library_sync.py:80-84`). One provider's failure never stops the others. `SyncCoordinator` (`library_sync.py:123-253`) is single-flight: requests that arrive during a run are coalesced into one follow-up, merged by provider id. The follow-up is silent only if every merged request was silent.

**D6: The multi-provider merge is a pure function (`services/library_merge.py`).** The input is the enabled providers' snapshots in **precedence order** (registry order, rekordbox first; `PROVIDERS_ENABLED` is written in that order). The output is merged tracks keyed by `path_key` and the combined crate index.
- **Identity is the path only:** `path_key = NFC(normcase(normpath(p)))` in the leaf module `source/models/path_identity.py`. No fuzzy matching. Phase 0 confirmed that rekordbox's `OrgFolderPath` matches every Serato track path in the user's library.
- **Precedence rules** (`library_merge.py:5-18`, `:59-84`):
  - `crates` is the ordered **union** of ids. `sources` (`Track.sources`) is the ordered tuple of provider ids that contain the file. `full_file_path` comes from the highest-precedence record.
  - Every other field takes the first **non-empty** value in precedence order (`""`, `0`, `0.0` and `None` count as empty). So **rekordbox wins per non-empty field**, and Serato only fills fields that rekordbox leaves empty. A shared track shows rekordbox's comment, even when Serato's is the structured one.
  - **`key` and `camelot_key` are taken as a pair** from the first record with a non-empty `camelot_key`, so a track never shows one provider's key beside the other's Camelot value.
  - **`play_count`:** if the highest-precedence record's provider declares `NATIVE_PLAY_COUNT`, its value wins **even when it is 0**. Both providers declare it, so rekordbox's play count always wins for shared tracks. The app passes the declaring ids (`app.py:289-294`).
  - Crate-id collisions across snapshots indicate a bug: they are logged and the first is kept.
- `TrackLibrary.replace_all(tracks, crates)` receives the merged data. The library reloads from **stored** snapshots, so a provider whose latest sync failed still contributes its older data.

**D7: Settings stay in `settings.env`, keyed `<PROVIDER>_<SETTING>`.** `PROVIDERS_ENABLED=rekordbox,serato` (ordered; the order is the merge precedence). `SERATO_SUBCRATES_DIR` keeps its legacy name. `REKORDBOX_DB_PATH` (blank = auto-detect) and `REKORDBOX_AUTO_REFRESH=on|off` (default `on`). `SETTINGS_SCHEMA=2`. **No key setting:** the rekordbox key is built into pyrekordbox 0.5.0. `SettingKind.TEXT` and `SettingSpec.secret` exist in the contract but are unused. `services/settings_migration.py` runs once at startup:
- an existing install gets `PROVIDERS_ENABLED=serato`;
- a fresh install enables whatever `detect()` finds, rekordbox first;
- the settings file is backed up once (`settings.env.pre-schema2.bak`), and nothing is ever deleted.

The dialog's Save writes the enabled list and every provider's values in **one** atomic write (`config.save_library_settings`, `source/config.py:174-190`).

**D8: The rekordbox provider reads a private copy of `master.db`.**
- **Copy-then-read (the read-only rule).** `rekordbox/db_copy.py` copies `master.db` and, when present, `master.db-wal`, `master.db-journal` and `masterPlaylists6.xml` into a fresh `tempfile.mkdtemp(prefix="sidecar-rb-")` folder (`db_copy.py:27-45`). **`master.db-shm` is not copied:** it is SQLite's shared-memory index, which SQLite rebuilds from `-wal` on the copy. A copied `-shm` can be inconsistent with the copied `-wal`, and the no-`-shm` copy is what Phase 0 verified while rekordbox was running. **SQLite never opens anything in rekordbox's folder**; opening the original in place would write `-shm`.
- **Torn-copy guard:** the change token is taken before and after copying, with up to 3 attempts 200 ms apart (`db_copy.py:69-89`). The copy must then pass `PRAGMA quick_check`; on failure the provider re-copies once (`provider.py:163-175`). If it still fails, the scan raises `ProviderError("Database is busy, try again")` and the last good snapshot stays loaded. The temp folder is deleted in `finally`, and stale `sidecar-rb-*` folders older than one hour are removed at the start of the next scan.
- **Only `rekordbox/db_reader.py` imports `pyrekordbox` or SQLAlchemy**, lazily (ADR-009 pattern). If the import fails, `validate()` reports `Not available in this build`, `scan()` raises the same message, and Serato keeps working. The reader calls no write API, even on the copy. It closes the database and disposes the engine so that Windows releases the file handles.
- **Key and log safety (requirement; tested).** Sidecar never passes, stores or logs a key. `services/log_safety.py` holds the **`pyrekordbox` logger tree at ERROR** and the **`sqlalchemy` tree at WARNING**, or stricter (`log_safety.py:19-22`). It is called in `main.py` before any project import, again after pyrekordbox is imported, and again after the engine is created. The `db_reader` boundary catches every pyrekordbox/SQLAlchemy exception, logs only the **type name**, and raises a fixed-text `ProviderError` outside the `except` block, so neither `__cause__` nor `__context__` carries the original message (`db_reader.py:223-237`).
- **Scope and mapping:** "crates" are playlists (`Attribute` 0, plus 4 = smart, read best-effort); folders (`Attribute` 1) only form `CrateInfo.path`. The library contains only tracks that are in at least one playlist, as with Serato. The path is resolved by `rekordbox/paths.resolve_track_path`: `OrgFolderPath` → local `FolderPath` (not `/contents_…`) → `rb_LocalFolderPath`, preferring a file that exists, then `os.path.normpath` to native separators. rekordbox's analysed key wins over any key in the comment. BPM is stored ×100. Energy follows the user's option (a): the comment's energy when it parses as `<key> - <energy> - …`, otherwise the file's `TXXX:EnergyLevel` tag (ID3 only), memoised in `energy_cache.py` by `(path_key, mtime_ns, size)`, otherwise 0. Rating, Colour, My Tag and `StockDate` are not mapped.

**D9: `date_added` stays file creation time for every provider** (ADR-013), read from the resolved path.

**D10: Rebrand to "Sidecar"; internal identities stay stable.** See the ADR-008 amendment: display name "Sidecar", file identifier `DJSidecar`, data dir `SeratoSidecar` → `DJSidecar` with a copy-forward migration. `AppId`, the updater manifest URL, `bundle_identifier`, provider ids and the logo asset do not change.

**D11: Live refresh by polling a stat-only change token (`services/library_watcher.py`).**
- **Token:** for rekordbox, `(st_mtime_ns, st_size)` of `master.db` **and** `master.db-wal`, with a missing file recorded as absent (`rekordbox/paths.py:56-69`). rekordbox writes to `-wal` first, so the token must include it. `-shm` is excluded because it changes with rekordbox's own reads and checkpoints. Serato returns `None`.
- **Policy** (constants in `source/config.py:226-234`; decisions are the pure functions `should_refresh` and `record_refresh_result`):
  - **Poll** every `REFRESH_POLL_SECONDS` = **10 s** on one daemon thread. Targets are the enabled providers that declare `CHANGE_DETECTION`.
  - A token that differs from the one in the provider's stored snapshot must stay stable for `REFRESH_SETTLE_SECONDS` = **5 s** (the write burst is over).
  - At most **one refresh per provider per `REFRESH_MIN_INTERVAL_SECONDS` = 60 s**.
  - **Adaptive backoff:** every **3** consecutive refreshes that changed nothing **double** the effective minimum interval, up to `REFRESH_MAX_INTERVAL_SECONDS` = **300 s**. An idle rekordbox rewrites its WAL about every 30 s. Any real change, or a manual sync, resets the interval to 60 s.
  - **Refresh on focus:** when the main window regains focus (`<FocusIn>`, debounced to one check per 2 s burst, `app.py:375-379`), a provider whose token differs from its baseline is refreshed at once, with no settle wait, provided at least `REFRESH_FOCUS_FLOOR_SECONDS` = **30 s** have passed since its last request. The floor is 30 s so that switching focus cannot bypass the backoff.
  - The stored token survives restarts, so the first tick at startup picks up changes made while Sidecar was closed.
- **A refresh is a silent sync of that one provider.** If `content_hash` is unchanged, nothing reloads. Otherwise `app._reload_library(preserve_state=True)` keeps the current track, setlist, filter selections and any playing preview, and no "Synced" toast is shown. A background failure shows one amber toast per distinct error. `REKORDBOX_AUTO_REFRESH=off` turns the watcher off for rekordbox; the change is picked up on the next tick, with no restart.

**D12: Load-to-deck is a reserved capability that no provider implements.** `ProviderCapability.DECK_LOAD` + `load_to_deck(settings, track_path, deck)`. **Both providers raise `DeckLoadNotSupported`**: Serato because of ADR-014 (`serato/provider.py:142-149`), rekordbox because it is the Phase 6 follow-up (`rekordbox/provider.py:157-159`). The single gate is `registry.first_deck_load_provider(provider_ids, settings_for)` (`registry.py:35-53`), which returns `None` today. **UI rule:** any deck-load control stays hidden while that gate returns `None` for the track's `sources`. Phase 6 needs its own ADR that meets ADR-014's bar.

#### Accepted layering exception
`services/diagnostics.py` imports `providers.rekordbox.paths` (`TOKEN_FILES`, `resolve_db_path`; `diagnostics.py:24-26`), the only import of a concrete-provider module outside `source/providers/` and `registry.py`. **Accepted** because the diagnostics are rekordbox-specific by purpose: `--self-check-rekordbox` (CI: the frozen build can import pyrekordbox and load SQLCipher, with no DB access) and `--check-rekordbox-library` (the upgrade runbook: a counts-only report with no titles, paths or key, home folder shown as `~`). Sharing the provider's path rule means the report and the provider cannot drift apart. No other module may follow this precedent without its own note here.

#### Consequences
- Pro: A third source means a new subpackage plus a registry entry. The engine, filters, session and playback do not change.
- Pro: Serato behaviour is guarded by a golden-equivalence test across the refactor (`tests/services/test_serato_equivalence.py`). An existing Serato user upgrades with no visible change.
- Pro: Crate identity is separated from display, which fixes a latent collision and lets a live refresh keep the filter state.
- Pro: rekordbox is live, with no export step and a sub-second read. Reading a private copy leaves rekordbox's folder untouched, even while rekordbox runs.
- Con: A mandatory native dependency (`sqlcipher3-wheels`) is in the product, and the decryption key lives in a third-party library. A rekordbox upgrade may break reading until pyrekordbox is updated and re-pinned (accepted; runbook in `docs/deployment-guide.md`). The last good snapshot keeps the app usable in the meantime.
- Con: pyrekordbox logs the key at DEBUG. This is a standing constraint: its loggers must never be turned down, and the guard is tested.
- Con: The energy fallback adds tag reads to rekordbox scans. They are limited to in-scope tracks without comment energy and memoised for the life of the process. The reader is ID3-only, so non-MP3 tracks get energy 0 unless the comment carries it.
- Con: More moving parts: about 20 new modules, a persisted format plus a converter, a watcher thread, and short-lived temp copies of the user's database.
- Con: The contract carries a method (`load_to_deck`) that no provider implements yet.
- Future option (not planned): an XML-export source mode inside `source/providers/rekordbox/`, without contract changes.
