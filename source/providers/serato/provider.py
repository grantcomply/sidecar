"""Serato DJ library provider.

Wraps the existing ``.crate`` parser and ID3 tag reader behind the
``LibraryProvider`` contract (ADR-015). Behaviour is identical to the
pre-provider sync: same track dicts, same crate set, same mtimes.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from source.providers.base import (
    CrateInfo,
    DeckLoadNotSupported,
    ProgressCallback,
    ProviderCapability,
    ProviderError,
    ProviderIssue,
    ProviderSnapshot,
    SettingKind,
    SettingSpec,
    TrackRecord,
)
from source.services import crate_parser

PROVIDER_ID = "serato"
_CRATE_SUFFIX = ".crate"
_CRATE_PATH_SEPARATOR = "%%"  # Serato encodes subcrate nesting in the filename
_FOLDER_NOT_FOUND = "Crates folder not found"
_NO_CRATES = "No crates found in this folder"


def _crate_id(stem: str) -> str:
    return f"{PROVIDER_ID}:{stem}"


def _folder_hint() -> str:
    if sys.platform == "win32":
        return "Usually Music\\_Serato_\\Subcrates."
    return "Usually Music/_Serato_/Subcrates."


class SeratoProvider:
    """Reads Serato crates from the ``_Serato_/Subcrates`` folder (read-only)."""

    id = PROVIDER_ID
    display_name = "Serato DJ"
    crate_noun = "crate"

    def setting_specs(self) -> tuple[SettingSpec, ...]:
        return (
            SettingSpec(
                key="subcrates_dir",
                env_key="SERATO_SUBCRATES_DIR",
                label="Crates folder",
                kind=SettingKind.DIRECTORY,
                placeholder="Choose your Serato crates folder",
                hint=_folder_hint(),
                browse_title="Select your Serato crates folder",
            ),
        )

    def default_settings(self) -> dict[str, str]:
        # Formerly config.FALLBACK_SUBCRATES_DIR (ADR-005 path detection now lives here).
        return {"subcrates_dir": str(Path.home() / "Music" / "_Serato_" / "Subcrates")}

    def detected_values(self, settings: Mapping[str, str]) -> dict[str, str]:
        # The crates folder default is pre-filled as a real value, not detected.
        return {}

    def detect(self) -> bool:
        return Path(self.default_settings()["subcrates_dir"]).is_dir()

    def capabilities(self, settings: Mapping[str, str]) -> frozenset[ProviderCapability]:
        # No CHANGE_DETECTION (a scan re-reads every file's tags; too heavy to
        # run automatically) and no DECK_LOAD (ADR-014).
        return frozenset({
            ProviderCapability.PLAYLIST_FOLDERS,
            ProviderCapability.NATIVE_PLAY_COUNT,
        })

    def validate(self, settings: Mapping[str, str]) -> list[ProviderIssue]:
        folder = Path(settings.get("subcrates_dir", ""))
        if not settings.get("subcrates_dir") or not folder.is_dir():
            return [ProviderIssue("error", _FOLDER_NOT_FOUND, "subcrates_dir")]
        try:
            has_crates = any(p.name.endswith(_CRATE_SUFFIX) for p in folder.iterdir())
        except OSError:
            return [ProviderIssue("error", _FOLDER_NOT_FOUND, "subcrates_dir")]
        if not has_crates:
            return [ProviderIssue("warning", _NO_CRATES, "subcrates_dir")]
        return []

    def scan(
        self,
        settings: Mapping[str, str],
        progress: ProgressCallback | None = None,
    ) -> ProviderSnapshot:
        """Parse every crate and read each track's tags.

        Raises ``ProviderError`` if the crates folder is missing. Other
        ``OSError``s (e.g. permission denied) propagate to the sync orchestrator.
        """
        folder = settings.get("subcrates_dir", "")
        if not folder or not Path(folder).is_dir():
            raise ProviderError(_FOLDER_NOT_FOUND)
        tracks, mtimes = crate_parser.parse_all_crates(
            folder,
            progress_callback=progress,
            crate_key=crate_parser.crate_stem,
        )

        # Built from the mtimes keys (every .crate filename) so empty crates are included.
        crates: dict[str, CrateInfo] = {}
        for filename in mtimes:
            stem = crate_parser.crate_stem(filename)
            crate_id = _crate_id(stem)
            crates[crate_id] = CrateInfo(
                id=crate_id,
                provider_id=PROVIDER_ID,
                label=crate_parser.crate_display_name(filename),
                path=tuple(stem.split(_CRATE_PATH_SEPARATOR)),
            )

        for meta in tracks.values():
            meta["crates"] = [_crate_id(stem) for stem in meta["crates"]]

        return ProviderSnapshot(
            provider_id=PROVIDER_ID,
            tracks=cast(dict[str, TrackRecord], tracks),
            crates=crates,
            fingerprint=dict(mtimes),
            change_token=None,
        )

    def change_token(self, settings: Mapping[str, str]) -> str | None:
        return None

    def load_to_deck(self, settings: Mapping[str, str], track_path: str, deck: int) -> None:
        """Not supported.

        Serato offers no way to load a *specific* track from outside the app; a
        MIDI "load" only loads whatever is selected in Serato's own browser
        (ADR-014). So Serato never declares ``ProviderCapability.DECK_LOAD``.
        """
        raise DeckLoadNotSupported("Loading to a deck isn't supported for Serato")
