# Architect Blueprint: DJ Library Providers (Serato + rekordbox)

> **Status:** Proposed, revised 2026-11-05 after the user's answers and again after the Phase 0 spike (see "Revision log" at the end). **Phases 1 and 2 are implemented and approved. Phase 0 has run. Phase 3 is ready for the engineer.** No user question blocks implementation. See §10.
> **Date:** 2026-11-05
> **Author:** Architect agent (UI sections revised by the UI designer; see `ui-design-brief.md`)
> **Plan folder:** `plans/dj-library-providers-2026-11/`
> **Companion:** `implementation-plan.md` (same folder)
> **Related ADRs:** ADR-002 / ADR-007 (cache; **ADR-007's single-file structure is superseded in part**), ADR-005 (Serato path detection moves into the provider), ADR-008 (distribution: data-dir rename, installer identity, **new mandatory native dependency**), ADR-009 (lazy-import / degrade-to-no-op pattern, reused for `pyrekordbox`), ADR-012 (`SuggestionFilters`, unchanged in shape), ADR-013 (`date_added` = file creation time, **kept for every provider**). Records **ADR-014** (rejected MIDI deck loader) and proposes **ADR-015** (§2).

---

## 1. Context

### 1.1 The request (verbatim)
> "i have migrated from serato to rekord box. Let's please move this to be completely a rekord box sidecar. In fact, let's make this a provider approach as we already understand serato, let's make the interactions behind a provider and we can then make the new provider being rekord box. In the app, when configuring you can set which providers you use and i'll be able to add rekordbox and keep serato selected, or just have one of them selected."

Follow-up decisions from the user (2026-11-05):
- rekordbox is read **live from its library database** (`master.db` via `pyrekordbox`), not from an XML export. The user accepts maintaining this across rekordbox upgrades.
- For rekordbox tracks, **rekordbox's own analysis and fields are the source of truth**. The one exception is energy, which rekordbox doesn't have: it comes from the rekordbox comment when that carries an energy number, otherwise from the file's energy tag (user decision after Phase 0, option (a)).
- The product name is **"Sidecar"**. The logo stays untouched for now.
- Music files are at the **same paths** in both libraries, so path-based de-duplication is enough. Phase 0 confirmed this, provided rekordbox's `OrgFolderPath` is used (D8).
- **Load-to-deck is part of the provider interface** from Phase 1. Serato does not support it. rekordbox support is a follow-up after this feature.

What that means here:
1. Put every DJ-software-specific interaction behind a **library provider** boundary: finding the library, listing crates/playlists, resolving track paths, reading metadata, producing a library snapshot, detecting changes, and (as a capability) loading a track to a deck.
2. Move the existing Serato code behind a `SeratoProvider` with **no change in behaviour** (done, Phase 1).
3. Add a `RekordboxProvider` that reads a **private copy** of `master.db` and refreshes automatically when rekordbox changes its library.
4. Let the user enable Serato only, rekordbox only, or both, each with its own settings. When both are enabled, merge the libraries: remove duplicate files and keep each crate/playlist tied to its provider.
5. Rebrand to "Sidecar" and migrate existing settings and cache so an upgrading Serato user loses nothing.

### 1.2 Where Serato assumptions lived (inventory; line numbers as of commit `ccac83b`, before Phases 1–2)

| Concern | Location | Notes |
|---|---|---|
| Serato default path | `source/config.py:33` (`FALLBACK_SUBCRATES_DIR`) | ADR-005. Moved to `SeratoProvider.default_settings()` in Phase 2 |
| Serato setting accessors | `source/config.py:75-85` (`get_subcrates_dir` / `save_subcrates_dir`, key `SERATO_SUBCRATES_DIR`) | Replaced by generic accessors in Phase 2 |
| App data dir name | `source/config.py:12` (`_APP_NAME = "SeratoSidecar"`), used by `user_data_dir()` `:15-28` | ADR-008 §5. Holds `settings.env` and the library snapshots |
| `.crate` binary parsing | `source/services/crate_parser.py:30-57` | Serato-only |
| Music root for relative crate paths | `source/services/crate_parser.py:18`, used at `:216` | Serato-only (crate paths have no drive/root) |
| Crate display names | `source/services/crate_parser.py:163-170` (`%%` → ` - `) | Serato-only |
| ID3 tag reading | `source/services/crate_parser.py:69-160` (now `source/services/tag_reader.py`) | Generic apart from `TXXX:SERATO_PLAYCOUNT`. Used by Serato for everything, and by rekordbox **for the energy fallback only** (D8) |
| Key → Camelot | `source/services/crate_parser.py:20-27, 60-66` (now `tag_reader.py:15-31`) | Generic. Reused by rekordbox for `djmdKey.ScaleName` |
| Whole-library scan | `source/services/crate_parser.py:173-238` (`parse_all_crates`) | Serato orchestration |
| Background sync | `source/services/crate_sync.py:7-37` | Replaced by `library_sync.py` (Phase 1) |
| Cache | `source/services/cache.py:16-108` | Replaced by `library_store.py` (Phase 2) |
| Library load | `source/models/library.py:54-73`; crate names `:75-81` | Replaced by `replace_all` / `crate_items` (Phase 2) |
| App orchestration | `source/app.py` | `_sync_finished` stops audio and resets the crate list on every sync (now `source/app.py:344-364`) |
| Settings dialog | `source/ui/sync_panel.py:7-83` | Serato-only UI until "Phase 3c" |
| Crate display | `source/ui/suggestion_panel.py:209-210`, `:476-477`, `source/ui/track_detail.py:165-169`, `source/ui/filter_bar.py:321-350` | Keyed by id since Phase 2 |
| Crate filter | `source/services/suggestion_filters.py:27,54`; `source/services/suggestion_engine.py:98` | Works with any hashable string id |
| Branding | `source/app.py:38` (now), `source/ui/sync_panel.py:12`, `serato-sidecar.spec:29,41,151`, `build/installer.iss:21-22,40,44,64-65`, `.github/workflows/release.yml:8-9,115-130,180-194`, `source/ui/SeratoSidecarLogo.png` (left untouched), `README.md`, `docs/*`, `CLAUDE.md` | §7 |

### 1.3 Facts that constrain the design
- **There is no "category" field and no category affinity in the code.** `SUGGESTION_WEIGHTS` contains only key/energy/bpm (`source/config.py:155`), and `Track` has no category field. Comments are stored raw and only displayed. **Phase 0:** none of the user's rekordbox comments name a category. About 14% start with `"<Camelot> - <energy>"`; most are free text (e.g. `Commercial`). Category stays display-only and is usually empty.
- **rekordbox has no energy field** (confirmed for rekordbox 7.2.19). The user chose **option (a)**:
  1. Use the energy number from the rekordbox comment when it parses as `"<key> - <energy> - ..."`.
  2. Otherwise read the file's `TXXX:EnergyLevel` tag, the same way Serato does today (`source/services/tag_reader.py:92-99`).

  Tag reads happen only for in-scope tracks without comment energy, and are cached by file mtime and size (D8).
- **rekordbox's file path field is not `FolderPath`.** For about 96% of tracks `DjmdContent.FolderPath` holds an internal `/contents_<id>/...` value, not a local path. `rb_LocalFolderPath` is always empty. `OrgFolderPath` holds the real local path (`C:/...`, forward slashes): 1,203 of 1,248 exist on disk, and it matches **all 700** Serato tracks exactly after `path_key`. The path-resolution rule is in D8.
- **`date_added` is file creation time** (ADR-013). rekordbox's `StockDate` is the import date (the migration date for this user), so it is a worse signal. Keep ADR-013 for all providers (D9). It costs one `stat` per rekordbox track on the resolved path.
- **A library reload resets crate filter selections.** `FilterDropdown.set_items` rebuilds every checkbox as checked, and `_sync_finished` stops audio preview (`source/app.py:349-351`). That is acceptable for a manual sync, but not for **automatic** refresh (D11).
- **Deck loading: the hard part is still unsolved, but the interface reserves it.** See ADR-014 and D12. No provider declares `DECK_LOAD` in this feature. **The read-only boundary towards DJ-software files stays:** providers never write to `_Serato_` or to anything in rekordbox's folder. For rekordbox, "never write" includes SQLite's `-shm` file, which is why Sidecar reads a private copy (D8).
- Shipping targets are Windows and macOS on bundled Python 3.11 (ADR-008, ADR-013). macOS is built but unverified (`docs/cross-platform-guide.md:10`). **Phase 0 ran on Windows only.**

### 1.4 rekordbox integration: decision (confirmed by Phase 0)

**Chosen: `master.db` via `pyrekordbox`, read from a private temporary copy, as the only rekordbox source mode.**

| Aspect | Design (Phase 0 result in *italics*) |
|---|---|
| Version and location | Windows `%APPDATA%\Pioneer\rekordbox\master.db`; macOS `~/Library/Pioneer/rekordbox/master.db` (*macOS unverified*). Overridable (`REKORDBOX_DB_PATH`). *rekordbox 7.2.19; WAL mode; `-wal` and `-shm` exist only while rekordbox runs* |
| How | **Copy-then-read** (D8): copy `master.db` + `master.db-wal` (+ `masterPlaylists6.xml`) into a private temp folder, open **the copy** with pyrekordbox on the sync thread, read, close, delete the copy. *The copy took 0.01 s while rekordbox was running; the copy's `PRAGMA quick_check` = ok; every rekordbox file was unchanged afterwards.* Opening the original in place would write to `-shm`, which breaks the read-only rule |
| Speed | *A full read of 1,248 tracks, 98 playlist rows and 2,922 entries took 0.39 s* |
| Freshness | Live. A stat-only change token on `master.db` **and `master.db-wal`** is polled and triggers an automatic background re-scan (D11) |
| Dependencies | **Pinned:** `pyrekordbox==0.5.0`, `sqlcipher3-wheels==0.5.7` (native), `SQLAlchemy==2.1.8` (*all installed as Python 3.11 wheels on Windows*). Real dependencies in `requirements.txt` and the PyInstaller build, but still **lazy-imported** (ADR-009), so the app starts and Serato works if they fail to load |
| Encryption key | *Built into pyrekordbox 0.5.0: no download, no configuration.* Sidecar never passes, stores, logs or commits a key. **pyrekordbox logs the key at DEBUG**, so Sidecar pins the `pyrekordbox` and `sqlalchemy` loggers at WARNING and turns every pyrekordbox/SQLAlchemy exception into a fixed message (D8, tested) |
| Playlists | `djmdPlaylist` (`Attribute` 0 = playlist, 1 = folder, 4 = smart; `ParentID` hierarchy) + `djmdSongPlaylist` (`TrackNo` order). *75 playlists, 23 folders, 0 smart playlists; 740 of 1,248 tracks are in at least one playlist* |
| Track fields used | `Title`, `ArtistName`, `AlbumName`, `GenreName`, `BPM` (×100, *confirmed*), `Key.ScaleName` (*mostly musical notation, a few Camelot, 8 unanalysed; all analysed keys map to Camelot*), `Commnt`, `DJPlayCount`, `ReleaseYear` (0 = unknown), `OrgFolderPath` / `FolderPath` / `rb_LocalFolderPath`. **Not used:** Rating, Colour, My Tag (*0 tracks use them*), `StockDate` (import date) |
| Risk | Medium–high: native dependency, schema drift, and the key built into a third-party library. Mitigations in §9. The user accepted maintaining this across rekordbox upgrades |

**XML export: not built, not needed as a fallback.** The last good rekordbox snapshot keeps loading if a rekordbox update breaks decryption (D4). If the DB route ever becomes impossible, an XML source mode can be added inside `source/providers/rekordbox/` without changing the contract.

---

## 2. Decisions: ADR-014 (record) and ADR-015 (proposed); text to copy into `docs/architecture-decisions.md` at merge

### 2.0 ADR-014: record the rejected MIDI approach
`plans/virtual-midi-deck-loader-2026-09/architect-blueprint.md` drafted an "ADR-014" that was never written into `docs/architecture-decisions.md` (the commit history marks that plan as failed). It is still relevant: its central finding constrains the new `DECK_LOAD` capability. **At merge, record:**

> ### ADR-014: Virtual MIDI deck loader (Serato)
> - **Status:** Rejected
> - **Date:** 2026-09-19 (recorded 2026-11-05)
> - **Context / finding:** A virtual MIDI note mapped to "Load to Deck" loads whatever track is *selected in the DJ app's own browser*. The note cannot identify a track, so it cannot load the track chosen in Sidecar. See `plans/virtual-midi-deck-loader-2026-09/architect-blueprint.md` §1.3.
> - **Consequence:** Any future deck-loading implementation (ADR-015 `DECK_LOAD` capability) must show how it targets a **specific** track before it is accepted.

---

### ADR-015: DJ library providers and per-provider library snapshots

- **Status:** Proposed
- **Date:** 2026-11-05
- **Supersedes in part:** ADR-007 (single `track_cache.json` → one snapshot file per provider, schema v4); ADR-005 (Serato default-path detection moves from `config.py` into `SeratoProvider`).
- **Relates to:** ADR-008 (data-dir rename + migration; installer `AppId` must not change; mandatory native dependency `pyrekordbox`/`sqlcipher3-wheels`), ADR-009 (lazy import / degradation, reused for `pyrekordbox`), ADR-012 (`SuggestionFilters.allowed_crates` stays `frozenset[str]` but now holds crate **ids**), ADR-013 (`date_added` stays file creation time for every provider), ADR-014 (constrains the `DECK_LOAD` capability).

#### Context
Sidecar was built as a Serato companion. Serato-specific parsing, paths and naming ran through config, services, the model loader, app orchestration and the settings dialog (inventory: blueprint §1.2). The user has moved to rekordbox and wants to enable either or both sources, with rekordbox read live from its database. The crate filter used display names as identities, so same-named crates from two sources would collide. The cache was one file with no notion of where data came from. The user also wants deck loading to be part of the provider contract, even though no provider implements it yet.

#### Decision

**D1: A `LibraryProvider` protocol is the only place DJ-software knowledge lives.** Package `source/providers/`:
- `base.py`: the contract, a stdlib-only leaf;
- `registry.py`: the registry;
- `serato/` and `rekordbox/`.

A provider is **stateless** with respect to the contract: settings are passed into every call. Pure memo caches inside a provider (the energy tag cache, D8) are allowed, because they never change results, only speed. Nothing outside `source/providers/` may import a concrete provider except `registry.py`. Providers may depend on `source/services/` leaf helpers (`tag_reader`, `camelot`, `file_times`, `comment_format`, `log_safety`) but **never** on UI, `config` accessors, or the library store. Contract: §3.

**D2: A provider produces a `ProviderSnapshot`, a normalised, serialisable view of its library.** It has tracks keyed by the provider's native absolute path (values follow the existing cache track-dict schema plus `crates: list[crate_id]`) and a crate index `dict[crate_id, CrateInfo]`. Providers never build `Track` objects and never touch `TrackLibrary`.

**D3: Crates get globally unique string ids, separate from their labels.** `crate_id = f"{provider_id}:{native_id}"`, where `native_id` is the provider's most stable identifier: the Serato `.crate` filename stem (`House%%Bangers`) or the rekordbox `djmdPlaylist.ID`. `CrateInfo` carries:
- `label`: provider-formatted display text, e.g. Serato `House - Bangers`, or rekordbox `Club / Peak`;
- `path`: the folder hierarchy;
- `provider_id` and `is_smart`.

`Track.crates` holds **ids**. `SuggestionFilters.allowed_crates` holds ids, so the engine and ADR-012 dirty detection are unchanged. The UI shows labels, never ids. Same-named crates from different providers are **distinct** entries, grouped by provider in the filter (UI brief §5.10). Stable rekordbox playlist ids are what let automatic refresh keep filter selections (D11).

**D4: One snapshot file per provider (cache schema v4).** `user_data_dir()/library/<provider_id>.json`, holding:
- `schema`, `provider`, `synced_at`;
- `fingerprint`: Serato crate mtimes, or the rekordbox `master.db` / `master.db-wal` mtimes;
- `change_token`: the provider's token at scan start (D11);
- `content_hash`: a hash of `tracks` + `crates`, used to skip no-op reloads;
- `crates` and `tracks`.

Writes are atomic. Why per-provider instead of one merged file:
- Syncing one provider never rescans another.
- A failed sync keeps that provider's last good snapshot. This is the safety net for a rekordbox upgrade that breaks decryption.
- Disabling a provider just skips loading its file, so re-enabling it is instant.
- The merge stays a pure in-memory function (D6).

The ADR-007 version-mismatch rule (return `None`, re-sync) applies per file.

**D5: Sync is orchestrated by `services/library_sync.py`, replacing `crate_sync.py`.** One daemon thread scans the requested providers **sequentially** and writes each snapshot on success. It reports a `SyncReport` (per-provider outcome: track count, crate count, warnings, error, `changed`). Error policy (debt #6):
- Providers raise `ProviderError` with a user-presentable message for configuration-level failures.
- Per-track problems become snapshot warnings.
- The orchestrator catches `ProviderError` and `OSError` per provider, plus **one** documented last-resort `except Exception` at the thread boundary.

Only one sync runs at a time. A request that arrives while one is running (manual or automatic) is coalesced into a single follow-up run (Phase 3b; Phase 2 ships a simpler re-entry guard).

**D6: Multi-provider merge is a pure function (`services/library_merge.py`).** Input: the snapshots of enabled providers, ordered by **precedence**. Precedence is registry order with rekordbox first, persisted as the order of `PROVIDERS_ENABLED` (D7). Output: merged track dicts plus the combined crate index.
- **Identity:** `path_key = unicodedata.normalize("NFC", os.path.normcase(os.path.normpath(p)))`, in the leaf module `source/models/path_identity.py`. rekordbox tracks are keyed by the path D8 resolves (normally `OrgFolderPath`, converted to native separators). Phase 0 confirmed that this key matches all 700 Serato tracks. Path is the only identity; fuzzy matching is out of scope.
- **Fields:** `crates` is the **union** of ids. `sources` is the set of provider ids that contain the track. Every scalar takes the first **non-empty** value in precedence order (`""`, `0`, `0.0` count as empty), except `date_added`, which is identical by construction (D9). With rekordbox first, a shared track's key, BPM, comments and energy come from rekordbox, and Serato only fills fields rekordbox leaves empty. That includes comments: a shared track shows rekordbox's comment (often free text) rather than Serato's. `full_file_path` comes from the highest-precedence provider.
- `TrackLibrary` receives already-merged data via `replace_all(tracks, crate_index)`. Loading lives in `services/library_store.py`.

**D7: Settings stay in `settings.env`, keyed `<PROVIDER_ID>_<SETTING>`.**
- `PROVIDERS_ENABLED=rekordbox,serato`: ordered, comma-separated, written in registry order. The order is the merge precedence.
- `SERATO_SUBCRATES_DIR`: **the existing key is unchanged**.
- `REKORDBOX_DB_PATH` (blank = auto-detect) and `REKORDBOX_AUTO_REFRESH=on|off` (default `on`).
- **No key setting.** The key is built into pyrekordbox 0.5.0. A future rekordbox encryption change needs a new pyrekordbox release anyway (the upgrade runbook), so a user-entered key would add a secret to store and protect for no realistic benefit. `SettingKind.TEXT` and `SettingSpec.secret` stay in the contract (Phase 1, final shape) but are unused for now.
- `SETTINGS_SCHEMA=2`.

Settings migration (`services/settings_migration.py`) is implemented (Phase 2):
- an **existing install** gets `PROVIDERS_ENABLED=serato`;
- a **fresh install** enables whatever is detected, rekordbox first;
- nothing is ever deleted.

**D8: rekordbox provider: database (private copy), rekordbox as source of truth, energy fallback from tags.**
- **Copy-then-read (read-only rule):**
  1. Before every read, copy `master.db` and, if present, `master.db-wal`, `master.db-journal` and `masterPlaylists6.xml` into a new private temp folder (`tempfile.mkdtemp(prefix="sidecar-rb-")`). The originals are only opened for reading by the copy routine. **SQLite never opens anything in rekordbox's folder.**
  2. `master.db-shm` is **not** copied. It is a shared-memory index that SQLite rebuilds from `-wal` on the private copy. A copied `-shm` can be inconsistent with the copied `-wal`, and Phase 0 verified the no-`-shm` copy. *(This deliberately differs from the coordinator brief's "copy db + wal + shm"; the rest of the brief is adopted.)*
  3. **Torn-copy guard:** take the change token (D11) before and after copying. If it changed, retry (up to 3 attempts, 200 ms apart). Then open the copy and require `PRAGMA quick_check` = `ok`. If it still fails, raise `ProviderError("rekordbox database is busy. Try again in a moment")`. The last good snapshot stays loaded.
  4. Open the copy with pyrekordbox in the **sync thread** (SQLite connections are thread-bound), read, then `close()` and `engine.dispose()` so Windows releases the file handles. Delete the temp folder in `finally`. Stale `sidecar-rb-*` folders older than one hour are removed at the start of the next scan, so a crash cannot leave copies behind for long.
  5. No write API is ever called, even on the copy.
- **Lazy import:** `pyrekordbox` is imported only inside `rekordbox/db_reader.py` (ADR-009 pattern). If the import fails, `validate()` reports an error and `scan()` raises `ProviderError("rekordbox support isn't available in this build")`. The app still starts and the last good snapshot still loads.
- **Key and log safety (requirement, tested):**
  - Sidecar never passes, stores or logs a key; pyrekordbox's built-in key is used.
  - `source/services/log_safety.py` pins the `pyrekordbox` and `sqlalchemy` loggers (and so their children) at **WARNING**. It is called from `main.py` right after logging is configured, and again inside `db_reader` immediately after importing pyrekordbox, in case pyrekordbox changes levels itself or the app's logging setup was skipped (tests, tools).
  - The adapter boundary in `db_reader` catches **every** exception from pyrekordbox or SQLAlchemy. It logs only the exception **type name** and re-raises a fixed-text `ProviderError(...) from None`, because SQLAlchemy/SQLCipher messages can embed the connection URL. So no key can reach the log, a traceback, a toast or a snapshot warning.
- **"Crates" = leaf playlists:** `Attribute` 0, and 4 = smart, included only if the pinned pyrekordbox can evaluate it, otherwise skipped with a warning; the user's library has none. Folders (`Attribute` 1) become `CrateInfo.path` prefixes; they are not crates.
- **Library scope = tracks in at least one playlist** (the Serato rule). Collection-only tracks are excluded (user default kept; 740 of 1,248 tracks are in scope).
- **Path resolution** (`rekordbox/paths.py`, pure, with an injectable `exists`), applied to each track's `OrgFolderPath`, `FolderPath` and `rb_LocalFolderPath`; first hit wins:
  1. `OrgFolderPath`, if non-empty and the file exists;
  2. `FolderPath`, if it is a local path (drive-letter or absolute OS path, **not** `/contents_…`) and the file exists;
  3. `rb_LocalFolderPath`, if non-empty and the file exists;
  4. `OrgFolderPath`, if non-empty (file missing; counted as a warning);
  5. `FolderPath`, if it is a local path (file missing; counted as a warning);
  6. otherwise, skip the track (counted as a warning: "no usable file path").

  The result goes through `os.path.normpath`, which turns forward slashes into native separators on Windows.
- **Field mapping:**

  | `TrackRecord` field | Source | Notes |
  |---|---|---|
  | `title`, `artist`, `album`, `genre` | `Title`, `ArtistName`, `AlbumName`, `GenreName` | Read with a defensive getattr (missing → `""`) against schema drift |
  | `bpm` | `BPM / 100` | ×100 confirmed |
  | `key` | `Key.ScaleName` | rekordbox's analysis **wins** over any key in the comment (they disagree for 29 of 179 tracks that have both) |
  | `camelot_key` | `tag_reader.to_camelot(ScaleName)` | Handles musical, Camelot and `♭`; unanalysed → `""` |
  | `comments` | `Commnt` | Raw |
  | `energy_level` | (1) `comment_format.parse_comment(Commnt).energy` when the comment parses as `<Camelot> - <1–8> - …`; (2) otherwise `tag_reader.read_energy_level(path)` for **in-scope tracks whose file exists**, through the energy cache; (3) otherwise `0` (neutral in scoring) | User option (a). The tag reader is ID3-only, so non-MP3 files fall through to `0` |
  | `play_count` | `DJPlayCount` | Never `SERATO_PLAYCOUNT` |
  | `date` | `ReleaseYear` as text; `0` → `""` | |
  | `date_added` | `file_times.file_creation_time(resolved path)`, `None` → `0.0` | ADR-013, D9 |
  | `full_file_path` / `file_name` | resolved path / basename | |

- **Energy tag cache** (`rekordbox/energy_cache.py`): a thread-safe in-process memo `{(path_key, st_mtime_ns, st_size): energy}`, shared across scans for the life of the process. The first scan after app start reads tags only for in-scope tracks without comment energy. That is the same order of cost as a Serato sync today, and it runs in the background. Later live refreshes cost only a `stat` per track. **Not persisted:** a disk cache would need provider-private storage, which the contract doesn't offer; revisit only if first-scan time is a problem in practice.
- **Not mapped:** Rating, Colour and My Tag (unused in the user's library); `StockDate` (import date).

**D9: `date_added` stays file creation time for every provider (ADR-013 holds).** rekordbox reads it from the **resolved** path (D8). Because both providers resolve to the same local file, merged tracks agree on `date_added` by construction.

**D10: Rebrand to "Sidecar"; keep internal identities stable.** (Details: §7.)
- **Change:** window title, dialog titles, README/docs, installer display name, exe and installer file names (identifier `DJSidecar`).
- **Change, with migration:** the platformdirs data dir (`SeratoSidecar` → `DJSidecar`), copy-forward.
- **Not now:** logo artwork and file name (user decision).
- **Never change:** Inno `AppId`, updater manifest URL, macOS `bundle_identifier`, provider ids.

**D11: Live refresh by polling a stat-only change token (`services/library_watcher.py`).**
- **Contract:** providers with `CHANGE_DETECTION` implement `change_token(settings) -> str | None`, using `stat` calls only.
  - For rekordbox the token is `(st_mtime_ns, st_size)` of **`master.db` and `master.db-wal`**, with a missing file recorded as absent. rekordbox's writes land in `-wal` first, so the token must include it.
  - `-shm` is **excluded**: it changes with rekordbox's own reads and checkpoints, which would cause refreshes that change nothing.
  - Serato returns `None` in this feature.
- **Watcher:** one daemon thread polls every `REFRESH_POLL_SECONDS` (10). It requests a refresh when:
  - the token differs from the one stored in the provider's snapshot;
  - the token has been stable for `REFRESH_SETTLE_SECONDS` (5);
  - at least `REFRESH_MIN_INTERVAL_SECONDS` (60) have passed since the last refresh.

  The decision is a pure function (`should_refresh`). The constants are defaults; Phase 0 did not measure write-burst timing, so tune them in Phase 3b against real use. Because the stored token survives restarts, the app also refreshes once on startup if rekordbox changed while Sidecar was closed.
- **Why polling:** no new dependency, the same behaviour on Windows and macOS, it sees WAL-only writes, and 2 `stat` calls every 10 s cost almost nothing.
- **Refresh = a silent sync of that one provider.** If `content_hash` is unchanged, nothing reloads. Otherwise `app._reload_library(preserve_state=True)` keeps the current track, session, filter selections and any playing audio, and shows no standard sync toast. A manual sync keeps today's behaviour.
- **Off switch:** `REKORDBOX_AUTO_REFRESH=off`.

**D12: Load-to-deck is a provider capability, reserved in the contract from Phase 1, implemented by no provider in this feature.**
- **Contract:** `ProviderCapability.DECK_LOAD` + `load_to_deck(settings, track_path, deck) -> None`. `deck` is 1-based. The method may block, so callers run it off the Tk thread. A provider without `DECK_LOAD` must raise `DeckLoadNotSupported` (contract-tested).
- **Serato:** not supported (ADR-014). **rekordbox:** not supported in this feature (Phase 6 follow-up).
- **UI hook rule:** any deck-load control stays **hidden** while no enabled provider declares `DECK_LOAD` for the track's sources. The single gate is `registry.first_deck_load_provider(...)` (implemented in Phase 2), wrapped by the app.

#### Consequences
- Pro: Adding a third source means a new subpackage and a registry entry. Engine, filters, session and playback do not change.
- Pro: Serato behaviour is guarded by a golden-equivalence test across the refactor.
- Pro: Crate identity is separated from display, which fixes a latent collision and lets live refresh keep filter state.
- Pro: rekordbox is live with no export step and a sub-second read. Reading a private copy keeps rekordbox's folder untouched, even while rekordbox runs.
- Pro: The interface shape, including deck loading and change detection, has been final since Phase 1.
- Pro: An existing Serato user upgrades with no visible change.
- Con: A mandatory native dependency (`sqlcipher3-wheels`) enters the product. The decryption key lives in a third-party library, so rekordbox upgrades may break reading until `pyrekordbox` is updated and re-pinned (accepted; upgrade runbook).
- Con: pyrekordbox logs secrets at DEBUG. This is a standing constraint: its loggers must never be turned up, and the guard is tested.
- Con: The energy fallback brings tag reads back into rekordbox scans. They are bounded to in-scope tracks without comment energy and memoised.
- Con: More moving parts: about 12 new modules, a persisted format plus converter, a watcher thread, and short-lived temp copies of the user's database.
- Con: The contract carries a method (`load_to_deck`) that no provider implements yet.
- Future option (not planned): an XML-export source mode inside `source/providers/rekordbox/`.

---

## 3. Provider contract (`source/providers/base.py`, implemented in Phase 1; unchanged by Phase 3)

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Protocol, TypedDict, runtime_checkable


class ProviderError(Exception):
    """Configuration-level failure with a user-presentable message
    (folder missing, DB unreadable, DB busy). Raised by scan()."""


class DeckLoadNotSupported(ProviderError):
    """Raised by load_to_deck() when the provider lacks ProviderCapability.DECK_LOAD."""


class SettingKind(str, Enum):
    DIRECTORY = "directory"
    FILE = "file"
    CHOICE = "choice"
    TEXT = "text"                             # free text (unused after the Phase 0 key finding; kept for contract stability)


@dataclass(frozen=True)
class SettingSpec:
    key: str                                  # provider-local, e.g. "subcrates_dir"
    env_key: str                              # persisted key, e.g. "SERATO_SUBCRATES_DIR" (explicit: legacy name kept)
    label: str                                # functional label; microcopy owned by UI designer
    kind: SettingKind
    choices: tuple[str, ...] = ()             # CHOICE only
    visible_when: tuple[str, str] | None = None   # (other_key, value)
    file_patterns: tuple[tuple[str, str], ...] = ()  # FILE only, e.g. (("rekordbox database", "master.db"),)
    placeholder: str = ""                     # UI-designer addition: empty-entry prompt
    hint: str = ""                            # UI-designer addition: one grey help line under the field (platform-specific text lives in the provider)
    browse_title: str = ""                    # UI-designer addition: title of the file/folder picker
    required: bool = True                     # architect addition: empty optional fields render no prompt (e.g. DB path override)
    secret: bool = False                      # architect addition: masked in the UI, never logged (unused for now)


class ProviderCapability(str, Enum):
    PLAYLIST_FOLDERS = "playlist_folders"     # crates have hierarchy worth grouping
    SMART_PLAYLISTS = "smart_playlists"
    NATIVE_PLAY_COUNT = "native_play_count"
    CHANGE_DETECTION = "change_detection"     # change_token() returns a real token (D11)
    DECK_LOAD = "deck_load"                   # load_to_deck() works (D12); no provider declares it yet


@dataclass(frozen=True)
class CrateInfo:
    id: str                  # f"{provider_id}:{native_id}" — globally unique, stable per provider
    provider_id: str
    label: str               # provider-formatted display text
    path: tuple[str, ...]    # folder hierarchy, leaf last
    is_smart: bool = False


class TrackRecord(TypedDict, total=False):
    """The track-dict contract — identical to the cache track schema plus crate ids."""
    file_name: str; title: str; artist: str; album: str
    bpm: float; key: str; camelot_key: str; genre: str; date: str
    comments: str; energy_level: int; play_count: int
    date_added: float        # file creation time, ADR-013
    full_file_path: str
    crates: list[str]        # crate ids


@dataclass(frozen=True)
class ProviderIssue:
    severity: Literal["error", "warning"]
    message: str
    setting_key: str | None = None


@dataclass
class ProviderSnapshot:
    provider_id: str
    tracks: dict[str, TrackRecord]          # keyed by provider-native absolute path
    crates: dict[str, CrateInfo]            # every crate seen, including empty ones
    fingerprint: dict[str, float] = field(default_factory=dict)
    change_token: str | None = None         # token observed at scan start (D11)
    warnings: list[str] = field(default_factory=list)


class ProgressCallback(Protocol):
    def __call__(self, message: str, current: int, total: int) -> None: ...


@runtime_checkable
class LibraryProvider(Protocol):
    id: str                  # persisted; NEVER rename ("serato", "rekordbox")
    display_name: str        # vendor styling: "Serato DJ", "rekordbox" (lowercase, even at the start of a label)
    crate_noun: str          # UI-designer addition: "crate" (Serato) | "playlist" (rekordbox); UI pluralises with "s"

    def setting_specs(self) -> tuple[SettingSpec, ...]: ...
    def default_settings(self) -> dict[str, str]: ...
    def detect(self) -> bool: ...
    def capabilities(self, settings: Mapping[str, str]) -> frozenset[ProviderCapability]: ...
    def detected_values(self, settings: Mapping[str, str]) -> dict[str, str]: ...
        # UI-designer addition (Phase 3c): values in effect for settings left empty (e.g. the
        # auto-detected database path), display only, never persisted, stat calls only. Serato: {}.
    def validate(self, settings: Mapping[str, str]) -> list[ProviderIssue]: ...
        # cheap, UI-thread safe; never imports optional deps (use importlib.util.find_spec)
    def scan(self, settings: Mapping[str, str],
             progress: ProgressCallback | None = None) -> ProviderSnapshot: ...
        # blocking; background thread only; raises ProviderError
    def change_token(self, settings: Mapping[str, str]) -> str | None: ...
        # stat-only, any thread; None unless CHANGE_DETECTION is declared (D11)
    def load_to_deck(self, settings: Mapping[str, str], track_path: str, deck: int) -> None: ...
        # may block — call off the Tk thread; raises DeckLoadNotSupported unless DECK_LOAD is declared (D12)
```

**Registry (`source/providers/registry.py`, implemented):** `PROVIDERS` (insertion order = display order and merge precedence: rekordbox, then serato), `get_provider(id)`, `all_providers()`, `first_deck_load_provider(...)`. `source/providers/__init__.py` stays empty, so `base.py` remains a standalone leaf.

---

## 4. Component design and data flow

```
source/
├── providers/
│   ├── __init__.py                  empty
│   ├── base.py                      contract (§3)                                   [done]
│   ├── registry.py                  registry + first_deck_load_provider              [done; rekordbox added in 3a]
│   ├── serato/provider.py           SeratoProvider                                    [done]
│   └── rekordbox/                                                                     [Phase 3a]
│       ├── provider.py              RekordboxProvider
│       ├── paths.py                 default DB path, change token, path resolution (pure)
│       ├── db_copy.py               private temp copy (db + wal [+ journal, playlists xml]), torn-copy guard, cleanup
│       ├── db_reader.py             the only pyrekordbox importer: open copy, read RbTrack/RbPlaylist, close
│       ├── energy_cache.py          memo of tag energy by (path_key, mtime_ns, size)
│       └── mapping.py               pure RbTrack → TrackRecord (D8 table)
├── services/
│   ├── log_safety.py                NEW (3a) — pin secret-bearing third-party loggers at WARNING
│   ├── tag_reader.py                + read_energy_level() (3a)
│   ├── comment_format.py            NEW (3a) — pure "4A - 7 - Banger - ..." parser
│   ├── library_sync.py / library_store.py / library_merge.py / settings_migration.py   [done]
│   └── library_watcher.py           NEW (3b)
└── models/
    ├── path_identity.py             path_key (leaf)                                   [done]
    ├── track.py / library.py                                                          [done; Track.sources in 4]
```

**Layering:** `ui → app → services(library_sync/store/merge/watcher) → providers → services(leaf: tag_reader, camelot, file_times, comment_format, log_safety)`.

### rekordbox scan (Phase 3a)
```
scan(settings):
   db = effective DB path; token_before = change_token
   with db_copy.private_copy(db) as copy:            (retry if token moved; quick_check)
       lib = db_reader.read_library(copy)            (pyrekordbox; loggers ≥ WARNING; fixed-text errors)
   for playlist in lib.playlists (Attribute 0 [+4]):
       for content_id in playlist (TrackNo order):
           first sight: path = resolve_track_path(...); date_added = creation time;
                        energy = comment energy or energy_cache.get(path) (tag read on miss)
                        record = to_track_record(...)
           append crate id "rekordbox:<playlist ID>"
   return ProviderSnapshot(tracks, crates, fingerprint, change_token=token_before, warnings)
```

### Sync, live refresh and load flows
Unchanged from the previous revision. Sync: `app._on_sync` → `library_sync.sync_providers` → `scan` → `library_store.save_snapshot` → `_sync_finished` → `_reload_library`. Live refresh: watcher → `should_refresh` → silent single-provider sync → `_reload_library(preserve_state=True)` when `changed`. Load: enabled snapshots → `library_merge.merge` → `library.replace_all`.

### Merge example
`C:\Music\Artist - Title.mp3` is in Serato crate `House%%Bangers` and rekordbox playlist ID 41 (`Club / Peak`), with `PROVIDERS_ENABLED=rekordbox,serato`. Result: one Track, `crates=["rekordbox:41", "serato:House%%Bangers"]`, `sources=("rekordbox","serato")`. Key, BPM, comments and energy come from rekordbox; Serato only fills empty fields.

---

## 5. Affected files

| File | Change | Phase |
|---|---|---|
| `source/providers/base.py`, `registry.py`, `serato/provider.py` | Contract, registry, Serato | 1–2 (done); `registry.py:18-20` gains rekordbox in 3a |
| `source/services/tag_reader.py`, `crate_parser.py`, `library_sync.py`, `library_store.py`, `library_merge.py`, `settings_migration.py`, `source/models/*` | Refactor, snapshots, migration | 1–2 (done) |
| `source/services/log_safety.py` | **New.** Logger pinning | 3a |
| `source/services/tag_reader.py` | `read_energy_level()`; narrow the bare `except` (`:77`) | 3a |
| `source/services/comment_format.py` | **New** | 3a |
| `source/providers/rekordbox/*` | **New** (§4) | 3a |
| `requirements.txt` | Pins `pyrekordbox==0.5.0`, `sqlcipher3-wheels==0.5.7`, `SQLAlchemy==2.1.8` | 3a |
| `serato-sidecar.spec`, `.github/workflows/release.yml` | Collect pyrekordbox/sqlcipher3; wheel-only guard; frozen self-check | 3a |
| `main.py` | `log_safety` call; `--self-check-rekordbox`, `--check-rekordbox-library` flags | 3a |
| `source/app.py` | `_prepare_sync` stop-gap (`:308-322`); watcher lifecycle + `preserve_state` | 3a, 3b |
| `source/config.py` | Refresh constants (after `KEY_OFFSET_RANGE`, `:178`); `TRACK_CATEGORIES`; data-dir rename | 3a, 3b, 5 |
| `source/services/library_watcher.py`, `source/ui/filter_bar.py` (`preserve_selection`), `source/ui/session_panel.py` (`rebind_tracks`) | Live refresh | 3b |
| `source/ui/sync_panel.py` | Provider cards (UI brief) | 3c |
| `source/models/track.py`, `library_merge.py` | `sources`, full merge | 4 |
| Branding files | §7 | 5 |
| `scripts/spike_rekordbox.py` | **Delete** once T3.12 lands (see the implementation plan) | 3a |
| `docs/*`, `CLAUDE.md` | At merge (implementation plan T5.8) | at merge |

---

## 6. Configuration, migration and upgrade path

**Settings surface: UI direction** (full detail, options and exact copy in `ui-design-brief.md` §4 and §6; the user's open questions O1–O10 there may still change taste-level details). Functional requirements remain architecture-owned and are all met:
1. **Provider list.** One card per registered provider, in registry order (rekordbox first). Each has an on/off switch (widget choice: brief O4). Any subset is valid, **including none**: the dialog disables "Sync enabled sources" with the message "Turn on at least one source to load tracks.", and the main window shows empty-library placeholders and an Info toast with an "Open settings" button (brief §5.8; a third placeholder, "Reading your library…", covers a pending automatic first import). A card that is off collapses to its header plus one grey line.
2. **Per-provider settings.** Rows are generated from `setting_specs()` (label, entry, Browse), honouring `visible_when`. A CHOICE spec with one choice is hidden; with two it renders as a two-tile preset row (precedent: `DateRangeControl`). The dialog stays provider-agnostic. Validation: `validate()` issues render inline; **errors block sync for that provider, warnings never do**. An empty *required* field renders as an amber prompt, not a red error, so a freshly-enabled card never opens red. *(Architect addition: specs with `required=False` render no prompt when empty; `secret=True` fields are masked.)*
3. **Per-provider status chip.** "Synced 2 hours ago · 1,204 tracks · 38 playlists" (or the automatic form of item 7), "Not synced yet", or "Syncing…" (every enabled card while busy; there is no per-provider "Waiting…" because the coordinator reports no per-provider progress). On failure: a red message without the path, plus "Using your library from {date}." (D4 keeps the last good snapshot). Snapshot warnings show as one amber line with a tooltip for the rest.
4. **Sync.** Footer button "Sync enabled sources" (saves, then scans every enabled provider that has no error issue; a provider with an error is skipped and named in an amber footer line, so one broken source never blocks the other). Per-provider sync buttons are **not** in v1 (brief O5).
5. **Save semantics.** Default: staged edits with `Cancel` / `Save` / `Sync enabled sources` and an "Unsaved changes" indicator, because disabling a provider changes the live library (brief O2). Save applies enable/disable and reloads from stored snapshots without a scan.
6. **Precedence** is not exposed in v1 (architecture default accepted). The dialog tells the user in one grey sentence when both are on: "When a track is in both, its details come from rekordbox." **Only true once Phase 4's merge exists:** `merge()` currently uses the first snapshot only (`library_merge.py:27-35`). Land `T4.1`/`T4.2` before releasing Phase 3c, or show the interim amber line from brief §5.9 until then.

7. **rekordbox card (database; UI designer, revised 2026-11-05 for Phase 3c).** Full layout and copy: `ui-design-brief.md` §5.3 and §7; build list: `implementation-plan.md` Phase 3c. Summary:
   - **Rows:** `Database` (FILE, `required=False`): empty means automatic, the detected path is shown as the entry's grey placeholder (via the new `LibraryProvider.detected_values`), and the placeholder is `Choose the file named master.db` when nothing is found. `Update automatically` (CHOICE, `On`/`Off` tiles, default on). Each has a static hint (copy in the brief).
   - **No key setup.** The key is built into pyrekordbox, so there is no key field, no "fetch key" action and no key-related copy.
   - **Status chip with `CHANGE_DETECTION`:** `Updates automatically · {n} tracks · {m} playlists` and a second line `Last updated {relative}`. With auto-update off the chip falls back to `Synced {relative} · …`, which makes staleness visible.
   - **Errors:** a wrongly chosen file (`Choose the file named master.db`) is red. An error on an *empty* field (for example `Database not found` when rekordbox is not installed) is amber, never red, so a card that is switched on without setup does not open red. If the database later disappears, the card shows red plus `Using your library from {date}.`, with no toast (`change_token()` returns `None`, so the watcher does nothing). A failing background refresh is one amber toast per distinct error: `rekordbox auto-update failed: {message}`.
   - **Snapshot warnings** (amber line, first plus `(+N more)` with a tooltip): the three the provider already emits (`{n} tracks have no file on this computer`, `{n} tracks have no usable file path`, `{n} playlist entries point to tracks that aren't in the collection`). Shown after the first sync or refresh of the session (they are not persisted).
   - **Live refresh feedback in the main window:** quiet. A refresh never steals focus, never stops audio, never resets filters, and has no "Synced N tracks" toast. The suggestion list defers its re-render while the pointer is over it or a preview plays; no "list updated" cue. The only success toast is the one-time `Imported {n} tracks from rekordbox` when a quiet refresh fills an empty library.
   - **pyrekordbox missing or broken in the build:** red card error `Support isn't available in this build` (the UI adds the provider name where needed). Serato keeps working.
8. **Dialog size.** Replace the fixed `600x220` non-resizable geometry (`sync_panel.py:13-14`) with a default of 640x580, minimum 540x420, resizable. The body is a `CTkScrollableFrame` and the footer is pinned, so the cards scroll rather than clip.

**Contract additions requested by the UI** (reflected in the §3 code block): `SettingSpec.placeholder`, `SettingSpec.hint`, `SettingSpec.browse_title`, and `LibraryProvider.crate_noun`. Without them the dialog would need `if provider.id == ...` branches for microcopy, which the architecture forbids. Architect additions: `SettingKind.TEXT`, `SettingSpec.required`, `SettingSpec.secret` (the latter two kinds are unused after Phase 0). **Provider message convention:** `ProviderIssue.message` and `ProviderError` text are short complete phrases with an initial capital, no trailing period, no provider name and no file path. Exact strings are in `ui-design-brief.md` §6 (database-mode strings to be re-supplied by the designer).

**Upgrade path for an existing Serato user** (no visible change until they choose to add rekordbox):

| Step | When | What |
|---|---|---|
| 1 | Phase 2 startup (done) | `settings_migration` writes `PROVIDERS_ENABLED=serato`, `SETTINGS_SCHEMA=2` (with a one-time `.pre-schema2.bak`). Existing keys are untouched |
| 2 | Phase 2 startup (done) | A v3 `track_cache.json` converts to `library/serato.json` with exact crate ids. The old file is **left in place**. No forced re-sync |
| 3 | Phase 5 first launch | Data dir: if `DJSidecar` has no `settings.env`, **copy** `settings.env` and `library/` from the old `SeratoSidecar` dir |
| 4 | Installer | Same `AppId` → in-place upgrade. Inno `[InstallDelete]` removes the stale `SeratoSidecar.exe` (R12) |

---

## 7. Naming and branding

**UI direction (brief §5.6, §7; strings land in Phase 3c):**
- **Name:** **"Sidecar"** is confirmed by the user. Display name "Sidecar"; filesystem identifier `DJSidecar` (architect recommendation, adopted).
- **In-app strings:** window title "Sidecar — DJ Track Selector" (`app.py:30`); dialog title "Settings — Sidecar v{version}" (`sync_panel.py:12`, same format). There is no other product-name surface in the live UI (no About box, no header), so in-app branding is two strings.
- **Logo:** *(revised per the user)* `source/ui/SeratoSidecarLogo.png` is **left untouched for now**, file name and artwork both. It is not loaded by any `source/` code (packaging icon source only, `release.yml:180-194`, `serato-sidecar.spec:41`), so the only effect is that the app/installer icon still shows the old artwork, a known gap. The former logo task (T5.10) is deferred and is no longer part of this feature.
- **Terminology:** "crate" vs "playlist" follows the enabled providers through `LibraryProvider.crate_noun` (Serato only = "Crates"; any rekordbox = "Playlists"), see brief O3.
- **Active providers in the top bar:** not shown by default; the 32 px top bar is full (toast + gear). Optional amber attention dot, brief O7.

Architecture notes:
- **Change:** the window title (`source/app.py:38` now), `sync_panel.py:12`, `installer.iss:21-22,40,44,64-65`, `serato-sidecar.spec:3,7,29` (optionally rename the spec file at the same time as `release.yml:8-9,115-130`, all in **one** commit; **leave** the logo entries `spec:41` and `release.yml:180-194` as they are), `README.md`, `docs/install-guide-for-friends.md`, docs headings, `CLAUDE.md`, `.claude/agents/*.md` and `.claude/commands/*.md` mentions (low priority; ask the user first).
- **Do not change:** `installer.iss:32` `AppId`, `updater.py:35-37` manifest URL, `serato-sidecar.spec:151` bundle id, the repo name, provider ids, the logo asset.

---

## 8. Phases (summary; tasks in `implementation-plan.md`)

| Phase | Goal | Visible change | Status / gate |
|---|---|---|---|
| **0** | rekordbox spike on the user's machine | None | **Done** (Windows, rekordbox 7.2.19, closed and running). Write-burst timing and the frozen-build check were not covered and move into 3b / 3a |
| **1** | Final provider contract + `SeratoProvider` + `library_sync` | None | **Done, approved** |
| **2** | Settings schema + migration; per-provider snapshots (v4) + v3 converter; crate ids end to end | None | **Done, approved** |
| **3a** | `RekordboxProvider`: private copy, read, path resolution, mapping, energy fallback, log safety, packaging, diagnostics | Usable via `settings.env` and the existing Sync button | **Ready** |
| **3b** | Live refresh: watcher, single-flight sync, state-preserving reload | rekordbox changes appear automatically | After 3a |
| **3c** | Settings dialog and empty states pulled forward from Phase 5 (UI designer) | rekordbox fully configurable in the UI | After 3a (3b for auto-refresh controls) |
| **4** | Multi-provider merge (`Track.sources`, full `merge`, multi-provider toasts) | Both providers load together | After 2 |
| **5** | Attribution, branding, data-dir rename, packaging identity, docs | Full feature | UI design brief |
| **6 (follow-up, separate feature)** | rekordbox load-to-deck: spike → own ADR → implement `DECK_LOAD` → reveal the UI hook | Deck-load control for rekordbox tracks | After this feature ships; ADR-014's finding addressed |

**Phase 6 stub (not part of this feature).** Goal: the selected Sidecar track lands on a chosen rekordbox deck.
- **Known facts:** rekordbox has no documented load-by-path API. MIDI mapping loads only rekordbox's *selected* track (ADR-014).
- **Candidate mechanisms for the spike:**
  - (a) a rekordbox-side integration that can be driven to a specific track, if any exists in the user's rekordbox version;
  - (b) Pro DJ Link (as used by beat-link) for **hardware players** only;
  - (c) a "select then trigger" hand-off (clipboard search + MIDI trigger), honestly labelled.
- **Exit:** a new ADR that either accepts a mechanism or records rejection.
- **Already in place:** `DECK_LOAD`, `load_to_deck(...)`, `DeckLoadNotSupported`, `registry.first_deck_load_provider`, and the hidden-UI rule.

---

## 9. Risks

- **R1: Phase 1 behaviour drift.** Closed (golden-equivalence and upgrade tests are in place).
- **R2: rekordbox decryption fragility.** The key is built into pyrekordbox 0.5.0. A rekordbox update that changes encryption or schema breaks reading until pyrekordbox releases a fix. *Mitigation:* the last good snapshot keeps the app usable (D4); the settings card states the failure clearly; the **upgrade runbook** is: run `--check-rekordbox-library`, then bump and re-pin pyrekordbox if needed, re-run the check, ship. The user accepted this maintenance. *Lowered* from "high": there is no third-party download or user key handling any more.
- **R3: mandatory native dependency in the build.** The Python 3.11 wheels are confirmed on Windows. The PyInstaller collection is **not yet verified** (Phase 0 did not build a frozen app), and macOS wheels are unverified. *Mitigation:* T3.1 acceptance requires a frozen Windows build that passes `--self-check-rekordbox` and `--check-rekordbox-library`; `--only-binary` CI guard; lazy import so a broken build still runs Serato.
- **R4: path identity misses duplicates.** *Closed for this user:* `OrgFolderPath` matches all 700 Serato tracks. The D8 resolution order keeps this robust if rekordbox later fills `FolderPath`/`rb_LocalFolderPath` differently.
- **R5: live-refresh churn and disruption mid-set.** *Mitigation:* settle delay + minimum interval; `-shm` excluded from the token; `content_hash` no-op detection; state-preserving reload; an off switch. Timing defaults are unmeasured; tune them in 3b.
- **R6: suggestions differ from the Serato era.** rekordbox's key wins: comment key vs analysed key disagree for 29 of 179 tracks that carry both. On shared tracks, rekordbox's free-text comment replaces Serato's structured one in the display. *Accepted* (user decision).
- **R7: settings/cache migration bug loses user setup.** Mitigated in Phase 2 (pure migrations, backups, originals kept).
- **R8: non-MP3 files.** About 68 of the user's 1,248 rekordbox tracks are not MP3. Their metadata comes from rekordbox, but the energy tag fallback is ID3-only, so those tracks fall back to energy `0` (neutral) unless the comment carries energy. pygame still cannot preview AAC/M4A (ADR-009 Con). Switching `tag_reader` to `mutagen.File` is a possible follow-up.
- **R9: reading while rekordbox runs.** *Resolved by design:* copy-then-read (D8) never opens rekordbox's files with SQLite, and Phase 0 verified this while rekordbox was running.
- **R10: smart playlists.** None in the user's library; if they appear, they are included when pyrekordbox can evaluate them, otherwise skipped with a warning.
- **R11: crate filter UI scale.** 75 playlists in 23 folders: the UI brief's grouped list (§4.5) is adequate for v1.
- **R12: exe rename leaves debris.** *Mitigation:* Inno `[InstallDelete]` + `[UninstallDelete]`; verify on a v0.1.6 install.
- **R13: macOS unverified.** The rekordbox DB path, `OrgFolderPath` format (expected `/Users/...`) and sqlcipher wheels on macOS are untested. The path resolution accepts POSIX absolute paths.
- **R14: rekordbox schema drift across versions.** *Mitigation:* every DB access goes through `db_reader.py` with defensive attribute reads; `--check-rekordbox-library` is the per-upgrade check.
- **R15: speculative `load_to_deck` surface.** *Mitigation:* capability gate, contract test, hidden-UI rule, ADR-014.
- **R16: bundle size and dependency surface.** SQLAlchemy plus pyrekordbox (and its dependency `psutil`, also native). *Mitigation:* lazy import; measure the bundle delta in T3.1.
- **R17 (new): key leakage through logs.** pyrekordbox logs the key at DEBUG, and SQLAlchemy/SQLCipher error text can embed the connection URL. *Mitigation (requirement, tested):* `log_safety` pins both logger trees at WARNING (in `main.py` and again after import); the `db_reader` boundary logs only the exception type and raises fixed-text `ProviderError ... from None`; no code path passes a key; tests simulate a key-bearing DEBUG record and a key-bearing exception and assert that neither reaches the captured logs or the error text.
- **R18 (new): temporary copies of the user's database.** They contain the user's library (and are encrypted, as the original is). *Mitigation:* private `mkdtemp` folder, deleted in `finally` after `engine.dispose()`; stale `sidecar-rb-*` folders older than one hour are cleaned at the next scan; never written anywhere else.
- **R19 (new): torn copy while rekordbox writes.** *Mitigation:* token before/after with retries, plus `PRAGMA quick_check` on the copy (D8). A checkpoint between copying `master.db` and `-wal` yields a stale but consistent snapshot, which the next token change refreshes.
- **R20 (new): spike script in the working tree.** `scripts/spike_rekordbox.py` is **not** covered by `.gitignore` (only its outputs are), and its redaction regex embeds a fragment of the database key. *Mitigation:* do not commit it; delete it once T3.12's built-in diagnostics land (implementation plan T3.12).

---

## 10. Open questions for the user (ordered by importance)

No question blocks implementation. Remaining, non-blocking:

1. **(Phase 5) Do you or your friends use Macs?** It decides how much effort goes into verifying the macOS rekordbox DB path, the `OrgFolderPath` format and the sqlcipher wheel (R13).
2. **(After 3a, optional) Non-MP3 energy.** About 68 non-MP3 tracks fall back to unknown energy unless their rekordbox comment carries it. Is that acceptable, or should the tag fallback learn other file formats later (a `mutagen.File` follow-up)?

Answered and folded in (2026-11-05):
- rekordbox source → database (D8, §1.4);
- rekordbox truth for key and comments (D8), with energy by option (a): comment energy, then the file tag (D8);
- the key is built into pyrekordbox, so there is no key setting or fetch action (D7, D8);
- collection-only tracks excluded; no smart playlists in use (D8);
- Rating, Colour and My Tag unused, so not mapped (D8);
- app name "Sidecar", logo untouched (D10, §7);
- same file paths in both libraries, via `OrgFolderPath` (D6, D8);
- precedence when a track is in both → rekordbox first (D6);
- same-named crates shown separately, grouped by provider (D3);
- load-to-deck in the contract (D12, Phase 6).

---

## Revision log

- **2026-11-05 (architect, after Phase 0):**
  - Phase 0 findings folded in throughout.
  - **D8 rewritten:**
    - copy-then-read of `master.db` + `-wal` (not `-shm`, as verified by the spike; a deliberate deviation from the brief's "db+wal+shm") with a torn-copy guard and temp cleanup;
    - key built into pyrekordbox 0.5.0, so the key resolution and "fetch key" action are removed;
    - new **log-safety requirement** (pyrekordbox logs the key at DEBUG);
    - path resolution `OrgFolderPath` → local `FolderPath` → `rb_LocalFolderPath` → fallbacks;
    - field mapping updated (`ArtistName`/`AlbumName`/`GenreName`, `ReleaseYear` 0 → empty);
    - **energy by user option (a)**: comment energy, else the file's energy tag via a new `tag_reader.read_energy_level` with an in-process mtime/size memo. This reverses "no tag reads for rekordbox" for energy only.
  - D6 identity confirmed (all 700 Serato tracks match via `OrgFolderPath`). D7 drops `REKORDBOX_DB_KEY`. D9 uses the resolved path.
  - **D11 token = `master.db` + `master.db-wal`; `-shm` excluded.**
  - §1.4 table, §4 module list (`db_copy.py`, `energy_cache.py`, `services/log_safety.py`; `db_key.py` dropped), §5, §6 item 7 (no key UI) and §8 status updated.
  - Risks: R2/R4/R9 lowered or closed; R17–R20 added (key leakage, temp copies, torn copy, spike script not gitignored).
  - Open questions reduced to two non-blocking ones.
- **2026-11-05 (architect, after the user's answers):** The rekordbox source changed from "XML first, DB optional" to **database only**. §1.4 was rewritten, and XML was dropped with the reason recorded. D8 was rewritten: rekordbox fields are the source of truth, there are no ID3 reads for rekordbox tracks, and key handling is new. **D11 (live refresh)** and **D12 (load-to-deck capability)** were added. ADR-014 changed from a three-line stub to a recorded "Rejected" ADR, which now constrains D12. The §3 contract gained `DeckLoadNotSupported`, `SettingKind.TEXT`, `SettingSpec.required` and `.secret`, the `CHANGE_DETECTION` and `DECK_LOAD` capabilities, `ProviderSnapshot.change_token`, `change_token()` and `load_to_deck()`; `MANUAL_EXPORT_REQUIRED` was removed. §6 item 7 (the XML reminders) was replaced by rekordbox-card requirements, marked for the UI designer. In §7 the name is confirmed and the logo deferred. The Phases now have 3a/3b/3c and a Phase 6 stub; Phase 4 is no longer gated. Risks were re-scored and R14–R16 added. Answered questions were removed.
- **2026-11-05 (UI designer):** §6 settings surface, §7 branding, and the §3 contract additions (`placeholder`, `hint`, `browse_title`, `crate_noun`). See `implementation-plan.md` "UI revisions applied".
- **2026-11-05 (UI designer, second revision, for Phase 3c):** §6 item 7 (rekordbox card) rewritten and its marker removed; items 3, 4 and 6 corrected (no per-provider "Waiting…", sync skips errored providers, precedence note depends on Phase 4); §3 gains `detected_values(settings)`; the settings copy module lives in `source/services/library_copy.py` (not `source/ui/`). Build list: `implementation-plan.md` Phase 3c. Architect to confirm: the `detected_values` addition, and the recommendation to land `T4.1`/`T4.2` before the 3c release.
