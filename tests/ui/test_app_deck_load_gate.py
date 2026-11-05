"""``DJTrackSelectorApp.deck_load_provider_for`` (T4.4): the hidden deck-load gate.

No window is built: the method only needs the app's provider helpers, so it
runs against a stub ``self``. Synthetic data; no provider settings are written.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from source import app as app_module
from source.app import DJTrackSelectorApp
from source.providers import registry
from source.providers.base import ProviderCapability
from source.providers.serato.provider import SeratoProvider


class _DeckLoadingProvider(SeratoProvider):
    id = "fake_deck"
    display_name = "Fake Deck"

    def capabilities(self, settings):
        return super().capabilities(settings) | {ProviderCapability.DECK_LOAD}


def _stub_app(enabled: list[str], monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A stand-in ``self`` using the app's real provider helpers."""
    monkeypatch.setattr(app_module, "effective_enabled_providers", lambda: list(enabled))
    stub = SimpleNamespace(_warned_unknown_providers=set())
    stub._enabled_registered_providers = (
        lambda: DJTrackSelectorApp._enabled_registered_providers(stub)  # type: ignore[arg-type]
    )
    stub._provider_settings = (
        lambda pid: DJTrackSelectorApp._provider_settings(stub, pid)  # type: ignore[arg-type]
    )
    return stub


def _gate(stub: SimpleNamespace, track):
    return DJTrackSelectorApp.deck_load_provider_for(stub, track)  # type: ignore[arg-type]


@pytest.fixture
def fake_deck(monkeypatch: pytest.MonkeyPatch) -> _DeckLoadingProvider:
    fake = _DeckLoadingProvider()
    monkeypatch.setitem(registry.PROVIDERS, fake.id, fake)
    return fake


def test_both_real_providers_return_none(monkeypatch, make_track):
    stub = _stub_app(["rekordbox", "serato"], monkeypatch)
    track = make_track()
    track.sources = ("rekordbox", "serato")

    assert _gate(stub, track) is None


def test_fake_provider_declaring_deck_load_in_sources_is_returned(
    monkeypatch, make_track, fake_deck,
):
    stub = _stub_app(["rekordbox", "serato", "fake_deck"], monkeypatch)
    track = make_track()
    track.sources = ("rekordbox", "fake_deck")

    assert _gate(stub, track) is fake_deck


def test_deck_load_provider_not_holding_the_track_is_ignored(
    monkeypatch, make_track, fake_deck,
):
    stub = _stub_app(["serato", "fake_deck"], monkeypatch)
    track = make_track()
    track.sources = ("serato",)

    assert _gate(stub, track) is None


def test_disabled_deck_load_provider_is_ignored(monkeypatch, make_track, fake_deck):
    stub = _stub_app(["serato"], monkeypatch)
    track = make_track()
    track.sources = ("serato", "fake_deck")

    assert _gate(stub, track) is None


def test_track_without_sources_returns_none(monkeypatch, make_track, fake_deck):
    stub = _stub_app(["fake_deck"], monkeypatch)

    assert _gate(stub, make_track()) is None
