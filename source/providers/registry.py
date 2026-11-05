"""Library provider registry (ADR-015).

The only module outside ``source/providers/<name>/`` allowed to import a
concrete provider. Insertion order of ``PROVIDERS`` (rekordbox first) is the
display order, the fresh-install detection order and the merge precedence.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping

from source.providers.base import LibraryProvider, ProviderCapability
from source.providers.rekordbox.provider import RekordboxProvider
from source.providers.serato.provider import SeratoProvider

logger = logging.getLogger(__name__)

PROVIDERS: dict[str, LibraryProvider] = {
    "rekordbox": RekordboxProvider(),
    "serato": SeratoProvider(),
}


def get_provider(provider_id: str) -> LibraryProvider:
    """Return the registered provider. Raises ``KeyError`` for an unknown id."""
    return PROVIDERS[provider_id]


def all_providers() -> list[LibraryProvider]:
    """Every registered provider, in registry (precedence) order."""
    return list(PROVIDERS.values())


def first_deck_load_provider(
    provider_ids: Iterable[str],
    settings_for: Callable[[str], Mapping[str, str]],
) -> LibraryProvider | None:
    """Return the first provider in ``provider_ids`` that declares ``DECK_LOAD``.

    ``provider_ids`` is in precedence order; unknown ids are logged and
    skipped. ``settings_for(provider_id)`` supplies the provider's current
    settings. Returns ``None`` when no provider can load to a deck, which is
    always the case in this feature (no provider declares the capability).
    """
    for provider_id in provider_ids:
        provider = PROVIDERS.get(provider_id)
        if provider is None:
            logger.warning("Unknown library provider id %r; skipped", provider_id)
            continue
        if ProviderCapability.DECK_LOAD in provider.capabilities(settings_for(provider_id)):
            return provider
    return None
