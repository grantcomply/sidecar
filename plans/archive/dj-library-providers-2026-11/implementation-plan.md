# Implementation Plan: DJ Library Providers (Serato + rekordbox)

> Companion to `architect-blueprint.md` (ADR-015 proposed). Run one phase at a time. Every phase ends with the app runnable and `python -m pytest` green.
> Line numbers in Phases 1–2 are as of commit `ccac83b`. **Line numbers in Phase 3 onward are as of the approved Phase 2 code.** Re-check them if earlier tasks have shifted the code.
> **Gates:**
> - **Phases 1 and 2: done and approved.**
> - **Phase 0: done** (findings below).
> - **Phase 3a is ready and executable as written.**
> - 3b follows 3a.
> - "Phase 3c" (UI, pulled forward) follows 3a.
> - Phase 4 needs only Phase 2.
> - Phase 5 needs the UI design brief.
> - Phase 6 (rekordbox load-to-deck) is a **separate follow-up feature**.
>
> Conventions: `docs/coding-standards.md`. Type hints on public APIs, `pathlib` in **new** code, `logging` not `print`, no bare `except Exception: pass`, tests named `test_<what>_<condition>_<expected>`.
> **Privacy rule for this plan and its tests:** use synthetic track data only. Never copy titles, artists or paths from the user's library or the spike reports into code, fixtures or docs.

---

## Phase 0: rekordbox database spike (done)

Run on the user's machine on 2026-11-05 with `scripts/spike_rekordbox.py`, twice: with rekordbox **closed** and **running**. The reports are `scripts/spike_rekordbox_output_*_closed.txt` / `*_running.txt` and are gitignored. The findings below are anonymised.

| Check | Finding | Effect on the plan |
|---|---|---|
| T0.1 versions | Python 3.11.9, Windows. `pyrekordbox==0.5.0`, `sqlcipher3-wheels==0.5.7`, `SQLAlchemy==2.1.8` (+ `psutil` 7.2.2, a pyrekordbox dependency) installed as wheels | Pins in T3.1. macOS wheels not checked (R13) |
| T0.2 key | **Built into pyrekordbox 0.5.0**: no download, no configuration. pyrekordbox **logs the key at DEBUG** (`logger.debug("Key: %s", key)`) | No key setting or fetch action. Log-safety requirement (T3.5) |
| T0.3 location and reads | rekordbox 7.2.19; `%APPDATA%\Pioneer\rekordbox\master.db` (~16 MB), WAL mode (`-wal`/`-shm` exist only while rekordbox runs). The spike **copied** `master.db` + `-wal` (+ `masterPlaylists6.xml`, **not** `-shm`) to a private temp folder in 0.01 s while rekordbox was running; the copy opened in 0.01 s, `PRAGMA quick_check` = ok, and all rekordbox files were unchanged afterwards. A full read of 1,248 tracks, 98 playlist rows and 2,922 entries took **0.39 s** | Copy-then-read (T3.4). Opening in place would write `-shm` (rejected) |
| T0.4 fields | `Key.ScaleName`: 1,233 musical (`Am`, `F#m`, `Bb`), 7 Camelot, 8 empty; **all analysed keys map to Camelot**. BPM ×100 (raw 9110–18000). 1,225 comments non-empty; **180 (14%) start `"<Camelot> - <energy>"`, all with an energy number, none with a category**; the rest are free text (e.g. `Commercial`). Comment key vs analysed key: 150 agree, 29 disagree. Rating/Colour/My Tag: 0 tracks. Play count > 0: 777. `ReleaseYear` often 0. Non-MP3 file types: about 68 | Mapping (T3.6), comment parser (T3.3), energy fallback (T3.11) |
| T0.4 playlists | 75 playlists (Attribute 0), 23 folders (Attribute 1), **0 smart**; entries are in `TrackNo` order; 740 of 1,248 tracks are in at least one playlist. One built-in rekordbox playlist with 0 entries exists | Scope = playlist tracks; empty playlists are indexed but not shown (Phase 2 `crate_items`) |
| T0.5 paths | `FolderPath`: about 96% `/contents_<id>/...` (not local), 45 local `C:/...`. `rb_LocalFolderPath`: always empty. **`OrgFolderPath`**: local `C:/...` for 1,215 (33 empty), 1,203 exist on disk, and it **matches all 700 Serato tracks** after `path_key` | Path resolution (T3.2) |
| T0.6 change token | Snapshot only: `master.db`, `master.db-wal`, `master.db-shm` sizes and mtimes recorded. Write-burst timing **not measured** | Token = db + wal (T3.2). Tune refresh timings in 3b |
| T0.7 frozen import | **Not done** | Becomes T3.1's acceptance criterion |

**Upgrade runbook (from now on):** after every rekordbox upgrade, run the app's `--check-rekordbox-library` diagnostic (T3.12) and compare it with the previous report. If reading fails, bump and re-pin pyrekordbox, re-run the check, then release.

---

## Phase 1: Final provider contract + Serato behind it (pure refactor, no behaviour change)

**Exit criteria:** no visible change. The v3 `track_cache.json` written by a sync is **identical** to the one written before (except `synced_at`). Toast and dialog messages are unchanged. Settings are unchanged. The contract in `base.py` is the **final** shape (blueprint §3), including `change_token` and `load_to_deck`.

### T1.1: Create the provider contract
New `source/providers/__init__.py` (empty for now) and `source/providers/base.py` with **exactly** the contract in blueprint §3:
- `ProviderError`, `DeckLoadNotSupported(ProviderError)`;
- `SettingKind` (`DIRECTORY`, `FILE`, `CHOICE`, `TEXT`);
- `SettingSpec` (including `placeholder`, `hint`, `browse_title`, `required`, `secret`);
- `ProviderCapability` (`PLAYLIST_FOLDERS`, `SMART_PLAYLISTS`, `NATIVE_PLAY_COUNT`, `CHANGE_DETECTION`, `DECK_LOAD`);
- `CrateInfo`, `TrackRecord`, `ProviderIssue`;
- `ProviderSnapshot` (including `change_token`);
- `ProgressCallback`;
- `LibraryProvider` (including `crate_noun`, `change_token()`, `load_to_deck()`).

Leaf module: stdlib imports only (mirrors `source/services/harmonic_tier.py`). **UI revision (kept):** the contract test (T1.9) asserts every provider sets `crate_noun` and every FILE/DIRECTORY spec sets `browse_title`.

### T1.2: Extract the shared tag reader
New `source/services/tag_reader.py`. **Move**, unchanged, from `source/services/crate_parser.py`:
- `KEY_TO_CAMELOT` (`:20-27`), `to_camelot` (`:60-66`), `_tag_text` (`:69-73`), `get_track_metadata` (`:76-160`);
- their imports: `mutagen.id3.ID3`, `parse_camelot`, `file_creation_time`, `os`.

In `crate_parser.py`, replace the moved code with a re-export:
```python
from source.services.tag_reader import KEY_TO_CAMELOT, get_track_metadata, to_camelot  # noqa: F401  re-export
```
`parse_all_crates` must keep calling `get_track_metadata` through the **`crate_parser` module global**. That keeps the existing test seam working: `monkeypatch.setattr(crate_parser, "get_track_metadata", ...)` at `tests/services/test_crate_parser.py:65,87`.
- Leave the bare `except Exception: return empty` (`crate_parser.py:112-113`) **as is** in this phase. Narrowing it changes behaviour, so it moves to T3.9.
- `TXXX:SERATO_PLAYCOUNT` (`:138`) stays in the reader (Serato parity). rekordbox does not use this reader (blueprint D8).

### T1.3: Let `parse_all_crates` key crates by id
`source/services/crate_parser.py:173-238`. Add a keyword parameter `crate_key: Callable[[str], str] = _crate_display_name`. Use it at `:206` (`crate_name = crate_key(crate_file)`). The default keeps today's labels, so existing tests and behaviour are untouched. Add a sibling helper next to `_crate_display_name` (`:163-170`):
```python
def _crate_stem(crate_filename: str) -> str:
    """'House%%Bangers.crate' -> 'House%%Bangers' (stable Serato native id)."""
```
Use `removesuffix(".crate")`, **not** `replace` (`:168` uses `replace`, which would also mangle a `.crate` in the middle of a name. Keep `:168` as is for label parity).

### T1.4: Implement `SeratoProvider`
New `source/providers/serato/__init__.py` and `source/providers/serato/provider.py`.
- `id = "serato"`, `display_name = "Serato DJ"`, `crate_noun = "crate"`.
- `setting_specs()` → one `SettingSpec(key="subcrates_dir", env_key="SERATO_SUBCRATES_DIR", label="Crates folder", kind=SettingKind.DIRECTORY, placeholder="Choose your Serato crates folder", hint=<platform string: "Usually Music\_Serato_\Subcrates." on Windows, "Usually Music/_Serato_/Subcrates." on macOS>, browse_title="Select your Serato crates folder")`. Copy owned by `ui-design-brief.md` §6.
- `default_settings()` → `{"subcrates_dir": str(Path.home() / "Music" / "_Serato_" / "Subcrates")}`. Same value as `source/config.py:33`. That constant stays in `config.py` until T2.3 removes it.
- `detect()` → `Path(default).is_dir()`.
- `capabilities()` → `frozenset({ProviderCapability.PLAYLIST_FOLDERS, ProviderCapability.NATIVE_PLAY_COUNT})`. **No** `CHANGE_DETECTION` and **no** `DECK_LOAD` (blueprint D11, D12).
- `validate()` → an error issue if the folder is missing; a warning if it has no `.crate` files.
- `change_token(settings)` → `return None`.
- `load_to_deck(settings, track_path, deck)` → `raise DeckLoadNotSupported("Loading to a deck isn't supported for Serato")`. ADR-014 is the reason; see the docstring.
- `scan(settings, progress)`:
  1. `tracks, mtimes = crate_parser.parse_all_crates(settings["subcrates_dir"], progress_callback=progress, crate_key=_crate_stem)`.
  2. Build `crates = {f"serato:{stem}": CrateInfo(id=..., provider_id="serato", label=_crate_display_name(fn), path=tuple(stem.split("%%")))}` from **`mtimes` keys** (filenames), so empty crates are included.
  3. Rewrite each track's `crates` list from stems to ids, preserving order.
  4. `fingerprint=mtimes`, `change_token=None`.

  **Phase 1 only:** let `OSError` from `os.listdir` (`crate_parser.py:194`) propagate unchanged, so the error toast text stays byte-identical to today's (`crate_sync.py:31-33` → `app.py:259-260`). Wrapping in `ProviderError` happens in T2.10.

### T1.5: Registry
`source/providers/__init__.py`:
- `PROVIDERS: dict[str, LibraryProvider] = {"serato": SeratoProvider()}`. T3.7 inserts rekordbox **before** serato.
- `get_provider(provider_id: str) -> LibraryProvider` (raises `KeyError`);
- `all_providers() -> list[LibraryProvider]`.

### T1.6: `library_sync` replaces `crate_sync`
New `source/services/library_sync.py`:
```python
@dataclass(frozen=True)
class SyncRequest:
    provider: LibraryProvider
    settings: Mapping[str, str]

@dataclass(frozen=True)
class ProviderSyncResult:
    provider_id: str
    track_count: int = 0
    crate_count: int = 0          # len(snapshot.crates) — INCLUDES empty crates (parity: crate_sync.py:28)
    warnings: tuple[str, ...] = ()
    error: str | None = None
    changed: bool = True          # Phase 2+: False when the new snapshot's content_hash equals the stored one

@dataclass(frozen=True)
class SyncReport:
    results: tuple[ProviderSyncResult, ...]
    # convenience properties: ok, total_tracks, total_crates, first_error, any_changed

def sync_providers(requests: Sequence[SyncRequest],
                   progress_callback: ProgressCallback | None = None,
                   done_callback: Callable[[SyncReport], None] | None = None) -> threading.Thread:
```
- Daemon thread, like `crate_sync.py:35-37`. For each request: `snapshot = provider.scan(...)`, then persist.
- **Phase 1 persistence:** convert the snapshot to the v3 shape with a private `_to_v3(snapshot) -> (tracks, crate_mtimes)`. It maps crate ids back to `snapshot.crates[id].label` and uses `crate_mtimes = snapshot.fingerprint`. Then call `cache.save_cache(tracks, crate_mtimes)` (`source/services/cache.py:80`).
- **Phase 1 guard:** `if len(requests) != 1: raise ValueError(...)`, because the v3 cache can't hold two providers. T2.6 removes this.
- Error handling per provider:
  - `except (ProviderError, OSError) as e` → `error=str(e)`;
  - then a documented last-resort `except Exception as e: logger.exception(...)` → `error=str(e)`. This is the thread boundary (blueprint D5), and today's `crate_sync.py:31` catches it without logging.
- Call `done_callback(report)` exactly once.
- Single-flight and coalescing (blueprint D5) arrive in T3b.3. Phase 1 keeps today's "one sync per click" behaviour.

### T1.7: Wire `app.py` to the provider
- `source/app.py:13`: replace the `crate_sync` import with `from source.services.library_sync import SyncRequest, SyncReport, sync_providers` and `from source.providers import get_provider`.
- `_on_sync` (`:241-256`): keep `save_subcrates_dir(subcrates_path)` at `:242`. Replace `sync_crates(...)` (`:253-256`) with `sync_providers([SyncRequest(get_provider("serato"), {"subcrates_dir": subcrates_path})], done_callback=lambda r: self.after(0, lambda: self._sync_finished(r)))`.
- `_sync_finished` (`:258-279`): change the signature to `(self, report: SyncReport)`. Error branch: `f"Sync failed: {report.first_error}"`, the same text as `:260`. Success branch: `f"Synced {self.library.count} tracks from {report.total_crates} crates"`, the same as `:267` (`num_crates` was `len(crate_mtimes)`, which equals `len(snapshot.crates)`).

### T1.8: Delete `crate_sync.py`, update packaging and docstrings
- Delete `source/services/crate_sync.py`.
- Update the stale reference in the `source/services/updater.py:16` docstring (→ `library_sync.py`).
- `serato-sidecar.spec:53-74`: remove `"source.services.crate_sync"` (`:65`). Add `"source.providers"`, `"source.providers.base"`, `"source.providers.serato"`, `"source.providers.serato.provider"`, `"source.services.tag_reader"`, `"source.services.library_sync"`. The pre-existing drift in this list is noted in the MIDI blueprint §7 and is out of scope.

### T1.9: Tests (Phase 1)
- `tests/fixtures/__init__.py` + `tests/fixtures/crate_bytes.py`: `build_crate_bytes(paths: list[str]) -> bytes`. It emits `b"vrsn"` + header, then for each path `b"otrk" + >I len + b"ptrk" + >I len + path.encode("utf-16-be")`. This is enough for `parse_crate_file` (`crate_parser.py:30-57`), which scans for `b"ptrk"`.
- `tests/services/test_tag_reader.py`: `to_camelot` for `Am`→`8A`, `F#m`→`11A`, `"8A"` passthrough, `"B\u266d"` → `6B`, unknown → `""`. `get_track_metadata` on a non-existent path returns the empty dict with `date_added` 0.0 (patch `file_creation_time`).
- `tests/providers/__init__.py`, `tests/providers/test_contract.py`: parametrised over `all_providers()`. Checks:
  - `isinstance(p, LibraryProvider)`;
  - ids are unique, lowercase and `[a-z0-9_]+`;
  - every `SettingSpec.env_key` is unique across providers;
  - `default_settings()` keys ⊆ spec keys;
  - `crate_noun` is non-empty, and every FILE/DIRECTORY spec has `browse_title`;
  - **if `CHANGE_DETECTION ∉ capabilities(default_settings())` then `change_token(default_settings()) is None`**;
  - **if `DECK_LOAD ∉ capabilities(...)` then `load_to_deck(default_settings(), "/x.mp3", 1)` raises `DeckLoadNotSupported`**.
- `tests/providers/test_serato_provider.py` (using `tmp_path` and real crate bytes via the fixture):
  - ids look like `serato:House%%Bangers` and labels like `House - Bangers`;
  - `path == ("House", "Bangers")`;
  - an empty crate appears in `crates` and in `fingerprint`;
  - a track in two crates has both ids in sorted-filename order;
  - a missing folder raises `OSError` (Phase 1 contract);
  - `load_to_deck` raises `DeckLoadNotSupported`.
- `tests/services/test_serato_equivalence.py` (**golden test, R1**): build a crate tree with 3 crates (one empty, one nested `A%%B`, one overlapping). Patch `crate_parser.get_track_metadata` with a deterministic stub. Assert that `library_sync._to_v3(SeratoProvider().scan(...))` equals `crate_parser.parse_all_crates(...)` (the old default `crate_key`) for both tracks and mtimes.
- `tests/services/test_library_sync.py`: a fake provider (a class satisfying the Protocol). Cases: the success report counts; `ProviderError` → `error` set and `save_cache` not called; an unexpected `RuntimeError` → reported and logged (use `caplog`); `done_callback` is called exactly once. Patch `cache.save_cache` and `join()` the returned thread.
- The existing `tests/services/test_crate_parser.py` must pass **unmodified**.

---

## Phase 2: Settings schema, migration, per-provider snapshots, crate ids end to end

**Exit criteria:** still Serato-only and visually identical. Existing users upgrade without a re-sync. Settings gain `PROVIDERS_ENABLED=serato` and `SETTINGS_SCHEMA=2`. The library is now stored as `library/serato.json`.

### T2.1: Pure settings migration
New `source/services/settings_migration.py`:
```python
SETTINGS_SCHEMA = 2

def migrate_settings(env: dict[str, str], *, has_legacy_cache: bool,
                     detected: Sequence[str]) -> dict[str, str]:
    """Return a NEW dict; never mutates or deletes keys. Idempotent."""
```
Rules (blueprint D7):
- `SETTINGS_SCHEMA` ≥ 2 → return a copy, unchanged.
- `SERATO_SUBCRATES_DIR` set **or** `has_legacy_cache` → `PROVIDERS_ENABLED="serato"`.
- Otherwise `PROVIDERS_ENABLED=",".join(detected)`, which may be `""`.
- Always set `SETTINGS_SCHEMA="2"`.

