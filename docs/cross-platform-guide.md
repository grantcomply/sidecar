# Cross-Platform Guide — Serato Sidecar

> Maintained by the Architect agent. Documents platform differences and how to handle them.

## Supported Platforms

| Platform | Status | Notes |
|----------|--------|-------|
| Windows 10/11 | Primary | Currently developed and tested here |
| macOS | Planned | Serato is popular on Mac — high priority |
| Linux | Future | Lower priority, but should work if we follow the rules |

## Serato Paths by Platform

| Platform | Subcrates Directory |
|----------|-------------------|
| Windows | `C:\Users\<user>\Music\_Serato_\Subcrates` |
| macOS | `/Users/<user>/Music/_Serato_/Subcrates` |
| Linux | N/A (Serato doesn't run natively on Linux) |

### Current Issues (must fix)
- `config.py:8` hardcodes `C:\Users\grant\Music\_Serato_\Subcrates` — breaks macOS/Linux
- `export_crates.py:13` hardcodes `DEFAULT_MUSIC_ROOT = "C:\\"` — breaks macOS/Linux
- `tooltip.py:32` hardcodes font `("Segoe UI", 10)` — Segoe UI is Windows-only

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

## Packaging & Distribution (future)

| Tool | Platform | Notes |
|------|----------|-------|
| PyInstaller | All | Single executable, most mature |
| cx_Freeze | All | Alternative to PyInstaller |
| py2app | macOS | macOS-specific, creates .app bundle |
| Nuitka | All | Compiles to C, best performance |

### Recommended approach
- PyInstaller for initial cross-platform distribution
- Platform-specific CI builds (GitHub Actions with matrix strategy)
- Separate `.spec` files per platform if needed
