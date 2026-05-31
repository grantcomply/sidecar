# Cross-Platform Guide — Serato Sidecar

> Maintained by the Architect agent. Documents platform differences and how to handle them.

## Supported Platforms

| Platform | Status | Notes |
|----------|--------|-------|
| Windows 10/11 | Shipped | Primary development and test platform; v0.1.1 verified end-to-end |
| macOS | Built (unverified) | CI produces a zipped `.app` per release, but no user has run it on a real Mac yet |
| Linux | Future | Lower priority; Serato doesn't run natively on Linux, so end-user demand is limited |

## Serato Paths by Platform

| Platform | Subcrates Directory |
|----------|-------------------|
| Windows | `C:\Users\<user>\Music\_Serato_\Subcrates` |
| macOS | `/Users/<user>/Music/_Serato_/Subcrates` |
| Linux | N/A (Serato doesn't run natively on Linux) |

### Current Issues

No known cross-platform issues as of v0.1.1. The historical list below is preserved for context — all items are resolved:

- ~~`config.py` hardcoded `C:\Users\grant\Music\_Serato_\Subcrates`~~ — resolved (uses `Path.home()`)
- ~~`crate_parser.py` hardcoded `DEFAULT_MUSIC_ROOT = "C:\\"`~~ — resolved (detects `sys.platform`)
- ~~`tooltip.py` hardcoded font `("Segoe UI", 10)`~~ — resolved (uses platform-default font)

### How to Handle
- Use `Path.home() / "Music" / "_Serato_" / "Subcrates"` as the default
- For music root: use `Path("/")` on macOS/Linux, `Path("C:/")` on Windows (or detect drive letter)
- Allow user override via Settings dialog (stored in `.env`)
- Never hardcode absolute paths

## File Path Rules

### Do
```python
from pathlib import Path

config_dir = Path.home() / ".serato-sidecar"
csv_path = export_dir / f"{crate_name}.csv"
```

### Don't
```python
import os
config_dir = os.path.join("C:\\Users\\grant", ".serato-sidecar")
csv_path = export_dir + "\\" + crate_name + ".csv"
```

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

The helper's fallback chain (first hit wins) is: `os.stat` (`OSError` → `None`) → `st_birthtime` if present and `> 0` → `st_ctime` if `sys.platform == "win32"` → `st_mtime`. The `> 0` guard handles filesystems that report `st_birthtime == 0` ("unknown birth"). `None` (stat failed) is distinct from `0.0`; the caller (`crate_parser.get_track_metadata`) maps `None` → `0.0` ("unknown"), which the suggestion engine's date filter excludes when a `date_from` is set.

The **Python 3.11-vs-3.12 Windows `st_birthtime` difference is the reason this helper exists** — a naïve `st_birthtime`-only or `st_ctime`-only read would be wrong on one platform/version combination. See `source/services/file_times.file_creation_time` and ADR-013.

## Packaging & Distribution

The shipped packaging system is a matrix of per-platform builds driven by a single PyInstaller spec and orchestrated by GitHub Actions. Released via the public repo at `grantcomply/sidecar`.

### Build pipeline

| Stage | Windows | macOS |
|-------|---------|-------|
| Bundle | `pyinstaller serato-sidecar.spec` (one-folder) | `pyinstaller serato-sidecar.spec` → `SeratoSidecar.app` (via `BUNDLE` block) |
| Installer | Inno Setup (`build/installer.iss`) → `SeratoSidecar-Setup-<version>.exe` | `ditto -c -k --keepParent` → `SeratoSidecar-<version>-mac.zip` |
| Runner | `windows-latest` GHA runner | `macos-latest` GHA runner |

The PyInstaller spec is one-folder (not one-file) to keep startup fast and reduce Windows Defender false positives. The CTk theme directory is bundled via `collect_all('customtkinter')` — missing this is the most common breakage.

### Release workflow

`.github/workflows/release.yml` triggers on `v*` tag pushes. It runs the two build jobs in parallel, then a `release` job on `ubuntu-latest` that:

1. Downloads both build artifacts.
2. Generates `latest.json` (the manifest consumed by the auto-updater).
3. Publishes a GitHub release with three assets (Windows installer, Mac zip, `latest.json`).
4. Re-points the floating `latest` tag at the new commit so the manifest URL stays stable: `https://github.com/grantcomply/sidecar/releases/download/latest/latest.json`.

Installed clients fetch that URL on startup and compare versions. See `source/services/updater.py` for the client side and `docs/deployment-guide.md` for the release runbook.

### Code signing

Neither platform ships signed binaries. Apple Developer Program ($99/year) and Windows OV/EV certs ($200+/year) aren't justified for a hobby app. The one-time SmartScreen and Gatekeeper workarounds are documented in `README.md`.