Plus `run_startup_migrations() -> None`:
1. `_load_env()`.
2. `detected` = ids from `all_providers()` (registry order, so rekordbox first once registered) whose `detect()` is true.
3. `has_legacy_cache` = `library_store.legacy_cache_exists()`.
4. If the result differs, `_save_env`.
5. Then `library_store.convert_legacy_cache_if_needed()` (T2.4).

Catch `OSError` and log. **A migration failure must never stop startup.**

### T2.2: Call migrations at startup
`main.py:12-16`: call `run_startup_migrations()` inside `main()` before `DJTrackSelectorApp()` (`:15`). `config.py` stays free of provider imports. Its existing import-time `_migrate_legacy_env()` (`source/config.py:36-51`) stays.

### T2.3: Generic provider settings accessors in `config.py`
`source/config.py`:
- Add these after `_save_env` (`:68-72`):
  - `get_enabled_providers() -> list[str]`: split `PROVIDERS_ENABLED`, strip, drop empties, keep order;
  - `save_enabled_providers(ids: Sequence[str])`: the caller passes ids in **registry order** (blueprint D6/D7: order = precedence, rekordbox first);
  - `get_provider_settings(specs, defaults) -> dict[str, str]`: reads each `spec.env_key` and falls back to `defaults[spec.key]`;
  - `save_provider_settings(specs, values)`.

  Use duck-typed specs (anything with `.key`/`.env_key`) so `config` does not import `source.providers`.
- Delete `FALLBACK_SUBCRATES_DIR` (`:33`) and `get_subcrates_dir` / `save_subcrates_dir` (`:75-85`).
- Update `source/app.py:8`. `_open_settings` (`:235-237`) gets the default path from `get_provider_settings(serato.setting_specs(), serato.default_settings())["subcrates_dir"]`. `_on_sync` (`:242`) saves through `save_provider_settings`. Both go through a small private `app._provider_settings(pid)` helper.

### T2.4: Per-provider snapshot store (schema v4)
New `source/services/library_store.py`:
- `SNAPSHOT_SCHEMA = 4`.
- `snapshot_dir() -> Path` (`user_data_dir() / "library"`, mkdir).
- `save_snapshot(snapshot: ProviderSnapshot) -> bool`:
  - JSON fields: `{schema, provider, synced_at (UTC ISO, as cache.py:97), fingerprint, change_token, content_hash, crates: {id: {provider_id, label, path, is_smart}}, tracks}`.
  - `content_hash` = SHA-256 of `json.dumps({"tracks": ..., "crates": ...}, sort_keys=True, ensure_ascii=False)`.
  - Returns `True` if the content hash differs from the stored file's, which feeds `ProviderSyncResult.changed`. Always rewrite the file anyway, so `synced_at` and `change_token` advance.
  - **Atomic:** write `<pid>.json.tmp` with `encoding="utf-8"`, `ensure_ascii=False` (as `cache.py:104`), then `os.replace`.
- `load_snapshot(provider_id) -> ProviderSnapshot | None`: returns `None` on a missing file, `JSONDecodeError`/`OSError`, schema mismatch or provider mismatch. Logs, the same as `cache.py:59-76`.
- `snapshot_summary(provider_id) -> SnapshotSummary | None` (synced_at, track count, crate count, change_token). Used by the watcher and the settings UI.
- `legacy_cache_exists()` and `convert_legacy_cache_if_needed()`:
  - If `library/serato.json` is missing and a v3 `track_cache.json` exists in `user_data_dir()` (or the old project root, as `cache.py:22-40` does), read it, but only `version == 3` (`cache.py:16,70`).
  - Map each track's crate **labels** to ids `"serato:" + label.replace(" - ", "%%")`. Synthesise a `CrateInfo` per distinct label (`path = tuple(stem.split("%%"))`).
  - `fingerprint = crate_mtimes`. Then `save_snapshot`.
  - **Do not delete or rename `track_cache.json`** (downgrade safety, R7).
  - A non-v3 legacy file → skip (the user re-syncs, the ADR-007 behaviour).

### T2.5: Library model takes merged data and stops importing the cache
- `source/models/library.py`: remove `import csv`/`os` (`:2-3`) and `from source.services.cache import load_cache` (`:7`). Delete `load_from_csv_dir` (`:24-52`) and `load_from_cache` (`:54-73`). Add:
  - `self._crates: dict[str, CrateInfo] = {}` in `__init__` (`:13-14`);
  - `replace_all(self, tracks: dict[str, Track], crates: Mapping[str, CrateInfo]) -> None`;
  - `crate_label(self, crate_id: str) -> str` (falls back to the raw id);
  - `track_by_path(self, path: str) -> Track | None` (looked up by `library_merge.path_key`; used by the state-preserving reload in T3b.4);
  - `crate_items` → `list[tuple[str, str]]` of `(id, label)` for crates that have **at least one track**, sorted by `label` **case-sensitively**. This is the same visible set and order as `crate_names` (`:75-81`), which only counted crates referenced by tracks and used a plain `sorted(names)` at `:81`. **UI revision:** keep the case-sensitive order in this phase (Phase 2 must look identical). Phase 5 (T5.3) switches the crate/playlist list to case-insensitive path order inside each provider group.
  - `crate_count`.

  Type-only import of `CrateInfo` from `source.providers.base` (a leaf module) is fine.
  > **Deviation (Phase 2 review):** `path_key` lives in a new stdlib-only leaf, `source/models/path_identity.py`, which `library.py` imports. `library_merge` re-exports it. That keeps `models` from importing `services` (otherwise library → library_merge → models.track would form a two-way layer dependency).
- `source/models/track.py`: delete `from_csv_row` (`:26-88`) and fix the docstring reference at `:94`.

### T2.6: Load path and `library_sync` persistence
- New `source/services/library_merge.py`:
  - `path_key(p: str) -> str = unicodedata.normalize("NFC", os.path.normcase(os.path.normpath(p)))`;
  - `merge(snapshots: Sequence[ProviderSnapshot]) -> tuple[dict[str, Track], dict[str, CrateInfo]]`.

  **Phase 2 version:** handles 0 or 1 snapshots and keys tracks by `path_key`. For more than 1 it logs a warning and uses only the first (completed in T4.1). Builds `Track.from_dict(record, path)` (`track.py:90-158`).
- `library_sync.py`: replace the `_to_v3` + `save_cache` path with `changed = library_store.save_snapshot(snapshot)`. Remove the single-request guard from T1.6. Delete `_to_v3`, but keep it inside the golden test (`test_serato_equivalence.py`) as a local helper so R1 stays covered.
- Delete `source/services/cache.py` once nothing imports it. The minimal v3 read lives in `library_store` (T2.4). Update `serato-sidecar.spec:62` (remove `source.services.cache`, add the new modules).

### T2.7: App reload helper
`source/app.py`: add `_reload_library(self, preserve_state: bool = False) -> None`:
```
snapshots = [s for pid in get_enabled_providers() if (s := library_store.load_snapshot(pid))]
tracks, crates = library_merge.merge(snapshots)
self.library.replace_all(tracks, crates)
self.suggestion_panel.set_crates(self.library.crate_items)
self.suggestion_panel.set_genres(self.library.genre_names)
```
(`preserve_state` is accepted now and implemented in T3b.4.)
- Use it in `_try_load_existing` (`:125-133`). Keep the toast only when the library is non-empty, with the same text, using `self.library.crate_count`.
- Use it in `_sync_finished` (`:264-266`).
- `_on_sync` builds requests for **every enabled provider** (only Serato for now) instead of hard-coding `"serato"`.

### T2.8: `FilterDropdown` separates key and label
`source/ui/filter_bar.py:321-350`. `set_items(self, items: Sequence[str | tuple[str, str]])`:
- normalise each item to `(key, label)` (a plain `str` → `(s, s)`);
- `self._vars[key]`, and a new `self._labels: dict[str, str]` (init next to `:277`);
- `CTkCheckBox(text=label)` (`:344-349`);
- in `_update_label` (`:378-382`), `only = truncate(self._labels[key], 10)`.

`selected` / `restore` / `all_selected` (`:413-434`) keep operating on keys. Genre calls (`suggestion_panel.py:213`) are unchanged.

### T2.9: Crate labels in the UI
- `source/ui/suggestion_panel.py:209-210`: `set_crates(self, items: list[tuple[str, str]])`. Pass to the dropdown and keep `self._crate_labels = dict(items)`. Tooltip `:476-477`: `', '.join(self._crate_labels.get(c, c) for c in track.crates)`.
- `source/ui/track_detail.py`: add `set_crate_label_fn(self, fn: Callable[[str], str])`, modelled on `set_search_fn` (`:123`). The info line `:165-169` maps `track.crates[:3]` through it. Wire it in `source/app.py:84`: `self.dashboard.set_crate_label_fn(self.library.crate_label)`.
- The visual result must be identical to today for a Serato-only library.

### T2.10: `ProviderError` in `SeratoProvider`
`source/providers/serato/provider.py` `scan`: check the folder first and raise `ProviderError("Crates folder not found")` instead of letting `os.listdir` raise. **UI revision:** no provider name and no path in the message (the UI prefixes the provider name and the path is visible in the settings field). That is the only Phase 2 copy change. From this task on, `app._sync_finished` renders a single-provider failure as `f"Serato sync failed: {report.first_error}"`, matching the final toast format in `ui-design-brief.md` §6 (this replaces the Phase 1 `"Sync failed: {error}"` form). `validate()` returns the same phrase as an error issue; its "no `.crate` files" warning reads `No crates found in this folder`.

> **Follow-up from Phase 1 review (empty error messages):** Phase 1 kept parity, so an exception with an empty message gives `report.first_error == ""` and `_sync_finished` (which branches on `if report.first_error:`) treats it as success. With this task: switch `_sync_finished` to `if not report.ok:`; in `library_sync._sync_one` record `error=str(e) or type(e).__name__`; and update `test_sync_exception_with_empty_message_reports_empty_first_error` in `tests/services/test_library_sync.py` to expect the exception type name.

### T2.11: Tests (Phase 2)
- `tests/services/test_settings_migration.py`, table-driven:
  - an existing user with `SERATO_SUBCRATES_DIR` → `serato`;
  - legacy cache only → `serato`;
  - fresh install, both detected → `rekordbox,serato` (pass a `detected` list);
  - nothing detected → `""`;
  - already schema 2 → unchanged;
  - idempotent (applying twice gives the same result);
  - never drops unknown keys (`CHECK_FOR_UPDATES`).
- `tests/services/test_library_store.py` (patch `user_data_dir` to `tmp_path`):
  - round-trip equality (including `change_token`);
  - no `.tmp` file left behind;
  - `save_snapshot` returns `False` for identical content and `True` after a change;
  - schema mismatch → `None`; provider mismatch → `None`; corrupt JSON → `None`;
  - v3 conversion: labels → ids, `"A - B"` → `serato:A%%B`, the legacy file still exists afterwards, a second run is a no-op;
  - non-v3 legacy → no snapshot.
- `tests/models/__init__.py`, `tests/models/test_library.py`: `replace_all`; `crate_items` excludes crates with no tracks and keeps sort order; `crate_label` falls back; `track_by_path` normalises; `search` (`library.py:92-104`) still works.
- `tests/services/test_library_merge.py`: 0 and 1 snapshot cases; `path_key` normalisation (T4 extends).
- `tests/ui/test_filter_dropdown_pairs.py` (follow the existing `tests/ui/test_filter_dropdown_clear.py` setup): with `(key, label)` items, `selected` returns keys, the checkbox text is the label, and `restore` works by key. The existing `tests/ui/test_filter_*` must pass unmodified.
- `tests/conftest.py:37,54` stays valid (crates are plain strings).

> **Phase 2 implementation notes (engineer, deviations to confirm):**
> - **Settings write safety:** `run_startup_migrations` copies `settings.env` once to `settings.env.pre-schema2.bak` (never overwritten) before its first write, and writes via temp file + `os.replace`. `_save_env` would otherwise drop comment lines.
> - **`_on_sync` enables Serato if needed:** the Phase 2 dialog is Serato-only, so a sync from it adds `serato` to `PROVIDERS_ENABLED` (in registry order) when missing. Without this, a fresh install with no detected Serato folder (`PROVIDERS_ENABLED=""`) could never sync. T3.8 replaces this.
> - **Failure toast** uses `display_name`: `"Serato DJ sync failed: Crates folder not found"`, not T2.10's literal `"Serato sync failed: ..."` (brief §6 says `{Provider}` and names the provider "Serato DJ"; the app avoids provider-specific strings). *UI designer, confirmed:* `{display_name} sync failed: {error}` is right (brief §5.5); the wording is kept and only the message text loses its provider name (T3c.3).
> - **T2.10 follow-up applied:** `_sync_finished` uses `if not report.ok:`; `library_sync` records `str(e) or type(e).__name__`.
> - **`crate_count`** counts crates with at least one track, so the startup toast matches the old `len(crate_names)`. The sync toast still uses `report.total_crates` (includes empty crates), as before.
> - **Startup toast** shows only for a non-empty library (as T2.7 says); before, an empty v3 cache showed "Loaded 0 tracks from 0 crates".
> - **Project-root legacy cache** is read in place; the old `cache.py` *moved* it into the user data dir.
> - **Golden test:** the v3 file-text comparison is gone (v3 is no longer written). `_to_v3` lives in the test, plus a new upgrade test: a converted v3 cache loads the same library as a fresh sync.
> - Small additions: `config.parse_provider_list` and `PROVIDERS_ENABLED_KEY`/`SETTINGS_SCHEMA_KEY`; `Track.crates` typed `list[str]`; `load_snapshot` also returns `None` for a structurally malformed file; `app._enabled_registered_providers()` (registry-filtered, unknown ids logged) feeds both `_on_sync` and `_reload_library`; `tests/conftest.py` gains an `isolated_data_dir` fixture.
> - **Phase 2 review follow-ups (applied):**
>   - Legacy conversion builds exact crate ids and adds empty crates from the v3 `crate_mtimes` filenames (via `crate_parser.crate_stem`/`crate_display_name`); reversing the label (` - ` → `%%`) is only a fallback for labels with no file. A converted snapshot now has the same content hash as a fresh sync.
>   - If writing `settings.env` fails, `settings_migration.effective_enabled_providers()` applies the migration in memory, so the library still loads. The app uses it instead of `config.get_enabled_providers()`.
>   - Writes to settings, snapshots and the backup copy all use a unique `tempfile.mkstemp` name in the same folder plus `os.replace`, and clean up the temp file on failure (`config._write_env_atomic` now backs `_save_env`). `snapshot_path()` no longer creates folders; only writes do.
>   - `app._on_sync` has a `_sync_in_progress` re-entry guard (cleared in `_sync_finished`). That is the minimal stand-in for T3b.3's coordinator. When it adds Serato to `PROVIDERS_ENABLED` it keeps ids the registry doesn't know (`with_provider_enabled`).
>   - `_detected_provider_ids` catches any exception per provider (logged, `BLE001` boundary).
>   - `tests/conftest.py` has a session-wide autouse redirect of config's data dir, so no test can write to the real user data folder.
> - **Left as-is, noted:**
>   - The PyInstaller `hiddenimports` list still has older drift (e.g. modules added before this feature that aren't listed). Only this feature's modules were added.
>   - `legacy_cache_exists()` is true for any `track_cache.json` (either location, any version), while `convert_legacy_cache_if_needed()` converts only a readable v3 file and stops at the first readable candidate. So a non-v3 legacy file still counts as an "existing install" (enables Serato) but produces no snapshot.

---

## Phase 3a: `RekordboxProvider` (private copy of the library database)

**Gate:** none (Phase 0 is done). **Exit criteria:**
- With `PROVIDERS_ENABLED=rekordbox` set by hand in `settings.env` (DB path auto-detected), the existing Sync button imports the user's rekordbox library: about 740 tracks in 75 playlists, in under about 2 s on a warm energy cache. Suggestions work.
- A sync while rekordbox is running leaves every file in rekordbox's folder unchanged.
- No key appears in any log, even with the root logger at DEBUG.
- Serato-only users see no change.
- A frozen Windows build passes `--self-check-rekordbox` and `--check-rekordbox-library`.

**Execution order:** T3.5 (log safety) **first**, then T3.1, T3.2, T3.3, T3.11, T3.4, T3.6, T3.7, T3.8, T3.9, T3.12. Write T3.10's tests alongside each task. (Task numbers keep the ids that the UI and engineer notes already reference.)

> **UI revision (no longer optional):** do the "Phase 3c" section below (T3c.1 to T3c.9; they replace T5.1, T5.2, the strings of T5.5 and T5.11) straight after Phase 3b. Reason: the interim T3.8 would leave a Serato-only path field in the dialog for a rekordbox-only user, which is misleading copy (design guide §8). T5.3/T5.4 (attribution) wait for Phase 4, since nothing needs attributing before two providers can coexist. *(Revised 2026-11-05 after Phases 3a and 3b: see "UI revisions applied", second entry.)*

### T3.1: Dependency and packaging
- `requirements.txt` (after `:5`), exact pins:
  ```
  pyrekordbox==0.5.0
  sqlcipher3-wheels==0.5.7
  SQLAlchemy==2.1.8
  ```
- `serato-sidecar.spec`:
  - next to the CTk collection (`:38`), add `collect_all("pyrekordbox")` and `collect_all("sqlcipher3")`, and merge their datas/binaries/hiddenimports into the lists at `:40-45` and `:84`;
  - add `collect_submodules("sqlalchemy.dialects.sqlite")` to `hiddenimports`;
  - add to the explicit list (`:53-82`): `source.services.log_safety`, `source.services.comment_format`, `source.services.diagnostics`, `source.providers.rekordbox`, `source.providers.rekordbox.provider`, `.paths`, `.db_copy`, `.db_reader`, `.energy_cache`, `.mapping`.
- `.github/workflows/release.yml` (both install steps): `pip install --only-binary=sqlcipher3-wheels,psutil -r requirements.txt`. After each PyInstaller build, run the frozen exe with `--self-check-rekordbox` and fail the job on a non-zero exit code. If the macOS job fails for lack of a wheel, stop and report; don't build from source.
- **Acceptance (replaces the skipped Phase 0 T0.7):**
  - a one-folder Windows build where `SeratoSidecar.exe --self-check-rekordbox` exits 0;
  - on the user's machine, `--check-rekordbox-library` (T3.12) reports roughly 740 tracks and 75 playlists;
  - record the bundle-size delta and any extra hidden imports you needed in the "Phase 0 findings" table above (T0.7 row).

### T3.2: Paths, change token and path resolution (pure)
New `source/providers/rekordbox/__init__.py` (empty) and `source/providers/rekordbox/paths.py`:
- `default_db_path() -> Path | None`. Windows: `Path(os.environ["APPDATA"]) / "Pioneer" / "rekordbox" / "master.db"` (if `APPDATA` is set). macOS: `Path.home() / "Library" / "Pioneer" / "rekordbox" / "master.db"` (unverified, R13). Otherwise `None`.
- `TOKEN_FILES = ("master.db", "master.db-wal")`. **`-shm` is deliberately excluded:** it changes with rekordbox's own reads and checkpoints (blueprint D11).
- `compute_change_token(db_path: Path) -> str` → `"master.db:<mtime_ns>:<size>|master.db-wal:<mtime_ns>:<size>"`, using `"<name>:-"` for an absent file. `stat` only.
- `is_local_path(p: str) -> bool`: true for a drive path (`^[A-Za-z]:[\\/]`), a UNC path (`\\\\`), or a POSIX absolute path that does **not** start with `/contents_`.
- `resolve_track_path(org: str, folder: str, local: str, *, exists: Callable[[str], bool] = os.path.exists) -> tuple[str | None, bool]` → `(path, file_exists)`. Rules, first hit wins (blueprint D8):
  1. `org` non-empty and exists;
  2. `folder` local and exists;
  3. `local` non-empty and exists;
  4. `org` non-empty (missing);
  5. `folder` local (missing);
  6. `(None, False)`.

  Return `os.path.normpath(path)`, which converts `/` to `\` on Windows.

### T3.3: Comment-format parser
New `source/services/comment_format.py` (leaf; imports only `camelot.parse_camelot`):
```python
@dataclass(frozen=True)
class CommentFields:
    camelot_key: str = ""
    energy: int = 0
    category: str = ""
    descriptors: str = ""

def parse_comment(comment: str) -> CommentFields
```
- Split on `" - "`, max 4 parts.
- **Part 0 must be a valid Camelot key** (`parse_camelot` after `strip().upper()`), otherwise return an empty `CommentFields`. That covers free text such as `Commercial`.
- Part 1: an int in 1–8 (also accept `"Energy 7"`); otherwise `energy = 0`.
- The category is matched case-insensitively against `TRACK_CATEGORIES = ("Banger","Driver","Groover","Filler","Chiller","Opener")`; add that constant to `source/config.py` after `KEY_OFFSET_RANGE` (`:178`). Unknown → `""` (all of the user's comments today).
- The remaining parts joined → `descriptors`.

This also clears the testing-strategy item `docs/testing-strategy.md:39-43`.

### T3.4: Copy-then-read: `db_copy.py` and `db_reader.py`
**`source/providers/rekordbox/db_copy.py`** (stdlib only):
```python
COPY_FILES = ("master.db", "master.db-wal", "master.db-journal", "masterPlaylists6.xml")
TEMP_PREFIX = "sidecar-rb-"

@contextmanager
def private_copy(db_path: Path, *, token_fn: Callable[[Path], str],
                 attempts: int = 3, delay_s: float = 0.2,
                 tmp_root: Path | None = None) -> Iterator[Path]: ...
def cleanup_stale_copies(*, tmp_root: Path | None = None, max_age_s: float = 3600) -> None: ...
```
- `master.db` missing → `ProviderError("rekordbox database not found")`.
- Each attempt:
  1. `before = token_fn(db_path)`;
  2. `tmp = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir=tmp_root))`;
  3. `shutil.copyfile` every file in `COPY_FILES` that exists (sources opened read-only by `copyfile`);
  4. `after = token_fn(db_path)`.

  If `before != after`, or the copy raised `OSError` (e.g. a sharing violation), remove `tmp`, sleep `delay_s`, and retry. After `attempts` failures → `ProviderError("rekordbox database is busy. Try again in a moment")`.
- **Never copy `master.db-shm`.** Explain why in a comment: SQLite rebuilds it from `-wal` on the copy, a copied one can be inconsistent, and this is the configuration Phase 0 verified.
- Yield `tmp / "master.db"`. In `finally`: `shutil.rmtree(tmp, ignore_errors=True)`; if the folder still exists, log at DEBUG (the next cleanup removes it).
- `cleanup_stale_copies`: delete `TEMP_PREFIX*` folders in the temp root whose mtime is older than `max_age_s`. Never touch anything else.

**`source/providers/rekordbox/db_reader.py`**, the **only** module that imports pyrekordbox or SQLAlchemy:
```python
@dataclass(frozen=True)
class RbTrack: content_id: str; title: str; artist: str; album: str; genre: str; bpm: float
               scale_name: str; comments: str; play_count: int; release_year: int
               org_path: str; folder_path: str; local_path: str
