# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Serato Sidecar.

One-folder build (not one-file). Platform-detecting: the same spec is used
on Windows and macOS. On macOS an additional BUNDLE step produces
`SeratoSidecar.app`.

Build with:
    pyinstaller serato-sidecar.spec

Phase 2 of plans/deployment-plan.md.
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# ---------------------------------------------------------------------------
# Version — single source of truth lives in source/__version__.py.
# We read it without importing the package (avoids pulling in customtkinter
# and friends during spec evaluation).
# ---------------------------------------------------------------------------
_version_ns: dict = {}
_version_path = Path(SPECPATH) / "source" / "__version__.py"
exec(_version_path.read_text(encoding="utf-8"), _version_ns)
APP_VERSION: str = _version_ns["__version__"]

APP_NAME = "SeratoSidecar"
IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"

# ---------------------------------------------------------------------------
# Data files.
# CustomTkinter loads theme JSONs dynamically at runtime; PyInstaller's
# static analyser misses them unless we explicitly collect the package.
# ---------------------------------------------------------------------------
ctk_datas, ctk_binaries, ctk_hiddenimports = collect_all("customtkinter")

datas = [
    ("source/ui/SeratoSidecarLogo.png", "source/ui"),
]
datas += ctk_datas

binaries = list(ctk_binaries)

# ---------------------------------------------------------------------------
# Hidden imports.
# The `source` package modules are only imported via `from source.xxx import
# yyy` strings that PyInstaller's AST walker normally picks up, but we list
# them explicitly to be safe against any dynamic / late imports added later.
# ---------------------------------------------------------------------------
hiddenimports = [
    "source",
    "source.app",
    "source.config",
    "source.__version__",
    "source.models",
    "source.models.track",
    "source.models.library",
    "source.services",
    "source.services.cache",
    "source.services.camelot",
    "source.services.crate_parser",
    "source.services.crate_sync",
    "source.services.suggestion_engine",
    "source.ui",
    "source.ui.session_panel",
    "source.ui.suggestion_panel",
    "source.ui.sync_panel",
    "source.ui.tooltip",
    "source.ui.track_detail",
    "source.ui.utils",
]
hiddenimports += ctk_hiddenimports

# ---------------------------------------------------------------------------
# Icons. Windows uses .ico, macOS uses .icns. The .icns file is NOT generated
# on Windows (see build/generate_icons.py). When building on a Mac the file
# is expected to exist at the repo root; otherwise we fall back to no icon
# so the build still succeeds.
# TODO(phase-3): generate icon.icns on the macOS runner before invoking
# pyinstaller, or commit a pre-built .icns once a Mac is available.
# ---------------------------------------------------------------------------
if IS_WINDOWS:
    icon_file: str | None = "icon.ico"
elif IS_MACOS:
    icns_path = Path(SPECPATH) / "icon.icns"
    icon_file = str(icns_path) if icns_path.is_file() else None
else:
    icon_file = None


block_cipher = None


a = Analysis(
    ["main.py"],
    pathex=[SPECPATH],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

if IS_MACOS:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon_file,
        bundle_identifier="com.grant.seratosidecar",
        version=APP_VERSION,
        info_plist={
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "NSHighResolutionCapable": True,
        },
    )
