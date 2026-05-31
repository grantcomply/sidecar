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
  - **v2** (ADR-011, 2026-05-30) — adds `date_added` (Unix timestamp float): the first-seen-in-cache time for the track, seeded from file `mtime` on first sight and carried forward unchanged across subsequent syncs. `CACHE_VERSION` is now `2` (`source/services/cache.py:16`). Because a version mismatch makes `load_cache` return `None` (see below), the bump forces a **one-time, self-healing re-sync** on upgrade — old v1 caches are ignored, every track is freshly mtime-seeded, and no bespoke migration code is needed. See ADR-011 Decision B.

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

  **5. `platformdirs` for user data locations.** Considered hand-rolled `os.environ["APPDATA"]` / `~/Library/Application Support` lookups. `platformdirs` is small, pure-Python, well-maintained, and correctly handles edge cases (XDG fallback on Linux, roaming vs local on Windows). Cache and settings live in `%APPDATA%\SeratoSidecar\` on Windows and `~/Library/Application Support/SeratoSidecar/` on macOS so they survive upgrades — PyInstaller bundles extract into read-only temp dirs, so storing user data next to the exe is not an option.

- **Consequences:**
  - Pro: Zero ongoing hosting cost, zero signing cost, free CI minutes on macOS.
  - Pro: Friends can install the app with one download and one click-through of a security prompt.
  - Pro: User data is preserved across upgrades automatically; no migration logic needed per release.
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

- **Status:** Accepted
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
- Con: **First-sync add-dates are mtime-approximate** and cluster oddly for pre-existing libraries; accuracy improves over time as new tracks get real first-seen dates. This must be stated plainly to users (the UI Designer pinned honest caveat copy in the date panel: "Dates are approximate for tracks added before your first sync.").
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