@dataclass(frozen=True)
class RbPlaylist: playlist_id: str; path: tuple[str, ...]; content_ids: tuple[str, ...]; is_smart: bool
@dataclass(frozen=True)
class RbLibrary: tracks: dict[str, RbTrack]; playlists: list[RbPlaylist]; warnings: list[str]

class CopyIntegrityError(ProviderError): ...   # quick_check != "ok" — caller re-copies once

def read_library(copy_path: Path, *, db_factory: Callable[..., Any] | None = None) -> RbLibrary
```
- **Lazy import:** `_ensure_pyrekordbox()` imports `pyrekordbox` and `sqlalchemy.text`, then **immediately calls `log_safety.silence_secret_loggers()`**. `ImportError`/`OSError` → `ProviderError("rekordbox support isn't available in this build")`. Mirror `source/services/audio_player.py:22-35`.
- **Open:** the default factory is `getattr(pyrekordbox.masterdb, "MasterDatabase", None) or pyrekordbox.Rekordbox6Database`, called as `factory(path=copy_path, db_dir=copy_path.parent)`. **No key argument:** the key built into pyrekordbox 0.5.0 is used (the spike opened this way with an empty key). Never read, store or pass a key.
- **Integrity:** `db.session.execute(text("PRAGMA quick_check")).scalar()` must equal `"ok"`, otherwise raise `CopyIntegrityError("rekordbox database is busy. Try again in a moment")`.
- **Read:** `db.get_content()`, `db.get_playlist()`, `db.get_playlist_songs()`.
  - Every attribute is read with a small `_attr(obj, name, default)` helper that returns the default for missing or `None` values (schema-drift tolerance, R14).
  - Content attributes: `ID`, `Title`, `ArtistName`, `AlbumName`, `GenreName`, `BPM` (÷100), `Key.ScaleName` (`""` when there is no key), `Commnt`, `DJPlayCount`, `ReleaseYear`, `OrgFolderPath`, `FolderPath`, `rb_LocalFolderPath`.
- **Playlists:** build each path from `ParentID` (cycle-safe: stop on a repeated id). `Attribute` 0 → playlist; content ids from songs with that `PlaylistID`, sorted by `TrackNo`. `Attribute` 1 → folder (only contributes to paths). `Attribute` 4 → `db.get_playlist_contents(p)` if it works, else skip and add the warning `"Smart playlists were skipped"` once. Ignore any other attribute.
- **Always clean up:** `finally:` `db.close()` then `db.engine.dispose()`, each in its own `contextlib.suppress(Exception)` (documented cleanup boundary). Windows must release the file handles before `private_copy` deletes the folder.
- **Error boundary (key safety):**
  - `except ProviderError: raise`;
  - `except Exception as e: logger.warning("rekordbox read failed (%s)", type(e).__name__); raise ProviderError("Couldn't read the rekordbox database") from None`.

  Never log or forward `str(e)`: SQLAlchemy/SQLCipher messages can embed the connection URL. `from None` keeps the original exception out of any traceback that `library_sync` might log.
- **No write calls** (`commit`, `add`, `delete`, `flush`), even on the copy.

### T3.5: Log safety (do this first)
New `source/services/log_safety.py` (stdlib only):
```python
SECRET_BEARING_LOGGERS = ("pyrekordbox", "sqlalchemy")

def silence_secret_loggers() -> None:
    """Pin third-party loggers that can emit the rekordbox DB key at WARNING or above.

    pyrekordbox logs the database key at DEBUG; SQLAlchemy can log connection
    details. Never lower these levels. Child loggers inherit the level.
    """
```
- For each name: if `logger.level == logging.NOTSET or logger.level < logging.WARNING`, set it to `logging.WARNING`. Never lower a stricter level.
- `main.py`: call it straight after `logging.basicConfig(...)` (`main.py:7-10`), before anything can import pyrekordbox.
- `db_reader._ensure_pyrekordbox()` calls it again after importing pyrekordbox (T3.4), in case pyrekordbox sets levels itself or the app's logging setup was bypassed (tests, diagnostics).
- Coding-standards note (T5.8): changing these logger levels, or logging exception text from the rekordbox adapter, is a review blocker.

### T3.6: Pure mapping and the provider
**`source/providers/rekordbox/mapping.py`**:
```python
def to_track_record(rb: RbTrack, *, path: str, date_added: float, energy: int) -> TrackRecord
```
This follows the blueprint D8 table exactly:
- `title`/`artist`/`album`/`genre` from `rb`;
- `bpm = rb.bpm`;
- `key = rb.scale_name`, `camelot_key = tag_reader.to_camelot(rb.scale_name)` (`""` when unanalysed);
- `comments = rb.comments`;
- `energy_level = energy`;
- `play_count = rb.play_count`;
- `date = str(rb.release_year) if rb.release_year else ""`;
- `date_added`, `full_file_path = path`, `file_name = os.path.basename(path)`;
- `crates` is left for the provider to fill.

**`source/providers/rekordbox/provider.py`**: `RekordboxProvider`.
- `__init__(self, *, db_factory=None, energy_cache: TagEnergyCache | None = None, exists=os.path.exists, energy_reader=tag_reader.read_energy_level)`. These are test seams. The registry uses the defaults (`energy_cache=energy_cache.DEFAULT`).
- `id = "rekordbox"`, `display_name = "rekordbox"`, `crate_noun = "playlist"`.
- **UI revision (copy), re-scoped after the database decision:** the earlier XML copy in `ui-design-brief.md` §6 is obsolete. The UI designer re-supplies the database-mode strings under the same convention (initial capital, no trailing period, no provider name, no path). Until then use the functional strings in this plan.
- `setting_specs()`:
  - `db_path`: FILE, env `REKORDBOX_DB_PATH`, `required=False`, `file_patterns=(("rekordbox database", "master.db"),)`, label `Database`, placeholder `Found automatically`, browse_title `Select your rekordbox database (master.db)`;
  - `auto_refresh`: CHOICE `("on", "off")`, env `REKORDBOX_AUTO_REFRESH`, label `Update automatically`.

  The UI designer may revise the copy. **No key setting** (blueprint D7).
- `default_settings()` → `{"db_path": "", "auto_refresh": "on"}`. A private `_db_path(settings) -> Path | None` returns `Path(settings["db_path"])` if set, else `default_db_path()`.
- `detect()` → `default_db_path()` is not `None` and the file exists.
- `capabilities(settings)` → `PLAYLIST_FOLDERS`, `NATIVE_PLAY_COUNT`, plus `CHANGE_DETECTION` **only when `auto_refresh == "on"`**. **Not** `SMART_PLAYLISTS` (unverified; the user has none). **Not** `DECK_LOAD` (Phase 6).
- `validate(settings)`: no DB open, UI-thread safe.
  - error `rekordbox database not found` (`setting_key="db_path"`) if `_db_path` is `None` or missing;
  - error `rekordbox support isn't available in this build` if `importlib.util.find_spec("pyrekordbox") is None`.
- `change_token(settings)` → `compute_change_token(path)` when `CHANGE_DETECTION` is declared and the path exists, else `None`.
- `load_to_deck(...)` → `raise DeckLoadNotSupported("Loading to a deck isn't available for rekordbox yet")`.
- `scan(settings, progress)`:
  1. `cleanup_stale_copies()`. Resolve `path` (missing → `ProviderError("rekordbox database not found")`). `token = compute_change_token(path)`, taken **before** copying, so a write during the scan triggers another refresh.
  2. `with private_copy(path, token_fn=compute_change_token) as copy: lib = db_reader.read_library(copy, db_factory=...)`. On `CopyIntegrityError`, repeat the copy + read **once**, then let it propagate.
  3. For each playlist (progress `("Reading playlists", i, total)`, same contract as `crate_parser.py:229-232`) and each content id:
     - an unknown id → count it as a warning;
     - on first sight of a track: `(track_path, file_exists) = resolve_track_path(rb.org_path, rb.folder_path, rb.local_path, exists=self._exists)`. `None` → count "no usable file path" and skip.
     - `date_added = file_creation_time(track_path) or 0.0` (ADR-013);
     - `energy = parse_comment(rb.comments).energy`; if `0` and `file_exists`: `energy = self._energy_cache.get(track_path, self._energy_reader)`;
     - `tracks[track_path] = to_track_record(...)`;
     - append the crate id.
  4. Crate id `f"rekordbox:{pl.playlist_id}"`. Label `" / ".join(pl.path)` (separator confirmed by the UI brief, §4.5; Serato keeps its " - "). Include empty playlists in `crates`. `is_smart` from `RbPlaylist`.
  5. Warnings (functional strings; copy by the UI designer):
     - `"{n} tracks have no file on this computer"`;
     - `"{n} tracks have no usable file path"`;
     - `"{n} playlist entries point to tracks that aren't in the collection"`;
     - plus `lib.warnings`.
  6. `fingerprint = {name: mtime}` for the `TOKEN_FILES` that exist; `change_token=token`.
  7. Log once at INFO: counts (tracks, playlists, tag reads performed, cache hits) and elapsed time. **No paths, titles or key.**
- **Library scope:** only tracks in at least one playlist (blueprint D8; user default kept).

### T3.7: Register
`source/providers/registry.py:18-20` → `PROVIDERS = {"rekordbox": RekordboxProvider(), "serato": SeratoProvider()}`, and update the module docstring (`:4-5`). **Insertion order rekordbox first** sets the display order, the fresh-install `detected` order (T2.1) and merge precedence. Importing the provider module must **not** import pyrekordbox (lazy import; tested in T3.10).

### T3.8: App sync stop-gap (replaces the Phase 2 "enable Serato" behaviour)
`source/app.py:308-322` (`_prepare_sync`). The existing dialog still calls `on_sync(path)` (`source/ui/sync_panel.py:71-73`).
- Save the dialog's Serato folder **only if Serato is enabled, or no provider is enabled**.
- Auto-enable Serato **only when no provider is enabled**. That keeps the Phase 2 fix for fresh installs but never re-enables Serato for a rekordbox-only user.
- Then build requests for **every enabled provider** (unchanged).
- With `PROVIDERS_ENABLED=rekordbox,serato` before Phase 4, the Phase 2 `merge` loads only the first snapshot (rekordbox) and logs a warning. That is expected until T4.1.

**UI revision:** this is a stop-gap only for the few commits between 3a and "Phase 3c" (see note above); do not ship it as a release. The enabled-provider list may be set by hand in `settings.env` until then.

### T3.9: Narrow the tag-reader bare except (debt #6)
`source/services/tag_reader.py:75-78`: `except (MutagenError, OSError) as e: logger.debug(...); return empty` (`from mutagen import MutagenError`; `ID3NoHeaderError` subclasses it). Add a module `logger`. Test: a non-ID3 file (e.g. a WAV header written to `tmp_path`) returns the empty dict, and an unexpected exception type is **not** swallowed. Serato behaviour is otherwise unchanged.

### T3.10: Tests (Phase 3a); synthetic data only
- `tests/services/test_log_safety.py`:
  - after `silence_secret_loggers()`, `logging.getLogger("pyrekordbox.db6.database").isEnabledFor(logging.DEBUG)` is `False`, and the same for `sqlalchemy.engine`;
  - with the root logger at DEBUG and `caplog.set_level(logging.DEBUG)` (root only), `logging.getLogger("pyrekordbox.x").debug("Key: %s", "SYNTHETIC-KEY-123")` leaves no record containing `SYNTHETIC-KEY-123`;
  - a stricter preset level (ERROR) is not lowered;
  - with `skipif(find_spec("pyrekordbox") is None)`: after `db_reader._ensure_pyrekordbox()`, `logging.getLogger("pyrekordbox").getEffectiveLevel() >= logging.WARNING`.
- `tests/services/test_comment_format.py`:
  - `"4A - 7 - Banger - Fat Bass Vocal"` → all fields;
  - `"8A - Energy 5 - Groover"`;
  - `"12B - 3"`;
  - `"Commercial"` → empty;
  - `"4A - high"` → key only, energy 0;
  - energy 9 → 0;
  - extra whitespace;
  - `""`.
- `tests/services/test_tag_reader.py` (extend):
  - `read_energy_level` on a synthetic ID3 file with `TXXX:EnergyLevel=6` (write it with mutagen in `tmp_path`) → 6;
  - no tag / non-ID3 / missing file → 0;
  - `get_track_metadata` energy is unchanged (parity);
  - T3.9's narrowed except.
- `tests/providers/rekordbox/__init__.py` and `fakes.py`:
  - `FakeMasterDb(contents, playlists, songs, quick_check="ok", smart_contents=None, raise_on=None)` with `get_content`, `get_playlist`, `get_playlist_songs`, `get_playlist_contents`, `session.execute(...).scalar()`, `close()`, `engine.dispose()`;
  - simple objects whose attribute names match the D8 list;
  - records any write-method call (`commit`, `add`, `delete`, `flush`) and whether `close`/`dispose` ran;
  - a `fake_factory(**kw)` that returns it.
