"""Contract tests run against every registered library provider (ADR-015)."""

from __future__ import annotations

import re

import pytest

from source.providers.registry import all_providers
from source.providers.base import (
    DeckLoadNotSupported,
    LibraryProvider,
    ProviderCapability,
    SettingKind,
)

PROVIDERS = all_providers()
_ID_RE = re.compile(r"[a-z0-9_]+")


@pytest.fixture(params=PROVIDERS, ids=lambda p: p.id)
def provider(request) -> LibraryProvider:
    return request.param


def test_registry_has_at_least_one_provider():
    assert PROVIDERS


def test_provider_satisfies_protocol(provider):
    assert isinstance(provider, LibraryProvider)


def test_provider_ids_unique_and_lowercase():
    ids = [p.id for p in PROVIDERS]
    assert len(ids) == len(set(ids))
    for provider_id in ids:
        assert _ID_RE.fullmatch(provider_id), provider_id


def test_setting_env_keys_unique_across_providers():
    env_keys = [spec.env_key for p in PROVIDERS for spec in p.setting_specs()]
    assert len(env_keys) == len(set(env_keys))


def test_default_settings_keys_subset_of_spec_keys(provider):
    spec_keys = {spec.key for spec in provider.setting_specs()}
    assert set(provider.default_settings()) <= spec_keys


def test_provider_sets_crate_noun_and_browse_titles(provider):
    assert provider.crate_noun
    assert provider.display_name
    for spec in provider.setting_specs():
        if spec.kind in (SettingKind.FILE, SettingKind.DIRECTORY):
            assert spec.browse_title, spec.key


def test_without_change_detection_change_token_is_none(provider):
    settings = provider.default_settings()
    if ProviderCapability.CHANGE_DETECTION in provider.capabilities(settings):
        pytest.skip("provider declares CHANGE_DETECTION")
    assert provider.change_token(settings) is None


def test_without_deck_load_load_to_deck_raises(provider):
    settings = provider.default_settings()
    if ProviderCapability.DECK_LOAD in provider.capabilities(settings):
        pytest.skip("provider declares DECK_LOAD")
    with pytest.raises(DeckLoadNotSupported):
        provider.load_to_deck(settings, "/x.mp3", 1)


def test_detected_values_returns_known_setting_keys(provider):
    values = provider.detected_values(provider.default_settings())
    assert isinstance(values, dict)
    assert set(values) <= {spec.key for spec in provider.setting_specs()}
    assert all(isinstance(v, str) for v in values.values())
