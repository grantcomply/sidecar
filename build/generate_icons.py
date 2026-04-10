"""Generate platform icon files from the master logo PNG.

Produces:
    <repo>/icon.ico  — Windows multi-resolution icon (16-256 px)
    <repo>/icon.icns — macOS icon (NOT generated here; see note below)

Run once from the repo root:
    python build/generate_icons.py

Regenerate whenever source/ui/SeratoSidecarLogo.png changes.

Note on .icns:
    The Pillow + Windows combination cannot reliably produce a macOS .icns
    bundle. Generating .icns requires either macOS tooling (`iconutil`) or
    a third-party library. Phase 2 only targets Windows, so we punt on
    .icns for now and the PyInstaller spec references it conditionally.
    When Phase 3 spins up a macOS runner (or when built on a Mac), add an
    `iconutil -c icns` step, or use a helper such as `icnsutil`.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_PNG = REPO_ROOT / "source" / "ui" / "SeratoSidecarLogo.png"
OUTPUT_ICO = REPO_ROOT / "icon.ico"

ICO_SIZES: list[tuple[int, int]] = [
    (16, 16),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
]


def generate_ico() -> None:
    """Create a multi-resolution Windows .ico from the logo PNG."""
    if not SOURCE_PNG.is_file():
        raise FileNotFoundError(f"Source logo not found: {SOURCE_PNG}")

    with Image.open(SOURCE_PNG) as img:
        # Pillow's ICO writer expects an image in RGBA mode; convert if needed.
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        img.save(OUTPUT_ICO, format="ICO", sizes=ICO_SIZES)

    print(f"Wrote {OUTPUT_ICO} (sizes: {ICO_SIZES})")


def main() -> None:
    generate_ico()


if __name__ == "__main__":
    main()