- `test_paths.py`:
  - the token changes when the `-wal` mtime or size changes; a `-shm` change does **not** change it; an absent `-wal` gives `master.db-wal:-`;
  - `is_local_path` for `C:/x`, `\\\\srv\\x`, `/Users/x` and `/contents_1/x`;
  - `resolve_track_path`, table-driven over all six rules, with an injected `exists`;
  - normalisation of forward slashes (assert against `os.path.normpath` of the expected path, so it passes on any OS).
- `test_db_copy.py` (`tmp_path` as both the "rekordbox folder" and `tmp_root`):
  - copies db, wal, journal and xml when present, and **never `-shm`**;
  - the source files' mtime and size are unchanged;
  - a `token_fn` that changes on the first attempt → retried, then succeeds;
  - one that always changes → `ProviderError` busy, with no temp folders left behind;
  - a missing db → `ProviderError` not found;
  - the temp folder is removed after the `with` block, even on an exception inside it;
  - `cleanup_stale_copies` removes only old `sidecar-rb-*` folders.
- `test_db_reader.py`:
  - field mapping, including BPM ÷ 100, a missing key → `""`, and a missing attribute → default;
  - folder hierarchy → `path`; folders are not playlists; `TrackNo` order; a `ParentID` cycle doesn't hang;
  - a smart playlist whose evaluation raises → skipped plus one warning;
  - `quick_check != "ok"` → `CopyIntegrityError`;
  - **key safety:** a factory raising `RuntimeError("pysqlcipher://:SYNTHETIC-KEY-123@/x")` → `ProviderError("Couldn't read the rekordbox database")`, with `e.__cause__ is None` and `e.__suppress_context__`, and `SYNTHETIC-KEY-123` absent from `caplog.text` and `str(e)`;
  - `close` and `dispose` are called on success and on error; no write method is ever called;
  - pyrekordbox import failure (monkeypatch `builtins.__import__` or `sys.modules`) → `ProviderError` "isn't available".
- `test_energy_cache.py`:
  - the first call reads, the second call (same mtime and size) hits the cache (reader called once);
  - an mtime change → re-read;
  - a stat `OSError` → 0, not cached;
  - thread-safe under concurrent `get` (smoke test).
- `test_mapping.py`:
  - every D8 row;
  - `camelot_key` from `Am`, `8A` and `B\u266d`, and `""` when unanalysed;
  - `release_year` 0 → `""`.
- `test_rekordbox_provider.py` (fake factory, synthetic files in `tmp_path`, `tmp_root` patched):
  - crate ids `rekordbox:<ID>` and labels `A / B`; a track in two playlists → both ids; an empty playlist is present in `crates`;
  - an unknown content id → warning; a missing file → warning, track kept; no usable path → warning, track skipped;
  - `OrgFolderPath` is preferred over a local `FolderPath`;
  - **energy:** comment energy used without calling the reader; no comment energy plus an existing file → reader called; a missing file → reader **not** called; a second scan → reader not called again (cache);
  - the token is taken before reading;
  - `CopyIntegrityError` on the first read → one re-copy, then success;
  - `validate()` without opening the DB (factory not called);
  - `CHANGE_DETECTION` only when `auto_refresh == "on"`;
  - `change_token` is `None` when the path is missing;
  - `load_to_deck` raises `DeckLoadNotSupported`;
  - importing `source.providers.rekordbox.provider` doesn't put `pyrekordbox` in `sys.modules` (run in a subprocess, or check for a fresh import).
- `tests/services/test_diagnostics.py` (T3.12):
  - the report contains the counts and exit code 0 for a fake provider snapshot;
  - **no synthetic title, artist or track path appears in the report**;
  - a provider error → exit 1 with the fixed message.
- The contract test (`tests/providers/test_contract.py`) now covers rekordbox automatically. On machines without rekordbox, `change_token(default_settings())` must return `None`.

### T3.11: Energy fallback from file tags (user option (a))
- `source/services/tag_reader.py`: add `read_energy_level(path: str) -> int`. It reads only `TXXX:EnergyLevel` with `ID3(path)` and returns 0 on `(MutagenError, OSError)`, a missing tag, or a non-integer value. Factor the int parsing used at `:92-99` into a small `_tag_int(tags, key) -> int` helper used by both, so `get_track_metadata` behaves exactly as before.
- New `source/providers/rekordbox/energy_cache.py`:
  ```python
  class TagEnergyCache:
      def get(self, path: str, reader: Callable[[str], int]) -> int   # key (path_key(path), st_mtime_ns, st_size)
      def clear(self) -> None
  DEFAULT = TagEnergyCache()
  ```
  - Guard it with a `threading.Lock`.
  - A `stat` `OSError` → 0, not cached.
  - In-process only. It is a pure memo, so the provider stays stateless as far as the contract is concerned (blueprint D1/D8). Persisting it is out of scope.

### T3.12: Built-in rekordbox diagnostics; retire the spike script
- New `source/services/diagnostics.py` (uses only `registry`, the provider contract and `config`):
  - `self_check_rekordbox() -> int`: calls `log_safety.silence_secret_loggers()`, imports `pyrekordbox`, `sqlcipher3` and `sqlalchemy.dialects.sqlite`, and returns 0 (or 1 on `ImportError`/`OSError`). **No DB access**, so it is CI-safe.
  - `check_rekordbox_library() -> int`:
    1. get `registry.get_provider("rekordbox")` and its settings via `config.get_provider_settings`;
    2. `validate()`, then `scan()` **without saving a snapshot**;
    3. write a report to `user_data_dir() / "diagnostics" / f"rekordbox-check-{YYYYmmdd-HHMMSS}.txt"` and print it to stdout.

    The report contains:
    - package versions (`importlib.metadata`);
    - the DB location and its file sizes/mtimes;
    - the elapsed time;
    - tracks in scope, playlists, playlists with tracks;
    - tracks with a Camelot key / without one;
    - tracks with energy > 0;
    - tracks whose file exists;
    - the snapshot warnings.

    **No track titles, artists, track paths or key.** Returns 0, or 1 on `ProviderError`. The fixed message is printed.
- `main.py`: at the top of `main()` (`:13`), before any Tk object is created, handle `--self-check-rekordbox` and `--check-rekordbox-library` (`sys.exit(<function>())`). The PyInstaller exe is windowed (`console=False`), so the file report is the readable output there, and CI relies on the exit code.
- **Spike script:** `scripts/spike_rekordbox.py` is **not** gitignored (only `scripts/spike_rekordbox_output_*.txt` is), and its redaction regex contains a fragment of the database key. **Do not commit it.** Once `--check-rekordbox-library` has been run successfully on the user's machine, delete `scripts/spike_rekordbox.py`, and ask the user to delete the two local report files. The built-in check replaces it for the upgrade runbook.

