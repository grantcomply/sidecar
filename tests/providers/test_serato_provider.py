"""Tests for ``SeratoProvider`` using real ``.crate`` bytes in ``tmp_path``."""

from __future__ import annotations

from pathlib import Path

import pytest

from source.providers.registry import first_deck_load_provider, get_provider
from source.providers.base import (
    CrateInfo,
    DeckLoadNotSupported,
    ProviderCapability,
    ProviderError,
)
from source.providers.serato.provider import SeratoProvider
from source.services import crate_parser
from tests.fixtures.crate_bytes import write_crate


def _stub_metadata(path: str) -> dict:
    return {
        "file_name": Path(path).name,
        "title": Path(path).stem,
        "bpm": 124.0,
        "camelot_key": "8A",
        "energy_level": 5,
        "date_added": 1.0,
        "full_file_path": path,
    }


@pytest.fixture
def subcrates(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(crate_parser, "get_track_metadata", _stub_metadata)
    folder = tmp_path / "Subcrates"
    folder.mkdir()
    return folder


def _abs(rel: str) -> str:
    """Absolute path the parser derives from a crate-relative path."""
    return str(Path(crate_parser.DEFAULT_MUSIC_ROOT) / Path(rel))


def _scan(folder: Path):
    return SeratoProvider().scan({"subcrates_dir": str(folder)})


def test_scan_crate_ids_and_labels_from_filenames(subcrates):
    write_crate(subcrates, "House%%Bangers.crate", ["Music/a.mp3"])

    snapshot = _scan(subcrates)

    assert snapshot.provider_id == "serato"
    assert snapshot.crates == {
        "serato:House%%Bangers": CrateInfo(
            id="serato:House%%Bangers",
            provider_id="serato",
            label="House - Bangers",
            path=("House", "Bangers"),
        ),
    }
    assert snapshot.tracks[_abs("Music/a.mp3")].get("crates") == ["serato:House%%Bangers"]


def test_scan_empty_crate_in_crates_and_fingerprint(subcrates):
    write_crate(subcrates, "Empty.crate", [])
    write_crate(subcrates, "Full.crate", ["Music/a.mp3"])

    snapshot = _scan(subcrates)

    assert "serato:Empty" in snapshot.crates
    assert "Empty.crate" in snapshot.fingerprint
    assert set(snapshot.fingerprint) == {"Empty.crate", "Full.crate"}
    assert len(snapshot.tracks) == 1


def test_scan_track_in_two_crates_has_both_ids_in_filename_order(subcrates):
    write_crate(subcrates, "B_Groovers.crate", ["Music/shared.mp3"])
    write_crate(subcrates, "A_Bangers.crate", ["Music/shared.mp3"])

    snapshot = _scan(subcrates)

    assert snapshot.tracks[_abs("Music/shared.mp3")].get("crates") == [
        "serato:A_Bangers",
        "serato:B_Groovers",
    ]


def test_scan_change_token_none_and_no_warnings(subcrates):
    write_crate(subcrates, "X.crate", ["Music/a.mp3"])

    snapshot = _scan(subcrates)

    assert snapshot.change_token is None
    assert snapshot.warnings == []


def test_scan_missing_folder_raises_provider_error(tmp_path):
    with pytest.raises(ProviderError, match="^Crates folder not found$"):
        SeratoProvider().scan({"subcrates_dir": str(tmp_path / "nope")})


def test_scan_blank_folder_setting_raises_provider_error():
    with pytest.raises(ProviderError):
        SeratoProvider().scan({"subcrates_dir": ""})


def test_load_to_deck_raises_not_supported():
    provider = SeratoProvider()
    with pytest.raises(DeckLoadNotSupported):
        provider.load_to_deck(provider.default_settings(), "/x.mp3", 1)


def test_capabilities_exclude_change_detection_and_deck_load():
    caps = SeratoProvider().capabilities({})
    assert ProviderCapability.CHANGE_DETECTION not in caps
    assert ProviderCapability.DECK_LOAD not in caps


def test_validate_missing_folder_returns_error(tmp_path):
    issues = SeratoProvider().validate({"subcrates_dir": str(tmp_path / "nope")})
    assert [(i.severity, i.message) for i in issues] == [("error", "Crates folder not found")]


def test_validate_folder_without_crates_returns_warning(tmp_path):
    issues = SeratoProvider().validate({"subcrates_dir": str(tmp_path)})
    assert [(i.severity, i.message) for i in issues] == [
        ("warning", "No crates found in this folder"),
    ]


def test_validate_folder_with_crates_returns_no_issues(subcrates):
    write_crate(subcrates, "X.crate", [])
    assert SeratoProvider().validate({"subcrates_dir": str(subcrates)}) == []


def test_default_settings_match_legacy_config_fallback():
    # The value config.FALLBACK_SUBCRATES_DIR had before Phase 2 removed it.
    expected = str(Path.home() / "Music" / "_Serato_" / "Subcrates")
    assert SeratoProvider().default_settings() == {"subcrates_dir": expected}


def test_registry_returns_serato_and_rejects_unknown_id():
    assert get_provider("serato").id == "serato"
    with pytest.raises(KeyError):
        get_provider("traktor")


# ── Deck-load gate (single check the app uses) ──


class _DeckLoadingProvider(SeratoProvider):
    id = "fake_deck"

    def capabilities(self, settings):
        return super().capabilities(settings) | {ProviderCapability.DECK_LOAD}


def test_first_deck_load_provider_serato_returns_none():
    assert first_deck_load_provider(["serato"], lambda _pid: {}) is None


def test_first_deck_load_provider_returns_declaring_provider(monkeypatch):
    from source.providers import registry

    fake = _DeckLoadingProvider()
    monkeypatch.setitem(registry.PROVIDERS, fake.id, fake)

    assert first_deck_load_provider(["serato", "fake_deck"], lambda _pid: {}) is fake


def test_first_deck_load_provider_skips_unknown_ids():
    assert first_deck_load_provider(["unknown", "serato"], lambda _pid: {}) is None
