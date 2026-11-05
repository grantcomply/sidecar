"""What the app should do with a finished sync (pure; Phase 3b review, Phase 3c copy).

Decides reload / audio / toast / dialog behaviour for manual syncs and quiet
live refreshes, so the rules are unit-tested without Tk. Key rule: reload
whenever any provider's content changed, even if another provider failed.
Otherwise a merged run where one provider fails and another succeeds would
hide the change for good, because the watcher's baseline has already moved.

Copy comes from ``library_copy`` (brief §5.5, §7); never "Synced" when every
provider failed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from source.config import ERROR_COLOR, WARNING_COLOR
from source.services import library_copy
from source.services.library_sync import SyncReport

SHORT_TOAST_MS = 4000
LONG_TOAST_MS = 8000


@dataclass(frozen=True)
class Toast:
    text: str
    color: str
    duration_ms: int
    action_label: str | None = None  # e.g. "Open settings" (the app supplies the callback)


@dataclass(frozen=True)
class SyncOutcome:
    errors: dict[str, str]  # provider id -> last error already shown (refresh dedup)
    reload: bool
    preserve_state: bool  # quiet refresh: keep track, setlist, filters, preview
    stop_audio: bool
    toasts: tuple[Toast, ...]
    success_toast: bool  # app shows "Synced N tracks..." after reloading (needs the count)
    clear_dialog_syncing: bool  # nothing more is queued behind this manual sync
    import_candidate: bool = False  # quiet first import: app toasts "Imported …" if non-empty
    ok_provider_ids: tuple[str, ...] = ()  # succeeded providers, report order


def _manual_failure_toasts(
    report: SyncReport, provider_name: Callable[[str], str],
) -> tuple[Toast, ...]:
    failed = [r for r in report.results if r.error is not None]
    if not failed:
        return ()
    ok = [provider_name(r.provider_id) for r in report.results if r.error is None]
    if ok:
        first = failed[0]
        return (Toast(
            library_copy.format_partial_failure(ok, provider_name(first.provider_id),
                                                first.error or ""),
            WARNING_COLOR, LONG_TOAST_MS,
        ),)
    if len(report.results) == 1:
        only = failed[0]
        return (Toast(
            library_copy.format_sync_failure(provider_name(only.provider_id), only.error or ""),
            ERROR_COLOR, SHORT_TOAST_MS,
        ),)
    return (Toast(
        library_copy.format_all_failed([provider_name(r.provider_id) for r in failed]),
        ERROR_COLOR, LONG_TOAST_MS, action_label=library_copy.ACTION_OPEN_SETTINGS,
    ),)


def sync_outcome(
    prev_errors: Mapping[str, str],
    report: SyncReport,
    *,
    silent: bool,
    provider_name: Callable[[str], str],
    library_was_empty: bool = False,
) -> SyncOutcome:
    """Decide the app's reaction to ``report``. ``prev_errors`` is not modified."""
    errors = dict(prev_errors)
    failed = [r for r in report.results if r.error is not None]
    ok_ids = tuple(r.provider_id for r in report.results if r.error is None)
    for pid in ok_ids:
        errors.pop(pid, None)

    if silent:
        toasts: list[Toast] = []
        for result in failed:
            if errors.get(result.provider_id) != result.error:
                errors[result.provider_id] = result.error or ""
                toasts.append(Toast(
                    library_copy.format_refresh_failure(
                        provider_name(result.provider_id), result.error or "",
                    ),
                    WARNING_COLOR, LONG_TOAST_MS,
                ))
        return SyncOutcome(
            errors=errors,
            reload=report.any_changed,
            preserve_state=True,
            stop_audio=False,
            toasts=tuple(toasts),
            success_toast=False,
            clear_dialog_syncing=False,
            import_candidate=library_was_empty and report.any_changed,
            ok_provider_ids=ok_ids,
        )

    for result in failed:
        errors[result.provider_id] = result.error or ""  # don't re-toast it on a refresh
    reload = report.ok or report.any_changed
    return SyncOutcome(
        errors=errors,
        reload=reload,
        preserve_state=False,
        stop_audio=reload,
        toasts=_manual_failure_toasts(report, provider_name),
        success_toast=report.ok,
        clear_dialog_syncing=not report.follow_up_pending,
        ok_provider_ids=ok_ids,
    )