> **Phase 3a implementation notes (engineer, deviations to confirm):**
> - **T0.7 / T3.1 acceptance (recorded here, not in the Phase 0 table):** a one-folder Windows build (PyInstaller 6.19, ~32 s) passes `--self-check-rekordbox` (exit 0) and `--check-rekordbox-library` (exit 0; 740 tracks, 75 playlists). The bundle is 111 MB, against 68 MB for the existing `dist/` build of unknown age. Identifiable additions: about 20 MB (`cryptography` 8 MB + `libcrypto-3.dll` 5 MB, `sqlcipher3` 5.7 MB, `sqlalchemy` 0.8 MB, `pyrekordbox` 0.5 MB, `psutil` 0.1 MB). `cryptography` arrives transitively through the pyrekordbox collection; not investigated further. No hidden imports beyond the planned ones were needed. Added `copy_metadata("SQLAlchemy")` and `copy_metadata("psutil")` so the frozen report shows their versions (it said "not installed" without them).
> - **CI self-check (Windows)** waits on the windowed exe with `Start-Process -Wait -PassThru` in PowerShell and checks `ExitCode`. Running a GUI-subsystem exe directly may not wait or return its code.
> - **No `db_reader.self_check()`:** T3.12 makes `diagnostics.self_check_rekordbox()` do the imports, so a second copy in `db_reader` would be dead code. As a result `diagnostics` imports pyrekordbox (via `importlib`) for the self-check, and also uses `providers.rekordbox.paths` (`default_db_path`, `TOKEN_FILES`) to report the DB location. It is rekordbox-specific by nature; flagging against the "only the registry imports concrete providers" rule.
> - **Diagnostics extras:** the energy line splits "from comment" / "from file tag"; `validate()` errors skip the scan; an unexpected exception is reported by type name only (exit 1).
> - **Provider:** constructor gains a `tmp_root` test seam (passed to `private_copy`/`cleanup_stale_copies`). The fingerprint is taken at the same moment as the change token (before copying), so the two always agree. `date_added` isn't `stat`ed for tracks whose file is missing (it would be `0.0` anyway). `TagEnergyCache` exposes `reads`/`hits` counters for the INFO log line.
> - **T3.8:** "no provider is enabled" means no *registered* provider is enabled (ids this version doesn't know don't count). When Serato is auto-enabled, unknown ids are kept (`with_provider_enabled`).
> - **`comment_format`** imports `config.TRACK_CATEGORIES` as the task specifies (so it is a leaf apart from `camelot` and `config`).
> - **Log noise:** pyrekordbox logs `WARNING Rekordbox is running!` on every open while rekordbox runs. It is harmless (no key) but appears on every scan and live refresh. Pinning `pyrekordbox` at ERROR would hide it (raising a level is allowed by T3.5's rule); not done without a decision. *(Resolved by the Phase 3a review: see below.)*
>
> **Phase 3a review follow-ups (applied):**
> - **RELEASE GATE: no release may be tagged until "Phase 3c" lands.** From Phase 3a on, a fresh install that detects rekordbox enables it (T2.1 + T3.7), but the settings dialog is still Serato-only, so behaviour changes before the UI supports it.
> - **`master.db` only:** `paths.is_master_db` (exact name; case-insensitive on Windows) is enforced by `validate()` (`Choose the file named master.db`, on `db_path`), `scan()`, `change_token()` (→ `None`) and, as defence in depth, `db_copy.private_copy`, so `-wal`/`-journal` are never paired with another database (e.g. a rekordbox backup).
> - **Shared path rule:** `paths.resolve_db_path(settings)` is used by both the provider and `diagnostics`. **Accepted layering deviation:** `services/diagnostics.py` imports `providers.rekordbox.paths`. *Architect: add one line to ADR-015 at T5.8.* Reports show the home folder as `~`.
> - **Key-safety boundaries:** `_ensure_pyrekordbox` and `read_library` catch `Exception`, log the type name only, and raise the fixed-text `ProviderError` **after** the `except` block, so `__cause__` and `__context__` are both `None`. `factory = db_factory or _default_factory()` is inside the guarded block.
> - **Log minimums:** `log_safety.SECRET_LOGGER_MINIMUMS = {"pyrekordbox": ERROR, "sqlalchemy": WARNING}`. Existing descendants with a lower explicit level are raised too; levels are never lowered. ERROR for pyrekordbox also hides "Rekordbox is running!". `main.py` configures logging and silences these loggers before importing `source.app`. A session-autouse test fixture silences them for every test.
> - **Self-check** also opens an in-memory SQLCipher database (`PRAGMA cipher_version`), and catches any exception (type name only). CI self-check steps have `timeout-minutes: 5`.
> - **`db_copy`:** any exception (including `KeyboardInterrupt`) during a copy, or from the "after" token, removes the candidate copy.
> - **Soft-deleted rows** (`rb_local_deleted` truthy) are skipped in contents, playlists and playlist songs.
> - **Energy fallback** is best effort: a per-track boundary catches any exception from the tag read, logs the type name once per file per scan, and uses 0. `tag_reader` keeps T3.9's narrowed except.
> - **T3.8 decision** is the pure `settings_migration.plan_sync(...)` (next to `with_provider_enabled`).
> - **Tests:** fake-based `db_reader`/provider tests no longer need pyrekordbox (they patch `db_reader._pyrekordbox`/`_sql_text`). A session fixture points `paths.default_db_path` at a missing temp file, so no test stats the real rekordbox folder. *Note:* the one real-pyrekordbox log test still runs pyrekordbox's own import-time configuration, which reads (never writes) rekordbox's settings files.
> - **NITs:** `to_camelot` maps `♯` to `#` and upper-cases pass-through Camelot (`8a` → `8A`). **This also affects Serato tags:** a lowercase Camelot `TKEY` used to give `""` and now gives the key. `_SnapshotBuilder` takes `exists`/`energy` callables.
> - **Bundle size:** not trimmed (`libcrypto` is CPython's own). *To do before release:* build the parent commit with the same PyInstaller for a real size baseline.

---

## Phase 3b: Live refresh (rekordbox)

**Exit criteria:** with rekordbox enabled and auto-refresh on, a change in rekordbox (comment edit, playlist add) appears in Sidecar within about `poll + settle` seconds. The current track, session, applied filters and an active audio preview are not disturbed. A no-op change (e.g. play-count-only writes when nothing visible changed) causes no reload. Turning auto-refresh off stops the watcher for rekordbox.

### T3b.1: Constants
`source/config.py` (after `KEY_OFFSET_RANGE`, `:178`): `REFRESH_POLL_SECONDS = 10`, `REFRESH_SETTLE_SECONDS = 5`, `REFRESH_MIN_INTERVAL_SECONDS = 60`. These are defaults: Phase 0 didn't measure write bursts, so tune them after trying it during a real session (play a few tracks, edit a comment). Record the result in the Phase 0 findings table (T0.6 row).

### T3b.2: Watcher service
New `source/services/library_watcher.py`:
```python
@dataclass
class WatchState:
    synced_token: str | None        # token stored in the provider's snapshot
    candidate: str | None = None    # last differing token seen
    candidate_since: float = 0.0
    last_refresh_at: float = 0.0

def should_refresh(state: WatchState, token: str | None, now: float, *,
                   settle_s: float, min_interval_s: float) -> bool   # PURE; updates candidate fields

class LibraryWatcher:
    def __init__(self, targets_fn: Callable[[], list[tuple[LibraryProvider, Mapping[str, str]]]],
                 synced_token_fn: Callable[[str], str | None],
                 on_refresh_needed: Callable[[str], None],
                 *, poll_s: float, settle_s: float, min_interval_s: float,
                 clock: Callable[[], float] = time.monotonic) -> None
    def start(self) -> None          # daemon thread "library-watcher"
    def stop(self, timeout: float = 1.0) -> None
    def mark_refreshed(self, provider_id: str, token: str | None) -> None
```
- Each tick re-reads `targets_fn()`, which gives the enabled providers that declare `CHANGE_DETECTION`. This way enabling, disabling or toggling auto-refresh takes effect without restarting the watcher.
- For each target it calls `provider.change_token(settings)` (2 `stat` calls for rekordbox), catching `OSError` and logging at debug, then `should_refresh(...)`.
- `on_refresh_needed(pid)` is called from the watcher thread. The app marshals it.
- **No Tk imports.** Uses `threading.Event` for stop and sleep, so `stop()` returns promptly.
- The startup refresh comes for free: the first tick compares against the snapshot's stored token.

### T3b.3: Single-flight sync with coalescing
`source/services/library_sync.py`: add a `SyncCoordinator` class, owned by `app`:
- `request(requests, *, silent: bool, done_callback)`: if no sync is running, start `sync_providers`. Otherwise **merge** the provider ids into one pending follow-up (a manual request upgrades `silent=False`).
- When a run finishes, its callback fires, then the pending run (if any) starts.
- Thread-safe with a `threading.Lock`.

This replaces direct `sync_providers` calls in `app.py`, and the Phase 2 `_sync_in_progress` guard (`source/app.py:45,286-300,345`).

### T3b.4: App integration and state-preserving reload
`source/app.py`:
- Create the watcher after `self._try_load_existing()` (`:52`):
  - `targets_fn` = enabled providers ∩ `CHANGE_DETECTION`, with their settings (`_provider_settings`, `:161`);
  - `synced_token_fn` = `library_store.snapshot_summary(pid).change_token`;
  - `on_refresh_needed = lambda pid: self.after(0, lambda: self._request_refresh(pid))`.

  `start()` it. In `_on_close` (`:128-131`), call `self._watcher.stop()` **before** `self.destroy()`, and guard `after()` calls from the watcher thread with a `_closing` flag (catch `RuntimeError`/`tk.TclError`), the same as the update-check thread pattern (`_check_for_updates_async`, `:228`).
- `_request_refresh(pid)` → coordinator `request([...], silent=True, done_callback=...)`. In the done handler (marshalled):
  1. `watcher.mark_refreshed(pid, snapshot token)`.
  2. If `report.any_changed`, `self._reload_library(preserve_state=True)`.
  3. On error, update the settings dialog card if it is open, and show at most one non-blocking toast per failure state. Copy: UI designer, blueprint §6 item 7.
  4. **No** `self._audio_player.stop()` and **no** standard "Synced…" toast.
- Implement `preserve_state=True` in `_reload_library` (`:144-157`):
  1. Re-resolve `self._current_track` via `library.track_by_path(old.full_file_path)`. If it disappeared, keep the old object displayed.
  2. Re-resolve session tracks: add `SessionPanel.rebind_tracks(resolve: Callable[[str], Track | None])` in `source/ui/session_panel.py`. It replaces entries by path and keeps order and missing ones (the `played_paths` semantics are unchanged).
  3. Call `set_crates`/`set_genres` with `preserve_selection=True` (T3b.5).
  4. `self._update_suggestions()` (`:401`) re-scores with `suggestion_panel.applied_filters` (ADR-012).
  5. The dashboard refreshes the current track's badges via `self.dashboard.set_track(...)` only, **without** adding it to the session again (`_on_track_selected`, `:378`, adds to the session).
- Manual sync (`_sync_finished`, `:344-364`) keeps today's behaviour (`preserve_state=False`, audio stop, toast).

### T3b.5: Filter selections survive a live refresh
- `source/ui/filter_bar.py` `FilterDropdown.set_items(items, *, preserve_selection: bool = False)`: when `True`, existing keys keep their `BooleanVar` value, new keys start checked, and removed keys are dropped. The pill label and staged/applied state stay correct: call `_update_label()` and don't fire `on_change`.
- `source/ui/suggestion_panel.py` `set_crates` / `set_genres` forward `preserve_selection`.
- The applied snapshot: when a crate id disappears, the applied `SuggestionFilters.allowed_crates` may still contain it. That is harmless to the engine (an intersection with nothing), but dirty detection would then see staged ≠ applied. **Rule:** after a `preserve_selection` reload, the panel prunes unknown ids from `_applied_filters` without re-scoring, so the Apply bar doesn't appear spuriously. Add `SuggestionPanel.prune_applied_filters(known_crate_ids, known_genres)`.
- *UI designer, resolved:* manual sync keeps today's behaviour (no `preserve_selection`). A manual sync is something the DJ asked for in the dialog, not a background event, and the library may have changed a lot.

### T3b.6: Tests (Phase 3b)
- `tests/services/test_library_watcher.py`, pure `should_refresh` with an injected clock:
  - same token → no;
  - a new token is not refreshed before `settle_s`;
  - a token that is still changing resets the settle window;
  - `min_interval_s` respected;
  - `None` token → never;
  - after `mark_refreshed` → no.

  Plus a threaded smoke test with `poll_s=0.01` and a fake provider whose token flips once: `on_refresh_needed` is called exactly once, and `stop()` returns within the timeout.
- `tests/services/test_library_sync.py`: the coordinator coalesces three requests during a run into one follow-up; a manual request upgrades a silent pending one.
- `tests/ui/test_filter_dropdown_pairs.py`: `preserve_selection` keeps unchecked keys unchecked, new keys checked, removed keys gone, and `on_change` not fired.
- `tests/ui/test_session_rebind.py` (follow the `tests/ui/` display-skip convention): order is kept, objects are replaced, missing entries are kept.

> **Phase 3b implementation notes (engineer, deviations to confirm):**
> - **Tk thread only:** background threads (sync, watcher, update check) never call Tk, not even `after()`. They `app._post(fn)` onto a `queue.SimpleQueue` that a Tk-thread pump drains every 100 ms (`UI_QUEUE_POLL_MS`). This replaces the plan's `after(0)` + `_closing`/`TclError` guard; `_closing` still stops posting and draining. The existing update-check thread uses it too.
> - **Coordinator callbacks:** `done_callback(report, silent)` gets the run's mode. Each distinct callback fires once per run, so a silent refresh merged into a manual follow-up is handled once, as manual (`silent=False`). Every successful result (manual or silent) calls `watcher.mark_refreshed(pid, result.change_token)`, so a manual sync also moves the watcher's baseline. `ProviderSyncResult` gains `change_token`. A follow-up that can't start reports `"Couldn't start the sync"` to its callbacks.
> - **Manual sync during a running sync** is now queued (merged), not ignored; the dialog shows "Syncing" either way.
> - **`WatchState.last_refresh_at`** defaults to `None` ("never"), not `0.0`: `time.monotonic()` can be under 60 s on a freshly booted machine. The request time (not the completion) starts the minimum interval, so a failing refresh retries at most once per interval.
> - **Snapshot missing:** with rekordbox enabled but never synced, the stored token is `None`, so the watcher performs the first import automatically (quietly) after the settle time.
> - **Filters across a refresh (T3b.5):** instead of `prune_applied_filters(known…)`, `SuggestionPanel.reconcile_applied_filters(old/new crates, old/new genres)` applies the same rule the checkboxes follow (`suggestion_filters.reconcile_allowed`: kept keys keep their state, new keys allowed, removed keys dropped, "covers every key" → `None`). Pruning alone would show a spurious Apply bar when a new crate arrives checked, or when the only unchecked crate disappears. Staged-but-unapplied edits stay staged.
> - **Audio preview:** `SuggestionPanel.set_suggestions` stops any preview, so while a preview is active the quiet refresh does **not** re-render suggestions. They re-score on the next track selection, filter Apply or setlist change. Selections from a pre-refresh list are re-resolved to the library's current object (`app._current_object`).
> - **Dashboard:** new `NowPlayingDashboard.refresh_track(track)` re-renders badges and the info line without touching the search box (`set_track` would overwrite what the DJ is typing).
> - **Failure feedback (functional minimum; UI designer to revise):** one red toast per provider per distinct error, `"{display_name} update failed: {error}"` (8 s); cleared on the next success. The Serato-only settings dialog is not updated for silent refreshes.
>   *UI designer, resolved (built in T3c.2 and T3c.5):* the toast becomes an **amber Warning** toast `"{display_name} auto-update failed: {error}"` (8 s), same dedup and clearing. Silent refresh results now **do** update the open settings dialog (chip, issue and warning lines only, never the staged values).
> - **"Nothing visible changed"** uses the snapshot `content_hash` (`report.any_changed`). Play-count changes do reload (play count is shown in the Now Playing info line).
> - **Phase 3b review follow-ups (applied):**
>   - **Sync outcome is a pure helper** (`services/sync_outcome.py`, new): the app reloads whenever `report.any_changed`, even if another provider failed, and still shows the failure toast. Otherwise a merged run where Serato fails and rekordbox succeeds would hide the change for good, since the watcher baseline already moved. Refresh-error toasts are deduplicated per provider until a success; a manual failure also suppresses the same error on the next refresh. `app._sync_finished`/`_refresh_finished` are replaced by it.
>   - **Unchanged snapshots aren't rewritten:** `library_store` keeps `<pid>.meta.json` (`synced_at`, `change_token`, `content_hash`, `fingerprint`, counts). An unchanged sync rewrites only that (a few hundred bytes); the previous hash is read from it, never by parsing the snapshot. `snapshot_summary` (the watcher baseline) reads it, falling back to the full snapshot for files without metadata. `load_snapshot` takes the metadata's token when its hash matches the snapshot's. Write order is snapshot then metadata, so a crash in between only causes one extra full write.
>   - **Main-thread work on a refresh:** `FilterDropdown.set_items(preserve_selection=True)` returns early when the `(key, label)` list is unchanged. `SessionPanel.rebind_tracks` skips the rebuild when the tracks are equal by value. The dashboard re-renders only if the current track changed by value. Suggestions: `SuggestionPanel.show_suggestions_quietly` re-renders only when the visible content (path, score, tier, title, artist, key, BPM, energy, crates) changed, keeps the scroll position, and **defers while the pointer is over the list** (re-checked every 400 ms) **or a preview is active** (playing or paused; rendered as soon as it stops or ends). This pending render is the "stale" flag; an explicit render (track pick, Apply, setlist change) supersedes it. *UI designer, resolved:* the defer-under-pointer and defer-during-preview behaviour is **confirmed** (rows must not move under the cursor in the core loop), and **no "list updated" cue** is added (brief §5.5, O14 for the override). One optional coherence fix (T3c.6, last bullet): apply the Now Playing badge refresh at the same moment as the deferred list render. (3d, handing the in-memory snapshot to the load path, not done: optional.)
>   - **Shutdown:** `SyncCoordinator.wait_idle(timeout)`; `_on_close` waits up to 2 s so an in-flight snapshot write completes. Startup (`run_startup_migrations`) deletes orphan `library/*.tmp` files older than 60 s.
>   - **Windows sharing violations:** `config.replace_with_retry` (5 attempts, 50 ms × attempt backoff) is used by `config._save_env`, `library_store` and the settings backup.
>   - **Dialog:** `SyncReport.follow_up_pending` (set by the coordinator before callbacks). The dialog's "Syncing" state and status are only updated when nothing is queued behind the run.
>   - The coordinator catches any exception from `_start`.
> - **Phase 3b follow-ups (after approval, applied):**
>   - **Focus floor is 30 s** (`REFRESH_FOCUS_FLOOR_SECONDS = 30`, also the watcher's default), not 10 s: an idle rekordbox changes its WAL about every 30 s, so a 10 s floor would let focus switching bypass the adaptive backoff.
>   - **Dialog "Syncing" rule:** cleared only when the coordinator recorded no follow-up when the run finished (`SyncReport.follow_up_pending`) **and** `SyncCoordinator.has_pending` (new) is false when the Tk thread handles the report. `not is_running` is deliberately not used: the finishing run is still marked running when its report is posted, so that test would keep "Syncing" up permanently. Accepted narrow race: a Sync click within the ~100 ms between a run finishing and its report being handled can briefly show not-syncing; the new run's report then sets the right state.
>   - **Quiet-render timer:** new public `SuggestionPanel.cancel_quiet_render()` (drops the pending render and its retry timer), used by explicit renders, `clear()` and `app._on_close`. `_try_quiet_render` cancels any existing retry timer first, so repeated refreshes can't stack retry loops.
> - **Refresh policy (decision; architect to note in ADR-015 D11):** base `REFRESH_MIN_INTERVAL_SECONDS = 60`, plus:
>   - **adaptive backoff:** every 3 consecutive successful refreshes with `changed=False` double the effective interval, up to `REFRESH_MAX_INTERVAL_SECONDS = 300` (60 → 120 → 240 → 300). Any real change or a manual sync resets it to 60. The pure `record_refresh_result(state, changed, manual, …)` is applied via `watcher.mark_refreshed(pid, token, changed=…, manual=…)`. Doubling *every* 3 unchanged refreshes (rather than once) is my reading of "double … up to 300 s".
>   - **refresh on focus:** `<FocusIn>` on the main window (throttled to one check per 2 s, because it fires per widget) calls `watcher.request_focus_check()`, which wakes the watcher thread. `should_refresh(..., focus=True)` requests a refresh if the token differs from the baseline, **without** the settle wait, with a floor of `REFRESH_FOCUS_FLOOR_SECONDS = 10` since the last request. Still single-flight through the coordinator.
> - **Timings** are the plan defaults (10 s / 5 s / 60 s). **T0.6 evidence (live run, rekordbox 7.2.19 open, 270 s, no user activity):** rekordbox appends to `master.db-wal` about **every 30 s** (+12,360 bytes each time) even when idle; `master.db` itself did not change. With the defaults the watcher refreshed exactly once per minimum interval (completion gaps 59.4/60.0/60.1/60.1 s). Each refresh took about 0.4–0.6 s (copy + read), and after the first import every one reported `changed=False`, so nothing reloaded and the UI wasn't touched. So **while rekordbox is open, Sidecar does one background copy+read per minute indefinitely**. Settle (5 s) is fine against 30 s write spacing. Raising `REFRESH_MIN_INTERVAL_SECONDS` would cut that background cost but slow how quickly real edits appear; left at 60 s pending a product decision. *(Decided in the Phase 3b review: keep 60 s, add adaptive backoff and refresh on focus; see above.)*
>   **Sizes and timings after the review fixes** (same machine, rekordbox open): 740 tracks in scope; `master.db` 16,011,264 bytes; `rekordbox.json` snapshot 568,219 bytes. First (changed) refresh 1.19 s; unchanged refreshes 0.39–0.44 s, each rewriting only `rekordbox.meta.json` (the snapshot file's mtime stayed constant across them).

---

## Phase 3c: Settings dialog, toasts, empty states (UI; replaces T5.1, T5.2, T5.5 strings, T5.11)

**Design source:** `ui-design-brief.md` (revised 2026-11-05). Every user-visible string below is final unless marked otherwise; the full copy tables are brief §5.5 and §7. **Gate:** Phases 3a and 3b are done. **Release gate (unchanged):** no release before this phase lands. **Sequencing recommendation:** do `T4.1` and `T4.2` (pure merge and `Track.sources`) first or alongside. Today `merge()` uses only the first snapshot (`source/services/library_merge.py:27-35`), so a DJ who switches Serato on next to rekordbox would see nothing change. If 3c must ship first, add the interim line from brief §5.9 (decision O15).

**Exit criteria:**
- A rekordbox-only user can turn rekordbox on and off, choose or clear the `Database` path, switch automatic updates on or off, save, and sync, and sees no Serato field, hint, prompt, error, toast, noun or placeholder. The name "Serato DJ" appears only as a switched-off provider card (`Off`), which is how Serato is turned on later. *(Reworded 2026-11-05 after the 3c audit; was "without ever seeing the word 'Serato'".)*
- With both providers on, the playlist filter is grouped by provider, searchable and wide enough to read (T3c.10).
- The dialog works at `540x420` (body scrolls, footer pinned).
- A fresh install with rekordbox detected goes from `Reading your library…` to the `Imported N tracks from rekordbox` toast with no clicks.
- Nothing in the dialog or toasts says "crates" to a rekordbox-only user.
- A refresh result never overwrites edits the DJ has staged in an open dialog.

**Execution order:** T3c.4, T3c.1, T3c.3, T3c.2, then T3c.5 to T3c.8 (any order, tests alongside), then T3c.10 and T3c.11 (from the UI audit, `ui-audit-phase-3c.md`), then T3c.9 (acceptance runs after them).

### T3c.1: Pure copy module
New `source/services/library_copy.py` (no Tk; **services, not ui**, because `services/sync_outcome.py` must use it and services must not import ui). It holds every string of brief §7 so copy changes touch one file. Functions (names are the contract; signatures may take primitives):
- `format_count(n) -> str`: `1248` becomes `"1,248"`.
- `relative_time(iso_utc: str, now: datetime) -> str`: under 45 s `"just now"`; `"1 minute ago"`, `"12 minutes ago"`; `"2 hours ago"`; `"3 days ago"` (up to 29); then `"on 3 Nov"`, or `"on 3 Nov 2025"` in another year. Empty or unparsable input returns `""`.
- `absolute_time(iso_utc) -> str`: local `"3 Nov, 14:20"`, for the fallback line.
- `crate_noun_for(nouns: Iterable[str]) -> str`: empty or all `"crate"` gives `"crate"`; all the same other noun gives that noun; any mix gives `"playlist"`. (Serato only = crate; rekordbox or a mix = playlist; brief O3.) Plus `pluralise(noun, n)` (`"1 playlist"`, `"75 playlists"`), `noun_title(noun, plural=True)` (`"Playlists"`).
- `status_chip(...) -> tuple[str, ...]` (one or two lines). Inputs: `enabled`, `busy`, `synced_at`, `track_count`, `crate_count`, `noun`, `auto_updates` (True when `CHANGE_DETECTION` is in the view's capabilities), `now`. Outputs: busy gives `("Syncing…",)`; no snapshot gives `("Not synced yet",)`; manual gives `("Synced 2 hours ago · 1,248 tracks · 75 playlists",)`; automatic gives `("Updates automatically · 1,248 tracks · 75 playlists", "Last updated 2 minutes ago")`. A disabled card gives `("Off. Saved library kept.",)` with a snapshot, else `("Off",)`.
- `issue_tone(issue, field_value) -> "error" | "warning"` (brief §5.2): warning severity gives warning; error severity whose `setting_key` field value is empty gives warning (amber prompt); any other error gives error.
- `footer_state(enabled_ids, errored_ids, names, dirty, busy) -> FooterState(sync_enabled, message, tone, close_label, save_enabled)`: zero enabled gives `sync_enabled=False`, message `Turn on at least one source to load tracks.` (warning); some enabled but all errored gives disabled with `Skipped {name}: {message}`; some errored gives enabled and the `Skipped …` line (first, `(+N more)`); `close_label` is `"Close"` when clean, `"Cancel"` when dirty; `save_enabled=dirty and not busy`.
- `format_load_toast(count, crate_count, noun)`: `Loaded 1,248 tracks from 75 playlists`.
- `format_sync_success(count, crate_count, noun, names)`: one source `Synced 1,248 tracks from 75 playlists`; several `Synced 1,300 tracks from rekordbox and Serato DJ` (`join_names`: `"a"`, `"a and b"`, `"a, b and c"`).
- `format_import_toast(count, names)`: `Imported 1,248 tracks from rekordbox`.
- `format_partial_failure(ok_names, failed_name, error)`: `Synced rekordbox. Serato DJ sync failed: Crates folder not found`.
- `format_sync_failure(name, error)`: `rekordbox sync failed: Database not found`. `format_all_failed(names)`: `Sync failed for rekordbox and Serato DJ`. `format_refresh_failure(name, error)`: `rekordbox auto-update failed: Database not found`.
- `empty_library_state(enabled_ids, auto_import_pending_ids, failed_ids) -> EmptyLibraryState(placeholder, toast_text | None)` (brief §5.8): none enabled gives `Turn on a music source in Settings (⚙) to begin` + toast `No music source is turned on`; some provider "will import by itself" (declares `CHANGE_DETECTION`, no snapshot, not in `failed_ids`) gives `Reading your library…` and no toast; otherwise `Sync your library in Settings (⚙) to begin` + toast `Your library isn't synced yet`. A non-empty library never reaches this function.
- Window and dialog titles: `WINDOW_TITLE = "Sidecar — DJ Track Selector"`, `dialog_title(version) = f"Settings — Sidecar v{version}"`.
- Strings only the dialog uses (section heading and sub-text, precedence note, interim line, `Unsaved changes`, `Settings saved`, `Using your library from {absolute}.`, hint texts live on the specs) are constants here.

### T3c.2: `sync_outcome` copy, colours and the first-import flag
`source/services/sync_outcome.py` (pure; update `tests/services/test_sync_outcome.py`). Colours come from T3c.4; text from T3c.1. Add `action_label: str | None = None` to `Toast`, and a `library_was_empty: bool` argument. New `SyncOutcome.import_candidate: bool` (= `silent and library_was_empty and report.any_changed`; the app confirms `library.count > 0` after the reload, then shows the import toast naming the succeeded providers).

| Case | Toasts |
|---|---|
| silent, a provider failed with a new error | Warning, 8 000 ms: `format_refresh_failure` (dedup and clearing exactly as now, `sync_outcome.py:53-64`) |
| manual, all OK | none from here; `success_toast=True` (app builds the count text) |
| manual, some OK and some failed | Warning, 8 000 ms: `format_partial_failure` (first failed provider) |
| manual, one provider in the report, failed | Error, 4 000 ms: `format_sync_failure` |
| manual, two or more providers, all failed | Error, 8 000 ms, `action_label="Open settings"`: `format_all_failed` |

`reload`, `preserve_state`, `stop_audio` and `clear_dialog_syncing` keep their current rules (`sync_outcome.py:65-92`). Never say "Synced" when every provider failed.

### T3c.3: Provider copy edits and the `detected_values` hook
- `source/providers/rekordbox/provider.py`: `_NOT_FOUND` (`:51`) becomes `"Database not found"`; `_UNAVAILABLE` (`:52`) becomes `"Support isn't available in this build"` (no provider name inside provider messages; the UI adds it). `db_path` spec (`:84-93`): `placeholder="Choose the file named master.db"`, `hint="Leave empty to use the database rekordbox created. Only choose a file if you moved it."`. `auto_refresh` spec (`:94-100`): `hint="Checks about once a minute and updates quietly. Your setlist and filters stay as they are."`. Keep `label="Database"` and `"Update automatically"`. The dialog shows CHOICE values as `choice.capitalize()` tiles (`On`, `Off`). Update the provider tests that assert the old strings.
- **Contract addition (blueprint §3):** `LibraryProvider.detected_values(settings) -> dict[str, str]` in `source/providers/base.py`: "values in effect for settings left empty, for display only, never persisted, stat calls only". `SeratoProvider` returns `{}`. `RekordboxProvider` returns `{"db_path": str(path)}` when `db_path` is empty and `resolve_db_path` finds an existing `master.db`, else `{}`. Reason: the dialog shows the detected path as a grey placeholder without branching on provider ids. Add it to the contract tests (returns a dict of known setting keys).
- Serato provider strings are already final (`provider.py:32-33,53-63`).

### T3c.4: Status colour constants
`source/config.py` (next to the other constants): `SUCCESS_COLOR = "#28a745"`, `WARNING_COLOR = "#ffc107"`, `ERROR_COLOR = "#dc3545"`, `INFO_COLOR = "#4AB8D4"`. Replace the literals in `app.py` (`:213`, `:335`, `:360`, `:439`, `:502`) and the `ERROR_COLOR` constant in `sync_outcome.py:19` (import it). Hint and secondary text use `#999999`. **No other new colours.** In the dialog, `Syncing…` uses `INFO_COLOR` (the `orange` literal at `sync_panel.py:78` goes away). `STAGED_TINT` is imported from `filter_bar.py:40` (or hoisted to config; engineer's choice).

### T3c.5: Settings dialog (`source/ui/sync_panel.py`, rewrite of `SettingsDialog`, `:7-83`)
Layout and behaviour: brief §4, §5.1 to §5.4. Keep `transient`, `grab_set`, `_center` (`:60-64`), the single-instance guard in `app._open_settings` (`app.py:447-459`), and the `ctk.CTkFont` sizes in guide §4.
- **View-model** (new pure module `source/services/settings_model.py`, no Tk, so it is unit-testable):
  ```python
  @dataclass(frozen=True)
  class ProviderSettingsView:
      provider_id: str; display_name: str; crate_noun: str
      enabled: bool
      specs: tuple[SettingSpec, ...]; values: dict[str, str]
      detected: dict[str, str]                 # provider.detected_values(values)
      capabilities: frozenset[ProviderCapability]
      summary: SnapshotSummary | None          # library_store.snapshot_summary(pid)
      issues: tuple[ProviderIssue, ...]        # provider.validate(values)
      warnings: tuple[str, ...]                # last sync or refresh warnings, this session
      last_error: str | None                   # last failed sync or refresh message
  ```
  plus `build_provider_views(...)` (T5.9's helper). `actions` and `on_provider_action` do not exist.
- **Constructor:** `SettingsDialog(master, views, *, on_save, on_sync, on_validate)` with `on_save(enabled_ids: list[str], values: dict[str, dict[str, str]])`, `on_sync(provider_ids: list[str])`, `on_validate(provider_id, values) -> list[ProviderIssue]`.
- **Public methods** (the app calls these through `_with_dialog`, `app.py:511`): `set_busy(bool)` (replaces `set_syncing`), `set_footer_status(text, color)` (replaces `set_status`), `update_status(views)` (refresh chips, issue, warning and fallback lines **only**; never touches entries, switches or tiles, so staged edits survive).
- **Geometry:** `640x580` clamped to `int(screen_height * 0.85)`, `minsize(540, 420)`, resizable. Body `CTkScrollableFrame`, footer `CTkFrame`, grid row weight on the body.
- **Card:** frame `fg_color="#2a2a2a"`, `corner_radius=10`. Header: `CTkSwitch` (O4; `CTkCheckBox` is the alternative), name (13 bold), chip label right-aligned (11, `#999999`, `wraplength` tied to the card width). Rows only while enabled; a disabled card shows header plus the grey `Off…` line.
- **Spec rows:** FILE/DIRECTORY: label, `CTkEntry` (`placeholder_text` = `detected[key]` when the value is empty and a detection exists, else `spec.placeholder`), `Browse` (`filedialog.askopenfilename(title=spec.browse_title, filetypes=spec.file_patterns, initialdir=<parent of value or detected path>)` / `askdirectory(title=spec.browse_title)`, cf. `sync_panel.py:66-69`). CHOICE with one choice: hidden; with two: tile row (`ACCENT_BLUE` active, `NEUTRAL_PILL` otherwise, as `filter_bar.py:815-818`), tile text `choice.capitalize()`. TEXT: plain entry, masked if `spec.secret`. `visible_when` honoured. `spec.hint` under the row (11, `#999999`, wraps).
- **Issues:** colour by `library_copy.issue_tone` (red `ERROR_COLOR`, amber `WARNING_COLOR`). Warnings: first warning plus ` (+N more)`, the rest in a `tooltip.py` tooltip. Fallback line `Using your library from {absolute}.` (grey) when a snapshot exists and (`last_error` or an error issue). Show `last_error` as a red line only if it differs from an issue already shown. Validate through `on_validate` on open, after Browse, on entry focus-out and Enter; **not per keystroke**.
- **Footer:** left, status label (12; green after sync/save, amber for `footer_state` messages); right of it `Unsaved changes` (11, `STAGED_TINT`) when dirty. Buttons: close (`Close` or `Cancel`), `Save` (disabled when clean or busy), `Sync enabled sources` (green `#28a745` / hover `#218838`, 14 bold, `sync_panel.py:42-48`; text `Syncing…` and disabled when busy or when `footer_state.sync_enabled` is false). "Dirty" = enabled set or any value differs from the views the dialog was given. `Sync enabled sources` calls `on_save(...)` then `on_sync(<enabled, error-free provider ids in registry order>)`.
- **Busy:** `set_busy(True)` disables switches, entries, Browse, tiles and Save; each enabled card's chip becomes `Syncing…` in `INFO_COLOR`. The close button stays enabled; closing does not cancel the sync. **No per-provider "Waiting…"** (the coordinator has no per-provider events).
- **Keys:** Esc closes; the window close button acts as Cancel (no prompt); Enter does not sync.
- **Heading and notes:** `Music sources` (13 bold) and the sub-text (11, `#999999`). Precedence note or interim line (brief §5.9) shown while two or more providers are enabled.

### T3c.6: App wiring (`source/app.py`)
- **`_open_settings`** (`:447-459`): build views with `build_provider_views` from `all_providers()`, `effective_enabled_providers()` (staged form uses the saved set), `_provider_settings`, `library_store.snapshot_summary`, `provider.validate`, `provider.detected_values`, a new in-memory `self._provider_warnings: dict[str, tuple[str, ...]]` and `self._refresh_errors` (`:67`). Remove the `default_path` argument.
- **`on_save`**: `save_enabled_providers(ids in registry order)`; `save_provider_settings(provider.setting_specs(), values[pid])` per provider; `self._reload_library()` (not preserved: the DJ asked for it); `self._update_empty_state()`; footer `Settings saved` (green). The watcher picks up enable/disable and auto-update changes on its next tick (T3b.2).
- **`on_sync(ids)`**: build `SyncRequest`s from `get_provider(pid)` and `_provider_settings(pid)`, then `self._sync.request(requests, silent=False, done_callback=self._on_sync_done)`; keep the failure path `_report_sync_start_failure` (`:501-509`). **Delete `_prepare_sync` and the `_on_sync(subcrates_path)` signature** (`:463-499`); `settings_migration.plan_sync` is then unused (remove it and its tests, or leave it; engineer's call).
- **`_sync_done_on_ui`** (`:310-346`): (1) store `self._provider_warnings[pid] = result.warnings` for every result, silent or manual; (2) capture `library_was_empty = self.library.count == 0` before reloading and pass it to `sync_outcome`; (3) after the reload, if `outcome.import_candidate and self.library.count`, show `format_import_toast(...)` (Success, 4 000 ms); (4) manual success text via `format_sync_success` (replaces `:334`); (5) **for silent results too**, call `dialog.update_status(views)` if the dialog is open (never `set_busy`, never the footer); (6) manual: `dialog.set_busy(False)` and `set_footer_status(text, color)` as now; (7) call `_update_empty_state()`; (8) pass `action_label`/callback (`self._open_settings`) when a `Toast` carries one.
- **Startup `_try_load_existing`** (`:207-214`): toast text via `format_load_toast(count, crate_count, noun)`; then `_update_empty_state()`.
- **`_update_empty_state()`** (new): if `library.count == 0`, `empty_library_state(enabled, pending_auto_import, failed_ids=self._refresh_errors keys)`, then `dashboard.set_empty_message(state.placeholder)`; the toast (Info `INFO_COLOR`, 15 000 ms, action `Open settings`, precedent `_show_update_toast` `:435-443`) only on startup, not on every reload. If the library is not empty, `dashboard.set_empty_message(None)`.
- **Window title** (`:52`): `WINDOW_TITLE`.
- **Noun:** after every reload, `noun = crate_noun_for(<crate_noun of each enabled provider>)`; call `suggestion_panel.set_noun(noun)` and `dashboard.set_crate_noun(noun)` (T3c.8).
- *Optional coherence fix (brief §5.5):* in `_restore_state_after_refresh` (`:236-256`), when the current track changed by value and the list render is deferred, apply `dashboard.refresh_track(fresh)` at the same moment as the deferred list render (from the quiet-render completion in `suggestion_panel.py:427-441`), so badges and list never disagree.

### T3c.7: Empty-library placeholder
`source/ui/track_detail.py`: `NowPlayingDashboard.set_empty_message(text | None)` sets the title label (`:80-83`); `None` restores `Search for a track to begin`; it must not overwrite a selected track's title (only act when no track is shown). No auto-opened dialog (O8).

### T3c.8: Noun in the main window (the noun-only part of T5.3/T5.4)
- `source/ui/filter_bar.py`: `FilterDropdown.set_label(noun_title)` (the pill label feeds the existing `pill_label` helper, `:99-102`, so `Playlists: 3/9` works); the overlay-empty text becomes `No {nouns} loaded. Sync a source in Settings.` (replace the `self._label.lower()` derivation near `:326-338`). The crate pill is built at `:940`; keep `label="Crates"` as the initial value.
- `source/ui/suggestion_panel.py`: `empty_state_message(..., noun="crate")` (`:50-65`): `No {nouns} selected — pick at least one {noun} to see suggestions.`; the row tooltip heading (`:585-587`) becomes `{Nouns}: …`; `SuggestionPanel.set_noun(noun)`.
- `source/ui/track_detail.py:184`: `f"{Nouns}: {crate_str}"`; `set_crate_noun(noun)`.
- **Not in T3c.8 (group headers, wider overlay, sort and search moved to T3c.10 on 2026-11-05; the leaf-name pill and per-provider tooltip lines stay in Phase 5).**

### T3c.10: Playlist filter at scale (pulled forward from T5.3; UI audit H1)
Design source: `ui-audit-phase-3c.md`, decision (a). Files: `source/ui/filter_bar.py` `FilterDropdown`, `source/models/library.py` `crate_items`, `source/ui/suggestion_panel.py:209-210` (the call site). Reason: the user's real data is 148 items (73 rekordbox playlists plus 75 Serato crates, many with identical names) in a 200x200 flat list. Minimal scope, nothing more:
- **Provider group headers.** `set_items` accepts a group per item. With two or more groups, render a non-interactive header per group in registry order (`REKORDBOX`, `SERATO DJ`; 10 bold, uppercase, **secondary `#999999`**, not tertiary). One group = flat list as today; a provider with no crates gets no header. `crate_items` must carry provider id and path (the engine contract is unchanged: `selected` returns crate ids; `preserve_selection` must keep working).
- **Sort** inside each group by `casefold`ed path tuple (replaces the case-sensitive sort at `library.py:52`).
- **Overlay size** about 300 x 320 (was 200 x 200, `filter_bar.py:326`), clamped to the left pane width and the window bottom; 200 px fallback at the narrowest pane. Truncate labels near 38 characters (`utils.py:1`); a `tooltip.py` tooltip only on truncated rows.
- **Type-to-filter.** Search entry at the top of the overlay, focused on open, placeholder `Find a {noun}`, 150 ms debounce, case-insensitive substring on the full label. Rows are hidden and shown (build the 148 checkboxes once), so selection survives typing; headers with no visible rows are hidden. While text is present the buttons read `Select shown` / `Clear shown` and act on visible rows only; with the text cleared they read `Select all` / `Clear`. No match: `No {nouns} match "{text}"` (same style as the empty label).
- **Not built here:** leaf-name pill, per-provider tooltip lines (T5.4), collapsible tree, clickable group headers (audit O17).
- **Tests** (`tests/ui/test_filter_dropdown_pairs.py`, extend): headers appear only with two or more groups; a provider with no crates gets no header; sort is case-insensitive within a group; search hides rows and headers but keeps checked state; `Select shown` ticks only visible rows; `selected` still returns crate ids; `set_items(preserve_selection=True)` keeps state across groups; no-match text.

### T3c.11: Settings dialog audit fixes (UI audit H2, M1, M2, M5, L1, L3)
Design source: `ui-audit-phase-3c.md`.
- **H2:** issue lines render directly under the row whose `setting_key` they name (between the entry and the hint, or replacing the hint while an issue shows); issues without a `setting_key` and the fallback and warning lines stay at the card bottom. Issue lines 12 pt (bold for error tone), no new colour token (`sync_panel.py:406-437`).
- **M1:** a disabled `Sync enabled sources` and `Save` get a low-chroma fill and restore on enable (`sync_panel.py:251-258`, `_refresh_footer`). Exact colour is the user's call.
- **M2:** startup toast with two or more enabled providers: `Loaded {n} tracks from rekordbox and Serato DJ` (`app.py:221`, new `library_copy.format_load_toast` form); the one-provider form is unchanged. Test in `test_library_copy.py`, strings at most 75 characters.
- **M5:** verify with real keyboard focus that the `Database` placeholder shows on open and after a sync; if not, do not focus an entry on open or after a sync.
- **L1:** use `SUCCESS_COLOR` for the Sync button fill (`sync_panel.py:39`); keep only the hover constant.
- **L3 (copy):** when no enabled provider can sync, the footer reads `Can't sync {name}: {error}`; when others can, `Skipped {name}: {error}` stays (`library_copy.py:252`).
- **Held until the user answers audit O18 to O20:** heading size (M3), off-card styling (L6), error-tint alternative.

### T3c.9: Tests and acceptance
- `tests/services/test_library_copy.py` (pure): every function in T3c.1 with the exact strings above (relative-time boundaries incl. 44/45 s, 59/60 min, 23/24 h, 29/30 d and a different year; `crate_noun_for` empty/serato/rekordbox/mixed; singular counts; chip lines for all five cases; `issue_tone` incl. empty-field error becomes warning; `footer_state` for zero, all errored, some errored, dirty, busy; `empty_library_state` three branches; all toast texts at most 75 characters and without a path; `format_*` never says "Synced" for an all-failed report).
- `tests/services/test_sync_outcome.py`: the table in T3c.2 incl. `import_candidate` and the `Open settings` action.
- `tests/services/test_settings_model.py`: `build_provider_views` (enabled flags, values fall back to defaults, detected values, issues, summary, warnings).
- `tests/providers/test_contract.py` (existing contract tests): `detected_values`; rekordbox tests for the new strings, `detected_values` with and without a database.
- `tests/ui/test_settings_dialog.py` (skip without a display, as `tests/ui/` does): zero sources disables sync and shows the footer message; an empty field with an error renders amber; a non-empty wrong path renders red; a disabled card shows no form; a one-choice spec renders no tiles; `update_status` keeps staged entry text and switches; `Close` relabels to `Cancel` when edited; a CHOICE spec with two choices renders `On`/`Off`.
- `tests/ui/test_filter_dropdown_pairs.py` (extend): `set_label("Playlists")` and the empty overlay text.
- **Manual acceptance (engineer, before handing to review):**
  1. Fresh settings with rekordbox detected: placeholder `Reading your library…`, then the `Imported … from rekordbox` toast, placeholder gone, no clicks.
  2. Open Settings at `540x420` and at 150% scaling: footer stays, cards scroll.
  3. Toggle rekordbox off, `Cancel`: nothing changed; toggle off, `Save`: tracks leave the list, `Off. Saved library kept.`
  4. Type a wrong filename (`backup.db`): red `Choose the file named master.db`; sync skips it.
  5. Clear the field with no rekordbox installed: amber `Database not found`, hint visible.
  6. Edit a playing track's comment in rekordbox with the dialog open and a staged unsaved change: chip updates, staged change survives.
  7. Hover the suggestion list while a refresh lands: list does not move; move out: it updates.

> **Phase 3c + T4.1/T4.2 implementation notes (engineer, deviations to confirm):**
> - **Contract addition accepted:** `LibraryProvider.detected_values(settings)` (base, Serato `{}`, rekordbox `{"db_path": …}` only when the field is empty and an existing `master.db` is found). *Architect: record it in ADR-015 / blueprint §3 at T5.8.*
> - **T4.1/T4.2 landed first** (brief O15 option 1), so the dialog shows the precedence note, not the interim line. `merge_records()` is exposed as the pure record-level half of `merge()`. Scalar fields take the first non-empty value field by field (`""`, `0`, `0.0`, `None` empty), so Serato fills e.g. a genre rekordbox left empty. Same-snapshot duplicates (case variants) go through the same rule.
> - **Provider messages:** besides `provider.py`'s `_NOT_FOUND`/`_UNAVAILABLE`, the same convention (no provider name) is applied to the other rekordbox `ProviderError`s: `db_copy` → `Database not found`, `Database is busy. Try again in a moment`; `db_reader` → `Support isn't available in this build`, `Couldn't read the database`. Otherwise toasts would read "rekordbox sync failed: rekordbox database …".
> - **`plan_sync` and `with_provider_enabled` removed** with their tests (dead once `_prepare_sync` is gone).
> - **Dialog entries** are read directly (no `textvariable`): CTkEntry hides `placeholder_text` whenever a textvariable is set, and the placeholder carries the detected path. Dirty tracking uses `<KeyRelease>`; validation still runs only on open, Browse, focus-out and Enter.
> - **`on_save` returns `bool`** (False when settings can't be written; the footer shows `Settings not saved: …`). After a successful save the app passes fresh views to `update_status`, so capability-driven text (the auto-update chip form) follows the saved values.
> - **Legacy conversion keeps the v3 cache's `synced_at`** (`save_snapshot(..., synced_at=…)`), so an upgraded Serato user's chip reads `Synced on 19 Sep · …`, not `Synced just now`.
> - **Disabled card:** header (switch, name) with an empty chip, plus the grey `Off…` line below, per brief §5.1's "header plus one grey line".
> - **Exit criterion "never seeing the word Serato":** a rekordbox-only user sees no Serato *prompt*, toast or noun, but the dialog always lists every registered provider, so the `Serato DJ` card (switched off) is visible, as in the brief's §4 mock-up. *UI designer, decided 2026-11-05:* confirmed; the criterion is reworded (above), the design is unchanged (`ui-audit-phase-3c.md`, decision (b)).
> - **Optional coherence fix done:** `show_suggestions_quietly(..., on_rendered=…)`; the Now Playing badges update in the same moment as a deferred list render (or at once when the list needs no render).
> - **Phase 3c review + audit follow-ups (applied):**
>   - **Save uses the preserved reload** (review decision; replaces "not preserved" in T3c.6's `on_save` bullet): `_reload_library(preserve_state=True)`, so filters are reconciled, the setlist and current track rebound and suggestions re-rendered (quietly: deferred while the pointer is over the list or a preview of a still-present track plays). A preview whose file left the library is stopped (`SuggestionPanel.preview_path` / `stop_preview()`). *Architect: update the T3c.6 wording.*
>   - **Atomic Save:** `config.save_library_settings(enabled_ids, [(specs, values), …])` loads `settings.env` once and writes once (temp file + `replace_with_retry`). CR/LF are stripped from every saved value (also in `save_provider_settings`). The failure footer shows `strerror` or the exception type name, never a path.
>   - **Dialog busy only for manual work:** `SyncCoordinator.manual_in_progress` (a manual run is running or merged into the pending follow-up). `_open_settings` uses it, and a quiet report clears a dialog left busy when no manual work remains.
>   - **Validation freshness:** `_sync()` re-validates every staged-enabled provider first. `_refresh_footer` re-validates when the form is dirty. A 400 ms debounce after the last keystroke re-renders the card's issue lines, so a pasted path enables Sync without a focus-out. The baseline (`_saved`) is captured after the cards are built, so the dialog never opens dirty.
>   - **Path identity** in the engine's self/setlist exclusion and in `SessionPanel.add_track`'s de-dup (`path_key`).
>   - **Merge rules:** `key`/`camelot_key` are taken as a pair from the first record with a non-empty `camelot_key`. `play_count`: if the highest-precedence record's provider declares `NATIVE_PLAY_COUNT` (`merge(..., native_play_count=…)`, filled by the app from capabilities), its value wins even when 0. Both providers declare it, so rekordbox's play count always wins for shared tracks.
>   - **Copy changes for the 75-character toast limit:** `Database is busy, try again` (was `… Try again in a moment`) and `Not available in this build` (was `Support isn't available in this build`, 78 characters in the partial-failure toast). Every known provider error is length-tested through `format_partial_failure`. *UI designer: confirm the two strings.*
>   - **Toasts:** a one-provider success uses that result's track count and that provider's noun. Startup with one loaded source uses its own noun (`Loaded 700 tracks from 75 crates` even while rekordbox, also enabled, has not imported yet). With two or more loaded sources: `Loaded {n} tracks from rekordbox and Serato DJ` (audit M2).
>   - **T3c.10 built as specified,** plus: `FilterDropdown(searchable=, overlay_size=)` (only the crate pill gets search and the 300 x 320 overlay); `TrackLibrary.crate_provider(id)`; `crate_items` sorts by casefolded path; the app passes `(id, label, provider name)` items in registry order. Group headers are not clickable (audit O17, decided).
>   - **T3c.11 built:** H2 field issues render between the entry and its hint, 12 pt, bold for error tone (O18 decided: existing red); M1 disabled fills `#2f3a32` (Sync) and `#2f3338` (Save); M2 above; M5 the dialog takes focus on open and after `set_busy(False)`, so no entry hides its placeholder; L1 `SUCCESS_COLOR`; L3 `Can't sync {name}: …` when nothing can sync. Decided by the coordinator: heading 15 pt (O19); off card names dimmed to secondary grey (O20).
>   - `SettingsDialog` closes through one `_cancel()` (Esc, window close, Close/Cancel), never calling `on_save`.
> - **Final 3c fixes (after approval):** `SettingsDialog.destroy()` cancels pending debounced validations; `Select shown` / `Clear shown` flush a pending search first; the filter's search text **clears when the overlay closes** (decided), so it always reopens unfiltered (`FloatingOverlay(on_close=…)`). **Long playlist labels are truncated from the start** (decided): `utils.truncate_start` keeps the end and cuts at a ` / ` or ` - ` separator where possible (`… / LiveSets / 02. CrumbsAndCream`), with the full path in a tooltip. *T5.3's leaf-name single-selection pill can build on `truncate_start`.*
> - **Not done here:** the 540x420 and 150% scaling manual checks (2), and the in-rekordbox edit with the dialog open (6), which needs the user. The playlist filter is **not grouped by provider** in 3c (group headers are Phase 5, T5.3); both providers' crates appear in one flat list. *UI designer, decided 2026-11-05:* grouping and type-to-filter are pulled forward into T3c.10.

---

## Phase 4: Multi-provider merge

**Gate:** Phase 2 (no user question; Phase 0 confirmed the paths match). **Exit criteria:** with `PROVIDERS_ENABLED=rekordbox,serato`, both libraries load. Shared files appear once with crates from both and rekordbox's metadata. A failed sync of one provider leaves the other intact.

### T4.1: Full merge
`source/services/library_merge.py` `merge(snapshots)` (precedence = input order = registry order, rekordbox first):
1. Group records by `path_key` (`source/models/path_identity.py`).
2. `crates` = ordered union.
3. `sources` = ordered tuple of provider ids.
4. Each scalar in `TrackRecord` = the first non-empty value (`""`/`0`/`0.0`/`None` count as empty).
5. `full_file_path` = the highest-precedence record's path.
6. Combined crate index = dict union. Ids are already provider-namespaced, so a collision means a bug: log an error and keep the first.

`TrackLibrary` is keyed by `path_key`. Only `Track.full_file_path` keeps the original string, which the engine (`suggestion_engine.py:92-95`), session (`source/ui/session_panel.py:67,74`) and playback (`suggestion_panel.py:495,545`) use. Because exactly one `Track` exists per file, those equality checks stay consistent.

### T4.2: `Track.sources`
`source/models/track.py`: add `sources: tuple[str, ...] = ()` after `crates`. `from_dict` reads `data.get("sources", ())`. `merge` sets it. Snapshots don't store it (it is derived at merge time).

### T4.3: Multi-provider sync report in the app
`source/app.py` `_sync_finished`:
- The library reloads when **any** provider succeeded.
- **Mostly done in Phase 3c (T3c.1, T3c.2, T3c.6).** Toast copy lives in `library_copy` and `sync_outcome`: both OK `Synced {n} tracks from rekordbox and Serato DJ`; partial failure (amber Warning, 8 000 ms) `Synced rekordbox. Serato DJ sync failed: {message}`; all failed (red) `Sync failed for rekordbox and Serato DJ` with an `Open settings` button. (The first brief wrote "Serato"; the provider display name is `Serato DJ`, and the all-failed text lost "Open Settings for details" in favour of the button.) Functional rule stays: never report "Synced" when every provider failed, and a partial failure names the failed provider. Reload from the stored snapshots (including the failed provider's older one), not just from the successful results.
- The amber Warning colour is `config.WARNING_COLOR` (T3c.4); nothing to add here.
- Per-provider results reach the dialog through `update_status` (T3c.5, T3c.6). Once the merge exists, drop the interim line and show the precedence note (brief §5.9).

### T4.4: Deck-load gate (hidden; no UI)
`registry.first_deck_load_provider(provider_ids, settings_for)` already exists (Phase 2). Add the app wrapper `deck_load_provider_for(self, track: Track) -> LibraryProvider | None`, which calls it with `track.sources` (filtered to enabled providers) and `self._provider_settings`. **Nothing calls it from the UI in this feature.** It is the single gate the Phase 6 UI will use (blueprint D12), and it returns `None` today. Test: with both real providers it returns `None`; with a fake provider declaring `DECK_LOAD` and present in `sources`, it returns that provider.

### T4.5: Tests
`tests/services/test_library_merge.py`:
- the same path in two snapshots → one track;
- `crates` union with both providers' ids;
- `sources` order follows precedence;
- scalar precedence: rekordbox key/BPM/comments/energy win; empty-fallback (rekordbox `bpm=0` → Serato's);
- `C:\Music\A.mp3` vs `c:/music/a.mp3` merge on Windows (`monkeypatch` `os.path.normcase` / mark `skipif` as needed);
- rekordbox-resolved `C:\Music\A.mp3` (from `C:/Music/A.mp3`) vs Serato `C:\Music\A.mp3` merge;
- NFD vs NFC names merge;
- disjoint tracks both present;
- the crate index contains both providers' crates;
- the crate filter (`get_suggestions(..., filters=SuggestionFilters(allowed_crates=frozenset({"serato:X"})))`) admits a merged track whose rekordbox crate is not selected but whose Serato crate is.

`tests/services/test_library_sync.py`: two fake providers, one raising → the report has one success and one failure, and the failing provider's existing snapshot file is untouched.

---

## Phase 5: Settings UI, crate attribution, branding, data dir, packaging, docs

> **UI revision:** T5.1, T5.2, the strings and colour of T5.5, and T5.11 have moved to **Phase 3c** (T3c.1 to T3c.9, above), which sits right after Phase 3b. T5.3 and T5.4 stay here (after Phase 4). Design source for all of Phase 5's UI tasks: `ui-design-brief.md`. Brief decisions O2 (staged save) and O3 (crate/playlist noun) are applied as **defaults** the user may override. O1 (name) is answered: **"Sidecar"**.

### T5.1: Settings dialog: provider cards, per-provider settings and status
**Moved to Phase 3c: T3c.5** (dialog), with the view-model in T3c.5 (`source/services/settings_model.py`) and the copy module in T3c.1 (`source/services/library_copy.py`, not `source/ui/`, because `services/sync_outcome.py` needs it). The rekordbox card specifics that were marked `<!-- UI-designer to revise -->` are now brief §5.3 and T3c.3/T3c.5 (no key field, no "Fetch key", `Database` and `Update automatically` rows, chip text for `CHANGE_DETECTION`, amber warning line). Per-provider sync buttons stay **out of v1** (brief O5).

### T5.2: App wiring for the new dialog
**Moved to Phase 3c: T3c.6.** The watcher picks up enable/disable/auto-refresh changes on its next tick (T3b.2), with no restart needed. Progress forwarding (`Syncing… 12 of 38 playlists`) and per-provider `Waiting…` are **dropped**: the coordinator reports no per-provider progress.

### T5.3: Crate attribution in the crate filter
> **Partly moved to T3c.10 (2026-11-05):** grouped headers, case-insensitive sort, the wider overlay and type-to-filter. **Remaining here:** the single-selection leaf-name pill and keeping all of it working with `preserve_selection`. Header text colour is now secondary `#999999`, not tertiary.

`source/ui/filter_bar.py` `FilterDropdown` / `source/ui/suggestion_panel.py:209-210`. Design: brief §5.10 (kept from the first brief) and §5.6. Extend `TrackLibrary.crate_items` to return richer items (id, label, provider id, path) for crates with at least one track. Then:
- **Grouped sections (default):** `set_items` accepts items with a group name. When two or more groups are present, render a non-interactive header row per group (9 bold, uppercase, tertiary `#666666`, as `track_detail.py:110`: `REKORDBOX`, `SERATO DJ`). With one group, render the flat list exactly as today (no header). A provider with no crates gets no header.
- **Order:** inside each group, case-insensitive (`casefold`) by path tuple, so folder siblings stay adjacent (replaces the parity sort of T2.5). Group order follows registry order.
- **Dynamic noun:** done in Phase 3c (T3c.8: `set_label`, overlay empty copy, cleared-filter message, tooltip heading). Nothing to do here except keep it working with groups.
- **Single-selection pill text:** show the leaf name (`path[-1]`), truncated at 10 chars as `filter_bar.py:379`, not the first 10 characters of the full label.
- **Width:** widen the crate overlay only: about 300 px wide and 280 px tall (`filter_bar.py:315` is 200x200 today), labels truncated with `truncate` (`utils.py:1`) near 38 characters plus a `tooltip.py` hover with the full label. Clamp to the left pane's width and to the window bottom (`FloatingOverlay` placement `filter_bar.py:115+`); at very narrow panes fall back to 200 px. Verify at the 1000x650 minimum.
- **Scale (R11):** the user's library is 75 playlists in 23 folders, so the UI designer now recommends building **type-to-filter** (brief tier 2, with "Select shown" / "Clear shown" relabelling while a search is active) **in this task** rather than as a follow-up (brief O6; the user may override and ship the flat grouped list first). Collapsible folder tree (tier 3) is out of scope.
- The engine contract is unchanged: `selected` returns crate ids. `preserve_selection` (T3b.5) must keep working with groups. (`empty_state_message`'s `noun` parameter is in T3c.8.)

### T5.4: Attribution elsewhere
Decisions are in brief §5.10:
- Suggestion tooltip (`source/ui/suggestion_panel.py:476-477`): one provider enabled = `{Nouns}: A, B` using labels; more than one = one line per provider (`rekordbox: Club / Peak, Warm up`, `Serato DJ: House - Bangers`), only providers that contain the track. Needs the crate-to-provider map from the library's crate index (extend `crate_label` with a sibling `crate_provider`).
- Now Playing info line (`source/ui/track_detail.py:165-169`): labels only, first 3 plus "(+N)", **no provider tag** (glanceability). `Track.sources` is not displayed anywhere in v1.
- Top-bar "active sources" indicator: **not built** (the 32 px bar, `app.py:65-68`, is full). Optional follow-up if the user says yes to brief O7: an amber attention dot beside the gear when a sync or auto-refresh failed.
- **Deck-load controls: none in this feature** (blueprint D12). Any future control is shown only when `app.deck_load_provider_for(track)` is not `None` (T4.4).

### T5.5: Branding and terminology strings
**Moved to Phase 3c** (window and dialog titles in T3c.1/T3c.5/T3c.6, toast strings in T3c.1/T3c.2, noun in T3c.8, the Warning colour in T3c.4). Nothing left here except the leftovers of T5.3/T5.4 (group headers, tooltip per-provider lines). **No provider colour anywhere** (colour is data, design guide §1).

### T5.10: (Deferred, not part of this feature) Logo artwork
The user asked to leave the logo untouched for now. `source/ui/SeratoSidecarLogo.png` keeps its name and artwork; the app/installer icon still shows the old artwork, a known, accepted gap. Revisit as a separate task when new artwork exists.

### T5.11: Empty-library and first-run states
**Moved to Phase 3c: T3c.1 (`empty_library_state`), T3c.6 (`_update_empty_state`) and T3c.7 (`set_empty_message`).** Revised there: a third variant, `Reading your library…`, covers the seconds before the automatic first import of a fresh install (brief §5.8).

### T5.6: Data-dir rename with copy-forward migration
`source/config.py:16`:
- `_APP_NAME = "DJSidecar"`, plus `_LEGACY_APP_NAMES = ("SeratoSidecar",)`.
- Add `_migrate_legacy_data_dir(new: Path) -> None` and call it from `user_data_dir()` (`:21`) once per process, guarded by a module flag. If `new / "settings.env"` doesn't exist and a legacy dir has one, **copy** (not move) `settings.env`, `settings.env.pre-schema2.bak` and the `library/` tree, plus the legacy `track_cache.json` if `library/` is absent, using `shutil.copy2` / `copytree(dirs_exist_ok=True)`. **Do not copy `diagnostics/`.** Catch `OSError` and log a warning.
- It must run **before** `ENV_FILE` is computed (`:37`) and before `_migrate_legacy_env` (`:40`).
- Update the docstring paths in `user_data_dir()`.
- Tests: `tests/test_config_migration.py`. Patch `platformdirs.user_data_dir` to return per-name dirs under `tmp_path`. Cases: copy happens; the legacy dir is left intact; no copy when the new dir already has settings; idempotent.

### T5.7: Packaging and release identity
- `serato-sidecar.spec`: `APP_NAME` (`:29`) → `"DJSidecar"`; docstring (`:3,7`). **Leave the logo datas entry (`:41`) and the logo file untouched** (T5.10 deferred). **Keep `bundle_identifier` (`:151`).** Optionally rename the spec file to `sidecar.spec`, in the **same commit** as the workflow changes.
- `build/installer.iss`: `MyAppName` (`:21`) → "Sidecar", `MyAppExeName` (`:22`) → "DJSidecar.exe", `DefaultDirName` (`:40`, which only affects fresh installs because Inno reuses the previous dir for the same `AppId`), `OutputBaseFilename` (`:44`), the source paths (`:64-65`). **Do not change `AppId` (`:32`).** Add `[InstallDelete] Type: files; Name: "{app}\SeratoSidecar.exe"` and remove the stale Start-menu/desktop shortcuts by their old names (R12).
- `.github/workflows/release.yml`: artifact names and paths (`:8-9,115-130`) and the `latest.json` asset URLs. **Leave the icon generation from `SeratoSidecarLogo.png` (`:180-194`) as is.** **Keep the manifest URL/tag** (`source/services/updater.py:35-37`). Keep the T3.1 wheel guard and self-check steps.
- Verification: install v0.1.6, upgrade to the new build. Check: the in-place install, no duplicate Start-menu entries, settings preserved, the library loads without a re-sync, the updater still detects the next version, and `--self-check-rekordbox` passes on the installed exe.

### T5.8: Docs and project instructions (architect applies at merge)
- `docs/architecture-decisions.md`: add ADR-014 (Rejected, recorded; text in blueprint §2.0), then ADR-015 (blueprint §2). Mark ADR-007 "Superseded in part by ADR-015 (structure → per-provider snapshots, schema v4)" and ADR-005 "path detection now lives in SeratoProvider". Update ADR-008's consequences for the mandatory `pyrekordbox`/`sqlcipher3-wheels` dependency.
- `docs/architecture-overview.md`: purpose, diagram, a new Providers layer table, the services table (remove `crate_sync`/`cache`; add `library_sync`, `library_store`, `library_merge`, `library_watcher`, `settings_migration`, `comment_format`, `log_safety`, `diagnostics`), the UI table, data flow incl. copy-then-read and live refresh. Debt: resolve #12 (stale `comments_parser`, now `comment_format.py`), note the layering smell fixed, add "path-only identity" and "ID3-only energy/tag reader (R8)" items.
- `docs/cross-platform-guide.md`: a rekordbox DB paths table; why the copy omits `-shm`; the sqlcipher wheel matrix; path resolution (`OrgFolderPath` first, `/` → native) and identity normalisation (NFC/normcase); the "Serato Paths" section generalised to "DJ software paths".
- `docs/testing-strategy.md`: provider contract tests (incl. the capability rules), fixture conventions (`tests/fixtures/crate_bytes.py`, `tests/providers/rekordbox/fakes.py`), the synthetic-data-only rule, golden equivalence, the pure watcher logic, the key-safety tests. Update the stale `export_crates.py`/CSV items (`:62-65`).
- `docs/coding-standards.md`:
  - "DJ-software-specific code lives only in `source/providers/`; nothing outside `registry.py` imports a concrete provider";
  - "only `rekordbox/db_reader.py` imports `pyrekordbox`/SQLAlchemy";
  - "never lower the `pyrekordbox`/`sqlalchemy` logger levels or log exception text from the rekordbox adapter (it can contain the DB key)";
  - "never open files in a DJ app's folder with SQLite; read a private copy".
- `docs/deployment-guide.md`: the **rekordbox upgrade runbook** (Phase 0 section above; `--check-rekordbox-library`; re-pin; self-check; release).
- `CLAUDE.md`: overview ("Sidecar"), tech stack (+pyrekordbox), project structure, domain concepts ("crate" = Serato crate or rekordbox playlist), cross-platform notes. Ask the user before editing `.claude/agents/*.md` (their prompts say "Serato Sidecar").
- `README.md`, `docs/install-guide-for-friends.md`: how to choose sources; the rekordbox caveat (rekordbox updates may need a Sidecar update); auto-refresh.

### T5.9: Tests (Phase 5)
- **Dialog, copy, view-model and toast tests moved to Phase 3c (T3c.9)**: `test_library_copy.py` now lives at `tests/services/test_library_copy.py`, `build_provider_views` is tested in `tests/services/test_settings_model.py`, and the dialog smoke tests are `tests/ui/test_settings_dialog.py`.
- `tests/test_config_migration.py` (T5.6).
- `tests/ui/test_filter_dropdown_groups.py`: two groups render headers; one group renders none; a provider with zero crates gets no header; `selected` returns ids only; sort is case-insensitive by path within a group; single-selection pill shows the leaf name; the empty overlay copy and disabled buttons; `preserve_selection` with groups. If type-to-filter (brief tier 2) is built: `Select shown` / `Clear shown` act on visible rows only.

---

## Phase 6 (follow-up, separate feature): rekordbox load-to-deck

**Not part of this feature.** Start only after Phases 1–5 have shipped and the rekordbox provider has been tested in real use. The contract, the capability, the gate (`registry.first_deck_load_provider` + `app.deck_load_provider_for`, T4.4) and the hidden-UI rule are already in place.

- **T6.1: Spike.** Investigate whether any mechanism can load a **specific** track onto a rekordbox deck in the user's rekordbox version (blueprint §8 Phase 6 lists the candidates). ADR-014's finding is the bar.
- **T6.2: ADR.** Write ADR-016, accepting a mechanism or rejecting it. If rejected, stop here; the capability simply stays undeclared.
- **T6.3: Implement** `RekordboxProvider.load_to_deck` and declare `DECK_LOAD` (possibly behind a setting). Calls run off the Tk thread.
- **T6.4: UI.** A UI-designer brief for the control (placement, deck choice, feedback, live-set safety). The control appears only when `deck_load_provider_for(track)` is not `None`.
- **T6.5: Tests.** A contract test with the capability declared; provider tests with a fake transport.

---

## Task dependency summary

```
P0 done ──▶ P3a
P1 done ──▶ P2 done ──▶ P3a ──▶ P3b
                 │        └──▶ Phase 3c = T3c.1..T3c.9 (replaces T5.1, T5.2, T5.5 strings, T5.11; done after P3b)
                 └──▶ P4 ──▶ T5.3, T5.4 (attribution needs two providers)
P3b done ──▶ Phase 3c = T3c.4 → T3c.1 → T3c.3 → T3c.2 → T3c.5..T3c.8 → T3c.9 (T4.1/T4.2 merge recommended first; release gate)
P3a internal order: T3.5 → T3.1 → T3.2 → T3.3 → T3.11 → T3.4 → T3.6 → T3.7 → T3.8 → T3.9 → T3.12 (tests T3.10 alongside)
P5 remainder (T5.6–T5.9) after P4
P6 (rekordbox load-to-deck) = separate follow-up after this feature ships
T5.10 (logo) deferred by the user
```

---

## UI revisions applied

Made by the UI designer agent on 2026-11-05. Design source: `ui-design-brief.md`.

- **Replaced all `<!-- UI-designer to revise -->` placeholders** in this plan (Phase 5, T5.1–T5.5) and in the blueprint (§6 settings surface, §7 branding) with concrete direction. T5.1 now specifies the dialog structure (provider cards, scrollable body, pinned footer, resizable `640x580` with `540x420` minimum); T5.3 the grouped crate filter; T5.4 the attribution decisions; T5.5 the branding and terminology strings.
- **Contract additions (blueprint §3, T1.1, T1.4, T3.6):** `SettingSpec.placeholder` / `.hint` / `.browse_title` and `LibraryProvider.crate_noun`. Reason: the dialog must stay provider-agnostic yet needs per-provider microcopy and the crate/playlist word. A message convention for `ProviderIssue` / `ProviderError` (initial capital, no trailing period, no provider name, no path) is added.
- **T2.10 error copy changed** from "Serato crates folder not found: {path}" to "Crates folder not found" (design guide §8: errors name what failed and stay short; the path is already in the settings field). Single-provider failure toast becomes "Serato sync failed: {message}".
- **T2.5 sort note rescoped:** case-sensitive order stays in Phase 2 (identical appearance); case-insensitive path order moves to T5.3.
- **T3.8 / Phase 3a note rescoped (the biggest change):** the dialog work (T5.1, T5.2, T5.5 strings, new T5.11) is pulled forward as "Phase 3c" and is no longer optional. Otherwise a rekordbox-only user sees a Serato-only field, which is misleading copy.
- **T4.3 toast copy specified** (both OK, partial failure, all failed) and an amber Warning toast colour added. Reload uses stored snapshots so a failed provider's older data stays usable.
- **New tasks:** T5.10 (logo artwork has "SERATO SIDECAR" baked in; needs the user), T5.11 (empty-library / first-run states). New pure module `source/ui/library_copy.py` (T5.1) holds all user-visible strings for unit testing.
- **Removed / not built:** no top-bar "active sources" indicator, no per-provider sync buttons, no provider colour, no `Track.sources` display in v1 (rationale in brief §4.7 and §4.3). Offered as options in brief O5 and O7.
- **T5.9 tests extended** for copy helpers, grouped filter, and dialog smoke tests.
- **Unchanged and still open:** O1 (name), O2 (staged vs live save), O3 (crate/playlist word), O6 (filter scale; needs the user's playlist count). The docs listed in brief §10 (design guide §3/§5/§6/§8, title) are updated after those answers; `docs/` was not edited.

### Second revision, 2026-11-05 (after Phases 1, 2, 3a and 3b)

Design source: `ui-design-brief.md` (rewritten in place; all XML and key content removed).

- **New "Phase 3c" section** with concrete tasks T3c.1 to T3c.9 (file, exact strings, layout, states, tests, manual acceptance). T5.1, T5.2, T5.5 and T5.11 are now stubs pointing there; T5.9's dialog/copy tests moved to T3c.9. Every `<!-- UI-designer to revise -->` marker in this plan (T5.1's rekordbox card block) and in the blueprint (§6 item 7) is replaced.
- **rekordbox card (database):** rows `Database` (detected path shown as a grey placeholder; must be `master.db`) and `Update automatically` (`On`/`Off` tiles); automatic chip `Updates automatically · N tracks · M playlists` plus `Last updated …`; no key field, no "Fetch key", no XML content. Errors: red for a wrongly chosen file, amber when the field is empty (`Database not found`), and no toast when the database later disappears (the watcher gets no token). Provider messages lose the provider name (T3c.3 edits `_NOT_FOUND`, `_UNAVAILABLE`).
- **Engineer's UI items decided:** (1) quiet refresh and defer-under-pointer confirmed, no "list updated" cue, one optional badge/list coherence fix; (2) final failure and success copy, background failures are **amber** `"{name} auto-update failed: {error}"`, manual partial failure amber, all-failed red with an `Open settings` button, success toasts use the provider noun and names (`Serato DJ`, not `Serato`); (3) one-time `Imported N tracks from rekordbox` toast on a silent first import, plus a `Reading your library…` placeholder while the automatic import is pending; (4) rekordbox card as above; (5) **Warning `#ffc107` adopted** as a token (shares its hex with the score "usable" bucket, `suggestion_panel.py:43`; accepted, brief §5.7).
- **Corrections to my first plan text:** `Sync enabled sources` skips a provider with an error instead of disabling the whole button (matches blueprint §6 rule 2); no per-provider "Waiting…" or progress (coordinator has none); hints use secondary `#999999` (tertiary `#666666` is about 2.4:1 on the card fill); `Syncing…` uses Info cyan `#4AB8D4` instead of orange (avoids confusion with Warning amber); `library_copy.py` moved from `source/ui/` to `source/services/` (layering); provider display name is `Serato DJ` in all copy.
- **New contract addition:** `LibraryProvider.detected_values(settings)` (T3c.3, blueprint §3), so the dialog shows the auto-detected path without branching on provider ids.
- **New finding:** `merge()` uses only the first snapshot (`library_merge.py:27-35`), so with both providers on, Serato would silently show nothing. Recommendation: land `T4.1`/`T4.2` before releasing 3c; otherwise the interim amber line in brief §5.9. (O15.)
- **Defaults applied for the user's never-answered questions (all overridable, brief §8):** O2 staged save, O3 noun follows providers, O4 switch, O5 no per-card sync, O6 grouped headers (plus tier-2 type-to-filter now recommended because the library has 75 playlists), O7 no attention dot, O8 no auto-opened dialog, O9 case-insensitive sort, O10 thousands separators. New: O11 refresh-failure colour (amber), O12 toast on first failure, O13 On/Off tiles, O14 no list cue, O15 merge before release, O16 cyan for in-progress.
- **Not edited:** `docs/` (the design guide updates are listed in brief §11) and `source/`.

### Third revision, 2026-11-05 (Phase 3c audit)

Design source: `ui-audit-phase-3c.md`.

- **Playlist filter pulled forward (engineer question a):** new **T3c.10** takes provider group headers, case-insensitive sort, a 300 x 320 overlay and type-to-filter (`Select shown` / `Clear shown`) out of T5.3, because the user's real data is 148 items. Leaf-name pill and per-provider tooltip lines stay in Phase 5. Group header text is **secondary `#999999`** (changed from the brief's tertiary `#666666`, about 2.4:1).
- **Exit criterion reworded (engineer question b):** a rekordbox-only user sees no Serato field, hint, prompt, error, toast, noun or placeholder; the switched-off `Serato DJ` card stays. Reason: it is the only way to turn Serato on later, and the dialog is provider-agnostic.
- **New T3c.11** from the audit: issue lines move under their field and get 12 pt bold (red at 11 pt on the card is about 3.2:1); disabled primary buttons are dimmed; a both-source startup toast (`Loaded {n} tracks from rekordbox and Serato DJ`); a `Can't sync {name}` footer form; focus check for the `Database` placeholder; `SUCCESS_COLOR` for the Sync fill.
- **Correction to my brief:** brief §5.3 put issue lines last in the card; screenshots show that detaches the error from its field.
- **New open questions:** audit O17 (clickable group header), O18 (error emphasis), O19 (dialog heading size), O20 (off-card styling). No defaults are built for O19 and O20 until answered.
- **Not edited:** `docs/` and `source/`.

---

## Architect revisions applied

The UI designer's and engineer's notes above are preserved. Where later decisions overtook them, the change is noted here and in place.

### After the user's answers (2026-11-05)
- **rekordbox source → database only.** Phase 0 is rewritten as a DB spike. Phase 3a becomes the database provider; the XML reader and fixtures are removed; the UI designer's XML copy in T3.6 is marked obsolete.
- **rekordbox is the source of truth** for rekordbox tracks; merge precedence is rekordbox first (T4.1).
- **New Phase 3b: live refresh** (watcher, pure `should_refresh`, single-flight sync, state-preserving reload, `preserve_selection`). Phase 2 gained `content_hash`/`change_token` (T2.4) and `track_by_path` (T2.5).
- **Load-to-deck in the contract from Phase 1** (`DECK_LOAD`, `load_to_deck()`, `DeckLoadNotSupported`, contract-test rules); hidden gate T4.4; **Phase 6** stub.
- **Name "Sidecar" confirmed; logo untouched** (T5.10 deferred; T5.7 leaves the logo asset and icon generation alone).
- **Phase 4 gate removed** (identical paths).
- Phase 5 UI tasks adjusted for the database decision (since revised again below).

### After Phase 0 (2026-11-05)
- **Restored sections.** When this revision started, this file ended after Phase 2: Phase 3a onward, "UI revisions applied" and this section were missing. They were restored from the previous architect revision, and the UI designer's section is reproduced verbatim. **Please check the restored sections against git history** in case anyone edited them after that revision.
- **Phase 0 marked done**, with an anonymised findings table and the upgrade runbook. T0.6 timing and T0.7 frozen build were not covered; they move to T3b.1 and T3.1's acceptance.
- **Copy-then-read** replaces "open read-only in place" (T3.4: `db_copy.py` + `db_reader.py`). `-shm` is **not** copied, as verified by the spike. This is a deliberate deviation from the brief's "db+wal+shm", with the reason in blueprint D8. Added a torn-copy guard (token before/after, retries, `quick_check`) and temp cleanup.
- **Key:** built into pyrekordbox 0.5.0. **T3.5 is now "Log safety"** (it was key resolution), and there is no key setting, no `db_key.py` and no fetch action. Removed the key bits from T3.6, T5.1 (`actions`, `on_provider_action`), T5.2 and T5.9.
- **New key-safety requirement and tests:**
  - `source/services/log_safety.py` pins the `pyrekordbox`/`sqlalchemy` loggers at WARNING (`main.py` + after import);
  - the `db_reader` boundary logs the exception type only and raises fixed-text `ProviderError ... from None`;
  - tests with a synthetic key string (T3.10).
- **Pins:** `pyrekordbox==0.5.0`, `sqlcipher3-wheels==0.5.7`, `SQLAlchemy==2.1.8` (T3.1). The spec collects `pyrekordbox`, `sqlcipher3` and the SQLAlchemy SQLite dialect. CI uses a wheel-only guard plus a frozen `--self-check-rekordbox`.
- **Change token = `master.db` + `master.db-wal`; `-shm` excluded** (T3.2, T3b.2).
- **Path resolution**: `OrgFolderPath` → local `FolderPath` → `rb_LocalFolderPath` → fallbacks, then normalised to native separators (T3.2).
- **Field mapping** uses `ArtistName`/`AlbumName`/`GenreName`, and `ReleaseYear` 0 → `""` (T3.6). Smart playlists are supported defensively but the capability is not declared (the user has none). Rating, Colour and My Tag are not mapped.
- **Energy by user option (a)** (new T3.11): comment energy, else `tag_reader.read_energy_level` for in-scope tracks with an existing file, memoised by mtime and size in `energy_cache.py`.
- **T3.7** points at `source/providers/registry.py:18-20` (the Phase 2 location). **T3.8** is rewritten for the Phase 2 `_prepare_sync` (`app.py:308-322`): Serato is no longer re-enabled for a rekordbox-only user. **T3.9** points at `tag_reader.py:75-78`.
- **New T3.12:** built-in `--check-rekordbox-library` diagnostics (counts only, no names, paths or key) and retirement of `scripts/spike_rekordbox.py`. That script is not gitignored and embeds a key fragment: **do not commit it; delete it after T3.12 is verified.**
- Phase 3b/4/5 line references updated to the Phase 2 code. T4.4 now wraps the existing `registry.first_deck_load_provider`. T5.6 copies the settings backup and skips `diagnostics/`. T5.8 adds coding-standard rules (provider imports, logger levels, no SQLite on DJ-app files) and the runbook.
