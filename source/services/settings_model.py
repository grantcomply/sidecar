"""View-model for the settings dialog (pure; no Tk). Plan T3c.5.

The dialog renders one card per ``ProviderSettingsView`` and never branches
on ``provider_id``: everything it needs (labels, hints, detected values,
issues, chip inputs) is in the view.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from source.providers.base import (
    LibraryProvider,
    ProviderCapability,
    ProviderIssue,
    SettingSpec,
)
from source.services.library_store import SnapshotSummary


def first_error_message(issues: Sequence[ProviderIssue]) -> str | None:
    """First error-severity issue message, or None (shared by view and dialog)."""
    return next((i.message for i in issues if i.severity == "error"), None)


@dataclass(frozen=True)
class ProviderSettingsView:
    provider_id: str
    display_name: str
    crate_noun: str
    enabled: bool
    specs: tuple[SettingSpec, ...]
    values: dict[str, str]
    detected: dict[str, str]  # provider.detected_values(values)
    capabilities: frozenset[ProviderCapability]
    summary: SnapshotSummary | None  # library_store.snapshot_summary(pid)
    issues: tuple[ProviderIssue, ...]  # provider.validate(values)
    warnings: tuple[str, ...]  # last sync or refresh warnings, this session
    last_error: str | None  # last failed sync or refresh message

    @property
    def auto_updates(self) -> bool:
        return ProviderCapability.CHANGE_DETECTION in self.capabilities

    def first_error(self) -> str | None:
        """First error-severity issue message (what makes Sync skip this provider)."""
        return first_error_message(self.issues)


def build_provider_views(
    providers: Sequence[LibraryProvider],
    enabled_ids: Sequence[str],
    settings_for: Callable[[str], Mapping[str, str]],
    summary_for: Callable[[str], SnapshotSummary | None],
    warnings: Mapping[str, tuple[str, ...]],
    last_errors: Mapping[str, str],
) -> list[ProviderSettingsView]:
    """One view per registered provider, in registry (display) order."""
    views: list[ProviderSettingsView] = []
    for provider in providers:
        values = dict(settings_for(provider.id))
        views.append(view_for(
            provider, values,
            enabled=provider.id in enabled_ids,
            summary=summary_for(provider.id),
            warnings=tuple(warnings.get(provider.id, ())),
            last_error=last_errors.get(provider.id),
        ))
    return views


def view_for(
    provider: LibraryProvider,
    values: Mapping[str, str],
    *,
    enabled: bool,
    summary: SnapshotSummary | None,
    warnings: tuple[str, ...],
    last_error: str | None,
) -> ProviderSettingsView:
    """Build (or rebuild, e.g. after an edit) one provider's view."""
    values = dict(values)
    return ProviderSettingsView(
        provider_id=provider.id,
        display_name=provider.display_name,
        crate_noun=provider.crate_noun,
        enabled=enabled,
        specs=tuple(provider.setting_specs()),
        values=values,
        detected=dict(provider.detected_values(values)),
        capabilities=frozenset(provider.capabilities(values)),
        summary=summary,
        issues=tuple(provider.validate(values)),
        warnings=warnings,
        last_error=last_error,
    )
