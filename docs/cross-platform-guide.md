# Cross-Platform Guide — Sidecar

> Maintained by the Architect agent. Documents platform differences and how to handle them.

## Supported Platforms

| Platform | Status | Notes |
|----------|--------|-------|
| Windows 10/11 | Shipped | Primary development and test platform. rekordbox support verified on Windows (rekordbox 7.2.19, Python 3.11) |
| macOS | Built (unverified) | CI produces a zipped `.app` per release and runs the frozen `--self-check-rekordbox`, but nobody has run it on a real Mac yet. The rekordbox DB path and `OrgFolderPath` format are unverified (blueprint R13) |
| Linux | Future | Lower priority; neither Serato nor rekordbox runs natively on Linux |

## DJ software paths

All DJ-software paths live in their provider (`source/providers/<name>/`), never in `config.py` (ADR-015). The user can override them in the Settings dialog; the values are stored in `settings.env`.

### Serato

| Platform | Subcrates directory (`SERATO_SUBCRATES_DIR`) |
|----------|-------------------|
| Windows | `C:\Users\<user>\Music\_Serato_\Subcrates` |
| macOS | `/Users/<user>/Music/_Serato_/Subcrates` |
| Linux | N/A |

Default: `Path.home() / "Music" / "_Serato_" / "Subcrates"` (`SeratoProvider.default_settings()`, `source/providers/serato/provider.py:66-68`).

### rekordbox

| Platform | Database (`REKORDBOX_DB_PATH`, blank = auto-detect) | Verified? |
|----------|-----------------------------------------------------|-----------|
| Windows | `%APPDATA%\Pioneer\rekordbox\master.db` | Yes (rekordbox 7.2.19) |
| macOS | `~/Library/Pioneer/rekordbox/master.db` | No (R13) |
| Linux | none (auto-detect returns `None`) | — |

Source: `rekordbox/paths.default_db_path()` (`source/providers/rekordbox/paths.py:24-32`). A user-chosen file must be named exactly `master.db` (case-insensitive on Windows, `paths.is_master_db`), because its `-wal`/`-journal` companions are found by name; pairing a backup DB with the live WAL would be wrong.

**Files next to `master.db` and how Sidecar treats them:**

| File | Exists when | Copied for reading? | In change token? |
|------|-------------|---------------------|------------------|
| `master.db` | always | yes | yes |
| `master.db-wal` | rekordbox running (WAL mode) | yes, if present | yes (rekordbox writes land here first) |
| `master.db-journal` | rarely | yes, if present | no |
| `masterPlaylists6.xml` | usually | yes, if present | no |
| `master.db-shm` | rekordbox running | **no** | **no** |

**Why the copy omits `-shm`:** `-shm` is SQLite's shared-memory index for the WAL. SQLite rebuilds it from `-wal` when it opens the private copy. A copied `-shm` taken a moment apart from the copied `-wal` can be inconsistent with it, and the no-`-shm` copy is the configuration verified while rekordbox was running. It is excluded from the change token because it changes on rekordbox's own reads and checkpoints, which would trigger refreshes that change nothing. **SQLite must never open a file in rekordbox's folder**: opening the original in place writes `-shm` (ADR-015 D8).

The private copy goes to `tempfile.gettempdir()` in a `sidecar-rb-*` folder. That is `%TEMP%` on Windows and `$TMPDIR` on macOS. It is deleted after every read; leftovers older than an hour are removed at the next scan. On Windows the reader disposes the SQLAlchemy engine before deletion, because open handles block deleting the folder.

### rekordbox track paths

rekordbox has three path fields per track. `rekordbox/paths.resolve_track_path` (`paths.py:81-112`) takes the first hit:

1. `OrgFolderPath`, if non-empty and the file exists (the normal case: a local `C:/…` path with forward slashes);
2. `FolderPath`, if it is a **local** path (drive letter, UNC or absolute POSIX, **not** rekordbox's `/contents_…` form) and the file exists;
3. `rb_LocalFolderPath`, if non-empty and the file exists;
4. `OrgFolderPath` / local `FolderPath` with the file missing (counted as a snapshot warning);
5. otherwise the track is skipped (warning).

The result goes through `os.path.normpath`, which turns `/` into `\` on Windows.

### Track identity across providers

Tracks from different providers are the same track only if their paths match after `path_key` (`source/models/path_identity.py`):

```python
unicodedata.normalize("NFC", os.path.normcase(os.path.normpath(p)))
```

- `normpath` unifies separators and `..`;
- `normcase` lower-cases on Windows only (case-insensitive file system); on macOS, which is usually case-insensitive too, case still matters to the key;
- NFC unifies composed and decomposed accents (macOS file systems may return NFD names).

Use `library.track_by_path(p)`, never a raw dict lookup by path string.

### History

All earlier cross-platform issues are resolved: the hard-coded `C:\Users\grant\...` Serato path, `DEFAULT_MUSIC_ROOT = "C:\\"`, and the hard-coded tooltip font.

### How to Handle
- Put DJ-software defaults in the provider's `default_settings()` / `paths.py`, built from `Path.home()` or environment variables (`APPDATA`).
- Let the user override them through a `SettingSpec` (stored in `settings.env`).
- Never hardcode absolute paths.

## File Path Rules

### Do
```python
from pathlib import Path

data_dir = config.user_data_dir()
snapshot = data_dir / "library" / f"{provider_id}.json"
```

### Don't
```python
import os
data_dir = os.path.join("C:\\Users\\grant", "AppData", "Roaming", "DJSidecar")
snapshot = data_dir + "\\library\\" + provider_id + ".json"
```

## User data directory

`config.user_data_dir()` uses `platformdirs` (ADR-008):

| Platform | Path |
|----------|------|
| Windows | `%APPDATA%\DJSidecar\` |
| macOS | `~/Library/Application Support/DJSidecar/` |
| Linux (dev) | `~/.local/share/DJSidecar/` (XDG) |

Up to v0.1.6 the folder was named `SeratoSidecar`. On launch of a newer version, Sidecar **copies** `settings.env`, `settings.env.pre-schema2.bak` and `library/` (or a legacy `track_cache.json`) from `SeratoSidecar` when `SeratoSidecar` holds any of `settings.env`, `track_cache.json` or `library/` (v0.1.6 only wrote `settings.env` once a setting was saved, so many installs have just the cache) and either `DJSidecar` has no `settings.env` or a `.copy-forward-pending` marker is present. The marker is written in `DJSidecar` before the copy and removed only after the last step succeeds, so a failed copy is retried on the next start even though startup has since written a fresh `settings.env` (the retry replaces it with the old one). While the marker is present, the settings migration treats the install as existing (Serato only), not as a fresh install. It does not copy `diagnostics/` and leaves the old folder intact (ADR-008 amendment, task T5.6).

## File I/O

- Always specify `encoding="utf-8"` — default encoding varies by platform
- Use `Path.mkdir(parents=True, exist_ok=True)` for directory creation
- Use `with` statements for all file handles
- Be aware: macOS file system is case-insensitive by default, Linux is case-sensitive

## UI Considerations

| Aspect | Windows | macOS | Linux |
|--------|---------|-------|-------|
| Font rendering | ClearType | Core Text | FreeType |
| Default fonts | Segoe UI | SF Pro | Varies |
| Window chrome | Title bar | Traffic lights | DE-dependent |
| DPI scaling | Per-monitor | Retina (2x) | Varies |

### Recommendations
- Use CustomTkinter's built-in scaling rather than manual DPI handling
- Test font sizes on multiple platforms (what looks good at 12pt on Windows may differ on Mac)
- Don't assume specific window decorations or title bar behavior

## Clipboard

The suggestion rows' copy button puts the track's paste query on the OS clipboard for the DJ to paste into rekordbox's or Serato's search (ADR-016). All writes go through `source/ui/clipboard.copy_to_clipboard`, which uses Tk's own clipboard (`clipboard_clear` + `clipboard_append`). There's no extra dependency. It runs on the Tk thread, catches `tk.TclError` only, and never calls `update()`.

Most rows below come from how Tk 8.6 implements its clipboard. They're assumptions until a manual check confirms them.

| | Windows (shipped) | macOS (built, unverified) | Linux (dev only) |
|---|---|---|---|
| How Tk publishes the text | Takes ownership of the clipboard with **delayed rendering**: the text is handed over when another app asks for it, served by Sidecar's running Tk event loop | Declares the text on the general `NSPasteboard`, possibly provided lazily | X11 `CLIPBOARD` selection, owned by Sidecar |
| DJ switches to rekordbox/Serato and pastes | Works: accepted by the user on Windows (M1-M3; per-check results not recorded) | Expected to work while Sidecar runs; **unverified (M12)** | Works while Sidecar runs |
| Sidecar is busy when the DJ pastes | The paste waits until the Tk thread is free (at most a 60-row re-render, a fraction of a second) | Same, if lazy | Same |
| Sidecar closed after copying | Tk renders all formats on shutdown, so the text should survive (M4) | May be lost on quit if lazy; **unverified (M12)** | Lost unless a clipboard manager holds it |
| Sidecar crashes or is killed after copying | The text is lost. Acceptable: Sidecar runs for the whole set | Same | Same |
| Another process holds the clipboard open (clipboard managers, remote desktop) | Tk may fail **without** raising `TclError`. The DJ then pastes old text and sees an unexpected search result before loading anything | Not expected | n/a |
| Emoji and other non-BMP characters | Tk 8.6 support is incomplete: they may paste as `?` or be dropped. The other words still match (M9) | Same | Same |
| Clipboard history / cloud sync | Win+V history and cloud clipboard keep the copied artist and title, as with any copy | Universal Clipboard may sync it | Clipboard managers may keep it |

**Copy-button glyphs.** `❐` (U+2750), `✓` (U+2713), `✕` (U+2715) and `—` (U+2014) are all in the Basic Multilingual Plane with no emoji presentation, and no font family is set, so Tk falls back to a symbol font. Gate G (2026-11-06, Windows dev machine) rendered them cleanly at CustomTkinter widget scaling 100% and 150%. Real Windows 150% *display* scaling (M11) and macOS rendering are unverified.

**Narrow window.** In a synthetic render at the 1000x650 minimum (M8), the Copy and Key columns are visible and BPM's cells are under the scrollbar. The Copy column is leftmost so it is never the one that clips.

**Verification status.** The user tried the Windows build and accepted the feature. The manual checks M1-M16 (`plans/copy-track-search-text-2026-11/implementation-plan.md`, T3.6, and `docs/testing-strategy.md`) were part of that acceptance, but **per-check results weren't recorded**. Explicitly **unverified:** M11 (real Windows 150% display scaling) and M12 (macOS paste, and paste after quitting Sidecar). When either is run, record the result here and replace "unverified".

## Binary File Parsing (Serato .crate files)

- Serato .crate files use UTF-16 Big Endian encoding for track paths
- Track paths inside .crate files use the OS-native separator from when they were created
- When reading paths from .crate files, normalize to the current OS: `Path(raw_path)`

## File creation time

The date-added filter sources `Track.date_added` from each file's **creation time** (ADR-013). There is no single cross-platform stat field for this, and the correct field depends on **both** the OS and the Python version, so the logic is isolated in one leaf helper: `source/services/file_times.file_creation_time(path) -> float | None`.

| Platform | Shipping? | Creation-time source (on the bundled **Python 3.11**) | Notes |
|----------|-----------|--------------------------------------------------------|-------|
| macOS | Yes | `os.stat().st_birthtime` | True creation time; available on macOS across all supported Python 3 versions. |
| Windows | Yes | `os.stat().st_ctime` | On **Windows**, `st_ctime` *is* the creation time (not inode-change time). `st_birthtime` is **not** exposed on Windows until **Python 3.12** — so on 3.11 the helper uses `st_ctime`. |
| Windows (future, 3.12+) | Yes | `st_birthtime` → `st_ctime` | When the bundled interpreter moves to 3.12, `st_birthtime` appears on Windows and is preferred automatically; `st_ctime` remains a correct fallback. No code change needed. |
| Linux / other | No (dev only) | none reliable → `st_mtime` | `st_ctime` on Linux is inode-change time (wrong meaning); `st_birthtime` is filesystem-dependent and not exposed by CPython. The helper degrades to `mtime` so dev machines stay functional without claiming false accuracy. |

The helper's fallback chain (first hit wins) is: `os.stat` (`OSError` → `None`) → `st_birthtime` if present and `> 0` → `st_ctime` if `sys.platform == "win32"` → `st_mtime`. The `> 0` guard handles filesystems that report `st_birthtime == 0` ("unknown birth"). `None` (stat failed) is distinct from `0.0`; the callers (`tag_reader.get_track_metadata` for Serato, the rekordbox provider for the resolved path) map `None` → `0.0` ("unknown"), which the suggestion engine's date filter excludes when a `date_from` is set.

The **Python 3.11-vs-3.12 Windows `st_birthtime` difference is the reason this helper exists** — a naïve `st_birthtime`-only or `st_ctime`-only read would be wrong on one platform/version combination. See `source/services/file_times.file_creation_time` and ADR-013.

## Packaging & Distribution

The shipped packaging system is a matrix of per-platform builds driven by a single PyInstaller spec and orchestrated by GitHub Actions. Released via the public repo at `grantcomply/sidecar`.

### Build pipeline

| Stage | Windows | macOS |
|-------|---------|-------|
| Bundle | `pyinstaller serato-sidecar.spec` (one-folder) → `dist/DJSidecar/DJSidecar.exe` | `pyinstaller serato-sidecar.spec` → `DJSidecar.app` (via `BUNDLE` block) |
| Self-check | `DJSidecar.exe --self-check-rekordbox` | `DJSidecar.app/Contents/MacOS/DJSidecar --self-check-rekordbox` |
| Installer | Inno Setup (`build/installer.iss`) → `DJSidecar-Setup-<version>.exe` | `ditto -c -k --keepParent` → `DJSidecar-<version>-mac.zip` |
| Runner | `windows-latest` GHA runner | `macos-latest` GHA runner |

The PyInstaller spec is one-folder (not one-file) to keep startup fast and reduce Windows Defender false positives. The CTk theme directory is bundled via `collect_all('customtkinter')` — missing this is the most common breakage. The spec must also collect `pyrekordbox`, `sqlcipher3` and the SQLAlchemy SQLite dialect. The frozen self-check catches a miss.

The installer keeps the same Inno `AppId`, so an install of a `SeratoSidecar.exe` version upgrades in place. `[InstallDelete]` removes the old exe and shortcuts. The macOS `bundle_identifier` and the app icon (`source/ui/SeratoSidecarLogo.png`) are unchanged.

### Native dependency matrix (rekordbox)

rekordbox support needs SQLCipher, which is native. All of these are pinned in `requirements.txt` and must install **as wheels** (CI: `pip install --only-binary=sqlcipher3-wheels,psutil`) for the bundled **Python 3.11**:

| Package | Pin | Native? | Windows (3.11) | macOS (3.11) |
|---------|-----|---------|----------------|--------------|
| `pyrekordbox` | `0.5.0` | no (contains the DB key) | verified | CI builds; unverified on a real Mac |
| `sqlcipher3-wheels` | `0.5.7` | **yes** | verified | CI builds; unverified on a real Mac |
| `SQLAlchemy` | `2.1.8` | optional C ext | verified | CI builds |
| `psutil` (pyrekordbox dependency) | unpinned | **yes** | verified | CI builds |

If a wheel is missing for a platform, the build fails at `pip install` (by design), not at runtime. If the native module fails to load at runtime anyway, the import is lazy: rekordbox shows "Not available in this build" and Serato keeps working (ADR-009 pattern).

### Release workflow

`.github/workflows/release.yml` triggers on `v*` tag pushes. It runs the two build jobs in parallel, then a `release` job on `ubuntu-latest` that:

1. Downloads both build artifacts.
2. Generates `latest.json` (the manifest consumed by the auto-updater).
3. Publishes a GitHub release with three assets (Windows installer, Mac zip, `latest.json`).
4. Re-points the floating `latest` tag at the new commit so the manifest URL stays stable: `https://github.com/grantcomply/sidecar/releases/download/latest/latest.json`.

Installed clients fetch that URL on startup and compare versions. See `source/services/updater.py` for the client side and `docs/deployment-guide.md` for the release runbook.

### Code signing

Neither platform ships signed binaries. Apple Developer Program ($99/year) and Windows OV/EV certs ($200+/year) aren't justified for a hobby app. The one-time SmartScreen and Gatekeeper workarounds are documented in `README.md`.
